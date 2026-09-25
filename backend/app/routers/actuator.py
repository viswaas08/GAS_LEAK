import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..config import settings
from .. import models, schemas, sms
from ..security import get_current_user, require_roles
from ..websocket_manager import manager

router = APIRouter(prefix="/api/actuator", tags=["actuator"])

# NOTE ON REAL FLOW:
# Website -> this endpoint -> MQTT publish to <zone>/actuator/cmd -> ESP32 relay/servo
# -> ESP32 publishes to <zone>/actuator/ack -> an MQTT subscriber service calls
# POST /api/actuator/ack with the result. Because no physical ESP32 is attached to
# this prototype, `_simulate_esp32_ack` below stands in for that MQTT round trip so
# the full state machine (COMMAND_SENT -> WAITING_CONFIRMATION -> CLOSED/FAILED/TIMEOUT)
# is still exercised end-to-end. Swap it for a real MQTT client without touching the
# state machine or the frontend.


async def _simulate_esp32_ack(zone_id: str, device_id: str, command_id: str, outcome: str = "success"):
    await asyncio.sleep(3)  # simulated network + actuator travel time
    db: Session = SessionLocal()
    try:
        device = db.query(models.Device).filter(models.Device.id == device_id).first()
        if not device or device.valve_command_id != command_id:
            return  # a newer command superseded this one
        zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
        if outcome == "success":
            device.valve_state = models.ValveState.CLOSED
            db.commit()
            if zone:
                for link in zone.user_links:
                    if link.user.phone_verified:
                        sms.send_sms(db, link.user.phone, sms.format_valve_closed_sms(zone.name))
        else:
            device.valve_state = models.ValveState.FAILED
            db.commit()
        await manager.broadcast("valve_update", {
            "zone_id": zone_id, "valve_state": device.valve_state.value, "command_id": command_id,
        })
    finally:
        db.close()


def _is_online(device: models.Device) -> bool:
    if not device or not device.last_heartbeat:
        return False
    return (datetime.utcnow() - device.last_heartbeat).total_seconds() <= settings.HEARTBEAT_OFFLINE_AFTER_SECONDS


@router.post("/shutoff", response_model=schemas.ValveStatusOut)
async def emergency_shutoff(req: schemas.ShutoffCommand, background_tasks: BackgroundTasks,
                             db: Session = Depends(get_db),
                             user: models.User = Depends(require_roles(models.Role.ADMIN, models.Role.OPERATOR))):
    if not req.confirm:
        raise HTTPException(400, "Confirmation required before sending a shutoff command")
    zone = db.query(models.Zone).filter(models.Zone.id == req.zone_id).first()
    if not zone or not zone.device:
        raise HTTPException(404, "Zone or device not found")
    device = zone.device

    if not _is_online(device):
        raise HTTPException(400, "Device is offline. Valve control is not available while hardware is offline.")

    command_id = str(uuid.uuid4())
    device.valve_command_id = command_id
    device.valve_command_sent_at = datetime.utcnow()
    device.valve_state = models.ValveState.COMMAND_SENT
    db.commit()

    db.add(models.AuditLog(user_id=user.id, module="ACTUATOR", action="EMERGENCY_SHUTOFF_COMMANDED",
                            detail=f"zone={zone.name} command_id={command_id}"))
    db.commit()

    await manager.broadcast("valve_update", {
        "zone_id": zone.id, "valve_state": device.valve_state.value, "command_id": command_id,
    })

    # move to WAITING_CONFIRMATION almost immediately (command left the backend)
    device.valve_state = models.ValveState.WAITING_CONFIRMATION
    db.commit()
    await manager.broadcast("valve_update", {
        "zone_id": zone.id, "valve_state": device.valve_state.value, "command_id": command_id,
    })

    # In production this is real MQTT; here we simulate the round trip.
    background_tasks.add_task(_simulate_esp32_ack, zone.id, device.id, command_id, "success")

    return schemas.ValveStatusOut(zone_id=zone.id, valve_state=device.valve_state,
                                   updated_at=device.valve_command_sent_at)


@router.post("/valve-control", response_model=schemas.ValveStatusOut)
async def manual_valve_control(req: schemas.ValveControlCommand, background_tasks: BackgroundTasks,
                               db: Session = Depends(get_db),
                               user: models.User = Depends(require_roles(models.Role.ADMIN, models.Role.OPERATOR))):
    """
    Manual switch to turn the valve ON (0° OPEN) or OFF (180° CLOSED).
    Valve control is rejected when the hardware device is offline.
    """
    zone = db.query(models.Zone).filter(models.Zone.id == req.zone_id).first()
    if not zone or not zone.device:
        raise HTTPException(404, "Zone or device not found")
    device = zone.device

    if not _is_online(device):
        raise HTTPException(400, "Device is offline. Valve control is not available while hardware is offline.")

    target = req.target_state.strip().upper()
    if target in ("OPEN", "ON", "0"):
        target_state = models.ValveState.OPEN
        action_name = "MANUAL_VALVE_SWITCH_OPEN"
        detail_msg = f"zone={zone.name} manual switch flipped ON (0° OPEN) by operator {user.name}"
    elif target in ("CLOSED", "OFF", "180", "SHUTOFF"):
        target_state = models.ValveState.CLOSED
        action_name = "MANUAL_VALVE_SWITCH_CLOSED"
        detail_msg = f"zone={zone.name} manual switch flipped OFF (180° CLOSED) by operator {user.name}"
    else:
        raise HTTPException(400, "Invalid target_state. Use 'OPEN' (ON) or 'CLOSED' (OFF)")

    command_id = str(uuid.uuid4())
    device.valve_command_id = command_id
    device.valve_command_sent_at = datetime.utcnow()
    device.valve_state = target_state
    db.commit()

    db.add(models.AuditLog(user_id=user.id, module="ACTUATOR", action=action_name, detail=detail_msg))
    db.commit()

    await manager.broadcast("valve_update", {
        "zone_id": zone.id, "valve_state": device.valve_state.value, "command_id": command_id,
    })

    return schemas.ValveStatusOut(zone_id=zone.id, valve_state=device.valve_state,
                                   updated_at=device.valve_command_sent_at)


@router.post("/ack")
async def actuator_ack(device_code: str, command_id: str, result: str, db: Session = Depends(get_db)):
    """
    Real ESP32 devices (via the MQTT bridge) call this to confirm a shutoff
    outcome: result = "closed" | "failed". Not used by the simulated flow above,
    but is the real production entry point.
    """
    device = db.query(models.Device).filter(models.Device.device_code == device_code).first()
    if not device or device.valve_command_id != command_id:
        raise HTTPException(409, "Stale or unknown command_id")
    device.valve_state = models.ValveState.CLOSED if result == "closed" else models.ValveState.FAILED
    db.commit()
    zone = db.query(models.Zone).filter(models.Zone.device_id == device.id).first()
    await manager.broadcast("valve_update", {
        "zone_id": zone.id if zone else None, "valve_state": device.valve_state.value, "command_id": command_id,
    })
    return {"detail": "acknowledged"}


@router.get("/{zone_id}/status", response_model=schemas.ValveStatusOut)
def valve_status(zone_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if not zone or not zone.device:
        raise HTTPException(404, "Zone or device not found")
    return schemas.ValveStatusOut(zone_id=zone.id, valve_state=zone.device.valve_state,
                                   updated_at=zone.device.valve_command_sent_at)

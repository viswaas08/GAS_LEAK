from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas, sms, rules
from ..websocket_manager import manager

router = APIRouter(prefix="/api/sensors", tags=["sensors"])


async def _notify_zone_users(db: Session, zone: models.Zone, status: str, reason: str):
    verified_links = [l for l in zone.user_links if l.user.phone_verified]
    sent_any = False
    for link in verified_links:
        sms.send_sms(db, link.user.phone, sms.format_alert_sms(zone.name, status, reason))
        sent_any = True
    return sent_any


@router.post("", response_model=schemas.SensorReadingOut)
async def ingest_reading(req: schemas.SensorIngest, db: Session = Depends(get_db)):
    """
    Called by the MQTT<->HTTP bridge (or directly by the simulator) whenever
    the ESP32 publishes a new sensor payload. In a real deployment this
    endpoint is invoked by a small MQTT subscriber service, not the ESP32
    itself, keeping device credentials off the public internet.
    """
    is_new = False
    device = db.query(models.Device).filter(models.Device.device_code == req.device_code).first()
    if not device:
        is_new = True
        from .pipeline import auto_assign_segment_and_position, get_segment_meta
        if req.segment_id:
            seg_meta = get_segment_meta(req.segment_id)
            seg_id = seg_meta["id"]
            seg_name = seg_meta["name"]
            pos = 0.5
        else:
            seg_id, seg_name, pos = auto_assign_segment_and_position(db, req.device_code)

        device = models.Device(
            device_code=req.device_code,
            segment_id=seg_id,
            segment_name=seg_name,
            position_ratio=pos,
            hardware_type="ESP32-WROOM-32 + MQ-2 + 180° Servo",
            last_heartbeat=datetime.utcnow(),
        )
        db.add(device)
        db.commit()
        db.refresh(device)
        zone = models.Zone(
            name=f"Pipeline {req.device_code}",
            location=f"{seg_name} (KM {round(pos * get_segment_meta(seg_id)['length_km'], 1)})",
            segment_id=seg_id,
            device_id=device.id,
        )
        db.add(zone)
        db.add(models.AuditLog(
            user_id="SYSTEM",
            module="SENSORS",
            action="MODULE_AUTO_DETECTED",
            detail=f"New module {req.device_code} auto-detected and inserted into {seg_name} (KM {round(pos * get_segment_meta(seg_id)['length_km'], 1)})",
        ))
        db.commit()
    elif not device.segment_id:
        from .pipeline import auto_assign_segment_and_position, get_segment_meta
        seg_id, seg_name, pos = auto_assign_segment_and_position(db, req.device_code)
        device.segment_id = seg_id
        device.segment_name = seg_name
        device.position_ratio = pos
        db.commit()

    device.last_heartbeat = datetime.utcnow()

    status, reason = rules.evaluate(req.mq2, req.mq135, req.pressure, req.flame_detected)

    reading = models.SensorReading(
        device_id=device.id, mq2=req.mq2, mq135=req.mq135, pressure=req.pressure,
        flame_detected=req.flame_detected, status=status, reason=reason,
    )
    db.add(reading)
    db.commit()
    db.refresh(reading)

    zone = db.query(models.Zone).filter(models.Zone.device_id == device.id).first()
    incident_payload = None
    if zone and status in (models.PipelineStatus.WARNING, models.PipelineStatus.CRITICAL):
        open_incident = (db.query(models.Incident)
                          .filter(models.Incident.zone_id == zone.id, models.Incident.resolved == False)
                          .first())
        if not open_incident:
            incident = models.Incident(zone_id=zone.id, status=status, reason=reason)
            db.add(incident)
            db.commit()
            db.refresh(incident)
            db.add(models.IncidentEvent(incident_id=incident.id, event=f"{status.value} — {reason}"))
            db.commit()

            if status == models.PipelineStatus.CRITICAL:
                sent = await _notify_zone_users(db, zone, status.value, reason)
                incident.sms_sent = sent
                db.add(models.IncidentEvent(incident_id=incident.id,
                                             event="SMS sent to assigned users" if sent else
                                             "No verified users assigned — SMS not sent"))
                db.commit()
            incident_payload = {"id": incident.id, "zone_id": zone.id, "status": status.value, "reason": reason}
        else:
            # escalate WARNING -> CRITICAL on an already-open incident
            if status == models.PipelineStatus.CRITICAL and open_incident.status != models.PipelineStatus.CRITICAL:
                open_incident.status = status
                db.add(models.IncidentEvent(incident_id=open_incident.id, event=f"Escalated to CRITICAL — {reason}"))
                db.commit()
                sent = await _notify_zone_users(db, zone, status.value, reason)
                open_incident.sms_sent = open_incident.sms_sent or sent
                db.commit()
    elif zone and status == models.PipelineStatus.SAFE:
        open_incident = (db.query(models.Incident)
                          .filter(models.Incident.zone_id == zone.id, models.Incident.resolved == False)
                          .first())
        if open_incident:
            open_incident.resolved = True
            open_incident.resolved_at = datetime.utcnow()
            db.add(models.IncidentEvent(incident_id=open_incident.id, event="Readings back to SAFE — incident resolved"))
        
        # In SAFE mode with no active hazard, auto-restore valve to OPEN
        if device.valve_state != models.ValveState.OPEN:
            device.valve_state = models.ValveState.OPEN
        db.commit()

    if is_new:
        await manager.broadcast("module_connected", {
            "device_code": device.device_code,
            "segment_id": device.segment_id,
            "segment_name": device.segment_name,
            "position_ratio": device.position_ratio,
            "hardware_type": device.hardware_type,
            "zone_id": zone.id if zone else None,
            "zone_name": zone.name if zone else None,
            "mq2": req.mq2,
            "flame": req.flame_detected,
            "status": status.value,
            "valve_state": device.valve_state.value,
            "timestamp": datetime.utcnow().isoformat(),
        })

    await manager.broadcast("sensor_update", {
        "device_code": device.device_code,
        "segment_id": device.segment_id,
        "zone_id": zone.id if zone else None,
        "zone_name": zone.name if zone else None,
        "mq2": req.mq2, "mq135": req.mq135, "pressure": req.pressure,
        "flame_detected": req.flame_detected,
        "status": status.value, "reason": reason,
        "valve_state": device.valve_state.value,
        "incident": incident_payload,
    })

    reading.valve_state = device.valve_state.value
    return reading

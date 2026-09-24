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
    device = db.query(models.Device).filter(models.Device.device_code == req.device_code).first()
    if not device:
        raise HTTPException(404, f"Unknown device_code {req.device_code}")
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
            db.commit()

    await manager.broadcast("sensor_update", {
        "device_code": device.device_code,
        "zone_id": zone.id if zone else None,
        "zone_name": zone.name if zone else None,
        "mq2": req.mq2, "mq135": req.mq135, "pressure": req.pressure,
        "flame_detected": req.flame_detected,
        "status": status.value, "reason": reason,
        "valve_state": device.valve_state.value,
        "incident": incident_payload,
    })

    return reading

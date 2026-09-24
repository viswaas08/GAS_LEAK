from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import settings
from .. import models, schemas
from ..security import get_current_user, require_roles

router = APIRouter(prefix="/api/zones", tags=["zones"])


def _is_online(device: models.Device) -> bool:
    if not device or not device.last_heartbeat:
        return False
    return (datetime.utcnow() - device.last_heartbeat).total_seconds() <= settings.HEARTBEAT_OFFLINE_AFTER_SECONDS


def _zone_out(db: Session, zone: models.Zone) -> schemas.ZoneOut:
    device = zone.device
    online = _is_online(device)
    latest = None
    if device:
        latest = (db.query(models.SensorReading)
                  .filter(models.SensorReading.device_id == device.id)
                  .order_by(models.SensorReading.created_at.desc()).first())
    status = models.PipelineStatus.OFFLINE if not online else (latest.status if latest else models.PipelineStatus.SAFE)
    latest_out = None
    if latest:
        latest_out = schemas.LatestReading(
            mq2=latest.mq2, mq135=latest.mq135, pressure=latest.pressure,
            flame_detected=latest.flame_detected, created_at=latest.created_at,
        )
    return schemas.ZoneOut(
        id=zone.id, name=zone.name, location=zone.location,
        device_code=device.device_code if device else None,
        status=status,
        valve_state=device.valve_state if device else models.ValveState.UNKNOWN,
        device_online=online,
        last_heartbeat=device.last_heartbeat if device else None,
        latest=latest_out,
    )


@router.get("", response_model=list[schemas.ZoneOut])
def list_zones(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    zones = db.query(models.Zone).all()
    return [_zone_out(db, z) for z in zones]


@router.get("/{zone_id}", response_model=schemas.ZoneOut)
def get_zone(zone_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if not zone:
        raise HTTPException(404, "Zone not found")
    return _zone_out(db, zone)


@router.post("", response_model=schemas.ZoneOut)
def create_zone(req: schemas.ZoneCreate, db: Session = Depends(get_db),
                 user: models.User = Depends(require_roles(models.Role.ADMIN))):
    device = db.query(models.Device).filter(models.Device.device_code == req.device_code).first()
    if not device:
        device = models.Device(device_code=req.device_code)
        db.add(device)
        db.commit()
        db.refresh(device)
    zone = models.Zone(name=req.name, location=req.location, device_id=device.id)
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return _zone_out(db, zone)


@router.post("/{zone_id}/assign")
def assign_user(zone_id: str, req: schemas.ZoneAssignUser, db: Session = Depends(get_db),
                 user: models.User = Depends(require_roles(models.Role.ADMIN, models.Role.OPERATOR))):
    zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    target = db.query(models.User).filter(models.User.id == req.user_id).first()
    if not zone or not target:
        raise HTTPException(404, "Zone or user not found")
    if not target.phone_verified:
        raise HTTPException(400, "User's phone must be OTP-verified before they can be assigned to a zone")
    exists = (db.query(models.UserZone)
              .filter(models.UserZone.zone_id == zone_id, models.UserZone.user_id == req.user_id).first())
    if exists:
        return {"detail": "Already assigned"}
    db.add(models.UserZone(user_id=req.user_id, zone_id=zone_id))
    db.add(models.AuditLog(user_id=user.id, action="ZONE_USER_ASSIGNED",
                            detail=f"zone={zone.name} user={target.email}"))
    db.commit()
    return {"detail": "Assigned"}


@router.get("/{zone_id}/readings", response_model=list[schemas.SensorReadingOut])
def zone_readings(zone_id: str, limit: int = 60, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if not zone or not zone.device:
        raise HTTPException(404, "Zone or device not found")
    rows = (db.query(models.SensorReading)
            .filter(models.SensorReading.device_id == zone.device.id)
            .order_by(models.SensorReading.created_at.desc()).limit(limit).all())
    return list(reversed(rows))

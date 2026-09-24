import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..security import get_current_user
from .sensors import ingest_reading
from ..schemas import SensorIngest

router = APIRouter(prefix="/api/simulate", tags=["simulation"])

SCENARIOS = {
    "safe":               dict(mq2=180, mq135=150, pressure=1.0, flame_detected=False),
    "gas_leak":           dict(mq2=820, mq135=300, pressure=1.0, flame_detected=False),
    "pressure_anomaly":   dict(mq2=200, mq135=180, pressure=1.55, flame_detected=False),
    "flame":              dict(mq2=250, mq135=200, pressure=1.0, flame_detected=True),
    "multi_warning":      dict(mq2=450, mq135=450, pressure=1.05, flame_detected=False),
}


@router.post("/event")
async def simulate_event(req: schemas.SimulateEvent, db: Session = Depends(get_db),
                          user: models.User = Depends(get_current_user)):
    zone = db.query(models.Zone).filter(models.Zone.id == req.zone_id).first()
    if not zone or not zone.device:
        raise HTTPException(404, "Zone or device not found")

    if req.scenario == "offline":
        # push the last heartbeat far into the past so the health check marks it OFFLINE
        zone.device.last_heartbeat = datetime.utcnow() - timedelta(hours=1)
        db.commit()
        return {"detail": "Device marked offline for demo purposes"}

    if req.scenario not in SCENARIOS:
        raise HTTPException(400, f"Unknown scenario. Options: {list(SCENARIOS)} + offline")

    payload = SCENARIOS[req.scenario]
    reading_req = SensorIngest(device_code=zone.device.device_code, **payload)
    reading = await ingest_reading(reading_req, db)
    return schemas.SensorReadingOut.model_validate(reading)


@router.post("/random-tick")
async def random_tick(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Nudges every device with small random noise around SAFE baseline — used to keep
    graphs looking 'live' during a demo without manually triggering scenarios each time."""
    results = []
    for device in db.query(models.Device).all():
        payload = SensorIngest(
            device_code=device.device_code,
            mq2=max(0, 180 + random.uniform(-30, 30)),
            mq135=max(0, 150 + random.uniform(-25, 25)),
            pressure=round(1.0 + random.uniform(-0.05, 0.05), 3),
            flame_detected=False,
        )
        results.append(await ingest_reading(payload, db))
    return {"updated": len(results)}


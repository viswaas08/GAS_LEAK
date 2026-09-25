from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import settings
from .. import models, schemas, rules
from ..security import get_current_user, require_roles
from ..websocket_manager import manager

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

PIPELINE_SEGMENTS = [
    {
        "id": "SEG-01",
        "name": "Segment 1 — Primary Compressor Inlet",
        "code": "SEG-01",
        "from_node": "Station Alpha (Main Compressor)",
        "to_node": "Junction Node J1 (High-Pressure Manifold)",
        "specs": "16-inch API-5L Carbon Steel · 2.5 Bar Max",
        "length_km": 3.2,
        "flow_direction": "east",
        "coordinates": {"x1": 70, "y1": 140, "x2": 280, "y2": 140},
    },
    {
        "id": "SEG-02",
        "name": "Segment 2 — Central Transmission Trunk",
        "code": "SEG-02",
        "from_node": "Junction Node J1 (High-Pressure Manifold)",
        "to_node": "Distribution Hub J2 (Central Manifold)",
        "specs": "14-inch Carbon Steel ASTM A106 · 2.2 Bar Max",
        "length_km": 4.8,
        "flow_direction": "east",
        "coordinates": {"x1": 280, "y1": 140, "x2": 540, "y2": 140},
    },
    {
        "id": "SEG-03",
        "name": "Segment 3 — Industrial Processing Loop",
        "code": "SEG-03",
        "from_node": "Distribution Hub J2 (Central Manifold)",
        "to_node": "Substation Gamma (Refinery/Turbine Feed)",
        "specs": "10-inch Stainless Steel 316L · 1.8 Bar Max",
        "length_km": 2.4,
        "flow_direction": "northeast",
        "coordinates": {"x1": 540, "y1": 140, "x2": 780, "y2": 65},
    },
    {
        "id": "SEG-04",
        "name": "Segment 4 — Distribution Feeder & City Gate",
        "code": "SEG-04",
        "from_node": "Distribution Hub J2 (Central Manifold)",
        "to_node": "City Gate Regulating Station Delta",
        "specs": "8-inch Coated High-Grade Polyethylene · 1.2 Bar Max",
        "length_km": 5.6,
        "flow_direction": "southeast",
        "coordinates": {"x1": 540, "y1": 140, "x2": 780, "y2": 215},
    },
    {
        "id": "SEG-05",
        "name": "Segment 5 — Flare & Emergency Vent Bypass",
        "code": "SEG-05",
        "from_node": "Junction Node J1 (High-Pressure Manifold)",
        "to_node": "Emergency Flare Interceptor Stack",
        "specs": "12-inch Heavy-Wall Steel · 3.0 Bar Max · 180° Interceptor",
        "length_km": 1.5,
        "flow_direction": "south",
        "coordinates": {"x1": 280, "y1": 140, "x2": 280, "y2": 270},
    }
]


def get_segment_meta(segment_id: str) -> dict:
    for seg in PIPELINE_SEGMENTS:
        if seg["id"] == segment_id:
            return seg
    return PIPELINE_SEGMENTS[0]


def is_device_online(device: models.Device) -> bool:
    if not device or not device.last_heartbeat:
        return False
    return (datetime.utcnow() - device.last_heartbeat).total_seconds() <= settings.HEARTBEAT_OFFLINE_AFTER_SECONDS


def auto_assign_segment_and_position(db: Session, device_code: str):
    """Automatically assigns a segment and balanced insertion position along that segment."""
    all_devices = db.query(models.Device).all()
    # Count modules per segment
    counts = {s["id"]: 0 for s in PIPELINE_SEGMENTS}
    for d in all_devices:
        if d.device_code != device_code and d.segment_id in counts:
            counts[d.segment_id] += 1

    # Pick segment with least modules
    chosen_segment_id = min(counts.keys(), key=lambda k: counts[k])
    seg_meta = get_segment_meta(chosen_segment_id)
    
    # Calculate offset position ratio
    existing_on_seg = counts[chosen_segment_id]
    if existing_on_seg == 0:
        pos = 0.50
    elif existing_on_seg == 1:
        pos = 0.75
    else:
        pos = min(0.90, max(0.15, 0.2 + 0.25 * existing_on_seg))

    return chosen_segment_id, seg_meta["name"], pos


@router.get("/schematic", response_model=schemas.SchematicOverviewOut)
def get_schematic(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Returns the full pipeline schematic topology, segments, and all inserted modules."""
    devices = db.query(models.Device).all()
    device_map = {}
    for d in devices:
        seg_id = d.segment_id or "SEG-01"
        if seg_id not in device_map:
            device_map[seg_id] = []
        device_map[seg_id].append(d)

    segments_out = []
    total_mods = 0
    online_mods = 0
    crit_count = 0
    warn_count = 0

    for seg in PIPELINE_SEGMENTS:
        seg_id = seg["id"]
        seg_devices = device_map.get(seg_id, [])
        seg_modules = []
        seg_status = "IDLE" if not seg_devices else "SAFE"
        seg_max_mq2 = 0.0
        seg_flame = False
        seg_valve_closed = False
        seg_pressure = 1.02

        for d in seg_devices:
            online = is_device_online(d)
            latest = (db.query(models.SensorReading)
                      .filter(models.SensorReading.device_id == d.id)
                      .order_by(models.SensorReading.created_at.desc()).first())

            status = models.PipelineStatus.OFFLINE if not online else (latest.status if latest else models.PipelineStatus.SAFE)
            total_mods += 1
            if online:
                online_mods += 1
            if status == models.PipelineStatus.CRITICAL:
                crit_count += 1
            elif status == models.PipelineStatus.WARNING:
                warn_count += 1

            latest_out = None
            if online and latest:
                latest_out = schemas.LatestReading(
                    mq2=latest.mq2, mq135=latest.mq135, pressure=latest.pressure,
                    flame_detected=latest.flame_detected, created_at=latest.created_at,
                )
                if latest.mq2 > seg_max_mq2:
                    seg_max_mq2 = latest.mq2
                if latest.flame_detected:
                    seg_flame = True
                seg_pressure = latest.pressure

            if d.valve_state == models.ValveState.CLOSED:
                seg_valve_closed = True

            zone = d.zone
            seg_modules.append(schemas.SchematicModuleOut(
                device_code=d.device_code,
                zone_id=zone.id if zone else None,
                zone_name=zone.name if zone else f"Pipeline {d.device_code}",
                segment_id=seg_id,
                segment_name=d.segment_name or seg["name"],
                position_ratio=d.position_ratio if d.position_ratio is not None else 0.5,
                hardware_type=d.hardware_type or "ESP32-WROOM-32 + MQ-2 + 180° Servo",
                status=status,
                valve_state=d.valve_state,
                device_online=online,
                last_heartbeat=d.last_heartbeat,
                latest=latest_out,
            ))

        # Determine segment-level status based on inserted modules
        if any(m.status == models.PipelineStatus.CRITICAL for m in seg_modules):
            seg_status = "CRITICAL"
        elif any(m.status == models.PipelineStatus.WARNING for m in seg_modules):
            seg_status = "WARNING"
        elif any(m.status == models.PipelineStatus.SAFE for m in seg_modules):
            seg_status = "SAFE"
        elif seg_modules and all(m.status == models.PipelineStatus.OFFLINE for m in seg_modules):
            seg_status = "OFFLINE"
        else:
            seg_status = "IDLE"

        # Sort modules along the segment from 0% to 100% position
        seg_modules.sort(key=lambda m: m.position_ratio)

        segments_out.append(schemas.SchematicSegmentOut(
            id=seg["id"],
            name=seg["name"],
            code=seg["code"],
            from_node=seg["from_node"],
            to_node=seg["to_node"],
            specs=seg["specs"],
            length_km=seg["length_km"],
            flow_direction=seg["flow_direction"],
            coordinates=seg["coordinates"],
            status=seg_status,
            pressure_bar=round(seg_pressure, 2),
            max_mq2=round(seg_max_mq2, 1),
            flame_detected=seg_flame,
            valve_closed=seg_valve_closed,
            modules=seg_modules,
        ))

    overall_status = "CRITICAL" if crit_count > 0 else ("WARNING" if warn_count > 0 else "SAFE")
    if total_mods == 0:
        overall_status = "SAFE"

    return schemas.SchematicOverviewOut(
        segments=segments_out,
        total_modules=total_mods,
        online_modules=online_mods,
        critical_count=crit_count,
        warning_count=warn_count,
        system_status=overall_status,
        timestamp=datetime.utcnow()
    )


@router.post("/modules/connect", response_model=schemas.SchematicModuleOut)
async def connect_module(req: schemas.ModuleConnectRequest, db: Session = Depends(get_db),
                         user: models.User = Depends(require_roles(models.Role.ADMIN, models.Role.OPERATOR))):
    """
    Connects/inserts a new module into a pipeline segment. If segment_id is not specified,
    it automatically detects the optimal pipeline segment and position.
    """
    segment_id = req.segment_id
    if not segment_id or segment_id not in [s["id"] for s in PIPELINE_SEGMENTS]:
        segment_id, seg_name, auto_pos = auto_assign_segment_and_position(db, req.device_code)
        position_ratio = req.position_ratio if req.position_ratio is not None else auto_pos
    else:
        seg_meta = get_segment_meta(segment_id)
        seg_name = seg_meta["name"]
        position_ratio = req.position_ratio if req.position_ratio is not None else 0.5

    device = db.query(models.Device).filter(models.Device.device_code == req.device_code).first()
    if not device:
        device = models.Device(
            device_code=req.device_code,
            segment_id=segment_id,
            segment_name=seg_name,
            position_ratio=position_ratio,
            hardware_type=req.hardware_type or "ESP32-WROOM-32 + MQ-2 + 180° Servo",
            last_heartbeat=datetime.utcnow(),
            valve_state=models.ValveState.OPEN,
        )
        db.add(device)
        db.commit()
        db.refresh(device)
        
        zone = models.Zone(
            name=req.name or f"Pipeline {req.device_code}",
            location=f"{seg_name} (KM {round(position_ratio * get_segment_meta(segment_id)['length_km'], 1)})",
            segment_id=segment_id,
            device_id=device.id,
        )
        db.add(zone)
        db.commit()
        db.refresh(zone)
    else:
        device.segment_id = segment_id
        device.segment_name = seg_name
        device.position_ratio = position_ratio
        if req.hardware_type:
            device.hardware_type = req.hardware_type
        device.last_heartbeat = datetime.utcnow()
        zone = db.query(models.Zone).filter(models.Zone.device_id == device.id).first()
        if zone:
            zone.segment_id = segment_id
            if req.name:
                zone.name = req.name
            zone.location = f"{seg_name} (KM {round(position_ratio * get_segment_meta(segment_id)['length_km'], 1)})"
        db.commit()

    # Create baseline sensor reading
    mq2 = req.initial_mq2 if req.initial_mq2 is not None else 160.0
    flame = req.initial_flame or False
    pressure = req.initial_pressure if req.initial_pressure is not None else 1.02
    status, reason = rules.evaluate(mq2, mq2 * 0.8, pressure, flame)
    
    reading = models.SensorReading(
        device_id=device.id,
        mq2=mq2,
        mq135=round(mq2 * 0.8, 1),
        pressure=pressure,
        flame_detected=flame,
        status=status,
        reason=reason,
    )
    db.add(reading)

    db.add(models.AuditLog(
        user_id=user.id,
        module="ZONES",
        action="MODULE_INSERTED",
        detail=f"Module {device.device_code} inserted into {seg_name} at {int(position_ratio*100)}% offset",
    ))
    db.commit()

    # Broadcast real-time module connection event
    await manager.broadcast("module_connected", {
        "device_code": device.device_code,
        "segment_id": segment_id,
        "segment_name": seg_name,
        "position_ratio": position_ratio,
        "hardware_type": device.hardware_type,
        "zone_id": zone.id if zone else None,
        "zone_name": zone.name if zone else f"Pipeline {device.device_code}",
        "mq2": mq2,
        "flame": flame,
        "status": status.value,
        "valve_state": device.valve_state.value,
        "timestamp": datetime.utcnow().isoformat(),
    })

    return schemas.SchematicModuleOut(
        device_code=device.device_code,
        zone_id=zone.id if zone else None,
        zone_name=zone.name if zone else f"Pipeline {device.device_code}",
        segment_id=segment_id,
        segment_name=seg_name,
        position_ratio=position_ratio,
        hardware_type=device.hardware_type,
        status=status,
        valve_state=device.valve_state,
        device_online=True,
        last_heartbeat=device.last_heartbeat,
        latest=schemas.LatestReading(
            mq2=reading.mq2, mq135=reading.mq135, pressure=reading.pressure,
            flame_detected=reading.flame_detected, created_at=reading.created_at,
        ),
    )


@router.put("/modules/{device_code}/position")
async def update_module_position(device_code: str, req: schemas.ModulePositionUpdate, db: Session = Depends(get_db),
                                 user: models.User = Depends(require_roles(models.Role.ADMIN))):
    """Moves a module to another segment or adjusts its position along the pipeline."""
    device = db.query(models.Device).filter(models.Device.device_code == device_code).first()
    if not device:
        raise HTTPException(404, f"Device {device_code} not found")

    seg_meta = get_segment_meta(req.segment_id)
    device.segment_id = req.segment_id
    device.segment_name = seg_meta["name"]
    device.position_ratio = req.position_ratio

    zone = db.query(models.Zone).filter(models.Zone.device_id == device.id).first()
    if zone:
        zone.segment_id = req.segment_id
        zone.location = f"{seg_meta['name']} (KM {round(req.position_ratio * seg_meta['length_km'], 1)})"

    db.add(models.AuditLog(
        user_id=user.id,
        module="ZONES",
        action="MODULE_REPOSITIONED",
        detail=f"Module {device_code} repositioned to {seg_meta['name']} at {int(req.position_ratio*100)}%",
    ))
    db.commit()

    await manager.broadcast("module_repositioned", {
        "device_code": device_code,
        "segment_id": req.segment_id,
        "segment_name": seg_meta["name"],
        "position_ratio": req.position_ratio,
    })

    return {"detail": "Module position updated successfully", "segment_id": req.segment_id, "position_ratio": req.position_ratio}


@router.delete("/modules/{device_code}")
async def disconnect_module(device_code: str, db: Session = Depends(get_db),
                            user: models.User = Depends(require_roles(models.Role.ADMIN))):
    """Disconnects / removes a hardware module from the pipeline."""
    device = db.query(models.Device).filter(models.Device.device_code == device_code).first()
    if not device:
        raise HTTPException(404, f"Device {device_code} not found")

    seg_id = device.segment_id
    seg_name = device.segment_name or "Pipeline"

    zone = db.query(models.Zone).filter(models.Zone.device_id == device.id).first()
    if zone:
        db.delete(zone)
    db.delete(device)

    db.add(models.AuditLog(
        user_id=user.id,
        module="ZONES",
        action="MODULE_DISCONNECTED",
        detail=f"Module {device_code} removed from {seg_name}",
    ))
    db.commit()

    await manager.broadcast("module_disconnected", {
        "device_code": device_code,
        "segment_id": seg_id,
    })

    return {"detail": f"Module {device_code} disconnected"}


@router.post("/scan-detect")
async def scan_and_detect_modules(db: Session = Depends(get_db),
                                  user: models.User = Depends(require_roles(models.Role.ADMIN, models.Role.OPERATOR))):
    """
    Scans for connected devices and automatically binds any unlinked devices
    to appropriate pipeline segments.
    """
    devices = db.query(models.Device).all()
    assigned = 0
    for d in devices:
        if not d.segment_id or d.segment_id not in [s["id"] for s in PIPELINE_SEGMENTS]:
            seg_id, seg_name, pos = auto_assign_segment_and_position(db, d.device_code)
            d.segment_id = seg_id
            d.segment_name = seg_name
            d.position_ratio = pos
            zone = db.query(models.Zone).filter(models.Zone.device_id == d.id).first()
            if zone:
                zone.segment_id = seg_id
            assigned += 1

    if assigned > 0:
        db.commit()

    return {
        "status": "ok",
        "scanned_devices": len(devices),
        "newly_mapped": assigned,
        "message": f"Scan complete. {len(devices)} active modules synchronized to pipeline schematic.",
    }

import io
import csv
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..security import require_roles

router = APIRouter(prefix="/api/audit", tags=["audit"])

# Standard System Modules definitions
MODULE_DEFINITIONS = [
    {
        "id": "AUTH",
        "name": "Auth & Access Control",
        "icon": "🔐",
        "tag": "Authentication",
        "description": "User authentication, registrations, phone OTP verification, and session security."
    },
    {
        "id": "ACTUATOR",
        "name": "180° Valve Interception",
        "icon": "🚨",
        "tag": "Actuator",
        "description": "180° servo emergency shutoffs, hardware command dispatches, and valve isolation."
    },
    {
        "id": "INCIDENTS",
        "name": "Hazard Incidents & Alarms",
        "icon": "⚠️",
        "tag": "Safety Incidents",
        "description": "Gas leak incidents, flame alarms, operator acknowledgements, and SMS dispatch."
    },
    {
        "id": "ZONES",
        "name": "Pipeline Zones & Grid",
        "icon": "🏭",
        "tag": "Infrastructure",
        "description": "Physical pipeline zone creation, operator sector assignments, and line configurations."
    },
    {
        "id": "SENSORS",
        "name": "Sensors & Telemetry",
        "icon": "📡",
        "tag": "Telemetry",
        "description": "MQ-2 gas stream, MQ-135 air index, flame IR optical sensors, and device heartbeats."
    },
    {
        "id": "SIMULATION",
        "name": "Simulation & Bridge",
        "icon": "⚡",
        "tag": "Simulator",
        "description": "Virtual scenario injections, hazard simulation runs, and Arduino/ESP32 bridge sync."
    },
]

def resolve_module(action: str, module: Optional[str] = None) -> str:
    if module and module.strip() and module.upper() not in ("SYSTEM", "ALL", "NONE", ""):
        return module.upper()
    act = (action or "").upper()
    if any(k in act for k in ["LOGIN", "REGISTER", "AUTH", "PASSWORD", "PHONE", "USER_REG", "TOKEN", "CREDENTIAL"]):
        if "ZONE_USER" in act:
            return "ZONES"
        return "AUTH"
    if any(k in act for k in ["SHUTOFF", "VALVE", "ACTUATOR", "SERVO", "INTERCEPTION"]):
        return "ACTUATOR"
    if any(k in act for k in ["INCIDENT", "ALARM", "HAZARD", "ACKNOWLEDGE", "SMS", "ALERT"]):
        return "INCIDENTS"
    if any(k in act for k in ["ZONE", "PIPELINE_UNIT", "GRID"]):
        return "ZONES"
    if any(k in act for k in ["SENSOR", "MQ2", "MQ135", "FLAME", "TELEMETRY", "READING"]):
        return "SENSORS"
    if any(k in act for k in ["SIMULAT", "SCENARIO", "RANDOM"]):
        return "SIMULATION"
    return "SYSTEM"


@router.get("/modules")
def get_audit_modules(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.Role.ADMIN, models.Role.OPERATOR))
):
    """
    Returns available system modules with their real-time audit record counts,
    allowing users to choose which module's audit trail to inspect.
    """
    all_logs = db.query(models.AuditLog).all()
    counts = {m["id"]: 0 for m in MODULE_DEFINITIONS}
    last_times = {m["id"]: None for m in MODULE_DEFINITIONS}

    for log in all_logs:
        mod = resolve_module(log.action, getattr(log, "module", None))
        if mod in counts:
            counts[mod] += 1
            if not last_times[mod] or log.created_at > last_times[mod]:
                last_times[mod] = log.created_at

    modules_out = []
    for m in MODULE_DEFINITIONS:
        modules_out.append({
            **m,
            "count": counts[m["id"]],
            "last_event_at": last_times[m["id"]]
        })

    return modules_out


@router.get("")
def list_audit(
    module: Optional[str] = Query(None, description="Module code (e.g. AUTH, ACTUATOR, INCIDENTS, ZONES, SENSORS, SIMULATION)"),
    search: Optional[str] = Query(None, description="Search term within module audit logs"),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.Role.ADMIN, models.Role.OPERATOR))
):
    """
    Module-isolated audit retrieval:
    The audit trail is separated for each module and can only be viewed by selecting the corresponding module.
    If no module is specified, returns 400 Bad Request instructing the user to select a module.
    """
    if not module:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audit logs are isolated per module. Please select a specific module (e.g. AUTH, ACTUATOR, INCIDENTS, ZONES, SENSORS, SIMULATION) to view its audit trail."
        )

    target_mod = module.strip().upper()
    rows = db.query(models.AuditLog).order_by(models.AuditLog.created_at.desc()).limit(500).all()

    filtered_logs = []
    for r in rows:
        r_mod = resolve_module(r.action, getattr(r, "module", None))
        if r_mod == target_mod:
            if search:
                s = search.lower()
                action_match = s in (r.action or "").lower()
                detail_match = s in (r.detail or "").lower()
                user_match = s in (r.user_id or "").lower()
                if not (action_match or detail_match or user_match):
                    continue
            filtered_logs.append({
                "id": r.id,
                "user_id": r.user_id,
                "module": r_mod,
                "action": r.action,
                "detail": r.detail,
                "created_at": r.created_at
            })

    mod_info = next((m for m in MODULE_DEFINITIONS if m["id"] == target_mod), {
        "id": target_mod, "name": f"{target_mod} Module", "icon": "📋", "description": ""
    })

    return {
        "module": mod_info,
        "total_records": len(filtered_logs),
        "logs": filtered_logs
    }


@router.get("/export.csv")
def export_module_audit_csv(
    module: str = Query(..., description="Module code to export"),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.Role.ADMIN, models.Role.OPERATOR))
):
    """Export audit trail for the selected module as CSV."""
    target_mod = module.strip().upper()
    rows = db.query(models.AuditLog).order_by(models.AuditLog.created_at.desc()).all()
    filtered = [r for r in rows if resolve_module(r.action, getattr(r, "module", None)) == target_mod]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "module", "user_id", "action", "detail", "created_at"])
    for r in filtered:
        writer.writerow([r.id, target_mod, r.user_id, r.action, r.detail, r.created_at])
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=audit_{target_mod.lower()}.csv"}
    )


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_db), user: models.User = Depends(require_roles(models.Role.ADMIN, models.Role.OPERATOR))):
    return db.query(models.User).all()

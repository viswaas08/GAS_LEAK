import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..security import get_current_user, require_roles

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("", response_model=list[schemas.IncidentOut])
def list_incidents(zone_id: str | None = None, status: str | None = None,
                    resolved: bool | None = None, q: str | None = Query(None, description="search text"),
                    db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    query = db.query(models.Incident)
    if zone_id:
        query = query.filter(models.Incident.zone_id == zone_id)
    if status:
        query = query.filter(models.Incident.status == status)
    if resolved is not None:
        query = query.filter(models.Incident.resolved == resolved)
    if q:
        query = query.filter(models.Incident.reason.ilike(f"%{q}%"))
    return query.order_by(models.Incident.created_at.desc()).all()


@router.post("/{incident_id}/acknowledge", response_model=schemas.IncidentOut)
def acknowledge(incident_id: str, req: schemas.AcknowledgeRequest, db: Session = Depends(get_db),
                 user: models.User = Depends(require_roles(models.Role.ADMIN, models.Role.OPERATOR))):
    incident = db.query(models.Incident).filter(models.Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(404, "Incident not found")
    incident.acknowledged_by = user.name
    db.add(models.IncidentEvent(incident_id=incident.id,
                                 event=f"Operator acknowledged by {user.name}" + (f" — {req.note}" if req.note else "")))
    db.add(models.AuditLog(user_id=user.id, action="INCIDENT_ACKNOWLEDGED", detail=incident_id))
    db.commit()
    db.refresh(incident)
    return incident


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    rows = db.query(models.Incident).order_by(models.Incident.created_at.desc()).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "zone_id", "status", "reason", "resolved", "acknowledged_by",
                      "sms_sent", "created_at", "resolved_at"])
    for r in rows:
        writer.writerow([r.id, r.zone_id, r.status.value, r.reason, r.resolved, r.acknowledged_by,
                          r.sms_sent, r.created_at, r.resolved_at])
    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv",
                              headers={"Content-Disposition": "attachment; filename=incidents.csv"})

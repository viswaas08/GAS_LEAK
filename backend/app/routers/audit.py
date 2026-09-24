from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..security import require_roles

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def list_audit(db: Session = Depends(get_db), user: models.User = Depends(require_roles(models.Role.ADMIN))):
    rows = db.query(models.AuditLog).order_by(models.AuditLog.created_at.desc()).limit(200).all()
    return [{"id": r.id, "user_id": r.user_id, "action": r.action, "detail": r.detail,
             "created_at": r.created_at} for r in rows]


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_db), user: models.User = Depends(require_roles(models.Role.ADMIN, models.Role.OPERATOR))):
    return db.query(models.User).all()

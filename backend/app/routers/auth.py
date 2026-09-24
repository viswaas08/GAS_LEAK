import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import settings
from .. import models, schemas, sms
from ..security import hash_password, verify_password, hash_otp, create_access_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


def log_audit(db: Session, user_id: str, action: str, detail: str = ""):
    db.add(models.AuditLog(user_id=user_id, action=action, detail=detail))
    db.commit()


@router.post("/register", response_model=schemas.UserOut)
def register(req: schemas.RegisterRequest, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.email == req.email).first():
        raise HTTPException(400, "Email already registered")
    if db.query(models.User).filter(models.User.phone == req.phone).first():
        raise HTTPException(400, "Phone already registered")

    # First registered user becomes admin; rest default to viewer (an admin can promote later)
    is_first_user = db.query(models.User).count() == 0
    user = models.User(
        name=req.name, email=req.email, phone=req.phone,
        password_hash=hash_password(req.password),
        role=models.Role.ADMIN if is_first_user else models.Role.VIEWER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_audit(db, user.id, "USER_REGISTERED", f"email={req.email}")
    return user


@router.post("/login", response_model=schemas.TokenResponse)
def login(req: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == req.email).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    token = create_access_token(user.id, user.role.value)
    log_audit(db, user.id, "LOGIN", "")
    return schemas.TokenResponse(access_token=token, role=user.role, user_id=user.id,
                                  phone_verified=user.phone_verified)


@router.post("/otp/request")
def request_otp(req: schemas.OTPRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.phone == req.phone).first()
    if not user:
        raise HTTPException(404, "No account with that phone number")
    code = f"{random.randint(0, 999999):06d}"
    otp = models.OTPCode(
        phone=req.phone,
        code_hash=hash_otp(code),
        expires_at=datetime.utcnow() + timedelta(seconds=settings.OTP_TTL_SECONDS),
    )
    db.add(otp)
    db.commit()
    sms.send_sms(db, req.phone, sms.format_otp_sms(code))
    return {"detail": "OTP sent", "ttl_seconds": settings.OTP_TTL_SECONDS}


@router.post("/otp/verify")
def verify_otp(req: schemas.OTPVerifyRequest, db: Session = Depends(get_db)):
    otp = (db.query(models.OTPCode)
           .filter(models.OTPCode.phone == req.phone, models.OTPCode.consumed == False)
           .order_by(models.OTPCode.expires_at.desc()).first())
    if not otp or otp.expires_at < datetime.utcnow():
        raise HTTPException(400, "OTP expired or not found — request a new one")
    if otp.code_hash != hash_otp(req.code):
        raise HTTPException(400, "Incorrect OTP")
    otp.consumed = True
    user = db.query(models.User).filter(models.User.phone == req.phone).first()
    user.phone_verified = True
    db.commit()
    log_audit(db, user.id, "PHONE_VERIFIED", "")
    return {"detail": "Phone verified"}


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return user

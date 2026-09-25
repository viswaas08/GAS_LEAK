from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field

from .models import Role, PipelineStatus, ValveState


# ---------- Auth ----------
class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    phone: str = Field(..., description="E.164 format, e.g. +919876543210")
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role
    user_id: str
    phone_verified: bool


class OTPRequest(BaseModel):
    phone: str


class OTPVerifyRequest(BaseModel):
    phone: str
    code: str


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    phone: str
    role: Role
    phone_verified: bool
    class Config:
        from_attributes = True


# ---------- Zones ----------
class ZoneCreate(BaseModel):
    name: str
    location: Optional[str] = None
    device_code: str


class ZoneAssignUser(BaseModel):
    user_id: str


class LatestReading(BaseModel):
    mq2: float
    mq135: float
    pressure: float
    flame_detected: bool
    created_at: datetime


class ZoneOut(BaseModel):
    id: str
    name: str
    location: Optional[str]
    device_code: Optional[str] = None
    status: PipelineStatus = PipelineStatus.OFFLINE
    valve_state: ValveState = ValveState.UNKNOWN
    device_online: bool = False
    last_heartbeat: Optional[datetime] = None
    latest: Optional[LatestReading] = None
    class Config:
        from_attributes = True


# ---------- Sensor ingestion (simulates ESP32 -> MQTT bridge -> backend) ----------
class SensorIngest(BaseModel):
    device_code: str
    mq2: float
    mq135: float
    pressure: float
    flame_detected: bool = False


class SensorReadingOut(BaseModel):
    mq2: float
    mq135: float
    pressure: float
    flame_detected: bool
    status: PipelineStatus
    reason: Optional[str]
    valve_state: Optional[str] = None
    created_at: datetime
    class Config:
        from_attributes = True


# ---------- Incidents ----------
class IncidentEventOut(BaseModel):
    event: str
    created_at: datetime
    class Config:
        from_attributes = True


class IncidentOut(BaseModel):
    id: str
    zone_id: str
    status: PipelineStatus
    reason: str
    resolved: bool
    acknowledged_by: Optional[str]
    sms_sent: bool
    created_at: datetime
    resolved_at: Optional[datetime]
    timeline_events: List[IncidentEventOut] = []
    class Config:
        from_attributes = True


class AcknowledgeRequest(BaseModel):
    note: Optional[str] = None


# ---------- Actuator ----------
class ShutoffCommand(BaseModel):
    zone_id: str
    confirm: bool = Field(..., description="Must be true — UI must show a confirmation dialog first")


class ValveControlCommand(BaseModel):
    zone_id: str
    target_state: str = Field(..., description="OPEN (valve ON / 0 deg) or CLOSED (valve OFF / 180 deg)")


class ValveStatusOut(BaseModel):
    zone_id: str
    valve_state: ValveState
    updated_at: Optional[datetime]


# ---------- Simulation ----------
class SimulateEvent(BaseModel):
    zone_id: str
    scenario: str = Field(..., description="gas_leak | pressure_anomaly | flame | offline | safe | "
                                            "valve_ack_success | valve_ack_fail")

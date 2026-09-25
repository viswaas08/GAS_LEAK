import enum
import uuid
from datetime import datetime

from sqlalchemy import (Column, String, Float, Boolean, DateTime, Enum, ForeignKey,
                         Integer, Text)
from sqlalchemy.orm import relationship

from .database import Base


def gen_id():
    return str(uuid.uuid4())


class Role(str, enum.Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class PipelineStatus(str, enum.Enum):
    SAFE = "SAFE"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    OFFLINE = "OFFLINE"


class ValveState(str, enum.Enum):
    OPEN = "OPEN"
    COMMAND_SENT = "COMMAND_SENT"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    CLOSED = "CLOSED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    phone = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(Enum(Role), default=Role.VIEWER, nullable=False)
    phone_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    zone_links = relationship("UserZone", back_populates="user", cascade="all, delete-orphan")


class Zone(Base):
    __tablename__ = "zones"
    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)              # e.g. "Zone 01"
    location = Column(String, nullable=True)
    device_id = Column(String, ForeignKey("devices.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    device = relationship("Device", back_populates="zone", uselist=False)
    user_links = relationship("UserZone", back_populates="zone", cascade="all, delete-orphan")


class UserZone(Base):
    """Many-to-many: which verified users get SMS alerts for which zone."""
    __tablename__ = "user_zones"
    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    zone_id = Column(String, ForeignKey("zones.id"), nullable=False)

    user = relationship("User", back_populates="zone_links")
    zone = relationship("Zone", back_populates="user_links")


class Device(Base):
    __tablename__ = "devices"
    id = Column(String, primary_key=True, default=gen_id)
    device_code = Column(String, unique=True, nullable=False)  # e.g. "ESP32-01"
    zone = relationship("Zone", back_populates="device", uselist=False)
    last_heartbeat = Column(DateTime, nullable=True)
    firmware_version = Column(String, default="1.0.0")
    valve_state = Column(Enum(ValveState), default=ValveState.OPEN)
    valve_command_id = Column(String, nullable=True)
    valve_command_sent_at = Column(DateTime, nullable=True)


class SensorReading(Base):
    __tablename__ = "sensor_readings"
    id = Column(String, primary_key=True, default=gen_id)
    device_id = Column(String, ForeignKey("devices.id"), nullable=False)
    mq2 = Column(Float, nullable=False)
    mq135 = Column(Float, nullable=False)
    pressure = Column(Float, nullable=False)
    flame_detected = Column(Boolean, default=False)
    status = Column(Enum(PipelineStatus), default=PipelineStatus.SAFE)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Incident(Base):
    __tablename__ = "incidents"
    id = Column(String, primary_key=True, default=gen_id)
    zone_id = Column(String, ForeignKey("zones.id"), nullable=False)
    status = Column(Enum(PipelineStatus), nullable=False)
    reason = Column(String, nullable=False)
    resolved = Column(Boolean, default=False)
    acknowledged_by = Column(String, nullable=True)
    sms_sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    resolved_at = Column(DateTime, nullable=True)

    timeline_events = relationship("IncidentEvent", back_populates="incident",
                                    cascade="all, delete-orphan", order_by="IncidentEvent.created_at")


class IncidentEvent(Base):
    __tablename__ = "incident_events"
    id = Column(String, primary_key=True, default=gen_id)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=False)
    event = Column(String, nullable=False)  # human-readable timeline step
    created_at = Column(DateTime, default=datetime.utcnow)

    incident = relationship("Incident", back_populates="timeline_events")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, nullable=True)
    module = Column(String, nullable=True, default="SYSTEM", index=True)
    action = Column(String, nullable=False)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class OTPCode(Base):
    __tablename__ = "otp_codes"
    id = Column(String, primary_key=True, default=gen_id)
    phone = Column(String, nullable=False, index=True)
    code_hash = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    consumed = Column(Boolean, default=False)


class SMSLog(Base):
    __tablename__ = "sms_logs"
    id = Column(String, primary_key=True, default=gen_id)
    phone = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    provider = Column(String, default="simulated")
    status = Column(String, default="sent")
    created_at = Column(DateTime, default=datetime.utcnow)

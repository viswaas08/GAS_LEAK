"""
Central configuration. All secrets are pulled from environment variables.
For the prototype, sensible defaults are provided via a local .env file
(see .env.example) — in production these MUST be overridden.
"""
import os
from datetime import timedelta
from pathlib import Path

# Automatically load local .env if present
for possible_env in [
    Path(__file__).resolve().parent.parent / ".env",
    Path.cwd() / ".env",
    Path.cwd() / "backend" / ".env"
]:
    if possible_env.exists():
        with open(possible_env, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
        break

class Settings:
    # --- Security ---
    JWT_SECRET: str = os.getenv("JWT_SECRET", "CHANGE_ME_DEV_ONLY_SECRET")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

    # --- Database ---
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./pipeline_gas.db")
    # In production, point this at PostgreSQL, e.g.:
    # postgresql+psycopg2://user:password@host:5432/pipeline_gas

    # --- OTP ---
    OTP_LENGTH: int = 6
    OTP_TTL_SECONDS: int = 300  # 5 minutes

    # --- SMS provider (simulated by default) ---
    SMS_PROVIDER: str = os.getenv("SMS_PROVIDER", "simulated")  # "simulated" | "twilio"
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER: str = os.getenv("TWILIO_FROM_NUMBER", "")

    # --- Actuator / MQTT bridge ---
    MQTT_BROKER_HOST: str = os.getenv("MQTT_BROKER_HOST", "localhost")
    MQTT_BROKER_PORT: int = int(os.getenv("MQTT_BROKER_PORT", "8883"))  # 8883 = MQTT over TLS
    MQTT_USE_TLS: bool = os.getenv("MQTT_USE_TLS", "true").lower() == "true"
    ACTUATOR_COMMAND_TIMEOUT_SECONDS: int = int(os.getenv("ACTUATOR_COMMAND_TIMEOUT_SECONDS", "20"))

    # --- Sensor thresholds (rule-based, not AI) ---
    MQ2_WARNING: float = float(os.getenv("MQ2_WARNING", "100.0"))
    MQ2_CRITICAL: float = float(os.getenv("MQ2_CRITICAL", "300.0"))
    MQ135_WARNING: float = float(os.getenv("MQ135_WARNING", "100.0"))
    MQ135_CRITICAL: float = float(os.getenv("MQ135_CRITICAL", "300.0"))
    PRESSURE_MIN_SAFE: float = 0.8   # bar, relative
    PRESSURE_MAX_SAFE: float = 1.2
    PRESSURE_WARNING_BAND: float = 0.15  # extra band beyond safe before CRITICAL

    # --- Device health ---
    HEARTBEAT_OFFLINE_AFTER_SECONDS: int = int(os.getenv("HEARTBEAT_OFFLINE_AFTER_SECONDS", "30"))

    CORS_ORIGINS = ["*"]  # tighten in production

settings = Settings()

ACCESS_TOKEN_EXPIRE = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

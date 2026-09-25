-- Reference schema — for documentation only.
-- The backend creates these tables automatically via SQLAlchemy
-- (see backend/app/models.py) against DATABASE_URL (SQLite by default,
-- point it at PostgreSQL for production — see backend/.env.example).
-- This file mirrors that schema in plain SQL for readers who want a
-- database-first view of the system.

CREATE TABLE users (
    id              VARCHAR PRIMARY KEY,
    name            VARCHAR NOT NULL,
    email           VARCHAR UNIQUE NOT NULL,
    phone           VARCHAR UNIQUE NOT NULL,
    password_hash   VARCHAR NOT NULL,
    role            VARCHAR NOT NULL DEFAULT 'viewer',   -- admin | operator | viewer
    phone_verified  BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE devices (
    id                      VARCHAR PRIMARY KEY,
    device_code             VARCHAR UNIQUE NOT NULL,      -- e.g. 'ESP32-01'
    last_heartbeat          TIMESTAMP,
    firmware_version        VARCHAR DEFAULT '1.0.0',
    valve_state             VARCHAR DEFAULT 'OPEN',
    valve_command_id        VARCHAR,
    valve_command_sent_at   TIMESTAMP
);

CREATE TABLE zones (
    id          VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL,
    location    VARCHAR,
    device_id   VARCHAR REFERENCES devices(id),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE user_zones (                                 -- who gets SMS alerts for which zone
    id       VARCHAR PRIMARY KEY,
    user_id  VARCHAR REFERENCES users(id),
    zone_id  VARCHAR REFERENCES zones(id)
);

CREATE TABLE sensor_readings (
    id              VARCHAR PRIMARY KEY,
    device_id       VARCHAR REFERENCES devices(id),
    mq2             FLOAT NOT NULL,
    mq135           FLOAT NOT NULL,
    pressure        FLOAT NOT NULL,
    flame_detected  BOOLEAN DEFAULT FALSE,
    status          VARCHAR,                               -- SAFE | WARNING | CRITICAL | OFFLINE
    reason          VARCHAR,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_sensor_readings_created_at ON sensor_readings(created_at);

CREATE TABLE incidents (
    id              VARCHAR PRIMARY KEY,
    zone_id         VARCHAR REFERENCES zones(id),
    status          VARCHAR NOT NULL,
    reason          VARCHAR NOT NULL,
    resolved        BOOLEAN DEFAULT FALSE,
    acknowledged_by VARCHAR,
    sms_sent        BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at     TIMESTAMP
);

CREATE TABLE incident_events (
    id           VARCHAR PRIMARY KEY,
    incident_id  VARCHAR REFERENCES incidents(id),
    event        VARCHAR NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE audit_logs (
    id          VARCHAR PRIMARY KEY,
    user_id     VARCHAR,
    module      VARCHAR DEFAULT 'SYSTEM',
    action      VARCHAR NOT NULL,
    detail      TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE otp_codes (
    id          VARCHAR PRIMARY KEY,
    phone       VARCHAR NOT NULL,
    code_hash   VARCHAR NOT NULL,
    expires_at  TIMESTAMP NOT NULL,
    consumed    BOOLEAN DEFAULT FALSE
);

CREATE TABLE sms_logs (
    id          VARCHAR PRIMARY KEY,
    phone       VARCHAR NOT NULL,
    message     TEXT NOT NULL,
    provider    VARCHAR DEFAULT 'simulated',
    status      VARCHAR DEFAULT 'sent',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

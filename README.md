# PipelineGuard — Smart Pipeline Gas Leak Detection, Monitoring, Alerting & Remote Shutoff

A full-stack prototype control-room system for monitoring gas pipeline
zones (ESP32 + sensors), detecting leaks with transparent rule-based logic,
alerting assigned users by SMS, and issuing a confirmed remote shutoff
command with a real command→acknowledgement state machine.

> **Safety scope.** This is an academic/prototype system. The "actuator"
> is a safe, simulated demonstration mechanism (relay/LED/servo) — see
> `esp32-firmware/README.md`. It is **not** certified equipment and must
> never be connected to a live gas installation.

## What's real vs. simulated in this prototype

| Piece | Status |
|---|---|
| Backend (FastAPI), rule engine, auth, OTP, incidents, audit log, shutoff state machine | **Fully functional**, runs end-to-end |
| Dashboard frontend | **Fully functional**, live via WebSocket |
| ESP32 ↔ backend transport | Simulated over plain HTTP (`/api/sensors`) for the demo; `esp32-firmware/firmware.ino` is reference code for the real MQTT/TLS path |
| SMS delivery | Simulated by default (logged to console + `sms_logs` table); swap to Twilio by setting `SMS_PROVIDER=twilio` + credentials — zero other code changes needed |
| Database | SQLite by default (zero setup); point `DATABASE_URL` at PostgreSQL for production (see `database/schema.sql`) |

## Quick start

```bash
cd backend
python -m venv venv && source venv/bin/activate      # optional but recommended
pip install -r requirements.txt
python -m app.seed          # creates 3 demo zones + an admin login
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000** — the backend also serves the frontend
directly, so there's nothing else to run for the UI itself.

**Demo admin login:** `admin@pipelineguard.io` / `Admin@12345`

To see live-looking telemetry and graphs without touching the dashboard,
run the software ESP32 stand-in in a second terminal:

```bash
python simulator/esp32_simulator.py
```

To inject a real leak/flame/pressure event and watch detection → alert →
incident → (optionally) shutoff happen live, use the **Demo simulation**
panel on the dashboard, or:

```bash
curl -X POST http://localhost:8000/api/simulate/event \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"zone_id":"<zone-id>","scenario":"gas_leak"}'
```

## Architecture

```
ESP32 (firmware.ino, reference)          esp32_simulator.py (used for this demo)
        │  MQTT/TLS                              │  HTTP
        ▼                                         ▼
   MQTT broker  ──▶ MQTT-HTTP bridge ──▶   POST /api/sensors  (FastAPI backend)
                                                   │
                                     rule engine (rules.py) → SAFE/WARNING/CRITICAL
                                                   │
                                    incident created/escalated + SMS to assigned users
                                                   │
                                     WebSocket broadcast ──▶ dashboard (live update)

Dashboard "Emergency shutoff" ──▶ POST /api/actuator/shutoff ──▶ MQTT cmd ──▶ ESP32
                                        (state: COMMAND_SENT → WAITING_CONFIRMATION)
ESP32 actuator confirms ──▶ POST /api/actuator/ack ──▶ state: CLOSED/FAILED → SMS confirmation
```

## Project layout

```
backend/            FastAPI app — auth, zones, sensors, incidents, actuator, simulation, audit
frontend/            Static dashboard (vanilla HTML/CSS/JS + Chart.js, no build step)
esp32-firmware/      Reference Arduino firmware + integration notes
simulator/           Software ESP32 stand-in used for this demo
database/            Reference SQL schema (mirrors backend/app/models.py)
```

## Security implemented

Password hashing (PBKDF2-HMAC-SHA256), JWT auth, OTP phone verification,
role-based access (admin/operator/viewer) enforced server-side on every
protected route, audit logging of logins/acknowledgements/shutoff
commands, environment-variable-driven secrets (`.env.example`). HTTPS and
MQTT/TLS termination are deployment-environment concerns (e.g. behind
Nginx/a load balancer) — the app is written to sit behind them but this
prototype's dev server runs plain HTTP/WS for local testing.

## Extending to real hardware

See `esp32-firmware/README.md` for the concrete steps (flash firmware,
run an MQTT broker, add a small MQTT↔HTTP bridge service). No backend or
frontend code changes are required — they already speak the production
`POST /api/sensors` / `POST /api/actuator/ack` contract; only the
transport in front of it changes from the simulator to real MQTT.

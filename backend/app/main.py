from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from sqlalchemy import text
from .database import Base, engine, is_sqlite
from .config import settings
from .websocket_manager import manager
from .routers import auth, zones, sensors, incidents, actuator, simulation, audit

Base.metadata.create_all(bind=engine)
try:
    with engine.begin() as conn:
        if is_sqlite:
            res = conn.execute(text("PRAGMA table_info(audit_logs)")).fetchall()
            cols = [r[1] for r in res]
            if "module" not in cols:
                conn.execute(text("ALTER TABLE audit_logs ADD COLUMN module VARCHAR DEFAULT 'SYSTEM'"))
        else:
            conn.execute(text("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS module VARCHAR DEFAULT 'SYSTEM'"))
except Exception as _mig_err:
    pass

try:
    from . import seed
    seed.run()
except Exception as _seed_err:
    pass

app = FastAPI(title="Smart Pipeline Gas Leak Detection & Shutoff System", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(zones.router)
app.include_router(sensors.router)
app.include_router(incidents.router)
app.include_router(actuator.router)
app.include_router(simulation.router)
app.include_router(audit.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "pipeline-gas-leak-backend"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # frontend doesn't send anything meaningful; keeps socket alive
    except WebSocketDisconnect:
        manager.disconnect(ws)


# Serve the frontend as static files if present (so `uvicorn app.main:app` alone can
# run the whole demo). In production you'd typically serve the frontend separately
_frontend_dir = os.getenv("FRONTEND_DIR") or os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if not os.path.isdir(_frontend_dir):
    # Fallback to local frontend or /app/frontend
    for candidate in ["./frontend", "/app/frontend", "../frontend"]:
        if os.path.isdir(candidate):
            _frontend_dir = candidate
            break

if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")

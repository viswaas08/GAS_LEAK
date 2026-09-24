"""
Run with: python -m app.seed
Creates 3 demo zones/devices and an admin account so the dashboard isn't
empty on first launch.
"""
from datetime import datetime
from .database import SessionLocal, Base, engine
from . import models
from .security import hash_password

Base.metadata.create_all(bind=engine)


def run():
    db = SessionLocal()
    try:
        if db.query(models.User).count() == 0:
            admin = models.User(
                name="Admin", email="admin@pipelineguard.io", phone="+910000000000",
                password_hash=hash_password("Admin@12345"),
                role=models.Role.ADMIN, phone_verified=True,
            )
            db.add(admin)
            print("Created admin login -> admin@pipelineguard.io / Admin@12345")

        for i in range(1, 4):
            code = f"ESP32-0{i}"
            if db.query(models.Device).filter(models.Device.device_code == code).first():
                continue
            device = models.Device(device_code=code, last_heartbeat=datetime.utcnow())
            db.add(device)
            db.commit()
            db.refresh(device)
            zone = models.Zone(name=f"Pipeline {i:02d}", location=f"Sector {i}", device_id=device.id)
            db.add(zone)
        db.commit()
        print("Seed complete.")
    finally:
        db.close()


if __name__ == "__main__":
    run()

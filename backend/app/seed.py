"""
Run with: python -m app.seed
Initializes the system by ensuring the Admin account exists.
No demo data is added — live zones and readings are populated by physical ESP32 devices.
"""
from datetime import datetime
from .database import SessionLocal, Base, engine
from . import models
from .security import hash_password

Base.metadata.create_all(bind=engine)


def run():
    db = SessionLocal()
    try:
        # Create default Admin if not exists
        if db.query(models.User).filter(models.User.email == "admin@pipelineguard.io").count() == 0:
            admin = models.User(
                name="Admin", email="admin@pipelineguard.io", phone="+910000000000",
                password_hash=hash_password("Admin@12345"),
                role=models.Role.ADMIN, phone_verified=True,
            )
            db.add(admin)
            db.commit()
            print("Admin user ready: admin@pipelineguard.io / Admin@12345")

        # Clean up legacy demo zones if they have no real sensor readings attached
        demo_zones = db.query(models.Zone).filter(models.Zone.name.in_(["Pipeline 01", "Pipeline 02", "Pipeline 03"])).all()
        for z in demo_zones:
            has_readings = db.query(models.SensorReading).filter(models.SensorReading.device_id == z.device_id).count() > 0
            if not has_readings:
                dev_id = z.device_id
                db.delete(z)
                if dev_id:
                    dev = db.query(models.Device).filter(models.Device.id == dev_id).first()
                    if dev:
                        db.delete(dev)
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    run()

"""
SMS provider abstraction. Ships with a 'simulated' provider (logs to DB and
console) so the prototype runs with zero external accounts. Swap in a real
provider (Twilio, MSG91, etc.) by implementing `send()` and setting
SMS_PROVIDER in the environment — no other code changes needed.
"""
from sqlalchemy.orm import Session
from .config import settings
from .models import SMSLog


class SimulatedSMSProvider:
    name = "simulated"

    def send(self, phone: str, message: str) -> str:
        print(f"[SIMULATED SMS] -> {phone}\n{message}\n")
        return "sent"


class TwilioSMSProvider:
    """Reference implementation — requires `pip install twilio` and real credentials."""
    name = "twilio"

    def send(self, phone: str, message: str) -> str:
        try:
            from twilio.rest import Client
        except ImportError:
            raise RuntimeError("twilio package not installed — pip install twilio")
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.messages.create(body=message, from_=settings.TWILIO_FROM_NUMBER, to=phone)
        return "sent"


def get_provider():
    if settings.SMS_PROVIDER == "twilio":
        return TwilioSMSProvider()
    return SimulatedSMSProvider()


def send_sms(db: Session, phone: str, message: str):
    provider = get_provider()
    status = provider.send(phone, message)
    log = SMSLog(phone=phone, message=message, provider=provider.name, status=status)
    db.add(log)
    db.commit()
    return log


def format_alert_sms(zone_name: str, status: str, reason: str) -> str:
    return (
        f"🚨 GAS ALERT\n"
        f"Zone: {zone_name}\n"
        f"Status: {status}\n"
        f"Reason: {reason}\n"
        f"Immediate attention required."
    )


def format_valve_closed_sms(zone_name: str) -> str:
    return f"✅ Valve CLOSED for {zone_name}. Pipeline has been safely isolated."


def format_otp_sms(code: str) -> str:
    return f"Your Pipeline Guard verification code is {code}. Valid for 5 minutes."

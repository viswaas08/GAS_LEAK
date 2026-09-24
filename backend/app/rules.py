"""
Simple, explainable rule-based logic (NOT AI/ML) for turning raw sensor
values into a pipeline status + human-readable reason. Every decision must
be traceable back to a specific rule for control-room trust and audit.
"""
from .config import settings
from .models import PipelineStatus


def evaluate(mq2: float, mq135: float, pressure: float, flame_detected: bool):
    reasons = []
    critical = False
    warning = False

    if flame_detected:
        critical = True
        reasons.append("Flame detected")

    if mq2 >= settings.MQ2_CRITICAL:
        critical = True
        reasons.append(f"MQ-2 gas level critical ({mq2:.0f})")
    elif mq2 >= settings.MQ2_WARNING:
        warning = True
        reasons.append(f"MQ-2 gas level elevated ({mq2:.0f})")

    if mq135 >= settings.MQ135_CRITICAL:
        critical = True
        reasons.append(f"MQ-135 air quality critical ({mq135:.0f})")
    elif mq135 >= settings.MQ135_WARNING:
        warning = True
        reasons.append(f"MQ-135 air quality elevated ({mq135:.0f})")

    low_bound = settings.PRESSURE_MIN_SAFE
    high_bound = settings.PRESSURE_MAX_SAFE
    band = settings.PRESSURE_WARNING_BAND
    if pressure < (low_bound - band) or pressure > (high_bound + band):
        critical = True
        reasons.append(f"Pressure out of safe range ({pressure:.2f} bar)")
    elif pressure < low_bound or pressure > high_bound:
        warning = True
        reasons.append(f"Pressure trending abnormal ({pressure:.2f} bar)")

    # Multiple simultaneous abnormal conditions escalate WARNING -> CRITICAL
    if warning and len(reasons) >= 2 and not critical:
        critical = True
        reasons.append("Multiple abnormal conditions detected simultaneously")

    if critical:
        status = PipelineStatus.CRITICAL
    elif warning:
        status = PipelineStatus.WARNING
    else:
        status = PipelineStatus.SAFE
        reasons = ["All readings within normal operating range"]

    return status, "; ".join(reasons)

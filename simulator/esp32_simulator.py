"""
Software stand-in for a physical ESP32 fleet. Continuously posts plausible
sensor readings for every seeded device to POST /api/sensors, so the
dashboard has live-looking telemetry and graphs even with no hardware
attached. Real critical events are injected through the dashboard's
"Demo simulation" panel (or POST /api/simulate/event) — this script just
keeps the baseline "heartbeat" noise flowing.

Usage:
    python simulator/esp32_simulator.py [--host http://localhost:8000] [--interval 3]
"""
import argparse
import random
import time
import urllib.request
import json

DEVICE_CODES = ["ESP32-01", "ESP32-02", "ESP32-03"]


def post_reading(host: str, device_code: str):
    payload = {
        "device_code": device_code,
        "mq2": max(0, 180 + random.uniform(-30, 30)),
        "mq135": max(0, 150 + random.uniform(-25, 25)),
        "pressure": round(1.0 + random.uniform(-0.05, 0.05), 3),
        "flame_detected": False,
    }
    req = urllib.request.Request(
        f"{host}/api/sensors",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except Exception as e:
        return f"error: {e}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="http://localhost:8000")
    parser.add_argument("--interval", type=float, default=3.0)
    args = parser.parse_args()

    print(f"Simulating {len(DEVICE_CODES)} ESP32 devices against {args.host} "
          f"every {args.interval}s. Ctrl+C to stop.")
    try:
        while True:
            for code in DEVICE_CODES:
                status = post_reading(args.host, code)
                print(f"  {code}: {status}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()

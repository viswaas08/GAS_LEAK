"""
PipelineGuard — Arduino USB Direct Bridge
=========================================
Forwards live telemetry from Arduino Uno (connected via USB cable) directly to 
the PipelineGuard website (local or Vercel), and transmits remote shutoff commands 
back to the Arduino servo motor.

Usage:
    python arduino_bridge.py
    python arduino_bridge.py --port COM3 --host http://localhost:8000
    python arduino_bridge.py --host https://your-app.vercel.app
"""

import sys
import time
import json
import argparse
import urllib.request
import urllib.error

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("[ERROR] 'pyserial' is not installed. Run: pip install pyserial")
    sys.exit(1)


def find_arduino_port():
    """Auto-detects the connected Arduino or CH340 COM port."""
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        desc = (p.description or "").lower()
        if "ch340" in desc or "arduino" in desc or "usb-serial" in desc:
            return p.device
    if ports:
        return ports[0].device
    return "COM3"


def post_reading(host: str, device_code: str, mq2: float, flame: bool, valve_closed: bool):
    """Posts sensor telemetry to the website backend and returns the valve state."""
    payload = {
        "device_code": device_code,
        "mq2": round(mq2, 1),
        "mq135": round(mq2 * 0.8, 1),
        "pressure": 0.2 if valve_closed else 1.0,
        "flame_detected": flame
    }

    url = f"{host.rstrip('/')}/api/sensors"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status in (200, 201):
                res_body = json.loads(response.read().decode("utf-8"))
                return res_body.get("status"), res_body.get("valve_state")
            return "OK", None
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}", None
    except Exception as e:
        return f"ERR: {e}", None


def main():
    parser = argparse.ArgumentParser(description="PipelineGuard Arduino USB Bridge")
    parser.add_argument("--port", default=None, help="COM port (e.g. COM3). Auto-detected if omitted.")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    parser.add_argument("--host", default="http://localhost:8000", help="Website backend URL (e.g. http://localhost:8000 or Vercel URL)")
    parser.add_argument("--device", default="ESP32-01", help="Device code in dashboard (default: ESP32-01)")
    args = parser.parse_args()

    port = args.port or find_arduino_port()
    print("================================================================")
    print(" PipelineGuard: Arduino USB ➔ Website Bridge (No ESP32 needed!) ")
    print("================================================================")
    print(f"Connecting to Arduino on {port} at {args.baud} baud...")
    print(f"Target Website Backend: {args.host}")
    print(f"Hardware Device Code:  {args.device}")
    print("Press Ctrl+C to stop.\n")

    try:
        ser = serial.Serial(port, args.baud, timeout=2)
        # Give Arduino time to reset on serial connection
        time.sleep(2)
        ser.reset_input_buffer()
        print(f"Connected to {port} successfully! Listening for telemetry...\n")
    except Exception as e:
        print(f"[FATAL] Could not open port {port}: {e}")
        print("Tip: Make sure the Arduino Serial Monitor in Arduino IDE is CLOSED.")
        sys.exit(1)

    try:
        while True:
            if ser.in_waiting > 0:
                raw_line = ser.readline().decode("utf-8", errors="ignore").strip()
                if not raw_line:
                    continue

                # Expected JSON from Arduino: {"mq2": 320.5, "flame": false, "valve_closed": true}
                if raw_line.startswith("{") and raw_line.endswith("}"):
                    try:
                        data = json.loads(raw_line)
                        mq2 = float(data.get("mq2", 0))
                        flame = bool(data.get("flame", False))
                        valve_closed = bool(data.get("valve_closed", False))

                        # Display live status in console
                        hazard_str = "🚨 HAZARD!" if (mq2 > 300 or flame) else "✅ SAFE"
                        valve_str = "180° CLOSED" if valve_closed else "0° OPEN"
                        print(f"[{time.strftime('%H:%M:%S')}] {hazard_str} Gas: {mq2:.1f} | Flame: {flame} | Valve: {valve_str}")

                        # Post reading to website backend
                        server_status, valve_cmd = post_reading(
                            args.host, args.device, mq2, flame, valve_closed
                        )
                        print(f"           ➔ Website Response: Status={server_status} | Remote Valve State={valve_cmd}")

                        # Remote website control: if website requested emergency shutoff
                        if valve_cmd in ("COMMAND_SENT", "CLOSED") and not valve_closed:
                            print("           ➔ [COMMAND] Sending SHUTOFF to Arduino Servo over USB!")
                            ser.write(b"SHUTOFF\n")
                            ser.flush()
                        elif valve_cmd == "OPEN" and valve_closed:
                            print("           ➔ [COMMAND] Sending OPEN to Arduino Servo over USB!")
                            ser.write(b"OPEN\n")
                            ser.flush()

                    except json.JSONDecodeError:
                        pass
                else:
                    # Non-JSON status message from Arduino
                    print(f"[Arduino Log] {raw_line}")

            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\nStopping Arduino bridge.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()

"""
PipelineGuard — Arduino USB Direct Bridge
=========================================
Forwards live telemetry from Arduino Uno (connected via USB cable) directly to 
the PipelineGuard website (local or Vercel), and transmits remote shutoff commands 
back to the Arduino servo motor.

Supports:
- Clean single-line JSON: {"mq2": 150.2, "flame": false, "valve_closed": false}
- Fragmented or multi-line serial buffers
- Text/CSV format: "Gas: 120.4 | Flame: NO" or "120.4,0,0"

Usage:
    python arduino_bridge.py
    python arduino_bridge.py --host https://gasleak-git-main-viswaas08s-projects.vercel.app
"""

import sys
import time
from datetime import datetime
import json
import re
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
        "pressure": 1.02, # Normal pipeline operating pressure (~1.0 bar)
        "flame_detected": flame,
        "valve_closed": valve_closed
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


def extract_telemetry(buffer: str):
    """Extracts (mq2, flame, valve_closed, remainder_buffer) from rolling buffer."""
    # 1. Try complete JSON object: {...}
    start = buffer.find("{")
    if start != -1:
        end = buffer.find("}", start)
        if end != -1:
            json_str = buffer[start:end+1]
            remainder = buffer[end+1:]
            try:
                # Clean stray unescaped control chars if any
                clean_json = re.sub(r'[\r\n\t]', '', json_str)
                data = json.loads(clean_json)
                mq2 = float(data.get("mq2", 0))
                flame = bool(data.get("flame", False))
                valve_closed = bool(data.get("valve_closed", False) or data.get("valve", 0) == 180)
                raw_gas = data.get("raw_gas")
                flame_pin = data.get("flame_pin")
                manual_sw = bool(data.get("manual_switch", False) or data.get("manual", False))
                return mq2, flame, valve_closed, raw_gas, flame_pin, manual_sw, remainder
            except Exception:
                pass

    # 2. Try Regex parsing from text stream (e.g. "Gas: 120.4 | Flame: NO")
    gas_match = re.search(r'(?:gas(?: level)?|mq2?)[:= ]*([0-9]+(?:\.[0-9]+)?)', buffer, re.I)
    if gas_match:
        mq2 = float(gas_match.group(1))
        flame = bool(re.search(r'flame[:= ]*(yes|true|1)', buffer, re.I))
        valve_closed = bool(re.search(r'valve[:= ]*(closed|180|true|1|off)', buffer, re.I))
        manual_sw = bool(re.search(r'manual[:= ]*(yes|true|1)', buffer, re.I))
        remainder = buffer[gas_match.end():]
        return mq2, flame, valve_closed, None, None, manual_sw, remainder

    # 3. Try CSV line (e.g. "150.2,0,0\n")
    csv_match = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*,\s*([01])\s*,\s*([01])', buffer)
    if csv_match:
        mq2 = float(csv_match.group(1))
        flame = (csv_match.group(2) == "1")
        valve_closed = (csv_match.group(3) == "1")
        remainder = buffer[csv_match.end():]
        return mq2, flame, valve_closed, None, None, False, remainder

    return None, None, None, None, None, False, buffer


def main():
    parser = argparse.ArgumentParser(description="PipelineGuard Arduino USB Bridge")
    parser.add_argument("--port", default=None, help="COM port (e.g. COM3). Auto-detected if omitted.")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    parser.add_argument("--host", default="https://gasleak-git-main-viswaas08s-projects.vercel.app", help="Website backend URL (default: https://gasleak-git-main-viswaas08s-projects.vercel.app)")
    parser.add_argument("--device", default="ESP32-01", help="Device code in dashboard (default: ESP32-01)")
    args = parser.parse_args()

    port = args.port or find_arduino_port()
    print("================================================================")
    print(" PipelineGuard: Arduino USB ➔ Website Bridge (Live Sync)        ")
    print("================================================================")
    print(f"Connecting to Arduino on {port} at {args.baud} baud...")
    print(f"Target Website Backend: {args.host}")
    print(f"Hardware Device Code:  {args.device}")
    print("Press Ctrl+C to stop.\n")

    try:
        ser = serial.Serial(port, args.baud, timeout=0.1)
        time.sleep(2)
        ser.reset_input_buffer()
        print(f"Connected to {port} successfully! Listening for telemetry at 0.1s frequency...\n")
    except Exception as e:
        print(f"[FATAL] Could not open port {port}: {e}")
        print("Tip: Make sure the Arduino Serial Monitor in Arduino IDE is CLOSED.")
        sys.exit(1)

    rx_buffer = ""
    last_post_time = 0

    try:
        while True:
            # Read all available bytes from serial
            if ser.in_waiting > 0:
                chunk = ser.read(ser.in_waiting).decode("utf-8", errors="ignore")
                rx_buffer += chunk

                # Prevent buffer from growing infinitely if no delimiter matches
                if len(rx_buffer) > 2048:
                    rx_buffer = rx_buffer[-512:]

                mq2, flame, valve_closed, raw_gas, flame_pin, manual_sw, rx_buffer = extract_telemetry(rx_buffer)

                if mq2 is not None:
                    current_time = time.time()
                    # 0.1s (100ms) Real-Time Ingestion
                    if current_time - last_post_time >= 0.1:
                        last_post_time = current_time

                        hazard_str = "🚨 HAZARD!" if (mq2 >= 100.0 or flame) else "✅ SAFE"
                        valve_str = "180° CLOSED (OFF)" if valve_closed else "0° OPEN (ON)"
                        ts = datetime.now().strftime('%H:%M:%S.%f')[:-4]
                        
                        extra_info = ""
                        if raw_gas is not None:
                            extra_info = f" (ADC: {raw_gas} | D2: {flame_pin})"
                        if manual_sw:
                            extra_info += " [🔘 MANUAL SWITCH TRIGGERED]"

                        print(f"[{ts}] {hazard_str} Gas: {mq2:.1f} PPM{extra_info} | Flame: {flame} | Valve: {valve_str}")

                        # Post reading to website backend
                        server_status, valve_cmd = post_reading(
                            args.host, args.device, mq2, flame, valve_closed
                        )
                        print(f"           ➔ Website Response: Status={server_status} | Remote Valve={valve_cmd}")

                        is_safe = (mq2 < 100.0 and not flame)

                        # Remote website control & Safe Mode Enforcement:
                        if is_safe and valve_closed:
                            # Environment is completely safe; ensure Arduino valve stays 0° OPEN
                            print("           ➔ [SAFE MODE] Environment safe ➔ Ensuring Arduino Servo is 0° OPEN!")
                            ser.write(b"OPEN\n")
                            ser.flush()
                        elif valve_cmd in ("COMMAND_SENT", "WAITING_CONFIRMATION") and not valve_closed and not is_safe:
                            print("           ➔ [COMMAND] Remote Emergency Shutoff ➔ Arduino Servo 180° CLOSED!")
                            ser.write(b"SHUTOFF\n")
                            ser.flush()
                        elif valve_cmd == "OPEN" and valve_closed:
                            print("           ➔ [COMMAND] Remote Switch ON / Open ➔ Arduino Servo 0° OPEN!")
                            ser.write(b"OPEN\n")
                            ser.flush()

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nStopping Arduino bridge.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()

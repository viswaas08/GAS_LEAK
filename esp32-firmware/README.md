# ESP32 Firmware (reference)

`firmware.ino` is reference Arduino code showing how a real ESP32 would
publish sensor data and receive shutoff commands over MQTT/TLS. It is not
compiled or run as part of this prototype — since no physical ESP32 is
attached, `/simulator/esp32_simulator.py` plays the same role in software
so the full pipeline (ingest → rules → alert → SMS → shutoff → ack) can be
demoed end-to-end without hardware.

To move from simulation to real hardware:
1. Flash `firmware.ino` (fill in Wi-Fi/MQTT credentials, calibrate the
   sensor-to-value mappings for your specific MQ-2/MQ-135/pressure
   modules) onto an ESP32.
2. Run an MQTT broker (e.g. Mosquitto) with TLS enabled.
3. Run a small MQTT→HTTP bridge service that subscribes to
   `pipeline/+/sensors` and calls `POST /api/sensors`, and that subscribes
   to `pipeline/+/actuator/ack` and calls `POST /api/actuator/ack`. The
   backend publishing a shutoff command should publish to
   `pipeline/<device_code>/actuator/cmd` (this bridge is not included here
   — it's a thin ~50-line service).
4. Wire sensors and a **safe, non-hazardous demonstration actuator only**
   (relay + LED, or a servo on a model valve). Never connect prototype
   electronics to a live gas installation — see the safety note at the top
   of `firmware.ino`.

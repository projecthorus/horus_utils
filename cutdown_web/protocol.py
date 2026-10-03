"""Standalone Horus radio packet formats used by the web ground station.

The wire formats here match the legacy ground station and LoRa UDP gateway.
No code from the legacy application is imported at runtime.
"""

from __future__ import annotations

import math
import struct

UDP_PORT = 55672
FULL_TELEMETRY = 0
CUTDOWN = 2
PARAMETER_CHANGE = 3
COMMAND_ACK = 4
SHORT_TELEMETRY = 5
PING_PARAMETER = 0

FULL_FORMAT = struct.Struct("<BBBHBBBffHBBBBBBBB")
SHORT_FORMAT = struct.Struct("<BBBBBffBBB")
PACKET_NAMES = {
    0: "Telemetry", 1: "Text message", 2: "Cutdown command",
    3: "Parameter change", 4: "Command acknowledgement",
    5: "Short telemetry", 6: "Slot request", 7: "Car telemetry",
    0x66: "SSDV FEC", 0x67: "SSDV",
}


def packet_bytes(value: object) -> bytes:
    if not isinstance(value, list) or not value or len(value) > 255:
        raise ValueError("payload must be a nonempty list of at most 255 bytes")
    if any(type(item) is not int or not 0 <= item <= 255 for item in value):
        raise ValueError("payload contains an invalid byte")
    return bytes(value)


def _position(latitude: float, longitude: float) -> None:
    if not (math.isfinite(latitude) and math.isfinite(longitude)
            and -90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("invalid latitude or longitude")


def _time(hour: int, minute: int, second: int) -> str:
    if hour > 23 or minute > 59 or second > 59:
        raise ValueError("invalid payload time")
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def decode_telemetry(payload: bytes) -> dict:
    if payload[0] == FULL_TELEMETRY:
        if len(payload) != FULL_FORMAT.size:
            raise ValueError("invalid full telemetry length")
        (kind, flags, payload_id, counter, hour, minute, second,
         latitude, longitude, altitude, speed, satellites, temperature,
         battery, pyro, received, noise, slots) = FULL_FORMAT.unpack(payload)
        _position(latitude, longitude)
        return {
            "kind": "full", "payload_id": payload_id, "counter": counter,
            "time": _time(hour, minute, second), "latitude": latitude,
            "longitude": longitude, "altitude_m": altitude,
            "speed_knots": speed, "speed_kmh": round(speed * 1.852, 1),
            "satellites": satellites,
            "temperature_c": temperature - 256 if temperature >= 128 else temperature,
            "battery_v": round(0.5 + 1.5 * battery / 255, 2),
            "pyro_v": round(5.0 * pyro / 255, 2),
            "received_packets": received, "noise_floor_dbm": noise - 164,
            "current_slot": slots & 0x0f, "used_slots": slots >> 4,
            "flags": flags,
        }
    if payload[0] == SHORT_TELEMETRY:
        if len(payload) != SHORT_FORMAT.size:
            raise ValueError("invalid short telemetry length")
        (kind, payload_id, hour, minute, second, latitude, longitude,
         speed, battery, satellites) = SHORT_FORMAT.unpack(payload)
        _position(latitude, longitude)
        return {
            "kind": "short", "payload_id": payload_id,
            "time": _time(hour, minute, second), "latitude": latitude,
            "longitude": longitude, "speed_knots": speed,
            "speed_kmh": round(speed * 1.852, 1), "satellites": satellites,
            "battery_v": round(0.5 + 1.5 * battery / 255, 2),
        }
    raise ValueError("not a telemetry packet")


def decode_ack(payload: bytes) -> dict:
    if len(payload) != 8 or payload[0] != COMMAND_ACK:
        raise ValueError("invalid command acknowledgement")
    command_type = payload[5]
    if command_type == CUTDOWN:
        command = "Cutdown"
        detail = f"{payload[6]} seconds"
    elif command_type == PARAMETER_CHANGE and payload[6] == PING_PARAMETER:
        command = "Ping"
        detail = f"Value {payload[7]}"
    elif command_type == PARAMETER_CHANGE:
        command = "Parameter change"
        detail = f"Parameter {payload[6]}, value {payload[7]}"
    else:
        command = "Unknown command"
        detail = f"Type {command_type}, bytes {payload[6]}, {payload[7]}"
    return {
        "payload_id": payload[2], "command": command, "detail": detail,
        "rssi_dbm": payload[3] - 164,
        "snr_db": round(struct.unpack("b", payload[4:5])[0] / 4, 2),
    }


def decode_rx(message: dict) -> tuple[dict, dict | None, dict | None]:
    payload = packet_bytes(message.get("payload"))
    flags = message.get("pkt_flags")
    if not isinstance(flags, dict) or flags.get("crc_error") not in (0, 1, False, True):
        raise ValueError("missing CRC flag")
    kind = payload[0]
    payload_id = payload[1] if kind == SHORT_TELEMETRY and len(payload) >= 2 else (
        payload[2] if len(payload) >= 3 else None
    )
    meta = {
        "timestamp": str(message.get("timestamp", "")),
        "payload_id": payload_id, "type": PACKET_NAMES.get(kind, f"Type {kind}"),
        "length": len(payload), "crc_ok": flags["crc_error"] == 0,
        "rssi_dbm": message.get("rssi"), "snr_db": message.get("snr"),
        "freq_error_hz": message.get("freq_error"),
        "repeated": bool(payload[1] & 1) if kind != SHORT_TELEMETRY and len(payload) > 1 else False,
    }
    if not meta["crc_ok"]:
        return meta, None, None
    telemetry = decode_telemetry(payload) if kind in (FULL_TELEMETRY, SHORT_TELEMETRY) else None
    ack = decode_ack(payload) if kind == COMMAND_ACK else None
    return meta, telemetry, ack


def build_command(command: object, payload_id: object, password: object, value: object) -> list[int]:
    if type(payload_id) is not int or not 0 <= payload_id <= 254:
        raise ValueError("select a valid payload ID")
    if not isinstance(password, str) or len(password) != 3 or not password.isascii() or (
        any(ord(char) < 32 or ord(char) > 126 for char in password)
    ):
        raise ValueError("password must be exactly three printable ASCII characters")
    if type(value) is not int:
        raise ValueError("value must be an integer")
    if command == "ping":
        if not 0 <= value <= 255:
            raise ValueError("Ping value must be between 0 and 255")
        return [PARAMETER_CHANGE, 0, payload_id, *password.encode("ascii"), PING_PARAMETER, value]
    if command == "cutdown":
        if not 1 <= value <= 10:
            raise ValueError("Cutdown duration must be between 1 and 10 seconds")
        return [CUTDOWN, 0, payload_id, *password.encode("ascii"), value, 0]
    raise ValueError("unsupported command")


def describe_transmission(value: object) -> tuple[int | None, str]:
    """Describe a TX packet without exposing its embedded three byte password."""
    try:
        payload = packet_bytes(value)
    except ValueError:
        return None, "unknown packet"
    payload_id = payload[2] if len(payload) > 2 else None
    if len(payload) == 8 and payload[0] == CUTDOWN:
        return payload_id, f"Cutdown, {payload[6]} seconds"
    if len(payload) == 8 and payload[0] == PARAMETER_CHANGE:
        if payload[6] == PING_PARAMETER:
            return payload_id, f"Ping, value {payload[7]}"
        return payload_id, f"Parameter change {payload[6]}, value {payload[7]}"
    return payload_id, PACKET_NAMES.get(payload[0], f"Type {payload[0]}")

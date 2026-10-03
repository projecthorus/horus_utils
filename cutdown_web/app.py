"""Browser based Horus ground station; run with web_test/venv/bin/python app.py."""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import json
import logging
import socket
import threading
import time

from flask import Flask, render_template
from flask_socketio import SocketIO, emit

from protocol import UDP_PORT, build_command, decode_rx, describe_transmission


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class GroundStation:
    def __init__(self, socketio: SocketIO, udp_port: int = UDP_PORT, udp_host: str = "255.255.255.255"):
        self.socketio = socketio
        self.udp_port = udp_port
        self.udp_host = udp_host
        self.lock = threading.RLock()
        self.payloads: dict[int, dict] = {}
        self.last_packet: dict | None = None
        self.status: dict = {}
        self.log: deque[dict] = deque(maxlen=150)
        self.uplinks: deque[dict] = deque(maxlen=60)
        self._last_status_log = 0.0
        self._stop = threading.Event()
        self._listener: threading.Thread | None = None
        self._udp_socket: socket.socket | None = None

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "payloads": list(self.payloads.values()), "status": self.status,
                "last_packet": self.last_packet,
                "log": list(self.log), "uplinks": list(self.uplinks),
            }

    def _log(self, kind: str, message: str, timestamp: str | None = None) -> None:
        entry = {"time": timestamp or now(), "kind": kind, "message": message[:240]}
        with self.lock:
            self.log.append(entry)
        self.socketio.emit("log_entry", entry)

    def _uplink(self, payload_id: int | None, stage: str, message: str,
                timestamp: str | None = None, **extra: object) -> None:
        event = {
            "time": timestamp or now(), "payload_id": payload_id,
            "stage": stage, "message": message, **extra,
        }
        with self.lock:
            self.uplinks.append(event)
        self.socketio.emit("uplink_event", event)

    def process_datagram(self, datagram: bytes) -> None:
        try:
            message = json.loads(datagram.decode("utf-8"))
        except (UnicodeError, ValueError):
            self._log("ERROR", "Discarded invalid UDP JSON")
            return
        if not isinstance(message, dict):
            return
        kind = message.get("type")
        if kind == "STATUS":
            status = {
                "time": str(message.get("timestamp", now()))[:40],
                "heard_at": now(), "frequency_mhz": message.get("frequency"),
                "rssi_dbm": message.get("rssi"),
                "queue_size": message.get("txqueuesize"),
            }
            with self.lock:
                changed = any(self.status.get(key) != status.get(key)
                              for key in ("frequency_mhz", "queue_size"))
                self.status = status
                log_status = changed or time.monotonic() - self._last_status_log >= 5
                if log_status:
                    self._last_status_log = time.monotonic()
            self.socketio.emit("station_status", status)
            if log_status:
                self._log("STATUS", f"Radio {status['frequency_mhz']} MHz · noise {status['rssi_dbm']} dBm · queue {status['queue_size']}", status["time"])
            return
        if kind == "RXPKT":
            try:
                meta, telemetry, ack = decode_rx(message)
            except (ValueError, TypeError, KeyError) as exc:
                self._log("ERROR", f"Discarded malformed RXPKT: {exc}")
                return
            payload_id = meta["payload_id"]
            label = f"Payload {payload_id}" if payload_id is not None else "Unknown payload"
            with self.lock:
                self.last_packet = meta
            self.socketio.emit("last_packet", meta)
            if not meta["crc_ok"]:
                self._log("RXPKT", f"{label}: CRC failed · RSSI {meta['rssi_dbm']} dBm", meta["timestamp"])
                return
            if payload_id is not None and payload_id != 255:
                with self.lock:
                    state = self.payloads.get(payload_id, {
                        "id": payload_id, "telemetry": None, "last_packet": None,
                    }).copy()
                    state["last_packet"] = meta
                    state["heard_at"] = now()
                    if telemetry is not None:
                        state["telemetry"] = telemetry
                    self.payloads[payload_id] = state
                self.socketio.emit("payload_update", state)
            self._log("RXPKT", f"{label}: {meta['type']} · RSSI {meta['rssi_dbm']} dBm · SNR {meta['snr_db']} dB", meta["timestamp"])
            if ack is not None:
                self._uplink(payload_id, "ACK", f"{ack['command']} acknowledged · {ack['detail']}",
                             meta["timestamp"], rssi_dbm=ack["rssi_dbm"], snr_db=ack["snr_db"])
            return
        if kind in ("TXQUEUED", "TXDONE"):
            payload_id, description = describe_transmission(message.get("payload"))
            stage = "QUEUED" if kind == "TXQUEUED" else "TRANSMITTED"
            timestamp = str(message.get("timestamp", now()))[:40]
            self._log(kind, f"{description} for payload {payload_id} · {stage.lower()}", timestamp)
            self._uplink(payload_id, stage, description, timestamp)
            return
        if kind == "ERROR":
            detail = str(message.get("str", "Radio reported an error"))[:200]
            self._log("ERROR", detail)
            self._uplink(None, "ERROR", detail)

    def send_command(self, data: object) -> dict:
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid command request"}
        payload_id = data.get("payload_id")
        command = data.get("command")
        try:
            packet = build_command(command, payload_id, data.get("password"), data.get("value"))
            if command == "cutdown" and data.get("confirmed") is not True:
                raise ValueError("Cutdown requires confirmation")
            with self.lock:
                if payload_id not in self.payloads:
                    raise ValueError("select a heard payload before sending")
            udp_message = {
                "type": "TXPKT", "payload": packet, "destination": payload_id,
                "timeout": 15,
            }
            wire = json.dumps(udp_message, separators=(",", ":")).encode("ascii")
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as transmitter:
                transmitter.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                transmitter.sendto(wire, (self.udp_host, self.udp_port))
        except (ValueError, OSError) as exc:
            # Never include a request body or raw radio packet in errors: it contains the password.
            error = str(exc) if isinstance(exc, ValueError) else "UDP send failed; check radio gateway connectivity"
            self._log("ERROR", error)
            return {"ok": False, "error": error}
        description = f"{'Ping' if command == 'ping' else 'Cutdown'} request for payload {payload_id}"
        self._log("TXPKT", description)
        self._uplink(payload_id, "REQUESTED", description)
        return {"ok": True, "message": "Request sent to UDP gateway; awaiting queue and radio confirmation"}

    def start_udp(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        listener.bind(("", self.udp_port))
        listener.settimeout(1)
        self._udp_socket = listener
        self._listener = threading.Thread(target=self._listen, daemon=True, name="horus-udp-listener")
        self._listener.start()

    def _listen(self) -> None:
        assert self._udp_socket is not None
        while not self._stop.is_set():
            try:
                datagram, _address = self._udp_socket.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self.process_datagram(datagram)
            except Exception:
                logging.exception("Unexpected UDP processing error")

    def stop_udp(self) -> None:
        self._stop.set()
        if self._udp_socket is not None:
            self._udp_socket.close()
        if self._listener is not None:
            self._listener.join(timeout=2)


def create_app(udp_port: int = UDP_PORT, udp_host: str = "255.255.255.255",
               uplink_password: str = "") -> tuple[Flask, SocketIO, GroundStation]:
    if uplink_password:
        build_command("ping", 0, uplink_password, 0)
    app = Flask(__name__)
    socketio = SocketIO(app, async_mode="threading")
    station = GroundStation(socketio, udp_port, udp_host)

    @app.get("/")
    def index():
        return render_template("index.html", uplink_password=uplink_password)

    @socketio.on("connect")
    def on_connect():
        emit("snapshot", station.snapshot())

    @socketio.on("send_command")
    def on_send_command(data):
        return station.send_command(data)

    return app, socketio, station


def main() -> None:
    def password_arg(value: str) -> str:
        try:
            build_command("ping", 0, value, 0)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from exc
        return value

    parser = argparse.ArgumentParser(description="Standalone Horus web ground station")
    parser.add_argument("--host", default="127.0.0.1", help="Browser server address (default: local only)")
    parser.add_argument("--port", type=int, default=5004, help="Browser server port")
    parser.add_argument("--udp-port", type=int, default=UDP_PORT, help="Horus UDP port")
    parser.add_argument("--udp-host", default="255.255.255.255", help="UDP command broadcast address")
    parser.add_argument("--password", type=password_arg, default="",
                        help="Three character uplink password to pre-fill on the page")
    args = parser.parse_args()
    app, socketio, station = create_app(args.udp_port, args.udp_host, args.password)
    station.start_udp()
    print(f"Horus web ground station: http://{args.host}:{args.port}/")
    print(f"Listening for radio UDP on port {args.udp_port}")
    try:
        socketio.run(app, host=args.host, port=args.port, use_reloader=False,
                     allow_unsafe_werkzeug=True)
    finally:
        station.stop_udp()


if __name__ == "__main__":
    main()

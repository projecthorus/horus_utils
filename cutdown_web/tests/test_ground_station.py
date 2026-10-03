import json
from pathlib import Path
import socket
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from protocol import build_command, decode_ack, decode_rx


def telemetry_packet(payload_id=7):
    return list(struct.pack(
        "<BBBHBBBffHBBBBBBBB", 0, 0, payload_id, 128,
        12, 34, 56, -34.9, 138.6, 26000, 10, 9,
        253, 170, 51, 12, 100, 0x23,
    ))


def rx_datagram(payload, crc_error=0):
    return json.dumps({
        "type": "RXPKT", "timestamp": "2026-10-03T03:04:05",
        "rssi": -110, "snr": 7.5, "freq_error": -132.0,
        "pkt_flags": {"crc_error": crc_error}, "payload": payload,
    }).encode()


class ProtocolTests(unittest.TestCase):
    def test_full_telemetry_and_ack(self):
        meta, telemetry, ack = decode_rx(json.loads(rx_datagram(telemetry_packet())))
        self.assertEqual(meta["payload_id"], 7)
        self.assertEqual(telemetry["counter"], 128)
        self.assertEqual(telemetry["time"], "12:34:56")
        self.assertAlmostEqual(telemetry["latitude"], -34.9, places=4)
        self.assertEqual(telemetry["altitude_m"], 26000)
        self.assertEqual(telemetry["temperature_c"], -3)
        self.assertEqual(telemetry["current_slot"], 3)
        self.assertIsNone(ack)

        result = decode_ack(bytes([4, 0, 7, 100, 0xFC, 3, 0, 42]))
        self.assertEqual(result["command"], "Ping")
        self.assertEqual(result["rssi_dbm"], -64)
        self.assertEqual(result["snr_db"], -1)

    def test_command_wire_format_and_validation(self):
        self.assertEqual(build_command("ping", 7, "abc", 42), [3, 0, 7, 97, 98, 99, 0, 42])
        self.assertEqual(build_command("cutdown", 7, "abc", 4), [2, 0, 7, 97, 98, 99, 4, 0])
        for command, value, password in [("cutdown", 11, "abc"), ("ping", 256, "abc"), ("ping", 1, "ab")]:
            with self.subTest(command=command, value=value, password=password):
                with self.assertRaises(ValueError):
                    build_command(command, 7, password, value)

    def test_short_telemetry_uses_second_byte_for_payload_id(self):
        packet = list(struct.pack("<BBBBBffBBB", 5, 9, 1, 2, 3, -35.0, 139.0, 12, 100, 8))
        meta, telemetry, _ack = decode_rx(json.loads(rx_datagram(packet)))
        self.assertEqual(meta["payload_id"], 9)
        self.assertEqual(telemetry["payload_id"], 9)
        self.assertEqual(telemetry["time"], "01:02:03")


class GroundStationTests(unittest.TestCase):
    def setUp(self):
        self.gateway = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.gateway.bind(("127.0.0.1", 0))
        self.gateway.settimeout(1)
        self.app, self.socketio, self.station = create_app(self.gateway.getsockname()[1], "127.0.0.1")
        self.client = self.socketio.test_client(self.app)

    def tearDown(self):
        self.client.disconnect()
        self.gateway.close()

    def test_radio_updates_browser_and_crc_failure_is_ignored(self):
        self.station.process_datagram(rx_datagram(telemetry_packet(), crc_error=1))
        self.assertFalse(self.station.snapshot()["payloads"])
        self.assertFalse(self.station.snapshot()["last_packet"]["crc_ok"])
        self.station.process_datagram(rx_datagram(telemetry_packet()))
        events = self.client.get_received()
        updates = [event["args"][0] for event in events if event["name"] == "payload_update"]
        self.assertEqual(updates[-1]["id"], 7)
        self.assertEqual(updates[-1]["telemetry"]["counter"], 128)
        self.station.process_datagram(json.dumps({"type": "STATUS", "frequency": 431.65,
                                                   "rssi": -117, "txqueuesize": 0}).encode())
        self.assertEqual(self.station.snapshot()["status"]["frequency_mhz"], 431.65)

    def test_page_loads_local_assets(self):
        browser = self.app.test_client()
        page = browser.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Payload operations", page.data)
        self.assertNotIn(b"https://", page.data)
        vendor = browser.get("/static/vendor/socket.io.min.js")
        self.assertEqual(vendor.status_code, 200)
        self.assertIn(b"Socket.IO v4.8.1", vendor.data[:150])
        vendor.close()

    def test_password_parameter_is_visible_and_html_escaped(self):
        app, _socketio, _station = create_app(uplink_password="A&B")
        page = app.test_client().get("/")
        self.assertIn(b'type="text"', page.data)
        self.assertIn(b'name="uplink-code"', page.data)
        self.assertIn(b'value="A&amp;B"', page.data)
        self.assertNotIn(b'type="password"', page.data)
        with self.assertRaises(ValueError):
            create_app(uplink_password="too-long")

    def test_confirmed_uplink_reaches_udp_gateway_without_exposing_password(self):
        self.station.process_datagram(rx_datagram(telemetry_packet()))
        refused = self.client.emit("send_command", {
            "command": "cutdown", "payload_id": 7, "password": "abc", "value": 4,
        }, callback=True)
        self.assertFalse(refused["ok"])
        response = self.client.emit("send_command", {
            "command": "cutdown", "payload_id": 7, "password": "abc", "value": 4,
            "confirmed": True,
        }, callback=True)
        self.assertTrue(response["ok"])
        wire, _address = self.gateway.recvfrom(2048)
        self.assertEqual(json.loads(wire), {
            "type": "TXPKT", "payload": [2, 0, 7, 97, 98, 99, 4, 0],
            "destination": 7, "timeout": 15,
        })
        self.station.process_datagram(json.dumps({
            "type": "TXQUEUED", "payload": [2, 0, 7, 97, 98, 99, 4, 0],
            "txqueuesize": 0,
        }).encode())
        self.station.process_datagram(rx_datagram([4, 0, 7, 100, 4, 2, 4, 0]))
        snapshot = self.station.snapshot()
        self.assertNotIn("abc", json.dumps(snapshot))
        self.assertEqual(snapshot["uplinks"][-1]["stage"], "ACK")
        self.assertEqual(snapshot["uplinks"][-1]["message"], "Cutdown acknowledged · 4 seconds")


if __name__ == "__main__":
    unittest.main()

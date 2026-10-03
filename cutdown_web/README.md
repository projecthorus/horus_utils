# Horus web ground station
Yes, this is vibe-coded slop. I used codex to generate this.
Sorry.

Standalone browser interface for the legacy Horus LoRa UDP gateway. All application code is in this directory. It uses Flask and Flask-SocketIO, Python's standard library for UDP and packet decoding, and a locally vendored Socket.IO browser client. The page makes no external network requests.

## Run

With the Python 3.13 virtual environment already set up:

```sh
web_test/venv/bin/python web_test/app.py
```

To pre-fill the visible uplink password box, pass the three character password at startup:

```sh
web_test/venv/bin/python web_test/app.py --password abc
```

The box is a plain text input and keeps its value after sending a command. The password can still be edited in the browser.

Open <http://127.0.0.1:5004/>. The app listens for gateway broadcasts on UDP port 55672. Run the radio gateway separately. For access from another computer on a trusted network, pass `--host 0.0.0.0` and use the computer's address in the browser. There is no web login; anyone who can reach the page can send radio commands using a valid payload password. Keep the web server on a trusted network.

The optional `--port`, `--udp-port`, and `--udp-host` flags change the browser port, Horus UDP port, and command broadcast destination. `--udp-host 127.0.0.1` is useful for a gateway running on the same computer when local broadcast is unavailable.

The first valid heard payload is selected automatically. Each browser can choose a different payload. Only IDs actually heard since startup can be used for uplink. The Cutdown button asks for explicit confirmation. A successful send means the request was sent to UDP; the uplink panel separately reports whether the gateway queued or transmitted it and whether a payload acknowledgement was heard. UDP packet history is kept in memory for this run only.

Ping uses the payload parameter change command (parameter 0). Cutdown uses the cutdown command. Both use the legacy eight byte radio format and the gateway's transmit after receive queue. Passwords are three printable ASCII characters and are never stored or displayed in the browser log.

## Tests

```sh
web_test/venv/bin/python -m unittest discover -s web_test/tests -v
```

## Vendored browser dependency

`static/vendor/socket.io.min.js` is Socket.IO client 4.8.1 from `https://cdn.socket.io/4.8.1/socket.io.min.js`. Its license is in `static/vendor/socket.io-LICENSE.txt`. All other browser assets are local application files.

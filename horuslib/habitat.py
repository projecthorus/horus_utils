#!/usr/bin/env python2.7
#
#   Project Horus - Habitat Communication Functions
#   Copyright 2017 Mark Jessop <vk5qi@rfhead.net>
#

import httplib
import json
from hashlib import sha256
from base64 import b64encode
from datetime import datetime
from .packets import telemetry_to_sentence

# Habitat Upload Functions
def habitat_upload_payload_telemetry(telemetry, payload_callsign = "HORUSLORA", callsign="N0CALL"):

    sentence = telemetry_to_sentence(telemetry, payload_callsign = payload_callsign, payload_id = telemetry['payload_id'])

    sentence_b64 = b64encode(sentence)

    date = datetime.utcnow().isoformat("T") + "Z"

    data = {
        "type": "payload_telemetry",
        "data": {
            "_raw": sentence_b64
            },
        "receivers": {
            callsign: {
                "time_created": date,
                "time_uploaded": date,
                },
            },
    }
    try:
        c = httplib.HTTPConnection("habitat.habhub.org",timeout=4)
        c.request(
            "PUT",
            "/habitat/_design/payload_telemetry/_update/add_listener/%s" % sha256(sentence_b64).hexdigest(),
            json.dumps(data),  # BODY
            {"Content-Type": "application/json"}  # HEADERS
            )

        response = c.getresponse()
        return (True,"OK")
    except Exception as e:
        return (False,"Failed to upload to Habitat: %s" % (str(e)))
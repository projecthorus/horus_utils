#!/usr/bin/env python2.7
#
#   Project Horus - Habitat Communication Functions
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#

import httplib
import requests # Because I'm lazy.
import json
import sys
import traceback
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


def habitat_upload_sentence(sentence, callsign="N0CALL", timeout=4):

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
        c = httplib.HTTPConnection("habitat.habhub.org",timeout=timeout)
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


# URL to the spacenear.us datanew.php script, which we use to grab a JSON blob of vehicle (payload) data.
SPACENEARUS_DATANEW_URL = "https://spacenear.us/tracker/datanew.php?mode=%s&type=positions&format=json&max_positions=%d&position_id=0"
SPACENEARUS_TIMEOUT = 10


def get_vehicle_data(max_positions=100, vehicle=None, timeout=SPACENEARUS_TIMEOUT, history='1hour'):
    '''
    Attempt to get vehicle data from spacenear.us, using the same interface as the tracker.

    Returns (True, json_data) if request was successful,
    otherwise returns (False, "error message")

    The 'history' parameter sets how many hours back to get data for. This can be either:
    1hour, 3hours, 6hours
     '''

    _request_url = SPACENEARUS_DATANEW_URL % (history, max_positions)

    # Add on the specific vehicle flag if we want it.
    if vehicle is not None:
        _request_url += "&vehicle=%s" % vehicle

    # Attempt to get JSON data.
    try:
        _data = requests.get(_request_url, timeout=timeout)
        return (True, _data.json())

    except Exception as e:
        return (False, str(e))


def get_vehicle_list(max_positions=100, timeout=SPACENEARUS_TIMEOUT, history='1hour'):
    ''' Wrapper for the above, returning a list of vehicles. '''

    (success, _data) = get_vehicle_data(max_positions=max_positions, timeout=timeout, history=history)

    if not success:
        return (success, _data)
    
    # Try and parse the JSON blob
    try:
        _positions = _data['positions']['position']

        _vehicle_list = []

        for _pos in _positions:

            _vehicle_name = _pos['vehicle']

            if _vehicle_name not in _vehicle_list:
                _vehicle_list.append(_vehicle_name)

        return (True, _vehicle_list)

    except Exception as e:
        return (False, str(e))


def get_latest_position(vehicle, timeout=SPACENEARUS_TIMEOUT, history='1hour'):
    ''' Attempt to get the most recent position for a given vehicle. '''

    (success, _vehicle_data) = get_vehicle_data(max_positions=1, vehicle=vehicle, history=history)

    if success:
        try:
            _position = _vehicle_data['positions']['position'][0]
            return (True, _position)
        except Exception as e:
            return (False, str(e))
    else:
        return (False, _vehicle_data)



if __name__ == '__main__':
    print(get_vehicle_list())

    if len(sys.argv) > 1:
        _vehicle_name = sys.argv[1]

        (success, _position) = get_latest_position(_vehicle_name)
        if success:
            #print(_position)
            print("Vehicle Name: %s" % _position['vehicle'])
            print("Timestamp: %s" % _position['gps_time'])
            print("Position: %.5f, %.5f, %.1f" % (float(_position['gps_lat']), float(_position['gps_lon']), float(_position['gps_alt'])))
            print("Receivers: %s" % _position['callsign'])
#!/usr/bin/env python
#
# Horus Ground Station - Packet Emulation Utilities
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#
from .oziplotter import *
from .packets import send_payload_summary
import sys
import time
import traceback
from dateutil.parser import *
from datetime import datetime, timedelta

def read_telemetry_csv(filename,
    datetime_field = 0,
    latitude_field = 3,
    longitude_field = 4,
    altitude_field = 5,
    delimiter=','):
    ''' 
    Read in a Telemetry CSV file.
    Fields to use can be set as arguments to this function.
    By default we maintain compatability with the log files output by radiosonde_auto_rx, as they are good sources
    of flight telemetry data.
    These have output like the following:
    2017-12-27T23:21:59.560,M2913374,982,-34.95143,138.52471,719.9,-273.0,RS92,401.520
    <datetime>,<serial>,<frame_no>,<lat>,<lon>,<alt>,<temp>,<sonde_type>,<freq>

    Note that the datetime field must be parsable by dateutil.parsers.parse.

    If any fields are missing, or invalid, this function will return None.

    The output data structure is in the form:
    [
        [datetime (as a datetime object), latitude, longitude, altitude],
        [datetime (as a datetime object), latitude, longitude, altitude],
        ...
    ]
    '''

    output = []

    f = open(filename,'r')

    for line in f:
        try:
            # Split line by comma delimiters.
            _fields = line.split(delimiter)

            # Attempt to parse fields.
            _datetime = parse(_fields[datetime_field])
            _latitude = float(_fields[latitude_field])
            _longitude = float(_fields[longitude_field])
            _altitude = float(_fields[altitude_field])

            output.append([_datetime, _latitude, _longitude, _altitude])
        except:
            traceback.print_exc()
            return None

    f.close()

    return output


def emulate_telemetry(telemetry_array,
                    hostname = 'localhost',
                    port = HORUS_OZIPLOTTER_PORT,
                    speed = 1.0,
                    summary=False
                    ):
    '''
    Use a telemetry array to emit a sequence of OziPlotter telemetry UDP messages,
    which take the format:
        TELEMETRY,HH:MM:SS,latitude,longitude,altitude\n
    '''

    # Use the current time as the start time for our telemetry sentences.
    _first_time = True

    # Read in first line.
    _first_line = telemetry_array[0]

    _telemetry_datetime = _first_line[0]
    _current_datetime = datetime.utcnow()
    _current_latitude = _first_line[1]
    _current_longitude =_first_line[2]
    _current_altitude = _first_line[3]

    for _telem in telemetry_array:

        _new_time = _telem[0]
        _current_latitude = _telem[1]
        _current_longitude = _telem[2]
        _current_altitude = _telem[3]

        # Get Delta in time between telemetry lines.
        _time_delta = _new_time - _telemetry_datetime
        _telemetry_datetime = _new_time

        # Calculate our delay before emitting this packet.
        _delay_time = _time_delta.seconds*(1.0/speed)

        # Increment the emitted datetime field.
        _current_datetime = _current_datetime + _time_delta

        # Delay
        print("Sleeping for %.1f seconds." % _delay_time)
        time.sleep(_delay_time)

        # Format telemetry datainto a dictionary.
        _upload_telemetry = {
            'time': _current_datetime.strftime("%H:%M:%S"),
            'latitude': _current_latitude,
            'longitude': _current_longitude,
            'altitude': _current_altitude
            }

        _sentence = oziplotter_upload_basic_telemetry(_upload_telemetry, hostname = hostname, udp_port = port)

        if summary:
            send_payload_summary("TEST", _current_latitude, _current_longitude, _current_altitude, short_time=_current_datetime.strftime("%H:%M:%S"))

        print(_sentence)


if __name__ == '__main__':

    filename = ""
    speed = 1.0
    hostname = 'localhost'
    udp_port = 55680

    if len(sys.argv) == 2:
        filename = sys.argv[1]
    elif len(sys.argv) == 3:
        filename = sys.argv[1]
        speed = float(sys.argv[2])


    telemetry_data = read_telemetry_csv(filename)

    emulate_telemetry(telemetry_data, 
                    hostname=hostname,
                    port=udp_port,
                    speed=speed)
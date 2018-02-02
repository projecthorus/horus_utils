#!/usr/bin/env python2.7
#
#   Project Horus - OziPlotter Communication Functions
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#

import socket
from . import *

# Default Oziplotter listen port is UDP 8942
HORUS_OZIPLOTTER_PORT = 8942


# The new 'generic' OziPlotter upload function, with no callsign, or checksumming (why bother, really)
def oziplotter_upload_basic_telemetry(telemetry, hostname="127.0.0.1", udp_port = HORUS_OZIPLOTTER_PORT):
    sentence = "TELEMETRY,%s,%.5f,%.5f,%d\n" % (telemetry['time'],telemetry['latitude'], telemetry['longitude'],telemetry['altitude'])

    try:
        ozisock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        ozisock.sendto(sentence,(hostname,udp_port))
        ozisock.close()
        return sentence
    except Exception as e:
        print("Failed to send to Ozi: " % e)
        return None

# Push a car waypoint into OziPlotter. Could be used for other waypoints too.
def oziplotter_upload_car_telemetry(car_telem, hostname="127.0.0.1", udp_port = HORUS_OZIPLOTTER_PORT):
    sentence = "WAYPOINT,%s,%.5f,%.5f,%s\n" % (car_telem['callsign'], car_telem['latitude'], car_telem['longitude'], car_telem['message'])

    try:
        ozisock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        ozisock.sendto(sentence,(hostname,udp_port))
        ozisock.close()
    except Exception as e:
        print("Failed to send to Ozi: " % e)
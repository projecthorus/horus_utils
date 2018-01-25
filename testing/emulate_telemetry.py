#
#   Project Horus - Telemetry Emulation Script
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#
from horuslib.emulation import *

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
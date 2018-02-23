#
#   Project Horus - Telemetry Emulation Script
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#
import argparse
from horuslib.emulation import *

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument("filename", type=str, help="Telemetry file to use as a data source.")
    parser.add_argument('-s', '--speed', type=int, default=1, help="Update multiplication factor (speed up packets by X times)")
    parser.add_argument("--udp_host", type=str, default='localhost', help="OziMux Hostname")
    parser.add_argument("--udp_port", type=int, default=55680, help="OziMux UDP Port (default=55680)")
    parser.add_argument("--summary", action='store_true', default=False, help="Emit Payload Summary messages.")
    args = parser.parse_args()

    telemetry_data = read_telemetry_csv(args.filename)

    emulate_telemetry(telemetry_data, 
                    hostname=args.udp_host,
                    port=args.udp_port,
                    speed=args.speed,
                    summary=args.summary)
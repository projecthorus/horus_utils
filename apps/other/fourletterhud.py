#!/usr/bin/env python2.7
#
#   Project Horus 
#   Pimoroni Four-Letter-Phat HUD
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#
#   Displays payload altitude on a Pimoroni 'Four Letter Phat'
#   See: https://learn.pimoroni.com/tutorial/sandyj/getting-started-with-four-letter-phat
#

import time, sys
from horuslib import *
from horuslib.listener import *
from horuslib.geometry import GenericTrack
from horuslib.atmosphere import time_to_landing
import fourletterphat as flp


car_altitude = 0.0
payload_track = GenericTrack()
landing_time = -1

display_mode = 'alt' # or 'time-to-landing'


def handle_payload_summary(packet):
    ''' Handle a 'payload summary' packet, received by the UDP Listener below '''
    global car_altitude, display_mode, payload_track, landing_time

    # Attempt to parse a timestamp from the supplied packet.
    try:
        packet_time = datetime.strptime(packet['time'], "%H:%M:%S")
        # Insert the hour/minute/second data into the current UTC time.
        packet_dt = datetime.utcnow().replace(hour=packet_time.hour, minute=packet_time.minute, second=packet_time.second, microsecond=0)

    except:
        # If no timestamp is provided, use system time instead.
        print("No time provided, using system time.")
        packet_dt = datetime.utcnow()


    new_latitude = packet['latitude']
    new_longitude = packet['longitude']
    new_altitude = packet['altitude']

    # Update the GenericTrack object with the latest position.
    payload_track.add_telemetry({'time':packet_dt, 'lat':new_latitude, 'lon':new_longitude, 'alt': new_altitude})

    # Grab the latest state out of the GenericTrack object, and extract the ascent rate from it.
    _latest_state = payload_track.get_latest_state()
    if _latest_state != None:
        ascent_rate = _latest_state['ascent_rate']
    else:
        ascent_rate = 0.0

    # If we are descending, calculate the time to landing.
    if ascent_rate < 0.0:
        landing_time = time_to_landing(new_altitude, ascent_rate, car_altitude)
        _landing_min = landing_time//60
        _landing_sec = landing_time%60
    else:
        landing_time = -1

    if display_mode == 'alt':
        # Show the current altitude
        current_alt = int(packet['altitude'])

        # Format the payload altitude (in metres) into something displayable.
        if current_alt > 9999:
            # Format into KK.MM (i.e. 31150M -> 31.15)
            alt_km = int(current_alt/1000.0)
            alt_m = (current_alt % 1000)/10
            alt_str = "%02d.%02d" % (alt_km, alt_m)
        elif current_alt < 10000:
            alt_str = "%04d" % current_alt
        else:
            alt_str = '0000'

        print("Got Altitude %d, displaying: %s" % (current_alt, alt_str))

        flp.print_number_str(alt_str)
        flp.show()

    else:
        # Show the time to landing if we are in descent, otherwise show --.--
        if landing_time < 0:
            ttl_string = "--.--"
        else:
            ttl_string = "%02d.%02d" % (_landing_min, _landing_sec)

        flp.print_number_str(ttl_string)
        flp.show()


def handle_car_telemetry(packet):
    ''' Handle a car position packet '''
    global car_altitude

    # All we need out of this packet is the current altitude
    try:
        car_altitude = packet['altitude']
    except:
        pass


if __name__ == "__main__":

    if len(sys.argv) > 1:
        if sys.argv[1] == 'ttl':
            display_mode = 'ttl'
        else:
            display_mode = 'alt'

    udp_rx = UDPListener(summary_callback=handle_payload_summary, gps_callback=handle_car_telemetry)
    udp_rx.start()

    flp.print_str("----")
    flp.show()

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        udp_rx.close()
        print("Closing.")
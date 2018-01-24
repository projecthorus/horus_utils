#!/usr/bin/env python2.7
#
#   Project Horus 
#   Pimoroni Four-Letter-Phat HUD
#   Copyright 2015 Mark Jessop <vk5qi@rfhead.net>
#
#   Displays payload altitude on a Pimoroni 'Four Letter Phat'
#   See: https://learn.pimoroni.com/tutorial/sandyj/getting-started-with-four-letter-phat
#

import time
from horuslib import *
from horuslib.listener import *
import fourletterphat as flp

def handle_payload_summary(packet):
    ''' Handle a 'payload summary' packet, received by the UDP Listener below '''

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

if __name__ == "__main__":
    udp_rx = UDPListener(summary_callback=handle_payload_summary)
    udp_rx.start()

    flp.print_str("----")
    flp.show()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        udp_rx.close()
        print("Closing.")
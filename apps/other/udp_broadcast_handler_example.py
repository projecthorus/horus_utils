#!/usr/bin/env python
# Example Handling of UDP broadcast messages.
# 2018-03-09 Mark Jessop <vk5qi@rfhead.net>
#
import time
from horuslib.listener import *


def handle_payload_summary(packet):
    ''' Handle a 'Payload Summary' UDP broadcast message, supplied as a dict. '''
    # Just print the packet.
    print(packet)


def handle_gps_data(packet):
    ''' Handle a 'GPS' UDP broadcast message (sent by ChaseTracker), supplied as a dict. '''
    # Just print the packet
    print(packet)


def handle_all_packets(packet):
    ''' Handle *all* packet types '''
    # Just print the packet
    print(packet)


if __name__ == '__main__':
    
    # Instantiate the UDP listener.
    udp_rx = UDPListener(
        callback = handle_all_packets,
        summary_callback = handle_payload_summary,
        gps_callback = handle_gps_data
        )
    # and start it
    udp_rx.start()

    # From here, everything happens in the callback functions above.
    try:
        while True:
            time.sleep(1)
    # Catch CTRL+C nicely.
    except KeyboardInterrupt:
        # Close UDP listener.
        udp_rx.close()
        print("Closing.")
#!/usr/bin/env python
# Example Handling of UDP broadcast messages.
# 2018-03-09 Mark Jessop <vk5qi@rfhead.net>
#
import time, datetime
from horuslib.listener import OziListener, UDPListener

# Exaple packet
#{u'speed': -1, u'altitude': 12469, u'longitude': 139.23114, u'callsign': u'Radiosonde Auto RX', 
# u'time': u'11:54:52', u'latitude': -34.99711, u'type': u'PAYLOAD_SUMMARY', u'heading': -1}
def handle_payload_summary(packet):
    ''' Handle a 'Payload Summary' UDP broadcast message, supplied as a dict. '''
    # Extract fields
    _callsign = packet['callsign']
    _lat = packet['latitude']
    _lon = packet['longitude']
    _alt = packet['altitude']
    _time = packet['time']
    # There are also 'speed' and 'heading' fields, but currently nothing provides useful data in these.

    # The comment field isn't always provided.
    if 'comment' in packet:
        _comment = packet['comment']
    else:
        _comment = "No Comment Provided"

    # Print out the data as a string.
    print("Payload Summary: %s, %s, %.5f, %.5f, %.1f, %s" % 
        (_callsign,
        _time,
        _lat,
        _lon,
        _alt,
        _comment
        ))


def handle_gps_data(packet):
    ''' Handle a 'GPS' UDP broadcast message (sent by ChaseTracker), supplied as a dict. '''
    # Extract fields.
    _lat = packet['latitude']
    _lon = packet['longitude']
    _alt = packet['altitude']
    _speed = packet['speed']
    # No timestamp is provided in these packets, so make our own.
    _time = datetime.datetime.utcnow().isoformat()

    # Print out the data as a string
    print("Car GPS: %s, %.5f, %.5f, %.1f, %.1f" % 
        (_time,
        _lat,
        _lon,
        _alt,
        _speed
        ))


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
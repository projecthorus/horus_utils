#!/usr/bin/env python
#
#   Output payload telemetry information to a serial port (or a file) as NMEA0183-compatible GPGGA sentences.
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#
import argparse, time, datetime, serial, sys
from dateutil.parser import parse
from horuslib.listener import UDPListener


# Output object (either a serial object, or a file object). We instantiate this in __main__
out_obj = None


def pos_to_nmea(lat,lon,alt,time=None):
    ''' 
    Convert a payload position to a GPGGA sentence. 
    If a time is provided (as a datetime object), it will be used for the time field.
    '''

    # Convert float latitude to NMEA format (DDMM.MMM)
    lat = float(lat)
    lat_degree = abs(int(lat))
    lat_minute = abs(lat - int(lat)) * 60.0
    lat_min_str = ("%02.3f" % lat_minute)
    lat_str = "%02d%s" % (lat_degree,lat_min_str)

    if lat>0.0:
        lat_dir = "N"
    else:
        lat_dir = "S"
    
    # Convert float longitude to NMEA format (DDDMM.MMM)
    lon = float(lon)
    lon_degree = abs(int(lon))
    lon_minute = abs(lon - int(lon)) * 60.0
    lon_min_str = ("%02.3f" % lon_minute)
    lon_str = "%03d%s" % (lon_degree,lon_min_str)
    if lon<0.0:
        lon_dir = "W"
    else:
        lon_dir = "E"

    # Convert the provided time into NMEA format (HHMMSS.SS)
    if time is None:
        _time_str = "000000.00"
    else:
        _time_str = time.strftime("%H%M%S.00")

    # Generate the GPGGA sentence (without the trailing checksum and line-endings, they are added later)
    _gpgga = "GPGGA,%s,%s,%s,%s,%s,1,10,1.0,%.1f,M,,,," % (
        _time_str,
        lat_str,
        lat_dir,
        lon_str,
        lon_dir,
        alt)

    # Calculate the XOR checksum of the generated sentence.
    _csum = 0
    for _c in _gpgga:
        _csum ^= ord(_c)

    # Create the final sentence.
    _out_gpgga = "$%s*%02X" % (_gpgga, _csum)

    return _out_gpgga


def handle_payload_summary(packet):
    ''' Handle a 'Payload Summary' UDP broadcast message, supplied as a dict. '''
    # Use the global serial object
    global s

    # Extract fields
    _callsign = packet['callsign']
    _lat = packet['latitude']
    _lon = packet['longitude']
    _alt = packet['altitude']
    _time = packet['time']
    # There are also 'speed' and 'heading' fields, but currently nothing provides useful data in these.

    # Convert the 'short' time field into a datetime object.
    _time_dt = parse(_time)

    # Generate the GPGGA sentence and print it
    _gpgga = pos_to_nmea(_lat,_lon,_alt,_time_dt)

    print(_gpgga)

    # Write to the serial/file object
    if out_obj is not None:
        out_obj.write(_gpgga + '\r\n')

        if type(out_obj) == file:
            out_obj.flush()



if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument('output', default='telem.nmea', help="Either a Serial Port name (i.e. /dev/ttyUSB or COM1), or a file name.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--serial", action="store_true", help="Output to a serial port.")
    group.add_argument("--file", action="store_true", help="Output to a file.")
    parser.add_argument('--serial_baud', type=int, default=4800, help="Serial Port baud rate, if using a serial port.")
    args = parser.parse_args()

    # Open the serial or file object.
    if args.serial:
        print("Opening serial port: %s at %d baud." % (args.output, args.serial_baud))
        out_obj = serial.Serial(args.output, args.serial_baud)
    else:
        print("Opening File: %s" % args.output)
        out_obj = open(args.output,'w')

    
    # Instantiate the UDP listener.
    udp_rx = UDPListener(
        summary_callback = handle_payload_summary
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
        out_obj.close()
        print("Closing.")
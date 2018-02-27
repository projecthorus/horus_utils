#!/usr/bin/env python
#
#   ChaseTracker - No GUI Version
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#
# Upload chase car (or stationary listener) positions to Habitat, for plotting on the map.
# Also pushes 'GPS' UDP broadcast packets into the local network, 
# for use by SummaryGUI, RotatorGUI and HorusGroundStation.
#
# Usage: python ChaseTracker_NoGUI.py
# All settings are read from defaults.cfg. 
#

import urllib2, json, ConfigParser, sys, time, serial, socket, re, logging, traceback
from threading import Thread
from base64 import b64encode
from hashlib import sha256
from datetime import datetime
from horuslib import *

# Attempt to read in config file
config = ConfigParser.RawConfigParser()
config.read("defaults.cfg")

callsign = config.get("User","callsign")
update_rate = int(config.get("GPS","update_rate"))
serial_port = config.get("GPS","serial_port")
serial_baud = int(config.get("GPS","serial_baud"))
speed_cap = int(config.get("GPS","speed_cap"))
stationary = config.getboolean("User","stationary")

# Only push GPS data out to the network, not to Habitat
gps_only = False


# Position Variables
position_valid = False
lat = -34.0
lon = 138.0
alt = 0
speed = 0 # m/s


# Broadcast our position within the local network via UDP broadcast,
# so other applications can make use of it.
def gps_via_udp():
    global lat,lon,alt,speed,position_valid
    packet = {
        'type' : 'GPS',
        'latitude': lat,
        'longitude': lon,
        'altitude': alt,
        'speed': speed*3.6, # Convert speed to kph.
        'valid': position_valid
    }

    # Set up our UDP socket
    s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    s.settimeout(1)
    # Set up socket for broadcast, and allow re-use of the address
    s.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except:
        pass
    s.bind(('',HORUS_UDP_PORT))
    try:
        s.sendto(json.dumps(packet), ('<broadcast>', HORUS_UDP_PORT))
    except socket.error:
        s.sendto(json.dumps(packet), ('127.0.0.1', HORUS_UDP_PORT))

# Courtesy of https://github.com/Knio/pynmea2/
def dm_to_sd(dm):
    '''
    Converts a geographic coordiante given in "degres/minutes" dddmm.mmmm
    format (ie, "12319.943281" = 123 degrees, 19.953281 minutes) to a signed
    decimal (python float) format
    '''
    # '12319.943281'
    if not dm or dm == '0':
        return 0.
    d, m = re.match(r'^(\d+)(\d\d\.\d+)$', dm).groups()
    return float(d) + float(m) / 60

# We currently only recognise GPGGA and GPRMC
def parseNMEA(data):
    global lat,lon,speed,alt,position_valid, speed_cap
    if "$GPRMC" in data:
        logging.debug("Got GPRMC.")
        gprmc = data.split(",")
        gprmc_lat = dm_to_sd(gprmc[3])
        gprmc_latns = gprmc[4]
        gprmc_lon = dm_to_sd(gprmc[5])
        gprmc_lonew = gprmc[6]
        gprmc_speed = float(gprmc[7])

        if gprmc_latns == "S":
            lat = gprmc_lat*-1.0
        else:
            lat = gprmc_lat

        if gprmc_lon == "W":
            lon = gprmc_lon*-1.0
        else:
            lon = gprmc_lon

        speed = min(speed_cap*0.27778, gprmc_speed*0.51444)

    if "$GPGGA" in data:
        logging.debug("Got GPGGA.")
        gpgga = data.split(",")
        gpgga_lat = dm_to_sd(gpgga[2])
        gpgga_latns = gpgga[3]
        gpgga_lon = dm_to_sd(gpgga[4])
        gpgga_lonew = gpgga[5]
        gpgga_fixstatus = gpgga[6]
        alt = float(gpgga[9])


        if gpgga_latns == "S":
            lat = gpgga_lat*-1.0
        else:
            lat = gpgga_lat

        if gpgga_lon == "W":
            lon = gpgga_lon*-1.0
        else:
            lon = gpgga_lon 

        if gpgga_fixstatus == 0:
            position_valid = False
        else:
            position_valid = True
            gps_via_udp()


# Habitat Upload Stuff, from https://raw.githubusercontent.com/rossengeorgiev/hab-tools/master/spot2habitat_chase.py
callsign_init = False
url_habitat_uuids = "http://habitat.habhub.org/_uuids?count=%d"
url_habitat_db = "http://habitat.habhub.org/habitat/"
uuids = []

def ISOStringNow():
    return "%sZ" % datetime.utcnow().isoformat()


def postData(doc):
    # do we have at least one uuid, if not go get more
    if len(uuids) < 1:
        fetch_uuids()

    # add uuid and uploade time
    doc['_id'] = uuids.pop()
    doc['time_uploaded'] = ISOStringNow()

    data = json.dumps(doc)
    headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'Referer': url_habitat_db,
            }

    logging.debug("Posting doc to habitat\n%s" % json.dumps(doc, indent=2))

    req = urllib2.Request(url_habitat_db, data, headers)
    return urllib2.urlopen(req, timeout=10).read()

def fetch_uuids():
    while True:
        try:
            resp = urllib2.urlopen(url_habitat_uuids % 10, timeout=10).read()
            data = json.loads(resp)
        except urllib2.HTTPError, e:
            logging.error("Unable to fetch uuids. Retrying in 10 seconds...");
            time.sleep(10)
            continue

        logging.debug("Received a set of uuids.")
        uuids.extend(data['uuids'])
        break;


def init_callsign(callsign):
    doc = {
            'type': 'listener_information',
            'time_created' : ISOStringNow(),
            'data': { 'callsign': callsign }
            }

    while True:
        try:
            resp = postData(doc)
            logging.info("Callsign initialized.")
            break;
        except urllib2.HTTPError, e:
            logging.error("Unable initialize callsign. Retrying in 10 seconds...");
            traceback.print_exc()
            time.sleep(10)
            continue

def uploadPosition():
    # initialize call sign (one time only)
    global callsign_init, callsign, lat, lon, alt, speed, stationary
    if not callsign_init:
        init_callsign(callsign)
        callsign_init = True

    doc = {
        'type': 'listener_telemetry',
        'time_created': ISOStringNow(),
        'data': {
            'callsign': callsign,
            'chase': (not stationary),
            'latitude': lat,
            'longitude': lon,
            'altitude': alt,
            'speed': speed,
        }
    }

    # post position to habitat
    try:
        postData(doc)
    except urllib2.HTTPError, e:
        logging.error("Unable to upload data!")
        traceback.print_exc()
        return

    logging.info("Uploaded Position Data at: %s" % ISOStringNow())


# Start UDP Listener Thread
serial_running = True
def serialListener():
    """ Serial Port Listener Thread
        Parse incoming serial data as NMEA and update global position variables
    """
    global serial_running, serial_port, serial_baud
    _ser = None

    while serial_running:
        # Attempt to connect to the serial port.
        while _ser == None:
            try:
                _ser = serial.Serial(port=serial_port,baudrate=serial_baud,timeout=5)
                logging.info("Connected to serial port.")
            except Exception as e:
                # Continue re-trying until we can connect to the serial port.
                # This should let the user connect the gps *after* this script starts if required.
                logging.error("Serial Port Error: %s" % e)
                logging.error("Sleeping 10s before attempting re-connect.")
                time.sleep(10)
                _ser = None
                continue

        # Read a line of (hopefully) NMEA from the serial port.
        try:
            data = _ser.readline()
        except:
            # If we hit a serial read error, attempt to reconnect.
            logging.error("Error reading from serial device! Attempting to reconnect.")
            _ser = None
            continue

        # Attempt to parse data.
        try:
            parseNMEA(data)
        except:
            pass

    # Clean up before exiting thread.
    _ser.close()
    logging.info("Closing Serial Thread.")


upload_loop_running = True
last_upload_time = time.time()
def uploadLoop():
    """ Habitat Uploader Thread.
        Every X seconds, upload current position to Habitat (if it is valid).
    """
    global position_valid, update_rate, upload_loop_running, last_upload_time
    while upload_loop_running:
        if position_valid and not gps_only:
            if (time.time() - last_upload_time) > update_rate:
                uploadPosition()
                last_upload_time = time.time()

        time.sleep(0.5)

    logging.info("Closing Habitat Upload Thread.")

## Start Qt event loop unless running in interactive mode or using pyside.
if __name__ == '__main__':

    if len(sys.argv) > 1:
        if sys.argv[1] == 'noupload':
            print("Not uploading to habitat...s")
            gps_only = True

    logging.basicConfig(format='%(asctime)s %(levelname)s:%(message)s', level=logging.INFO)
    logging.info("Starting Serial Listener Thread.")
    serial_thread = Thread(target=serialListener)
    serial_thread.start()

    time.sleep(5)

    logging.info("Starting Habitat Uploader Thread.")
    habitat_thread = Thread(target=uploadLoop)
    habitat_thread.start()

    # Sleep until die.
    while True:
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            upload_loop_running = False
            serial_running = False
            sys.exit(1)




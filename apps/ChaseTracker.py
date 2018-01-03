#!/usr/bin/env python
#
# ChaseTracker 2.0
# Written by: Mark Jessop <vk5qi@rfhead.net> (C) 2015
#
import urllib2, json, ConfigParser, sys, time, serial, Queue, socket
from threading import Thread
from base64 import b64encode
from hashlib import sha256
from datetime import datetime
from PyQt5 import QtGui, QtWidgets, QtCore
from horuslib import *

# Attempt to read in config file
config = ConfigParser.RawConfigParser()
config.read("defaults.cfg")

callsign = config.get("User","callsign")
update_rate = int(config.get("GPS","update_rate"))
serial_port = config.get("GPS","serial_port")
serial_baud = int(config.get("GPS","serial_baud"))
speed_cap = int(config.get("GPS","speed_cap"))
stationary = bool(config.get("User","stationary"))

# RX Message queue to avoid threading issues.
rxqueue = Queue.Queue(16)

# Position Variables
position_valid = False
lat = -34.0
lon = 138.0
alt = 0
speed = 0 # m/s

# GUI Initialisation
app = QtWidgets.QApplication([])

currentPositionLabel = QtWidgets.QLabel("")

gpsStatusLabel = QtWidgets.QLabel("No Data Yet...")
gpsStatusLabel.setWordWrap(True)

habitatStatusLabel = QtWidgets.QLabel("No Data Yet...")
habitatStatusLabel.setWordWrap(True)

uploadEnabled = QtWidgets.QCheckBox("Enable Upload")
uploadEnabled.setChecked(True)

# Create and Lay-out window
win = QtWidgets.QWidget()
win.resize(350,100)
win.show()
win.setWindowTitle("ChaseTracker - %s" % callsign)
layout = QtWidgets.QGridLayout()
win.setLayout(layout)
# Add Widgets
layout.addWidget(currentPositionLabel,0,0,1,1)
layout.addWidget(uploadEnabled,0,1,1,1)
layout.addWidget(gpsStatusLabel,1,0,1,2)
layout.addWidget(habitatStatusLabel,2,0,1,2)


def updateGui():
    positionText = "<b>Lat/Long:</b> %.5f, %.5f <br> <b>Speed:</b> %d kph<br> <b>Alt:</b> %d m" % (lat,lon,speed*3.6,alt)
    currentPositionLabel.setText(positionText)

updateGui()

# Broadcast our position within the local network via UDP broadcast,
# so other applications can make use of it.
def gps_via_udp():
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
import re
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
    global lat,lon,speed,alt,position_valid,speed_cap
    if "$GPRMC" in data:
        gpsStatusLabel.setText("Got GPRMC.")
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
        gpsStatusLabel.setText("Got GPGGA.")
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

    updateGui()


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

    habitatStatusLabel.setText("Posting doc to habitat\n%s" % json.dumps(doc, indent=2))

    req = urllib2.Request(url_habitat_db, data, headers)
    return urllib2.urlopen(req).read()

def fetch_uuids():
    while True:
        try:
            resp = urllib2.urlopen(url_habitat_uuids % 10).read()
            data = json.loads(resp)
        except urllib2.HTTPError, e:
            habitatStatusLabel.setText("Unable to fetch uuids. Retrying in 10 seconds...");
            time.sleep(10)
            continue

        habitatStatusLabel.setText("Received a set of uuids.")
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
            habitatStatusLabel.setText("Callsign initialized.")
            break;
        except urllib2.HTTPError, e:
            habitatStatusLabel.setText("Unable initialize callsign. Retrying in 10 seconds...");
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
        habitatStatusLabel.setText("Unable to upload data!")
        return

    habitatStatusLabel.setText("Uploaded Data at: %s" % ISOStringNow())


def uploadTimer():
    if position_valid:
        try:
            if uploadEnabled.isChecked():
                uploadPosition()
        except:
            pass

timer = QtCore.QTimer()
timer.timeout.connect(uploadTimer)
timer.start(update_rate*1000)

def readQueue():
    try:
        data = rxqueue.get_nowait()
        parseNMEA(data)
    except:
        pass

timer2 = QtCore.QTimer()
timer2.timeout.connect(readQueue)
timer2.start(200)

# Start UDP Listener Thread
serial_running = True
def serialListener():
    try:
        ser = serial.Serial(port=serial_port,baudrate=serial_baud,timeout=5)
    except Exception as e:
        gpsStatusLabel.setText("Serial Port Error: %s" % e)
        return

    while serial_running:
        data = ser.readline()
        try:
            rxqueue.put_nowait(data)
        except:
            pass

    ser.close()

t = Thread(target=serialListener)
t.start()

## Start Qt event loop unless running in interactive mode or using pyside.
if __name__ == '__main__':
    if (sys.flags.interactive != 1) or not hasattr(QtCore, 'PYQT_VERSION'):
        QtWidgets.QApplication.instance().exec_()
        serial_running = False
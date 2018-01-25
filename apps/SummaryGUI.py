#!/usr/bin/env python2.7
# -*- coding: UTF-8 -*-
#
#   Project Horus 
#   Payload Summary GUI
#   Used as a 'quick look' summary of basic payload statistics (alt, ascent rate, etc)
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#

from horuslib import *
from horuslib.packets import *
from horuslib.earthmaths import *
from threading import Thread
from PyQt5 import QtGui, QtCore, QtWidgets
from datetime import datetime
import socket,json,sys,Queue,traceback,time,math


udp_broadcast_port = HORUS_UDP_PORT
udp_listener_running = False

# RX Message queue to avoid threading issues.
rxqueue = Queue.Queue(16)

# At what data age (Seconds) do we show a warning or error indication?
PAYLOAD_DATA_WARN = 20.0
PAYLOAD_DATA_ERROR = 60.0
GPS_DATA_WARN = 10.0 # We expect GPS data to be coming in once per second.
GPS_DATA_ERROR = 30.0

# Local Payload state variables.
use_supplied_time = False
payload_latitude = 0.0
payload_longitude = 0.0
payload_altitude = 0.0
payload_lastdata = -1
payload_data_age = 0

# Car state variables
car_latitude = 0.0
car_longitude = 0.0
car_altitude = 0.0
car_bearing = -1
car_speed = 0
car_lastdata = -1
car_data_age = 0


# PyQt Window Setup
app = QtWidgets.QApplication([])

#
# Create and Lay-out window
#
main_widget = QtWidgets.QWidget()
layout = QtWidgets.QGridLayout()
main_widget.setLayout(layout)
# Create Widgets
data_font_size = 18
altitudeLabel = QtWidgets.QLabel("<b>Alt</b>")
altitudeValue = QtWidgets.QLabel("<b>00000m</b>")
altitudeValue.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
speedLabel = QtWidgets.QLabel("<b>Speed</b>")
speedValue = QtWidgets.QLabel("<b>000kph</b>")
speedValue.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
ascrateLabel = QtWidgets.QLabel("<b>Asc</b>")
ascrateValue = QtWidgets.QLabel("<b>-00.0m/s</b>")
ascrateValue.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
azimuthLabel = QtWidgets.QLabel("<b>Az</b>")
azimuthValue = QtWidgets.QLabel("<b>NNE(000°)</b>")
azimuthValue.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
elevationLabel = QtWidgets.QLabel("<b>Elev</b>")
elevationValue = QtWidgets.QLabel("<b>00°</b>")
elevationValue.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
rangeLabel = QtWidgets.QLabel("<b>Range</b>")
rangeValue = QtWidgets.QLabel("<b>0000m</b>")
rangeValue.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))

statusLabel1 = QtWidgets.QLabel("<b>Payload Data Age:</b>")
statusLabel1.setAlignment(QtCore.Qt.AlignRight)
statusValue1 = QtWidgets.QLabel("%0.1fs" % (payload_data_age))
statusValue1.setAlignment(QtCore.Qt.AlignCenter)
statusLabel2 = QtWidgets.QLabel("<b>GPS Data Age:</b>")
statusLabel2.setAlignment(QtCore.Qt.AlignRight)
statusValue2 = QtWidgets.QLabel("%0.1fs" % (car_data_age))
statusValue2.setAlignment(QtCore.Qt.AlignCenter)
statusValue1.setAutoFillBackground(True)
statusValue1.setStyleSheet("background: green")
statusValue2.setAutoFillBackground(True)
statusValue2.setStyleSheet("background: green")


# Lay Out Widgets
layout.addWidget(altitudeLabel,0,0)
layout.addWidget(altitudeValue,0,1)
layout.addWidget(speedLabel,0,2)
layout.addWidget(speedValue,0,3)
layout.addWidget(ascrateLabel,0,4)
layout.addWidget(ascrateValue,0,5)
layout.addWidget(azimuthLabel,1,0)
layout.addWidget(azimuthValue,1,1)
layout.addWidget(elevationLabel,1,2)
layout.addWidget(elevationValue,1,3)
layout.addWidget(rangeLabel,1,4)
layout.addWidget(rangeValue,1,5)
layout.addWidget(statusLabel1,2,0,1,2)
layout.addWidget(statusValue1,2,2,1,1)
layout.addWidget(statusLabel2,2,3,1,2)
layout.addWidget(statusValue2,2,5,1,1)


mainwin = QtWidgets.QMainWindow()
mainwin.setWindowFlags(mainwin.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

# Finalise and show the window
mainwin.setWindowTitle("Payload Summary")
mainwin.setCentralWidget(main_widget)
mainwin.resize(600,100)
mainwin.show()

# Speed Calculation Should probably move this to another file.
def speed_calc(lat,lon,lat2,lon2,timediff):

    temp = position_info((lat,lon,0.0), (lat2,lon2,0.0))

    return (temp['great_circle_distance']/float(timediff))*3.6


def calculate_az_el_range():
    global payload_latitude, payload_longitude, payload_altitude, car_latitude, car_longitude, car_altitude, azimuthValue, elevationValue, rangeValue

    # Don't calculate anything if either the car or balloon data is invalid.
    if car_lastdata == -1:
        return

    if payload_lastdata == -1:
        return

    # Calculate az/el/range using the CUSF EarthMaths library.
    balloon_coords = position_info((car_latitude,car_longitude,car_altitude), (payload_latitude, payload_longitude, payload_altitude))
    azimuth = balloon_coords['bearing']
    elevation = balloon_coords['elevation']
    range_val = balloon_coords['straight_distance']
    # Calculate cardinal direction (N/NW/etc) from azimuth
    cardinal_direction = bearing_to_cardinal(azimuth)

    # Set display values.
    azimuthValue.setText("%3s(%3d°)" % (cardinal_direction,int(azimuth)))
    elevationValue.setText("%2d°" % int(elevation))
    # Display range in km if >1km, in metres otherwise.
    if range_val >= 1000.0:
        rangeValue.setText("%3.1fkm" % (range_val/1000.0))
    else:
        rangeValue.setText("%4dm" % int(range_val))

    

def update_payload_stats(packet):
    global payload_latitude, payload_longitude, payload_altitude, payload_lastdata, payload_data_age, altitudeValue, speedValue, ascrateValue, use_supplied_time
    try:
        # Attempt to parse a timestamp from the supplied packet.
        try:
            packet_time = datetime.strptime(packet['time'], "%H:%M:%S")
            # Insert the hour/minute/second data into the current UTC time.
            packet_dt = datetime.utcnow().replace(hour=packet_time.hour, minute=packet_time.minute, second=packet_time.second, microsecond=0)
            # Convert into a unix timestamp:
            timestamp = (packet_dt - datetime(1970, 1, 1)).total_seconds()
        except:
            # If no timestamp is provided, use system time instead.
            print("No time provided, using system time.")
            packet_dt = datetime.utcnow()
            timestamp = (packet_dt - datetime(1970, 1, 1)).total_seconds()

        # Get the time difference in seconds.
        time_diff = timestamp - payload_lastdata

        new_latitude = packet['latitude']
        new_longitude = packet['longitude']
        new_altitude = packet['altitude']

        ascent_rate = (new_altitude - payload_altitude)/time_diff
        speed = speed_calc(payload_latitude, payload_longitude, new_latitude, new_longitude, time_diff)

        # Update Displays.
        altitudeValue.setText("%5dm" % int(new_altitude))
        speedValue.setText("%3dkph" % int(speed))
        ascrateValue.setText("%2.1fm/s" % ascent_rate)
        mainwin.setWindowTitle("Payload Summary - %s" % packet['callsign'])

        # Save payload state values.
        payload_latitude = new_latitude
        payload_longitude = new_longitude
        payload_altitude = new_altitude
        payload_lastdata = timestamp
        payload_data_age = 0.0
        calculate_az_el_range()
    except:
        traceback.print_exc()

    calculate_az_el_range()

def update_car_stats(packet):
    global car_latitude, car_longitude, car_altitude, car_lastdata, car_data_age, car_bearing, car_speed
    try:
        timestamp = time.time()
        time_diff = timestamp - car_lastdata

        new_car_latitude = packet['latitude']
        new_car_longitude = packet['longitude']
        new_car_altitude = packet['altitude']

        car_speed = speed_calc(car_latitude,car_longitude, new_car_latitude, new_car_longitude,time_diff)

        if car_speed > 15:
            car_movement = position_info((car_latitude,car_longitude,car_altitude), (new_car_latitude,new_car_longitude,new_car_altitude))
            car_bearing = car_movement['bearing']

        car_latitude = new_car_latitude
        car_longitude = new_car_longitude
        car_altitude = new_car_altitude

        car_lastdata = timestamp
        car_data_age = 0.0
        calculate_az_el_range()
    except:
        traceback.print_exc()

# Method to process UDP packets.
def process_udp(udp_packet):
    try:
        packet_dict = json.loads(udp_packet)

        # TX Confirmation Packet?
        if packet_dict['type'] == 'PAYLOAD_SUMMARY':
            update_payload_stats(packet_dict)
        elif packet_dict['type'] == 'GPS':
            update_car_stats(packet_dict)
        else:
            #print(".")
            pass
            #print("Got other packet type (%s)" % packet_dict['type'])

    except:
        traceback.print_exc()
        pass

def udp_rx_thread():
    global udp_listener_running
    s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    s.settimeout(1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except:
        pass
    s.bind(('',HORUS_UDP_PORT))
    print("Started UDP Listener Thread.")
    udp_listener_running = True
    while udp_listener_running:
        try:
            m = s.recvfrom(MAX_JSON_LEN)
        except socket.timeout:
            m = None
        
        if m != None:
            rxqueue.put_nowait(m[0])
    
    print("Closing UDP Listener")
    s.close()


def read_queue():
    global statusValue1, statusValue2, payload_data_age, car_data_age
    try:
        packet = rxqueue.get_nowait()
        process_udp(packet)
    except:
        pass

    # Update 'data age' text.
    payload_data_age += 0.1
    car_data_age += 0.1
    statusValue1.setText("%0.1fs" % payload_data_age)
    statusValue2.setText("%0.1fs" % car_data_age)

    if payload_data_age > PAYLOAD_DATA_ERROR:
        statusValue1.setStyleSheet("background: red") 
    elif payload_data_age > PAYLOAD_DATA_WARN:
        statusValue1.setStyleSheet("background: yellow")
    else:
        statusValue1.setStyleSheet("background: green")

    if car_data_age > GPS_DATA_ERROR:
        statusValue2.setStyleSheet("background: red") 
    elif car_data_age > GPS_DATA_WARN:
        statusValue2.setStyleSheet("background: yellow")
    else:
        statusValue2.setStyleSheet("background: green")

# Start a timer to attempt to read the remote station status every 5 seconds.
timer = QtCore.QTimer()
timer.timeout.connect(read_queue)
timer.start(100)

## Start Qt event loop unless running in interactive mode or using pyside.
if __name__ == '__main__':
    if (sys.flags.interactive != 1) or not hasattr(QtCore, 'PYQT_VERSION'):
        t = Thread(target=udp_rx_thread)
        t.start()
        QtWidgets.QApplication.instance().exec_()
        udp_listener_running = False

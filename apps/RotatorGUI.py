#!/usr/bin/env python2.7
# -*- coding: UTF-8 -*-
#
#   Project Horus 
#   Rotator Control GUI
#   Derivative of the SummaryGUI App, used to control a rotator.
#   Copyright 2017 Mark Jessop <vk5qi@rfhead.net>
#
#
# TODO LIST:
# [x] Make location/az/el overrides work
# [ ] Handle +/- 180 degree azimuth better for some rotctld rotators.
# [ ] Allow for azimuth-only rotators.
# [ ] Test on real hardware!
# [ ] Get payload positions from other sources.
#     [ ] Habitat ?
#     [ ] APRS ?

from horuslib import *
from horuslib.packets import *
from horuslib.earthmaths import *
from horuslib.rotators import PSTRotator, ROTCTLD
from threading import Thread
from PyQt5 import QtGui, QtCore, QtWidgets
from datetime import datetime
import socket,json,sys,Queue,traceback,time,math,ConfigParser,logging


logging.basicConfig(format='%(asctime)s %(levelname)s:%(message)s', level=logging.INFO)

# Read in Config Data
config = ConfigParser.RawConfigParser()
config.read("defaults.cfg")

rotator_type = config.get("Rotator", "rotator_type")
rotator_hostname = config.get("Rotator", "rotator_hostname")
rotator_poll_rate = int(config.get("Rotator", "rotator_poll_rate"))
if rotator_type == 'pstrotator':
    rotator_port = int(config.get("Rotator", "pstrotator_port"))
elif rotator_type == 'rotctld':
    rotator_port = int(config.get("Rotator", "rotctld_port"))
else:
    logging.error("Invalid Rotator Specified!")
    sys.exit(1)


# RX Message queue to avoid threading issues.
rxqueue = Queue.Queue(16)

# Me/Payload/Az/El Globals
PAYLOAD_DATA_VALID = False
PAYLOAD_LATITUDE = 0.0
PAYLOAD_LONGITUDE = 0.0
PAYLOAD_ALTITUDE = 0.0
PAYLOAD_DATA_AGE = 0.0
PAYLOAD_AZIMUTH = 0.0
PAYLOAD_ELEVATION = 0.0

MY_LATITUDE = 0.0
MY_LONGITUDE = 0.0
MY_ALTITUDE = 0.0
MY_DATA_VALID = False
MY_DATA_AGE = 0.0

# Rotator Object
rotator = None

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

# FRAME 1 - My Location
myDataFrame = QtWidgets.QFrame()
myDataFrame.setFrameStyle(QtWidgets.QFrame.Box)

myDataLabel = QtWidgets.QLabel("<b><u>My Location</u><b>")
myLatitudeLabel = QtWidgets.QLabel("<b>Latitude</b>")
myDataLatitudeValue = QtWidgets.QLabel("???.?????")
myDataLatitudeValue.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
myLongitudeLabel = QtWidgets.QLabel("<b>Longitude</b>")
myDataLongitudeValue = QtWidgets.QLabel("???.?????")
myDataLongitudeValue.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
myAltitudeLabel = QtWidgets.QLabel("<b>Altitude</b>")
myDataAltitudeValue = QtWidgets.QLabel("????m")
myDataAltitudeValue.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
myDataFixLocation = QtWidgets.QCheckBox("Lock Location")
myDataStatus = QtWidgets.QLabel("No Data Yet.")

myDataLayout = QtWidgets.QGridLayout()
myDataLayout.addWidget(myDataLabel,0,0)
myDataLayout.addWidget(myDataFixLocation,0,2)
myDataLayout.addWidget(myLatitudeLabel,1,0)
myDataLayout.addWidget(myLongitudeLabel,1,1)
myDataLayout.addWidget(myAltitudeLabel,1,2)
myDataLayout.addWidget(myDataLatitudeValue,2,0)
myDataLayout.addWidget(myDataLongitudeValue,2,1)
myDataLayout.addWidget(myDataAltitudeValue,2,2)
myDataLayout.addWidget(myDataStatus,3,0,1,3)
myDataFrame.setLayout(myDataLayout)


# FRAME 2 - Payload Location
payloadDataFrame = QtWidgets.QFrame()
payloadDataFrame.setFrameStyle(QtWidgets.QFrame.Box)

payloadDataLabel = QtWidgets.QLabel("<b><u>Payload Location</u><b>")
payloadLatitudeLabel = QtWidgets.QLabel("<b>Latitude</b>")
payloadLongitudeLabel = QtWidgets.QLabel("<b>Longitude</b>")
payloadAltitudeLabel = QtWidgets.QLabel("<b>Altitude</b>")
payloadDataLatitudeValue = QtWidgets.QLabel("???.?????")
payloadDataLatitudeValue.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
payloadDataLongitudeValue = QtWidgets.QLabel("???.?????")
payloadDataLongitudeValue.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
payloadDataAltitudeValue = QtWidgets.QLabel("????m")
payloadDataAltitudeValue.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
payloadDataStatus = QtWidgets.QLabel("No Data Yet.")

payloadDataLayout = QtWidgets.QGridLayout()
payloadDataLayout.addWidget(payloadDataLabel,0,0)
payloadDataLayout.addWidget(payloadLatitudeLabel,1,0)
payloadDataLayout.addWidget(payloadLongitudeLabel,1,1)
payloadDataLayout.addWidget(payloadAltitudeLabel,1,2)
payloadDataLayout.addWidget(payloadDataLatitudeValue,2,0)
payloadDataLayout.addWidget(payloadDataLongitudeValue,2,1)
payloadDataLayout.addWidget(payloadDataAltitudeValue,2,2)
payloadDataLayout.addWidget(payloadDataStatus,3,0,1,3)
payloadDataFrame.setLayout(payloadDataLayout)

# FRAME 3 - Calculated Info
calculatedDataFrame = QtWidgets.QFrame()
calculatedDataFrame.setFrameStyle(QtWidgets.QFrame.Box)

calculatedDataLabel = QtWidgets.QLabel("<b><u>Calculated Data</u><b>")
azimuthLabel = QtWidgets.QLabel("<b>Azimuth</b>")
azimuthValue = QtWidgets.QLabel("<b>NNE(000.0°)</b>")
azimuthValue.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
elevationLabel = QtWidgets.QLabel("<b>Elev</b>")
elevationValue = QtWidgets.QLabel("<b>00.0°</b>")
elevationValue.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
rangeLabel = QtWidgets.QLabel("<b>Range</b>")
rangeValue = QtWidgets.QLabel("<b>0000m</b>")
rangeValue.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
rotatorEnableButton = QtWidgets.QPushButton("Enable")

calculatedDataLayout = QtWidgets.QGridLayout()
calculatedDataLayout.addWidget(calculatedDataLabel,0,0,1,1)
calculatedDataLayout.addWidget(azimuthLabel,1,0)
calculatedDataLayout.addWidget(elevationLabel,1,1)
calculatedDataLayout.addWidget(rangeLabel,1,2)
calculatedDataLayout.addWidget(azimuthValue,2,0)
calculatedDataLayout.addWidget(elevationValue,2,1)
calculatedDataLayout.addWidget(rangeValue,2,2)
calculatedDataFrame.setLayout(calculatedDataLayout)

# FRAME 4 - Rotator Control
rotatorFrame = QtWidgets.QFrame()
rotatorFrame.setFrameStyle(QtWidgets.QFrame.Box)

rotatorLabel = QtWidgets.QLabel("<b><u>Rotator Control</u><b>")
rotatorConnectButton = QtWidgets.QPushButton("Connect")
rotatorHomeButton = QtWidgets.QPushButton("Park")
rotatorHoldButton = QtWidgets.QPushButton("Hold")
rotatorHoldButton.setCheckable(True)
rotatorHoldButton.setChecked(True)
rotatorCurrentLabel = QtWidgets.QLabel("<b>Current Position:<b>")
rotatorCurrentValue = QtWidgets.QLabel("Az: ---.-°  Elev: --.-°")
rotatorCurrentValue.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
rotatorCommandedLabel = QtWidgets.QLabel("<b>Commanded Position:<b>")
rotatorCommandedValue = QtWidgets.QLabel("Az: ---.-°  Elev: --.-°")
rotatorCommandedValue.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
rotatorStatusLabel = QtWidgets.QLabel("Not Connected")

rotatorLayout = QtWidgets.QGridLayout()
rotatorLayout.addWidget(rotatorLabel,0,0)
rotatorLayout.addWidget(rotatorConnectButton,1,0)
rotatorLayout.addWidget(rotatorHomeButton,1,1)
rotatorLayout.addWidget(rotatorHoldButton,1,2)
rotatorLayout.addWidget(rotatorCurrentLabel,2,0,1,1)
rotatorLayout.addWidget(rotatorCurrentValue,2,1,1,2)
rotatorLayout.addWidget(rotatorCommandedLabel,3,0,1,1)
rotatorLayout.addWidget(rotatorCommandedValue,3,1,1,2)
rotatorLayout.addWidget(rotatorStatusLabel,4,0,1,3)

rotatorFrame.setLayout(rotatorLayout)

# Lay Out Widgets
layout.addWidget(myDataFrame,0,0)
layout.addWidget(payloadDataFrame,1,0)
layout.addWidget(calculatedDataFrame,2,0)
layout.addWidget(rotatorFrame,3,0)


mainwin = QtWidgets.QMainWindow()
# Add Menu Options
exitAction = QtWidgets.QAction('&Exit', mainwin)        
exitAction.setShortcut('Ctrl+Q')
exitAction.setStatusTip('Exit application')
exitAction.triggered.connect(QtWidgets.qApp.quit)



menubar = mainwin.menuBar()
menubar.setNativeMenuBar(False)
fileMenu = menubar.addMenu('&File')
fileMenu.addAction(exitAction)

settingsMenu = menubar.addMenu('&Overrides')

# Finalise and show the window
mainwin.setWindowTitle("Horus Rotator Control")
mainwin.setCentralWidget(main_widget)
mainwin.resize(600,100)
mainwin.show()


def connect_rotator():
    global rotator, rotator_type, rotator_hostname, rotator_port, rotator_poll_rate
    global rotatorStatusLabel, rotatorConnectButton

    # Close a rotator object if one exists
    try:
        rotator.close()
    except:
        pass

    if rotator_type == 'pstrotator':
        # PST Rotator handles polling internally, we don't need to pass it a poll rate variable.
        rotator = PSTRotator(rotator_hostname, rotator_port)
        # Not much need to check this one, as it talks entirely via UDP.
        # Can only tell if its working by watching the PSTRotator window...
        rotatorStatusLabel.setText("Started PSTRotator Connection.")
    elif rotator_type == 'rotctld':
        # Create object, and start connection.
        rotator = ROTCTLD(rotator_hostname, rotator_port)
        try:
            model = rotator.connect()
            rotatorStatusLabel.setText("Connected to Rotator Type: %s" % model)
        except:
            rotatorStatusLabel.setText("Failed to connect to rotator!")
            rotator = None

rotatorConnectButton.clicked.connect(connect_rotator)


def rotator_update():
    """ Update the rotator position when new data is received """
    global rotator, rotatorHoldButton, rotatorCommandedValue
    global PAYLOAD_DATA_VALID, MY_DATA_VALID, PAYLOAD_ELEVATION, PAYLOAD_AZIMUTH

    if rotatorHoldButton.isChecked():
        # Don't do any updates if the hold button is checked. 
        return

    if rotator == None:
        # Rotator isn't connected.
        return

    if PAYLOAD_DATA_VALID and MY_DATA_VALID:
        response = rotator.set_azel(PAYLOAD_AZIMUTH, PAYLOAD_ELEVATION)
        if response:
            rotatorCommandedValue.setText("Az: %3.1f°  Elev: %2.1f°" % (PAYLOAD_AZIMUTH, PAYLOAD_ELEVATION))
        else:
            rotatorCommandedValue.setText("Comms Fault!")
    else:
        return

def park_rotator():
    """ Set Rotator to 0,0 """
    global rotator, rotatorHoldButton, rotatorCommandedValue

    if rotator != None:
        response = rotator.set_azel(0.0, 0.0)
        if response:
            rotatorCommandedValue.setText("Az: %3.1f°  Elev: %2.1f°" % (0.0, 0.0))
            rotatorHoldButton.setChecked(True)
        else:
            rotatorCommandedValue.setText("Comms Fault!")

rotatorHomeButton.clicked.connect(park_rotator)


def poll_rotator():
    """ Try and poll the rotator for data """
    global rotator, rotatorCurrentValue

    if rotator != None:
        try:
            (_az,_el) = rotator.get_azel()
            if (_az == None) or (_el == None):
                rotatorCurrentValue.setText("Az: ???.?°  Elev: ??.?°")
            else:
                rotatorCurrentValue.setText("Az: %3.1f°  Elev: %2.1f°" % (_az,_el))
        except:
            rotatorCurrentValue.setText("Comms Fault!")

rotator_poll_timer = QtCore.QTimer()
rotator_poll_timer.timeout.connect(poll_rotator)
rotator_poll_timer.start(rotator_poll_rate*1000)


def override_location():
    """ Allow user to set a manual location """
    global MY_LATITUDE, MY_LONGITUDE, MY_ALTITUDE, MY_DATA_VALID, MY_DATA_AGE
    global myDataLatitudeValue, myDataLongitudeLabel, myDataLatitudeValue, myDataFixLocation

    text, ok = QtWidgets.QInputDialog.getText(main_widget,'Set Manual Location', 'New Location: lat,lon,alt ')

    if ok:
        try:
            _params = text.split(',')
            _latitude = float(_params[0])
            _longitude = float(_params[1])
            _altitude = float(_params[2])

            # Update global variables.
            MY_LATITUDE = _latitude
            MY_LONGITUDE = _longitude
            MY_ALTITUDE = _altitude
            MY_DATA_VALID = True

            # Update GUI Labels
            myDataLatitudeValue.setText("%.5f" % MY_LATITUDE)
            myDataLongitudeValue.setText("%.5f" % MY_LONGITUDE)
            myDataAltitudeValue.setText("%d" % int(MY_ALTITUDE))

            myDataFixLocation.setChecked(True)
            calculate_az_el_range()

        except:
            logging.error("Invalid manual location entered.")
            _msgBox = QtWidgets.QMessageBox()
            _msgBox.setText("Invalid entry format!")
            _msgBox.exec_()


# Add menu option.
myPosOverrideAction = QtWidgets.QAction('&My Position', mainwin)
myPosOverrideAction.setShortcut('Ctrl+M')
myPosOverrideAction.setStatusTip('Set My Latitude, Longitude, and Altitude Manually')
myPosOverrideAction.triggered.connect(override_location)
settingsMenu.addAction(myPosOverrideAction)


def override_payload_position():
    """ Allow user to set a manual payload position """
    global PAYLOAD_LATITUDE, PAYLOAD_LONGITUDE, PAYLOAD_ALTITUDE, PAYLOAD_DATA_VALID, PAYLOAD_DATA_AGE
    global payloadDataLatitudeValue, payloadDataLongitudeValue, payloadDataAltitudeValue, rotatorHoldButton

    text, ok = QtWidgets.QInputDialog.getText(main_widget,'Set Manual Payload Position', 'New Position: lat,lon,alt ')

    if ok:
        try:
            _params = text.split(',')
            _latitude = float(_params[0])
            _longitude = float(_params[1])
            _altitude = float(_params[2])

            # Update global variables.
            PAYLOAD_LATITUDE = _latitude
            PAYLOAD_LONGITUDE = _longitude
            PAYLOAD_ALTITUDE = _altitude
            PAYLOAD_DATA_VALID = True

            # Update GUI Labels
            payloadDataAltitudeValue.setText("%5dm" % int(PAYLOAD_ALTITUDE))
            payloadDataLatitudeValue.setText("%.5f" % PAYLOAD_LATITUDE)
            payloadDataLongitudeValue.setText("%.5f" % PAYLOAD_LONGITUDE)

            rotatorHoldButton.setChecked(True)
            calculate_az_el_range()

        except:
            logging.error("Invalid manual location entered.")
            _msgBox = QtWidgets.QMessageBox()
            _msgBox.setText("Invalid entry format!")
            _msgBox.exec_()


# Add menu option.
payloadPosOverrideAction = QtWidgets.QAction('&Payload Position', mainwin)
payloadPosOverrideAction.setShortcut('Ctrl+P')
payloadPosOverrideAction.setStatusTip('Set Payload Latitude, Longitude, and Altitude Manually')
payloadPosOverrideAction.triggered.connect(override_payload_position)
settingsMenu.addAction(payloadPosOverrideAction)


def override_azel():
    """ Allow user to set a manual azimuth and elevation """
    global azimuthValue, elevationValue, rotatorHoldButton
    global PAYLOAD_AZIMUTH, PAYLOAD_ELEVATION, PAYLOAD_DATA_VALID
    text, ok = QtWidgets.QInputDialog.getText(main_widget,'Set Manual Azimuth and Elevation', 'New Position: azimuth,elevation')

    if ok:
        try:
            _params = text.split(',')
            _azimuth = float(_params[0])
            _elevation = float(_params[1])

            # Update global variables.
            PAYLOAD_AZIMUTH = _azimuth
            PAYLOAD_ELEVATION = _elevation
            PAYLOAD_DATA_VALID = True
            rotatorHoldButton.setChecked(False)
            rotator_update()

            rotatorHoldButton.setChecked(True)

        except:
            logging.error("Invalid manual position entered.")
            _msgBox = QtWidgets.QMessageBox()
            _msgBox.setText("Invalid entry format!")
            _msgBox.exec_()


# Add menu option.
rotatorOverrideAction = QtWidgets.QAction('&Rotator Position', mainwin)
rotatorOverrideAction.setShortcut('Ctrl+R')
rotatorOverrideAction.setStatusTip('Set Rotator Azimuth/Elevation Manually')
rotatorOverrideAction.triggered.connect(override_azel)
settingsMenu.addAction(rotatorOverrideAction)


def calculate_az_el_range():
    """ Calculate Azimuth/Elevation/Range from my location and Payload Data """
    global azimuthValue, elevationValue, rangeValue, rotatorHoldButton
    global PAYLOAD_LATITUDE, PAYLOAD_LONGITUDE, PAYLOAD_ALTITUDE, PAYLOAD_AZIMUTH, PAYLOAD_ELEVATION, PAYLOAD_DATA_VALID
    global MY_LATITUDE, MY_LONGITUDE, MY_ALTITUDE, MY_DATA_VALID

    # Don't calculate anything if either the car or balloon data is invalid.
    if not MY_DATA_VALID:
        return

    if not PAYLOAD_DATA_VALID:
        return

    # Calculate az/el/range using the CUSF EarthMaths library.
    balloon_coords = position_info((MY_LATITUDE, MY_LONGITUDE, MY_ALTITUDE), (PAYLOAD_LATITUDE, PAYLOAD_LONGITUDE, PAYLOAD_ALTITUDE))
    PAYLOAD_AZIMUTH = balloon_coords['bearing']
    PAYLOAD_ELEVATION = balloon_coords['elevation']
    range_val = balloon_coords['straight_distance']
    # Calculate cardinal direction (N/NW/etc) from azimuth
    cardinal_direction = bearing_to_cardinal(PAYLOAD_AZIMUTH)

    # Set display values.
    azimuthValue.setText("%3s(%3.1f°)" % (cardinal_direction,PAYLOAD_AZIMUTH))
    elevationValue.setText("%2.1f°" % PAYLOAD_ELEVATION)
    # Display range in km if >1km, in metres otherwise.
    if range_val >= 1000.0:
        rangeValue.setText("%3.1fkm" % (range_val/1000.0))
    else:
        rangeValue.setText("%4dm" % int(range_val))

    # Update rotator position!
    rotator_update()


def update_payload_stats(packet):
    """ Parse a Payload Summary UDP Packet and update the payload location fields """
    global PAYLOAD_LATITUDE, PAYLOAD_LONGITUDE, PAYLOAD_ALTITUDE, PAYLOAD_DATA_VALID, PAYLOAD_DATA_AGE
    global payloadDataLatitudeValue, payloadDataLongitudeValue, payloadDataAltitudeValue

    try:
        # Set Global Variables
        PAYLOAD_LATITUDE = packet['latitude']
        PAYLOAD_LONGITUDE = packet['longitude']
        PAYLOAD_ALTITUDE = packet['altitude']
        PAYLOAD_DATA_VALID = True
        PAYLOAD_DATA_AGE = 0.0


        # Update Displays.
        payloadDataAltitudeValue.setText("%5dm" % int(PAYLOAD_ALTITUDE))
        payloadDataLatitudeValue.setText("%.5f" % PAYLOAD_LATITUDE)
        payloadDataLongitudeValue.setText("%.5f" % PAYLOAD_LONGITUDE)

        # Re-calculate azimuth and elevation.
        calculate_az_el_range()
    except:
        traceback.print_exc()


def update_my_stats(packet):
    """ Parse a GPS UDP packet and update the 'my location' fields """
    global MY_LATITUDE, MY_LONGITUDE, MY_ALTITUDE, MY_DATA_VALID, MY_DATA_AGE
    global myDataLatitudeValue, myDataLongitudeLabel, myDataLatitudeValue, myDataFixLocation
    try:
        MY_DATA_AGE = 0.0
        # Don't update anything if the 'fix location' Checkbox is checked.
        if myDataFixLocation.isChecked():
            return
        # Update global variables.
        MY_LATITUDE = packet['latitude']
        MY_LONGITUDE = packet['longitude']
        MY_ALTITUDE = packet['altitude']
        MY_DATA_VALID = True

        # Update GUI Labels
        myDataLatitudeValue.setText("%.5f" % MY_LATITUDE)
        myDataLongitudeValue.setText("%.5f" % MY_LONGITUDE)
        myDataAltitudeValue.setText("%d" % int(MY_ALTITUDE))

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
            update_my_stats(packet_dict)
        else:
            pass
            #print("Got other packet type (%s)" % packet_dict['type'])

    except:
        traceback.print_exc()
        pass

udp_listener_running = False
def udp_rx_thread():
    """ Listen for broadcast UDP packets from ChaseTracker / HorusGroundStation, and push into a queue """
    global udp_listener_running
    s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    s.settimeout(1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except:
        pass
    s.bind(('',HORUS_UDP_PORT))
    logging.debug("Started UDP Listener Thread.")
    udp_listener_running = True
    while udp_listener_running:
        try:
            m = s.recvfrom(MAX_JSON_LEN)
        except socket.timeout:
            m = None
        
        if m != None:
            rxqueue.put_nowait(m[0])
    
    logging.debug("Closing UDP Listener")
    s.close()


def read_queue():
    """ Read a packet from the Queue """
    global myDataStatus, payloadDataStatus, PAYLOAD_DATA_AGE, MY_DATA_AGE
    try:
        packet = rxqueue.get_nowait()
        process_udp(packet)
    except:
        pass

    # Update 'data age' text.
    PAYLOAD_DATA_AGE += 0.1
    MY_DATA_AGE += 0.1
    myDataStatus.setText("Position Data Age: %0.1fs" % MY_DATA_AGE)
    payloadDataStatus.setText("Payload Data Age: %0.1fs" %  PAYLOAD_DATA_AGE)


# Start a timer to attempt to read a UDP packet every 100ms
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
        rotator.close()

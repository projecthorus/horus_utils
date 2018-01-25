#!/usr/bin/env python2.7
#
#   Project Horus - Habitat (well, ok, spacenear.us) -> OziMux Bridge
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#
#   Grab a list of currently observed vehicles on spacenear.us, and 
#   allow the user to select from them. Once one is selected, continue
#   to check for updates and push them through to OziMux.
#
#   Copyright 2017 Mark Jessop <vk5qi@rfhead.net>
#

import time
import sys
import datetime
import traceback
from dateutil.parser import parse
from horuslib import *
from horuslib.oziplotter import *
from horuslib.habitat import *
from PyQt5 import QtGui, QtWidgets, QtCore

# I/O Settings. These generally don't need to be changed.
OZIMUX_OUTPUT_HOST = 'localhost'
OZIMUX_OUTPUT_PORT = 55682
HABITAT_UPDATE_RATE = 10 # Check for updates every x seconds.
HABITAT_HISTORY = '1hour' # How old data we want. Can be either 1hour, 3hours, or 6hours.

# Global stuff
data_age = 0.0
last_position = {'gps_time':'None'}


# PyQt Window Setup
app = QtWidgets.QApplication([])

#
# Create and Lay-out window
#
main_widget = QtWidgets.QWidget()
layout = QtWidgets.QGridLayout()
main_widget.setLayout(layout)

# Create Widgets
vehicleLabel = QtWidgets.QLabel("<b>Payload Selection:<b>")
vehicleList = QtWidgets.QComboBox()
vehicleList.addItem("<None>")
vehicleUpdate = QtWidgets.QPushButton("Update")

vehicleData = QtWidgets.QLabel("No Data Yet...")
vehicleData.setFont(QtGui.QFont("Courier New", 14, QtGui.QFont.Bold))
vehicleData2 = QtWidgets.QLabel("No Data Yet...")

outputEnabled = QtWidgets.QCheckBox("Enable")

statusLabel = QtWidgets.QLabel("No Payload Selected.")
dataAgeLabel = QtWidgets.QLabel("No Data Yet...")


# Final layout of frames
layout.addWidget(vehicleLabel,0,0,1,1)
layout.addWidget(vehicleList,0,1,1,2)
layout.addWidget(vehicleUpdate,0,3,1,1)
layout.addWidget(vehicleData,1,0,1,3)
layout.addWidget(outputEnabled,1,3,1,1)
layout.addWidget(vehicleData2,2,0,1,3)
layout.addWidget(dataAgeLabel,2,3,1,1)
layout.addWidget(statusLabel,3,0,1,4)


mainwin = QtWidgets.QMainWindow()

# Finalise and show the window
mainwin.setWindowTitle("Habitat Bridge")
mainwin.setCentralWidget(main_widget)
mainwin.resize(500,50)
mainwin.show()


def data_age_timer():
    ''' Update the 'data age' status display '''
    global data_age, dataAgeLabel
    data_age += 0.1
    dataAgeLabel.setText("Data Age: %0.1fs" % data_age)


def update_vehicle_list():
    ''' Update the list of vehicles from Habitat '''
    global vehicleList

    statusLabel.setText("Attempting to get vehicle list...")
    # Attempt to get a list of vehicles from Habitat.
    (success, _vehicle_list) = get_vehicle_list(history=HABITAT_HISTORY)

    if not success:
        statusLabel.setText("Failed to get vehicle list: %s" % _vehicle_list)
        return

    # Otherwise, add the vehicles to the list.

    # Clear out existing list of items.
    for i in range(vehicleList.count()):
        vehicleList.removeItem(0)

    # Add in the 'None' item again.
    vehicleList.addItem("<None>")

    for _vehicle in _vehicle_list:
        vehicleList.addItem(_vehicle)

    statusLabel.setText("Vehicle List Updated.")


vehicleUpdate.clicked.connect(update_vehicle_list)

def update_from_habitat():
    ''' Update the selected vehicles position from Habitat '''

    global vehicleList, statusLabel, vehicleData, vehicleData2, last_position, outputEnabled, data_age

    if vehicleList.currentText() == "<None>":
        statusLabel.setText("No Payload Selected.")
        return

    statusLabel.setText("Getting Vehicle Position Update...")

    try:
        # Wrap all this in a try/catch, in case of unexpected errors.
        (success, _position) = get_latest_position(vehicleList.currentText(), history=HABITAT_HISTORY)

        if not success:
            statusLabel.setText("Failed to get position update: %s" % _position)
            return

        if last_position['gps_time'] != _position['gps_time']:
            # We have a new position!
            last_position = _position

            # Extract fields.
            _current_lat = float(_position['gps_lat'])
            _current_lon = float(_position['gps_lon'])
            _current_alt = float(_position['gps_alt'])
            _current_datetime = parse(_position['gps_time'])
            _current_shorttime = _current_datetime.strftime("%H:%M:%S")
            _current_listeners = _position['callsign']

            # Update status labels
            vehicleData.setText("%s %.5f, %.5f, %.1f" % (_current_shorttime, _current_lat, _current_lon, _current_alt))
            vehicleData2.setText("Listeners: %s" % _current_listeners)

            # Reset data age.
            data_age = 0.0

            # If enabled, upload position to OziMux
            if outputEnabled.isChecked():
                # Get data into a format useful for the oziplotter output function
                _telem = {
                    'time': _current_shorttime,
                    'latitude': _current_lat,
                    'longitude': _current_lon,
                    'altitude': _current_alt
                }
                ozi_success = oziplotter_upload_basic_telemetry(_telem, hostname=OZIMUX_OUTPUT_HOST, udp_port=OZIMUX_OUTPUT_PORT)
                if ozi_success:
                    statusLabel.setText("Pushed position update to OziMux.")
                else:
                    statusLabel.setText("WARNING: Failed to push position update to OziMux.")
            else:
                statusLabel.setText("Position updated.")


        else:
            statusLabel.setText("No new position update.")

    except Exception as e:
        traceback.print_exc()
        statusLabel.setText("Could not update! %s" % str(e))



# Timer to update Data Age indicator
timer1 = QtCore.QTimer()
timer1.timeout.connect(data_age_timer)
timer1.start(100)

# Timer to update Habitat data
timer2 = QtCore.QTimer()
timer2.timeout.connect(update_from_habitat)
timer2.start(1000*HABITAT_UPDATE_RATE)


if __name__ == "__main__":

    if (sys.flags.interactive != 1) or not hasattr(QtCore, 'PYQT_VERSION'):
        QtWidgets.QApplication.instance().exec_()

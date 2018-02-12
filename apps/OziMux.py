#!/usr/bin/env python2.7
#
#   Project Horus 
#   OziPlotter Input Multiplexer
#   Allow switching between multiple data sources for OziPlotter
#   Also provides a unified source of 'Payload Summary' packets.
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#
import ConfigParser
import argparse
import socket
import sys
import os
import time
import traceback
import logging
import Queue
from threading import Thread
from PyQt5 import QtGui, QtCore, QtWidgets
from horuslib import *
from horuslib.packets import *

# RX Message queue to avoid threading issues.
rxqueue = Queue.Queue(32)

MAX_INPUTS = 4

class TelemetryListener(object):
    """
    Telemetry listener object. Listen on a supplied UDP port for OziPlotter-compatible telemetry data,
    and if enabled, output telemetry to OziPlotter.

    Incoming sentences are of the form:
    TELEMETRY.HH:MM:SS,latitude,longitude,altitude\n
    WAYPOINT,waypoint_name,latitude,longitude,comment\n
    """

    allowed_sentences = ['TELEMETRY', 'WAYPOINT']

    def __init__(self,
                source_name = "None",
                source_short_name = "none",
                oziplotter_host = "127.0.0.1",
                oziplotter_port = 8942,
                input_port = 55680,
                output_enabled = False,
                summary_enabled = False,
                pass_waypoints = True,
                callback = None,
                debug_output = True,
                log_enabled = False,
                log_path = "./log/"):

        self.source_name = source_name
        self.source_short_name = source_short_name
        self.ozi_host = (oziplotter_host, oziplotter_port)
        self.input_port = input_port
        self.output_enabled = output_enabled
        self.summary_enabled = summary_enabled
        self.pass_waypoints = pass_waypoints
        self.callback = callback
        self.log_enabled = log_enabled
        self.log_file = None
        self.log_path = log_path

        self.udp_listener_running = True

        self.t = Thread(target=self.udp_rx_thread)
        self.t.start()


    def enable_output(self, enabled):
        """
        Set the output enabled flag.
        """
        if enabled:
            self.output_enabled = True
        else:
            self.output_enabled = False

    def enable_summary(self, enabled):
        """
        Set the output enabled flag.
        """
        if enabled:
            self.summary_enabled = True
        else:
            self.summary_enabled= False


    def attach_callback(self, callback):
        self.callback = callback


    def udp_rx_thread(self):
        """
        Listen for incoming UDP packets, and pass them off to another function to be processed.
        """

        print("INFO: Starting Listener Thread: %s, port %d " % (self.source_name, self.input_port))
        self.s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        self.s.settimeout(1)
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except:
            pass
        self.s.bind(('',self.input_port))
        
        while self.udp_listener_running:
            try:
                m = self.s.recvfrom(256)
            except socket.timeout:
                m = None
            
            if m != None:
                try:
                    self.handle_packet(m[0])
                except:
                    traceback.print_exc()
                    print("ERROR: Couldn't handle packet correctly.")
                    pass
        
        print("INFO: Closing UDP Listener: %s" % self.source_name)
        self.s.close()


    def close(self):
        """
        Close the UDP listener thread.
        """
        self.udp_listener_running = False


    def send_packet_to_ozi(self, packet):
        """
        Send a string to OziPlotter
        """
        try:
            ozisock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
            ozisock.sendto(packet,self.ozi_host)
            ozisock.close()
        except Exception as e:
            print("ERROR: Failed to send to OziPlotter: %s" % e)


    def send_packet_summary(self, packet):
        """
        Attempt to parse the incoming packet into fields and send out a payload summary UDP message
        """

        try:
            _fields = packet.split(',')
            _short_time = _fields[1]
            _lat = float(_fields[2])
            _lon = float(_fields[3])
            _alt = int(_fields[4])

            send_payload_summary(self.source_name, _lat, _lon, _alt, short_time = _short_time)
        except:
            traceback.print_exc()


    def send_ozimux_broadcast(self, packet):
        """
        Attempt to parse the incoming packet into fields and send out an ozimux broadcast UDP message
        """

        try:
            _fields = packet.split(',')
            _short_time = _fields[1]
            _lat = float(_fields[2])
            _lon = float(_fields[3])
            _alt = int(_fields[4])

            send_ozimux_broadcast_packet(self.source_name, _lat, _lon, _alt, short_time=_short_time, comment="Via OziMux")
        except:
            traceback.print_exc()


    def handle_packet(self, packet):
        """
        Check an incoming packet matches a valid type, and then forward it on.
        """

        # Extract header (first field)
        packet_type = packet.split(',')[0]

        if packet_type not in self.allowed_sentences:
            print("ERROR: Got unknown packet: %s" % packet)
            return

        # Send received data to a callback function for display on a GUI.
        if self.callback != None:
            try:
                self.callback(self.source_name, packet)
            except:
                pass

        # Now send on the packet if we are allowed to.
        if packet_type == "TELEMETRY":
            self.send_ozimux_broadcast(packet)

        if packet_type == "TELEMETRY" and self.output_enabled:
            self.send_packet_to_ozi(packet)

        if packet_type == "TELEMETRY" and self.output_enabled and self.summary_enabled:
            self.send_packet_summary(packet)

        # Generally we always want to pass on waypoint data.
        if packet_type == "WAYPOINT" and self.pass_waypoints:
            self.send_packet_to_ozi(packet)

        # Handle logging, if enabled.
        if self.log_enabled:
            # Create log file, if it doesn't exist
            if self.log_file == None:
                # Log file name is timestamp + source short name
                # i.e. 20180201-010101_fldigi.log
                _log_file_name = os.path.join(self.log_path, datetime.utcnow().strftime("%Y%m%d-%H%M%S") + "_ozimux_%s.log"%self.source_short_name)
                self.log_file = open(_log_file_name,'w')

            # Each log entry is timestamped with the packet's received time.
            _log_entry = "%s,%s,%s" % (datetime.utcnow().isoformat(), self.source_short_name, packet)
            self.log_file.write(_log_entry)
            self.log_file.flush()



def read_config(filename="ozimux.cfg"):
    """
    Read in the ozimux config file.
    """
    config = ConfigParser.ConfigParser()
    config.read(filename)

    config_dict = {}

    config_dict['oziplotter_host'] = config.get("Global", "oziplotter_host")
    config_dict['oziplotter_port'] = config.getint("Global", "oziplotter_port")

    config_dict['number_of_inputs'] = config.getint("Global", "number_of_inputs")

    config_dict['enable_logging'] = config.getboolean("Global", "enable_logging")
    config_dict['log_directory'] = config.get("Global", "log_directory")

    config_dict['inputs'] = {}

    for n in range(config_dict['number_of_inputs']):
        input_name = config.get("Input_%d"%n, "input_name")
        input_port = config.getint("Input_%d"%n, "input_port")
        input_enabled = config.getboolean("Input_%d"%n, "enabled")
        short_name = config.get("Input_%d"%n, "input_short_name")

        config_dict['inputs'][input_name] = {}
        config_dict['inputs'][input_name]['port'] = input_port
        config_dict['inputs'][input_name]['enabled_at_start'] = input_enabled
        config_dict['inputs'][input_name]['source_short_name'] = short_name

    return config_dict



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

input1Frame = QtWidgets.QFrame()
input1Frame.setFixedSize(400,90)
input1Frame.setFrameStyle(QtWidgets.QFrame.Box)
input1Frame.setLineWidth(2)
input1Selected = QtWidgets.QCheckBox("Selected")
input1Title = QtWidgets.QLabel("<b><u>Not Active</u></b>")
input1Data = QtWidgets.QLabel("???.?????, ???.?????, ?????")
input1Data.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
input1DataAge = QtWidgets.QLabel("No Data Yet...")

input1Layout = QtWidgets.QGridLayout()
input1Layout.addWidget(input1Selected,0,1,1,1)
input1Layout.addWidget(input1Title,0,0)
input1Layout.addWidget(input1Data,1,0,1,2)
input1Layout.addWidget(input1DataAge,2,0,1,2)
input1Frame.setLayout(input1Layout)


input2Frame = QtWidgets.QFrame()
input2Frame.setFixedSize(400,90)
input2Frame.setFrameStyle(QtWidgets.QFrame.Box)
input2Frame.setLineWidth(2)
input2Selected = QtWidgets.QCheckBox("Selected")
input2Title = QtWidgets.QLabel("<b><u>Not Active</u></b>")
input2Data = QtWidgets.QLabel("???.?????, ???.?????, ?????")
input2Data.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
input2DataAge = QtWidgets.QLabel("No Data Yet...")

input2Layout = QtWidgets.QGridLayout()
input2Layout.addWidget(input2Selected,0,1,1,1)
input2Layout.addWidget(input2Title,0,0)
input2Layout.addWidget(input2Data,1,0,1,2)
input2Layout.addWidget(input2DataAge,2,0,1,2)
input2Frame.setLayout(input2Layout)

input3Frame = QtWidgets.QFrame()
input3Frame.setFixedSize(400,90)
input3Frame.setFrameStyle(QtWidgets.QFrame.Box)
input3Frame.setLineWidth(2)
input3Selected = QtWidgets.QCheckBox("Selected")
input3Title = QtWidgets.QLabel("<b><u>Not Active</u></b>")
input3Data = QtWidgets.QLabel("???.?????, ???.?????, ?????")
input3Data.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
input3DataAge = QtWidgets.QLabel("No Data Yet...")

input3Layout = QtWidgets.QGridLayout()
input3Layout.addWidget(input3Selected,0,1,1,1)
input3Layout.addWidget(input3Title,0,0)
input3Layout.addWidget(input3Data,1,0,1,2)
input3Layout.addWidget(input3DataAge,2,0,1,2)
input3Frame.setLayout(input3Layout)

input4Frame = QtWidgets.QFrame()
input4Frame.setFixedSize(400,90)
input4Frame.setFrameStyle(QtWidgets.QFrame.Box)
input4Frame.setLineWidth(2)
input4Selected = QtWidgets.QCheckBox("Selected")
input4Title = QtWidgets.QLabel("<b><u>Not Active</u></b>")
input4Data = QtWidgets.QLabel("???.?????, ???.?????, ?????")
input4Data.setFont(QtGui.QFont("Courier New", data_font_size, QtGui.QFont.Bold))
input4DataAge = QtWidgets.QLabel("No Data Yet...")

input4Layout = QtWidgets.QGridLayout()
input4Layout.addWidget(input4Selected,0,1,1,1)
input4Layout.addWidget(input4Title,0,0)
input4Layout.addWidget(input4Data,1,0,1,2)
input4Layout.addWidget(input4DataAge,2,0,1,2)
input4Frame.setLayout(input4Layout)

# Exclusive CheckBox group
inputSelector = QtWidgets.QButtonGroup()
inputSelector.addButton(input1Selected,0)
inputSelector.addButton(input2Selected,1)
inputSelector.addButton(input3Selected,2)
inputSelector.addButton(input4Selected,3)
inputSelector.setExclusive(True)

enableSummaryOutput = QtWidgets.QCheckBox("Enable Payload Summary Output")
enableSummaryOutput.setChecked(True)

# Indexed access to widgets.
inputTitles = [input1Title, input2Title, input3Title, input4Title]
inputData = [input1Data, input2Data, input3Data, input4Data]
inputDataAge = [input1DataAge, input2DataAge, input3DataAge, input4DataAge]
inputActive = [input1Selected, input2Selected, input3Selected, input4Selected]
inputLastData = [0,0,0,0]

# Final layout of frames
layout.addWidget(input1Frame)
layout.addWidget(input2Frame)
layout.addWidget(input3Frame)
layout.addWidget(input4Frame)
layout.addWidget(enableSummaryOutput)

mainwin = QtWidgets.QMainWindow()

# Finalise and show the window
mainwin.setWindowTitle("OziPlotter Input Mux")
mainwin.setCentralWidget(main_widget)
mainwin.resize(400,100)
mainwin.show()

def telemetry_callback(input_name, packet):
    """
    Place any new data into the receive queue, for processing
    """
    rxqueue.put((input_name,packet))



parser = argparse.ArgumentParser()
parser.add_argument("--config", type=str, default='ozimux.cfg', help="Configuration file. Default: ozimux.cfg")
args = parser.parse_args()


# Read in config file.
try:
    config = read_config(args.config)
except:
    print("Error reading %s, trying to read default!" % args.config)
    # Revert to the example config file if we don't have a custom config file to read, or if read fails.
    try:
        config = read_config("ozimux.cfg.example")
    except:
        print("Could not read example config file!")
        sys.exit(1)

# Extract input names into a list, which we will iterate through.
input_list = config['inputs'].keys()
input_list.sort()
if len(input_list) > MAX_INPUTS:
    input_list = input_list[:MAX_INPUTS]

num_inputs = len(input_list)

listener_objects = []

# Create Objects
for n in range(num_inputs):
    _obj = TelemetryListener(source_name = input_list[n],
                            source_short_name = config['inputs'][input_list[n]]['source_short_name'],
                            oziplotter_host = config['oziplotter_host'],
                            oziplotter_port = config['oziplotter_port'],
                            input_port = config['inputs'][input_list[n]]['port'],
                            output_enabled = config['inputs'][input_list[n]]['enabled_at_start'],
                            summary_enabled = config['inputs'][input_list[n]]['enabled_at_start'],
                            callback = telemetry_callback,
                            log_enabled = config['enable_logging'],
                            log_path = config['log_directory']
                            )

    listener_objects.append(_obj)

    # Set up GUI Widgets
    inputTitles[n].setText("<b><u>%s</u></b>" % input_list[n])
    if config['inputs'][input_list[n]]['enabled_at_start']:
        inputActive[n].setChecked(True)


# Handle checkbox changes.
def handle_checkbox():
    _checked_id = inputSelector.checkedId()
    for n in range(num_inputs):
        if n == _checked_id:
            listener_objects[n].enable_output(True)
            listener_objects[n].enable_summary(enableSummaryOutput.isChecked())
        else:
            listener_objects[n].enable_output(False)
            listener_objects[n].enable_summary(False)

inputSelector.buttonClicked.connect(handle_checkbox)
enableSummaryOutput.stateChanged.connect(handle_checkbox)


def handle_telemetry(input_name, packet):
    try:
        input_index = input_list.index(input_name)
        packet_fields = packet.split(',')

        if packet_fields[0] != 'TELEMETRY':
            return

        short_time = packet_fields[1]
        latitude = float(packet_fields[2])
        longitude = float(packet_fields[3])
        altitude = int(packet_fields[4])

        data_string = "%.5f, %.5f, %d" % (latitude, longitude, altitude)
        inputData[input_index].setText(data_string)
        inputLastData[input_index] = 0.0
    except:
        # Invalid input name, discard.
        return



def read_queue():
    """ Read a packet from the Queue """
    try:
        (input_name, packet) = rxqueue.get_nowait()
        handle_telemetry(input_name, packet)
    except:
        pass

    # Update 'data age' text.
    for n in range(num_inputs):
        inputLastData[n] += 0.1
        inputDataAge[n].setText("Data Age: %0.1fs" % inputLastData[n])


# Start a timer to attempt to read a UDP packet every 100ms
timer = QtCore.QTimer()
timer.timeout.connect(read_queue)
timer.start(100)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    if (sys.flags.interactive != 1) or not hasattr(QtCore, 'PYQT_VERSION'):
        QtWidgets.QApplication.instance().exec_()
        # If we get here, we've closed the window. Close all threads.
        for _obj in listener_objects:
            _obj.close()





    







#!/usr/bin/env python2.7
#
#   Project Horus - FlDigi -> OziMux Bridge
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#
#   Receive sentences from FlDigi, and pass them onto OziMux or OziPlotter.
#   Sentences must be of the form $$CALLSIGN,count,HH:MM:SS,lat,lon,alt,other,fields*CRC16
#
#   Note: You can change the port fldigi listens on by using the command line option:
#   --arq-server-port PORT
#   i.e. ./dl-fldigi --hab --arq-server-port 7323
#
#   and then run this application with:
#   python FldigiBridge.py --fldigi_port=7323
#
#   TODO:
#   [ ] Better handling of connection timeouts.
#   [ ] Display incoming data 'live'?
#

import socket
import time
import sys
import argparse
import Queue
import crcmod
from datetime import datetime
import traceback
from threading import Thread
from horuslib import *
from horuslib.oziplotter import *
from horuslib.habitat import *
from PyQt5 import QtGui, QtWidgets, QtCore

FLDIGI_PORT = 7322
FLDIGI_HOST = '127.0.0.1'
OUTPUT_PORT = 55683
OUTPUT_HOST = '127.0.0.1'

class FldigiBridge(object):
    """
    Attept to read UKHAS standard telemetry sentences from a local FlDigi instance, 
    and forward them on to either OziPlotter, or OziMux.
    """

    # Receive thread variables and buffers.
    rx_thread_running = True
    MAX_BUFFER_LEN = 256
    input_buffer = ""


    def __init__(self,
                output_host = '127.0.0.1',
                output_port = 55683,
                fldigi_host = FLDIGI_HOST,
                fldigi_port = FLDIGI_PORT,
                log_file = "None",
                callback = None,
                habitat_call = 'N0CALL',
                enable_habitat = False
                ):

        self.output_hostname = output_host
        self.output_port = output_port
        self.fldigi_host = (fldigi_host, fldigi_port)
        self.callback = callback # Callback should accept a string, which is a valid sentence.
        self.habitat_call = habitat_call
        self.enable_habitat = enable_habitat

        if log_file != "None":
            self.log_file = open(log_file,'a')
        else:
            self.log_file = None

        # Start receive thread.
        self.rx_thread_running = True
        self.t = Thread(target=self.rx_thread)
        self.t.start()


    def close(self):
        self.rx_thread_running = False

        if self.log_file is not None:
            self.log_file.close()


    def rx_thread(self):
        """
        Attempt to connect to fldigi and receive bytes.
        """
        while self.rx_thread_running:
            # Try and connect to fldigi. Keep looping until we have connected.
            try:
                _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                _s.settimeout(1)
                _s.connect(self.fldigi_host)
            except socket.error as e:
                print("ERROR: Could not connect to fldigi - %s" % str(e))
                if self.callback != None:
                    self.callback("ERROR: Could not connect to fldigi. Retrying...")
                time.sleep(10)
                continue

            # OK, now we're connected. Start reading in characters.
            if self.callback != None:
                    self.callback("CONNECTED - WAITING FOR DATA.")

            while self.rx_thread_running:
                try:
                    _char = _s.recv(1)
                except socket.timeout:
                    # No data received? Keep trying...
                    continue
                except:
                    # Something else gone wrong? Try and kill the socket and re-connect.
                    if self.callback != None:
                        self.callback("CONNECTION ERROR!")

                    try:
                        _s.close()
                    except:
                        pass
                    break

                # Append to input buffer.
                self.input_buffer += _char
                # Roll buffer if we've exceeded the max length.
                if len(self.input_buffer) > self.MAX_BUFFER_LEN:
                    self.input_buffer = self.input_buffer[1:]

                # If we have received a newline, attempt to process the current buffer of data.
                if _char == '\n':
                    self.process_data(self.input_buffer)
                    # Clear the buffer and continue.
                    self.input_buffer = ""
                else:
                    continue

        _s.close()


    def crc16_ccitt(self,data):
        """
        Calculate the CRC16 CCITT checksum of *data*.
        
        (CRC16 CCITT: start 0xFFFF, poly 0x1021)
        """
        crc16 = crcmod.predefined.mkCrcFun('crc-ccitt-false')
        return hex(crc16(data))[2:].upper().zfill(4)


    def send_to_callback(self, data):
            ''' If we have been given a callback, send data to it. '''
            if self.callback !=  None:
                try:
                    self.callback(data)
                except:
                    pass


    def process_data(self, data):
        """
        Attempt to process a line of data, and extract time, lat, lon and alt
        """
        try:
            # If we have a log file open, write the data out to disk.
            if self.log_file is not None:
                # Append trailing LF, since we don't get passed that.
                self.log_file.write(data)
                # Immediately flush the file to disk.
                self.log_file.flush()

            # Try and proceed through the following. If anything fails, we have a corrupt sentence.
            # Strip out any leading/trailing whitespace.
            data = data.strip()

            # First, try and find the start of the sentence, which always starts with '$$''
            _sentence = data.split('$$')[-1]
            # Hack to handle odd numbers of $$'s at the start of a sentence
            if _sentence[0] == '$':
                _sentence = _sentence[1:]
            # Now try and split out the telemetry from the CRC16.
            _telem = _sentence.split('*')[0]
            _crc = _sentence.split('*')[1]

            # Now check if the CRC matches.
            _calc_crc = self.crc16_ccitt(_telem)

            if _calc_crc != _crc:
                self.send_to_callback("ERROR - CRC Fail.")
                return

            # We now have a valid sentence! Extract fields..
            _fields = _telem.split(',')

            _telem_dict = {}
            _telem_dict['time'] = _fields[2]
            _telem_dict['latitude'] = float(_fields[3])
            _telem_dict['longitude'] = float(_fields[4])
            _telem_dict['altitude'] = int(_fields[5])
            # The rest we don't care about.


            # Perform some sanity checks on the data.

            # Attempt to parse the time string. This will throw an error if any values are invalid.
            try:
                _time_dt = datetime.strptime(_telem_dict['time'], "%H:%M:%S")
            except:
                self.send_to_callback("ERROR - Invalid Time.")

            # Check if the lat/long is 0.0,0.0 - no point passing this along.
            if _telem_dict['latitude'] == 0.0 or _telem_dict['longitude'] == 0.0:
                self.send_to_callback("ERROR - Zero Lat/Long.")
                return

            # Place a limit on the altitude field. We generally store altitude on the payload as a uint16, so it shouldn't fall outside these values.
            if _telem_dict['altitude'] > 65535 or _telem_dict['altitude'] < 0:
                self.send_to_callback("ERROR - Invalid Altitude.")
                return

            # We now have valid data!

            # If we have been given a callback, send the valid string to it.
            if self.callback !=  None:
                try:
                    self.callback("VALID: " + _sentence)
                except:
                    pass

            # Send the telemetry information onto OziMux/OziPlotter.
            oziplotter_upload_basic_telemetry(_telem_dict, hostname=self.output_hostname, udp_port = self.output_port)

            if self.enable_habitat:
                (success, message) = habitat_upload_sentence("$$"+_sentence+'\n', callsign=self.habitat_call)
                if not success:
                    print("Failed to upload to Habitat: %s" % message)

        except:
            return


rxqueue = Queue.Queue(32)
data_age = 0.0


# PyQt Window Setup
app = QtWidgets.QApplication([])

#
# Create and Lay-out window
#
main_widget = QtWidgets.QWidget()
layout = QtWidgets.QGridLayout()
main_widget.setLayout(layout)
# Create Widgets


fldigiData = QtWidgets.QLabel("Not Connected.")
fldigiData.setFont(QtGui.QFont("Courier New", 14, QtGui.QFont.Bold))
fldigiAge = QtWidgets.QLabel("No Data Yet...")

# Final layout of frames
layout.addWidget(fldigiData)
layout.addWidget(fldigiAge)

mainwin = QtWidgets.QMainWindow()

# Finalise and show the window
mainwin.setWindowTitle("FlDigi Bridge")
mainwin.setCentralWidget(main_widget)
mainwin.resize(500,50)
mainwin.show()


def data_callback(data):
    global rxqueue
    rxqueue.put(data)


def read_queue():
    global fldigiData, fldigiAge, rxqueue, data_age
    try:
        packet = rxqueue.get_nowait()
        fldigiData.setText(packet)
        data_age = 0.0

    except:
        pass

    # Update 'data age' text.
    data_age += 0.1
    fldigiAge.setText("Packet Data Age: %0.1fs" % data_age)


# Start a timer to attempt to read a UDP packet every 100ms
timer = QtCore.QTimer()
timer.timeout.connect(read_queue)
timer.start(100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fldigi_host", type=str, default=FLDIGI_HOST, help="dl-fldigi TCP interface hostname. (default=127.0.0.1)")
    parser.add_argument("--fldigi_port", type=int, default=FLDIGI_PORT, help="dl-fldigi TCP interface port. (default=7322)")
    parser.add_argument("--output_host", type=str, default=OUTPUT_HOST, help="OziMux destination hostname. (default=127.0.0.1)")
    parser.add_argument("--output_port", type=int, default=OUTPUT_PORT, help="OziMux destination UDP port. (default=55683)")
    parser.add_argument("--enable_habitat", action='store_true', help="Enable uploading of telemetry sentences to Habitat")
    parser.add_argument("--habitat_call", type=str, default="N0CALL", help="Callsign to use when uploading to Habitat.")
    parser.add_argument("--log", type=str, default="None", help="Optional log file. All new telemetry data is appened to this file.")
    args = parser.parse_args()


    _fldigi = FldigiBridge(callback=data_callback,
                        fldigi_host=args.fldigi_host,
                        fldigi_port=args.fldigi_port,
                        output_host=args.output_host,
                        output_port=args.output_port,
                        log_file=args.log,
                        habitat_call=args.habitat_call,
                        enable_habitat=args.enable_habitat)

    if (sys.flags.interactive != 1) or not hasattr(QtCore, 'PYQT_VERSION'):
        QtWidgets.QApplication.instance().exec_()
        _fldigi.close()

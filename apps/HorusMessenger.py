#!/usr/bin/env python2.7
#
#   Project Horus - LoRa Text Messenger
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#

from horuslib import *
from horuslib.packets import *
from threading import Thread
from PyQt5 import QtGui, QtWidgets, QtCore
from datetime import datetime
import socket,json,sys,Queue,traceback
import ConfigParser

udp_broadcast_port = HORUS_UDP_PORT
udp_listener_running = False

current_payload = 0

# RX Message queue to avoid threading issues.
rxqueue = Queue.Queue(16)
txed_packets = []

# PyQt Window Setup
app = QtWidgets.QApplication([])

# Widgets
statusLabel = QtWidgets.QLabel("No updates yet..")
console = QtWidgets.QPlainTextEdit()
console.setReadOnly(True)
callsignBox = QtWidgets.QLineEdit("N0CALL")
callsignBox.setFixedWidth(100)
callsignBox.setMaxLength(8)
messageBox = QtWidgets.QLineEdit("")
messageBox.setMaxLength(55)

# Create and Lay-out window
win = QtWidgets.QWidget()
win.resize(600,200)
win.show()
win.setWindowTitle("Horus Messenger")
layout = QtWidgets.QGridLayout()
win.setLayout(layout)

# PAYLOAD SELECTION WIDGET (from HorusGroundStation)
payloadSelectionFrame = QtWidgets.QFrame()
payloadSelectionFrame.setFixedSize(150,220)
payloadSelectionFrame.setFrameStyle(QtWidgets.QFrame.Box)
payloadSelectionFrame.setLineWidth(2)
payloadSelectionTitle = QtWidgets.QLabel("<b><u>Payload ID</u></b>")
payloadSelectionLabel = QtWidgets.QLabel("<b>Current:</b>")
payloadSelectionValue = QtWidgets.QLabel("%d" % current_payload)
payloadSelectionListLabel = QtWidgets.QLabel("<b>Heard Payloads:</b>")
payloadSelectionList = QtWidgets.QListWidget()

payloadSelectionLayout = QtWidgets.QGridLayout()
payloadSelectionLayout.addWidget(payloadSelectionTitle,0,0,1,2)
payloadSelectionLayout.addWidget(payloadSelectionLabel,1,0,1,1)
payloadSelectionLayout.addWidget(payloadSelectionValue,1,1,1,1)
payloadSelectionLayout.addWidget(payloadSelectionListLabel,2,0,1,2)
payloadSelectionLayout.addWidget(payloadSelectionList,3,0,2,2)
payloadSelectionFrame.setLayout(payloadSelectionLayout)

def newSelectedPayload(curr, prev):
    global current_payload
    current_payload = int(curr.text())
    payloadSelectionValue.setText("%d" % current_payload)
    console.appendPlainText("PAYLOAD SELECTION SET TO #%d" % current_payload)

payloadSelectionList.currentItemChanged.connect(newSelectedPayload)

# Add Widgets
layout.addWidget(payloadSelectionFrame,0,0,4,1)
layout.addWidget(statusLabel,0,1,1,4)
layout.addWidget(console,1,1,1,4)
layout.addWidget(callsignBox,2,1,1,1)
layout.addWidget(messageBox,2,2,1,3)

# Now attempt to read in a config file to preset various parameters.
try:
    config = ConfigParser.ConfigParser()
    config.read('defaults.cfg')
    callsign = config.get('User','callsign')
    callsignBox.setText(callsign)
except:
    print("Problems reading configuration file, skipping...")


# Send a message!
def send_message():
    global current_payload
    callsign = str(callsignBox.text())
    message = str(messageBox.text())
    message_packet = create_text_message_packet(callsign,message, destination=current_payload)
    tx_packet(message_packet,destination=current_payload)
    messageBox.setText("")

messageBox.returnPressed.connect(send_message)
callsignBox.returnPressed.connect(send_message)

def getHeardPayloadList():
    global payloadSelectionList
    if payloadSelectionList.__len__() == 0:
        return []
    else:
        payloads = []
        for x in range(payloadSelectionList.__len__()):
            # Note that we have to store items in the list as strings, so convert back to int.
            payloads.append(int(payloadSelectionList.item(x).text()))
        return payloads


def process_rxpkt(packet_dict):
    global current_payload

    # Now delve into the payload.
    payload = packet_dict['payload']

    payload_id = decode_payload_id(payload)

    # If we haven't heard any payloads yet, add this new payload to the list and set it as the current payload.
    if len(getHeardPayloadList()) == 0:
        payloadSelectionList.addItem(str(payload_id))
        payloadSelectionList.setCurrentRow(0)
        current_payload = payload_id

    if payload_id not in getHeardPayloadList():
        payloadSelectionList.addItem(str(payload_id))


    if(packet_dict['payload'][0] == HORUS_PACKET_TYPES.TEXT_MESSAGE):
        line = datetime.utcnow().strftime("%H:%M ")
        rssi = float(packet_dict['rssi'])
        snr = float(packet_dict['snr'])
        print(packet_dict['payload'])
        (source,message) = read_text_message_packet(packet_dict['payload'])

        payload_flags = decode_payload_flags(packet_dict['payload'])
        if payload_flags['is_repeated']:
            line += "<%8s via #%d>" % (source,payload_id)
        else:
            line += "<%8s>" % (source)

        line += " [R:%.1f S:%.1f] %s" % (rssi,snr,message)
        console.appendPlainText(line)

# Method to process UDP packets.
def process_udp(udp_packet):
    try:
        packet_dict = json.loads(udp_packet)

        # Start every line with a timestamp
        line = datetime.utcnow().strftime("%H:%M ")
        print packet_dict['type']
        # TX Confirmation Packet?
        if packet_dict['type'] == 'TXDONE':
            if(packet_dict['payload'][0] == HORUS_PACKET_TYPES.TEXT_MESSAGE):
                (source,message) = read_text_message_packet(packet_dict['payload'])
                line += "<%8s> %s" % (source,message)
                console.appendPlainText(line)
                messageBox.setText("")
        elif packet_dict['type'] == "TXQUEUED":
            messageBox.setText("Message in TX Queue, Please Wait...")
        elif packet_dict['type'] == 'RXPKT':
            process_rxpkt(packet_dict)
        elif packet_dict['type'] == 'STATUS':
            rssi = float(packet_dict['rssi'])
            timestamp = packet_dict['timestamp']
            status_text = "%s RSSI: %.1f dBm" % (timestamp,rssi)
            statusLabel.setText(status_text)
        else:
            print("Got other packet type (%s)" % packet_dict['type'])
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

t = Thread(target=udp_rx_thread)
t.start()

def read_queue():
    try:
        packet = rxqueue.get_nowait()
        process_udp(packet)
    except:
        pass

# Start a timer to attempt to read the remote station status every 5 seconds.
timer = QtCore.QTimer()
timer.timeout.connect(read_queue)
timer.start(100)

## Start Qt event loop unless running in interactive mode or using pyside.
if __name__ == '__main__':
    if (sys.flags.interactive != 1) or not hasattr(QtCore, 'PYQT_VERSION'):
        QtWidgets.QApplication.instance().exec_()
        udp_listener_running = False

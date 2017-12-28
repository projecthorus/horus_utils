#!/usr/bin/env python2.7
#
#   Project Horus 
#   Payload Telemetry Habitat Uploader
#   Copyright 2015 Mark Jessop <vk5qi@rfhead.net>
#
#   This is mainly intended for headless receive stations. It will upload received telemetry to Habitat,
#   using the binary packet to ASCII-sentence translation from here:
#   https://github.com/projecthorus/HorusGroundStation/blob/master/HorusPackets.py#L256
#   The payload callsign (by default HORUSLORA + Payload ID) can be set in defaults.cfg
#
#   Usage: python TelemetryUpload.py YOURCALL
#
#   Options:
#       --summary       Enable emission of a 'payload summary' UDP broadcast packet into the local network.
#                       This is used to provide payload location information to  RotatorGUI and SummaryGUI.
#
#       -l log_file.txt Write a log file of received telemetry to the supplied filename.
#

from horuslib import *
from horuslib.packets import *
from horuslib.habitat import *
from threading import Thread
from datetime import datetime
import socket,json,sys,argparse,ConfigParser

udp_broadcast_port = HORUS_UDP_PORT
udp_listener_running = False

parser = argparse.ArgumentParser()
parser.add_argument("callsign", help="Listener Callsign")
parser.add_argument("-l","--log_file",default="telemetry.log",help="Log file for RX Telemetry")
parser.add_argument("--summary",default=False,action='store_true',help="Emit Payload Summary message via UDP broadcast on valid packet.")
args = parser.parse_args()

# Read in payload callsign from config file.
try:
    config = ConfigParser.ConfigParser()
    config.read('defaults.cfg')
    payload_callsign = config.get('Payload','payload_callsign')
except:
    print("Problems reading configuration file, skipping...")
    payload_callsign = "HORUSLORA"


def write_log_entry(packet):
    timestamp = datetime.utcnow().isoformat()
    rssi = str(packet['rssi'])
    snr = str(packet['snr'])
    if packet['pkt_flags']['crc_error'] != 0:
        sentence = "CRC FAIL\n"
    else:
        if decode_payload_type(packet['payload']) == HORUS_PACKET_TYPES.PAYLOAD_TELEMETRY:
            telemetry = decode_horus_payload_telemetry(packet['payload'])
            sentence = telemetry_to_sentence(telemetry, payload_callsign=payload_callsign, payload_id = telemetry['payload_id'])
        else:
            sentence = "NOT TELEMETRY\n"

    log = open(args.log_file,'a')
    log_string = "%s,%s,%s,%s" % (timestamp,rssi,snr,sentence)
    print(log_string)
    log.write(log_string)
    log.close()

def emit_payload_summary(telemetry):
    """ Do some sanity checking on the telemetry, and then emit a a payload summary packet via UDP. """
    # send_payload_summary(callsign, latitude, longitude, altitude, speed=-1, heading=-1)
    _callsign = payload_callsign
    _latitude = telemetry['latitude']
    _longitude = telemetry['longitude']
    _altitude = telemetry['altitude']

    if (_latitude != 0.0) and (_longitude != 0.0):
        send_payload_summary(_callsign, _latitude, _longitude, _altitude)

def process_udp(udp_packet):
    try:
        packet = json.loads(udp_packet)
        # Only process received telemetry packets.
        if packet['type'] != "RXPKT":
            return

        write_log_entry(packet)

        # Only upload packets that pass CRC (though we log if CRC failed)
        if packet['pkt_flags']['crc_error'] != 0:
            return

        payload = packet['payload']
        payload_type = decode_payload_type(payload)

        # Only process payload telemetry packets.
        if payload_type == HORUS_PACKET_TYPES.PAYLOAD_TELEMETRY:
            telemetry = decode_horus_payload_telemetry(payload)
            sentence = telemetry_to_sentence(telemetry, payload_callsign=payload_callsign, payload_id=telemetry['payload_id'])
            if args.summary is True:
                emit_payload_summary(telemetry)
            (success,error) = habitat_upload_payload_telemetry(telemetry, payload_callsign=payload_callsign, callsign=args.callsign)
            if success:
                print("Uploaded Successfuly!")
            else:
                print("Upload Failed: %s" % error)
        else:
            return
    except Exception as e:
        print("Invalid packet, or decode failed: %s" % e)

def udp_rx_thread():
    global udp_listener_running
    s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    s.settimeout(1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('',HORUS_UDP_PORT))
    print("Started UDP Listener Thread.")
    udp_listener_running = True
    while udp_listener_running:
        try:
            m = s.recvfrom(MAX_JSON_LEN)
        except socket.timeout:
            m = None
        
        if m != None:
                process_udp(m[0])
    
    print("Closing UDP Listener")
    s.close()

try:
    udp_rx_thread()
except KeyboardInterrupt:
    print("Closing.")
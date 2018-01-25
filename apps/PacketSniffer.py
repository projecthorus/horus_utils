#!/usr/bin/env python2.7
#
#   Project Horus 
#   Basic Telemetry RX
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#
#   A quick hack to test the binary telemetry decoder.

from horuslib import *
from horuslib.packets import *
import socket,json,sys,Queue

udp_listener_running = False

def process_udp(udp_packet, address="0.0.0.0"):
    try:
        packet_dict = json.loads(udp_packet)
        
        print(udp_packet_to_string(packet_dict))
        sys.stdout.flush()
    except:
        pass

def udp_rx_thread():
    global udp_listener_running
    s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    s.settimeout(0.2)
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
            (m,addr) = s.recvfrom(MAX_JSON_LEN)
            print(addr)
        except socket.timeout:
            m = None
        
        if m != None:
                process_udp(m)
    
    print("Closing UDP Listener")
    s.close()

try:
    udp_rx_thread()
except KeyboardInterrupt:
    print("Closing.")
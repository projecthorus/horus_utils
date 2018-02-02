#!/usr/bin/env python2.7
#
#   Project Horus - UDP Packet Listener
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#

import socket, json, sys, traceback
from threading import Thread
from . import *
from .packets import *


class UDPListener(object):
    ''' UDP Broadcast Packet Listener 
    Listens for Horus Lib UDP broadcast packets, and passes them onto a callback function
    '''

    def __init__(self,
        callback=None,
        summary_callback = None,
        gps_callback = None,
        port=HORUS_UDP_PORT):

        self.udp_port = port
        self.callback = callback
        self.summary_callback = summary_callback
        self.gps_callback = gps_callback

        self.listener_thread = None
        self.s = None
        self.udp_listener_running = False


    def handle_udp_packet(self, packet):
        ''' Process a received UDP packet '''
        try:
            packet_dict = json.loads(packet)

            if self.callback is not None:
                self.callback(packet_dict)

            if packet_dict['type'] == 'PAYLOAD_SUMMARY':
                if self.summary_callback is not None:
                    self.summary_callback(packet_dict)

            if packet_dict['type'] == 'GPS':
                if self.gps_callback is not None:
                    self.gps_callback(packet_dict)

        except Exception as e:
            print("Could not parse packet: %s" % str(e))
            traceback.print_exc()


    def udp_rx_thread(self):
        ''' Listen for Broadcast UDP packets '''

        self.s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        self.s.settimeout(1)
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except:
            pass
        self.s.bind(('',self.udp_port))
        print("Started UDP Listener Thread.")
        self.udp_listener_running = True

        while self.udp_listener_running:
            try:
                m = self.s.recvfrom(MAX_JSON_LEN)
            except socket.timeout:
                m = None
            
            if m != None:
                self.handle_udp_packet(m[0])
        
        print("Closing UDP Listener")
        self.s.close()


    def start(self):
        if self.listener_thread is None:
            self.listener_thread = Thread(target=self.udp_rx_thread)
            self.listener_thread.start()


    def close(self):
        self.udp_listener_running = False
        self.listener_thread.join()

if __name__ == '__main__':
    # Example script, essentially repeats functionality of PacketSniffer.py
    import time, sys

    def process_packet(packet):
        print(udp_packet_to_string(packet))

    if len(sys.argv) > 1:
        udp_port = int(sys.argv[1])
    else:
        udp_port = HORUS_UDP_PORT

    udp_rx = UDPListener(callback=process_packet, port=udp_port)
    udp_rx.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        udp_rx.close()
        print("Closing.")




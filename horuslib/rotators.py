#!/usr/bin/env python2.7
#
#   Project Horus - Rotator Abstraction Layers
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#
import socket
import time
import logging
import traceback
from threading import Thread

class ROTCTLD(object):
    """ rotctld (hamlib) communication class """
    # Note: This is a massive hack. 

    def __init__(self, hostname, port=4533, poll_rate=5, timeout=5, az_180 = False):
        """ Open a connection to rotctld, and test it for validity """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)

        self.hostname = hostname
        self.port = port


    def connect(self):
        """ Connect to rotctld instance """
        self.sock.connect((self.hostname,self.port))
        model = self.get_model()
        if model == None:
            # Timeout!
            self.close()
            raise Exception("Timeout!")
        else:
            return model

    def close(self):
        self.sock.close()

    def send_command(self, command):
        """ Send a command to the connected rotctld instance,
            and return the return value.
        """
        self.sock.sendall(command+'\n')
        try:
            return self.sock.recv(1024)
        except:
            return None

    def get_model(self):
        """ Get the rotator model from rotctld """
        model = self.send_command('_')
        return model

    def set_azel(self,azimuth,elevation):
        """ Command rotator to a particular azimuth/elevation """
        # Sanity check inputs.
        if elevation > 90.0:
            elevation = 90.0
        elif elevation < 0.0:
            elevation = 0.0

        if azimuth > 360.0:
            azimuth = azimuth % 360.0


        command = "P %3.1f %2.1f" % (azimuth,elevation)
        response = self.send_command(command)
        if "RPRT 0" in response:
            return True
        else:
            return False

    def get_azel(self):
        """ Poll rotctld for azimuth and elevation """
        # Send poll command and read in response.
        response = self.send_command('p')

        # Attempt to split response by \n (az and el are on separate lines)
        try:
            response_split = response.split('\n')
            _current_azimuth = float(response_split[0])
            _current_elevation = float(response_split[1])
            return (_current_azimuth, _current_elevation)
        except:
            logging.error("Could not parse position: %s" % response)
            return (None,None)



class PSTRotator(object):
    """ PSTRotator communication class """

    # Local store of current azimuth/elevation
    current_azimuth = None
    current_elevation = None

    azel_thread_running = False
    last_poll_time = 0

    def __init__(self, hostname='localhost', port=12000, poll_rate=1):
        """ Start a PSTRotator connection instance """
        self.hostname = hostname
        self.port = port
        self.poll_rate = poll_rate
        self.azel_thread_running = True

        self.t_rx = Thread(target=self.azel_rx_loop)
        self.t_rx.start()

        self.t_poll = Thread(target=self.azel_poll_loop)
        self.t_poll.start()


    def close(self):
        self.azel_thread_running = False

    def set_azel(self,azimuth,elevation):
        """ Send an Azimuth/Elevation move command to PSTRotator """

        # Sanity check inputs.
        if elevation > 90.0:
            elevation = 90.0
        elif elevation < 0.0:
            elevation = 0.0

        if azimuth > 360.0:
            azimuth = azimuth % 360.0

        # Generate command
        pst_command = "<PST><TRACK>0</TRACK><AZIMUTH>%.1f</AZIMUTH><ELEVATION>%.1f</ELEVATION></PST>" % (azimuth,elevation)
        logging.debug("Sent command: %s" % pst_command)
        # Send!
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.sendto(pst_command, (self.hostname,self.port))
        udp_socket.close()

        return True

    def poll_azel(self):
        """ Poll PSTRotator for an Azimuth/Elevation Update """
        az_poll_command = "<PST>AZ?</PST>"
        el_poll_command = "<PST>EL?</PST>"
        try:
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket.sendto(az_poll_command, (self.hostname,self.port))
            time.sleep(0.2)
            udp_socket.sendto(el_poll_command, (self.hostname,self.port))
            udp_socket.close()
        except:
            pass

    def azel_poll_loop(self):
        while self.azel_thread_running:
            self.poll_azel()
            logging.debug("Poll sent to PSTRotator.")
            time.sleep(self.poll_rate)

    def azel_rx_loop(self):
        """ Listen for Azimuth and Elevation reports from PSTRotator"""
        s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        s.settimeout(1)
        s.bind(('',(self.port+1)))
        logging.debug("Started PST Rotator Listener Thread.")
        while self.azel_thread_running:
            try:
                m = s.recvfrom(512)
            except socket.timeout:
                m = None
            
            if m != None:
                # Attempt to parse Azimuth / Elevation
                logging.debug("Received: %s" % m[0])

                data = m[0]
                if data[:2] == 'EL':
                    self.current_elevation = float(data[3:])
                elif data[:2] == 'AZ':
                    self.current_azimuth = float(data[3:])

        
        logging.debug("Closing UDP Listener")
        s.close()


    def get_azel(self):
        return (self.current_azimuth, self.current_elevation)

if __name__ == "__main__":
    logging.basicConfig(format='%(asctime)s %(levelname)s:%(message)s', level=logging.DEBUG)

    rot = PSTRotator()
    time.sleep(10)
    rot.set_azel(45.0,45.0)
    time.sleep(10)
    rot.close()
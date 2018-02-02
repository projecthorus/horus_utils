#!/usr/bin/env python2.7
#
#   Project Horus - Pre-Flight Check GUI
#   Display information about all payloads seen by OziMux on a 2.8" Adafruit PiTFT
#   Note: This is a massive hack.
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#
#   NOTE:
#   This requires the pygame-text helper module 'ptext.py', which you can get by running
#   wget https://raw.githubusercontent.com/cosmologicon/pygame-text/master/ptext.py
#
#   It also obviously requires a Adafruit 2.8" PiTFT display, with all the associated setup.
#   Because getting it running under the Rasbian Stretch is currently a nightmare (yay requirement for ancient SDL),
#   I'm just using the Adafruit supplied image...
#

import os
import time
import RPi.GPIO as GPIO
import pygame
from pygame.locals import *
from horuslib import *
from horuslib.wenet import *
from horuslib.listener import *
from horuslib.earthmaths import *
from subprocess import check_output

import ptext
 
WATCHDOG_HOSTNAME = "127.0.0.1" # Update this with a IP Address that should always be pingable.
WATCHDOG_STATUS = "FAIL"
WIFI_STATUS = "Not Connected."

X_MAX = 320
Y_MAX = 240

ptext.DEFAULT_BACKGROUND = (0,0,0)
# Define font sizes
font_big = pygame.font.Font(None, 50)
font_med = pygame.font.Font(None, 30)
font_small = pygame.font.Font(None, 15)

# Data Stores.
LAST_PACKETS = ["No Data.", "No Data.", "No Data.", "No Data."] # The last few packets we have seen on the network, converted to strings.
MAX_PACKETS = 4
LAST_PACKETS_DISCARD = ['LOWPRIORITY', 'WENET', 'OZIMUX']

LAST_DATA_TIMES = [time.time(), time.time(), time.time(), time.time()] # LoRa, RTTY, Wenet, ??
LAST_DATA_AGE = [0,0,0,0]

# LoRa Status Data
LORA_DATA = [000.000, -255, -255, -255] # Frequency, Noise Level, Packet RSSI, Packet SNR

# OziMux Data
OZIMUX_DATA = {}

# Wenet Data
LAST_WENET_TEXT = "Debug: No Data Yet"
LAST_WENET_GPS = "GPS: No Data Yet."

# Environment variables so we write to the right display.
os.putenv('SDL_FBDEV', '/dev/fb1')
os.putenv('SDL_MOUSEDRV', 'TSLIB')
os.putenv('SDL_MOUSEDEV', '/dev/input/touchscreen')

# Startup Display, and fill with black.
pygame.init()
pygame.mouse.set_visible(False)
lcd = pygame.display.set_mode((320, 240))
lcd.fill((0,0,0))
pygame.display.update()


def update_screen():
    ''' Re-draw all information onto the display '''
    lcd.fill((0,0,0))

    # OziMux Data
    ptext.draw("Telemetry via OziMux", (X_MAX/2,0), fontsize=20, bold=True, underline=True, surf=lcd)

    _ozimux_str = ""
    if len(OZIMUX_DATA.keys()) == 0:
        _ozimux_str = "No Data."
    else:
        for _key in OZIMUX_DATA.keys():
            _data_str = "%s \tAge: %.1f\n%.4f, %.4f, %d\n" % (_key, 
                                                            (time.time() - OZIMUX_DATA[_key]['packet_time']),
                                                            OZIMUX_DATA[_key]['latitude'], 
                                                            OZIMUX_DATA[_key]['longitude'],
                                                            OZIMUX_DATA[_key]['altitude'])
                                                            
            _ozimux_str += _data_str

    ptext.draw(_ozimux_str, (X_MAX/2,20), fontsize=16, surf=lcd)

    # Last seen Packets.
    last_packets_str = "\n".join(LAST_PACKETS)
    ptext.draw(last_packets_str, (0,Y_MAX-20*3), fontsize=16, surf=lcd)

    # Network Watchdog.
    ptext.draw("Network: %s" % WATCHDOG_STATUS, (0,Y_MAX-20*4), fontsize=24, surf=lcd)
    ptext.draw("SSID: %s" % WIFI_STATUS, (X_MAX/2, Y_MAX-20*4), fontsize=16, surf=lcd)

    # LoRa RX Section (Top Left)
    ptext.draw("LoRa RXer", (0,0), fontsize=20, bold=True, underline=True, surf=lcd)
    ptext.draw("Age: %.1fs" % (LAST_DATA_AGE[0]), (70,0), fontsize=16, surf=lcd)
    _lora_status_str = "%0.3f Noise: %d dBm\nRSSI: %d dBm SNR: %d dB" % (LORA_DATA[0], LORA_DATA[1], LORA_DATA[2], LORA_DATA[3])
    ptext.draw(_lora_status_str, (0,20), fontsize=16, surf=lcd)

    # Wenet Data:
    ptext.draw("Wenet", (0,90), fontsize=20, bold=True, underline=True, surf=lcd)
    ptext.draw("Age: %.1fs" % (LAST_DATA_AGE[2]), (70,90), fontsize=16, surf=lcd)
    ptext.draw(LAST_WENET_GPS, (0,110), fontsize=16, surf=lcd)
    ptext.draw(LAST_WENET_TEXT, (0,126), fontsize=16, width=320, surf=lcd)


    pygame.display.update()

# Initial update
update_screen()


def handle_wenet_packets(packet):
    ''' Handle Wenet payload specific packets '''
    global LAST_DATA_TIMES, LAST_WENET_GPS, LAST_WENET_TEXT
    packet_type = decode_wenet_packet_type(packet)

    if packet_type == WENET_PACKET_TYPES.TEXT_MESSAGE:
        _text_data = decode_text_message(packet)
        LAST_WENET_TEXT = "Debug %d: " % _text_data['id'] + _text_data['text']
    elif packet_type == WENET_PACKET_TYPES.GPS_TELEMETRY:
        _gps_telem = gps_telemetry_decoder(packet)
        LAST_WENET_GPS = "GPS: %.5f,%.5f,%d SVs:%d Asc: %.1f" % (_gps_telem['latitude'], _gps_telem['longitude'], _gps_telem['altitude'], _gps_telem['numSV'], _gps_telem['ascent_rate'])
    else:
        pass

    LAST_DATA_TIMES[2] = time.time()



def handle_packets(packet):
    ''' Handle received UDP packets '''
    global LAST_PACKETS, LORA_DATA, LAST_DATA_TIMES, LAST_DATA_AGE, OZIMUX_DATA

    # Update packet ages.
    for n in range(len(LAST_DATA_TIMES)):
        LAST_DATA_AGE[n] = time.time() - LAST_DATA_TIMES[n]

    # Convert packet to string, and add it to the list of LAST_PACKETS
    if packet['type'] not in LAST_PACKETS_DISCARD:
        _packet_str = " ".join(udp_packet_to_string(packet).split(" ")[1:])
        LAST_PACKETS = LAST_PACKETS[-1:] + LAST_PACKETS[:-1]
        LAST_PACKETS[0] = _packet_str


    # Handle LoRa Status Messages
    if packet['type'] == 'STATUS':
        LORA_DATA[0] = packet['frequency']
        LORA_DATA[1] = float(packet['rssi'])
        LAST_DATA_TIMES[0] = time.time()
    # LoRa RX Packets
    elif packet['type'] == 'RXPKT':
        LORA_DATA[2] = float(packet['rssi'])
        LORA_DATA[3] = float(packet['snr'])
        LAST_LORA_PACKET = time.time()

    elif packet['type'] == 'WENET':
        handle_wenet_packets(packet['packet'])

    elif packet['type'] == 'OZIMUX':
        # Shorten the data source name.
        if packet['source_name'] == "Horus Ground Station (LoRa)":
            _src_name = "LoRa"
        elif packet['source_name'] == "Fldigi Bridge":
            _src_name = "RTTY"
        elif packet['source_name'] == "Radiosonde Auto RX":
            _src_name = "Sonde"
        else:
            _src_name = packet['source_name']

        # Add data to our store of ozimux data
        OZIMUX_DATA[_src_name] = {}
        OZIMUX_DATA[_src_name]['latitude'] = packet['latitude']
        OZIMUX_DATA[_src_name]['longitude'] = packet['longitude']
        OZIMUX_DATA[_src_name]['altitude'] = packet['altitude']
        OZIMUX_DATA[_src_name]['packet_time'] = time.time()


    else:
        pass

    # And updat the screen with the new data.
    update_screen()


def ping_host(hostname="localhost"):
    ''' Quick function to attempt to ping a hostname. This acts as a watchdog of sorts. '''
    response = os.system("ping -c 1 -w2 " + hostname + " > /dev/null 2>&1")
    if response == 0:
        return "OK"
    else:
        return "FAIL"
 
def get_wifi_ssid():
    ''' Get the Wifi ESSID we are currently connected to. '''
    iwconfigoutput = check_output(["iwconfig"])

    for line in iwconfigoutput.split('\n'):
        if "ESSID:" in line:
            _wifi_ssid = line.split("ESSID:")[1].strip()
            return _wifi_ssid

    return "None."


if __name__ == "__main__":
    horus_udp_rx = UDPListener(callback=handle_packets)
    horus_udp_rx.start() 

    try:
        while True:
            time.sleep(2)
            WATCHDOG_STATUS = ping_host(WATCHDOG_HOSTNAME)
            WIFI_STATUS = get_wifi_ssid()
    except KeyboardInterrupt:
        horus_udp_rx.close()
        print("Closing.")

#!/usr/bin/env python
#
#   UpuTronics LoRa Zero Shield LED Driver
#
#   Mark Jessop 2018-05
#
#   This script is intended to run continuously in the background on a LoRa receiver.
#   It uses the two LEDs on the LoRa-Zero shield to indicate if 
#   a) The Pi has a valid WiFi network connection, and
#   b) The Pi is seeing telemetry traffic (from either a Radiosonde, or a LoRa payload)
#   
#   Link to shield in use: https://store.uputronics.com/index.php?route=product/product&path=61&product_id=99
#
import subprocess
import time
import RPi.GPIO as GPIO
from horuslib.listener import OziListener, UDPListener
from horuslib.packets import *

# What port to listen on for OziMux traffic
OZI_LISTEN_PORT = 55681 # Radiosonde RX port

# LoRa Shield LEDs pins
LINK_LED = 6
DATA_LED = 13

# If no packet received after X seconds, disable LED.
LAST_PACKET_TIMEOUT = 10

# Global variable to indicate when a valid packet was last seen.
last_valid_packet = time.time()


def read_iwconfig():
    """
    Read from iwconfig, and attempt to parse out the link quality value.
    Scale link quality to a single float between 0-1.0 and return.
    """

    data = subprocess.check_output(['iwconfig'])

    for line in data.split('\n'):
        if 'Link Quality' in line:
            lq_data = line.split('=')[1].split('  ')[0]
            lq_level = float(lq_data.split('/')[0])
            lq_max = float(lq_data.split('/')[1])
            return lq_level/lq_max

    return 0.0


def handle_ozimux_packet(data):
    ''' Handle a received OziMux telemetry packet '''
    global last_valid_packet
    # We assume all received packets are valid (it at least indicates we are seeing *something)
    # Set the last valid packet timer to *now*
    last_valid_packet = time.time()
    print("Got OziMux Packet!")


def handle_udp_packet(packet):
    ''' Handle a received UDP Broadcast packet '''
    global last_valid_packet
    # Look for RXPKT messages, which indicate we have seen a LoRa packet
    if packet['type'] == 'RXPKT':
        last_valid_packet = time.time()
        print("Got LoRa Packet!")
    else:
        pass



if __name__ == '__main__':
    # Configure RPi GPIO pins
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(LINK_LED, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(DATA_LED, GPIO.OUT, initial=GPIO.LOW)


    # Instantiate the UDP Broadcast listener.
    udp_rx = UDPListener(
        callback = handle_udp_packet
        )
    # and start it
    udp_rx.start()

    # Instantiate the OziMux listener (this one auto-starts...)
    ozi_rx = OziListener(telemetry_callback=handle_ozimux_packet, port=OZI_LISTEN_PORT)


    # From here, everything happens in the callback functions above.
    try:
        while True:
            time.sleep(5)

            # Check status of last valid packet.
            if (time.time()-last_valid_packet) < LAST_PACKET_TIMEOUT:
                GPIO.output(DATA_LED, 1)
            else:
                GPIO.output(DATA_LED, 0)

            # Check status of network connection.
            if read_iwconfig() > 0.0:
                GPIO.output(LINK_LED, 1)
            else:
                GPIO.output(LINK_LED, 0)

    # Catch CTRL+C nicely.
    except KeyboardInterrupt:
        # Close UDP listener.
        udp_rx.close()
        ozi_rx.close()
        print("Closing.")





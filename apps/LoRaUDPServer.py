#!/usr/bin/env python2.7
#
#   Project Horus
#   LoRa-UDP Gateway Server
#   Copyright 2015 Mark Jessop <vk5qi@rfhead.net>
#
#   - Connects to and configures a LoRa receiver (SX127x family of ICs)
#   - Uses UDP broadcast (port 55672) to send/receive as json-encoded dicts:
#       - Receiver status updates (RSSI, SNR)
#       - Received packets.
#   - Listens for json-encoded packets to be transmitted on the same port.
#       - Any received packets go into a queue to be transmitted when the
#       channel is clear.
#
#   Dependencies
#   ============
#   Requires the modified version of pySX127x which lives here:
#   https://github.com/darksidelemm/pySX127x
#   This currently doesn't have any installer, so the SX127x folder will need to be dropped into
#   the current directory.
#
#   TODO
#   ====
#   [x] Allow selection of hardware backend (RPi, SPI-UART Bridge) from
#       command line arg.
#   [ ] Read LoRa configuration data (frequency, rate, etc) from a
#       configuration file.
#
#
#   JSON PACKET FORMATS
#   ===================
#
#   TRANSMIT PACKET
#   Packet to be transmitted by the LoRa server. Is added to a queue and
#   transmitted when channel is clear.
#   ---------------
#   {
#       'type' : 'TXPKT',
#       'payload' : [<payload as a list of bytes>] # Encode this using list(bytearray('string'))
#       'destination' : payload_id # Optional field. If given, the UDP server will cache the packet in a separate queue, and 
#                                    will wait until it observes a packet from the given payload ID before TXing.
#   }
#
#   TRANSMIT QUEUE STATUS
#   Provides information on the state of the Transmit Queue. Useful for sending lots of packets in a row.
#   Send by LoRaUDPServer immediately after receiving a TXPKT message.
#   ---------------------
#   {
#     'type' : 'TXQUEUED',
#     'timestamp' : '<ISO-8601 formatted timestamp>',
#     'payload' : [<payload as a list of bytes>]
#     'txqueuesize' : Number of packets remaining in the transmit queue.
#   }
#
#   TRANSMIT CONFIRMATION
#   Sent when a packet has been transmitted.
#   ---------------------
#   {
#     'type' : 'TXDONE',
#     'timestamp' : '<ISO-8601 formatted timestamp>',
#     'payload' : [<payload as a list of bytes>]
#     'txqueuesize' : Number of packets remaining in the transmit queue.
#   }
#
#
#   STATUS PACKET
#   Broadcast frequently (5Hz or so) to indicate current modem status, for
#   RSSI plotting or similar.
#   -------------
#   {
#       'type' : 'STATUS',
#       'timestamp : '<ISO-8601 formatted timestamp>',
#       'rssi' : <Current RSSI in dB>,
#       'status': {<Current Modem Status, straight from pySX127x's get_modem_status()},
#       'frequency': <Current RX frequency>,
#       'uplink_callsign': <Callsign used for low priority uplink>
#       'uplink_slot_id': <Current uplink slot ID>
#       'uplink_destination': <Current uplink destination ID>
#   }
#
#   RX DATA PACKET
#   Broacast whenever a LoRa packet is received
#   Packets are sent out even if the CRC failed. CRC info is available in the
#   'pkt_flags' dict.
#   --------------
#   {
#     'type' : 'RXPKT',
#     'timestamp' : '<ISO-8601 formatted timestamp>',
#     'rssi' : <Current RSSI in dB>,
#     'snr'  : <Packet SNR in dB>,
#     'payload' : [<payload as a list of bytes>],
#     'pkt_flags' : {LoRa IRQ register flags at time of packet RX}# pkt_flags["crc_error"] == 0 if CRC is ok.
#   }
#
#   PING
#   Ping this server to check it is running.
#   ---
#   {
#       'type' : 'PING',
#       'data' : '<Arbitrary data>'
#   }
#   This server immediately responds with:
#   {
#       'type' : 'PONG',
#       'data' : '<Copy of whatever was in the PING packet>'
#   }
#
#   RF
#   Allows at-runtime variation of the operating frequency.
#   The new frequency change will be reflected in the next STATUS packet.
#   --
#   {
#       'type' : 'RF',
#       'frequency' : <New operating frequency, in MHz.>
#   }
#
#
#   LOWPRIORITY
#   Update various parameters used in the low priority uplink system
#   Note that all fields are optional, and can be updated independently
#   ------------
#   {
#       'callsign'  :   '<Callsign used for uplink slot requests. Max 9 chars.',
#       'destination': <Payload ID we uplink to>,
#       'payload':  [<Packet to transmit during the low priority uplink timeslot, as a list of bytes>],
#       'reset': 'Dummy data - send this field to reset the uplink slot to -1, triggering a request for a new uplink timeslot'
#
#

import json,socket,Queue,random, argparse, sys, traceback, time, random
from threading import Thread
from horuslib import *
from horuslib.packets import *
from datetime import datetime

from SX127x.LoRa import *


class LoRaTxRxCont(LoRa):
    def __init__(self,hw,verbose=False,max_payload=255,mode=0,frequency=431.650, callsign='blank', low_priority_destination=-1):
        super(LoRaTxRxCont, self).__init__(hw,verbose)
        self.set_mode(MODE.SLEEP)
        self.set_dio_mapping([0] * 6)

        self.rf_mode = mode
        self.frequency = frequency
        self.max_payload = max_payload
        self.udp_broadcast_port = HORUS_UDP_PORT

        self.udprxqueue = Queue.Queue(128) # Queue for incoming UDP packets to be processed.
        self.txqueue = Queue.Queue(TX_QUEUE_SIZE)
        self.udp_listener_running = False

        self.status_counter = 0
        self.status_throttle = 20

        # TX-after-RX Queue. I with python queues had a peek method... 
        # Data stored into this queue is of the form (payload,destination_id)
        self.tx_after_rx = Queue.Queue(1)
        self.default_tx_timeout = 15

        # Settings change queue, as we need to do these changes in the main processing loop, not the UDP processing thread.
        # These will just be (key,value) tuples to change some basic LoRa settings via UDP commands.
        self.settings_changes = Queue.Queue(10)

        # Low Priority Packet related variables
        # This data is sent whenever the relevant payload indicates that is is 'our' time to transmit.
        self.my_uplink_timeslot = -1
        self.slot_request_holdoff = 0
        self.my_callsign = callsign
        self.low_priority_destination = low_priority_destination
        self.low_priority_packet = []


    def set_common(self):
        self.set_mode(MODE.STDBY)
        self.set_freq(self.frequency)
        self.set_rx_crc(True)
        if self.rf_mode==0:
            self.set_bw(BW.BW125)
            self.set_coding_rate(CODING_RATE.CR4_8)
            self.set_spreading_factor(10)
            self.set_low_data_rate_optim(True)
            self.tx_delay_fudge = 0.5
        elif self.rf_mode==1:
            self.set_bw(BW.BW125)
            self.set_coding_rate(CODING_RATE.CR4_8)
            self.set_spreading_factor(8)
            self.set_low_data_rate_optim(True)
            self.tx_delay_fudge = 1.2
        elif self.rf_mode==2:
            self.set_bw(BW.BW250)
            self.set_coding_rate(CODING_RATE.CR4_8)
            self.set_spreading_factor(7)
            self.set_low_data_rate_optim(False)
            self.tx_delay_fudge = 0.4



        self.set_max_payload_length(self.max_payload)
        self.set_hop_period(0xFF)
        self.set_implicit_header_mode(False)

    def set_rx_mode(self):
        self.set_lna_gain(GAIN.G1)
        self.set_pa_config(pa_select=0,max_power=0,output_power=0)
        self.set_agc_auto_on(True)
        if self.rf_mode == 0:
            self.set_detect_optimize(0x03)
            self.set_detection_threshold(0x0A)
        elif self.rf_mode == 1:
            self.set_detect_optimize(0x03)
            self.set_detection_threshold(0x0A)
        self.set_dio_mapping([0] * 6)
        self.set_mode(MODE.RXCONT)

    def set_tx_mode(self):
        self.set_lna_gain(GAIN.G6)
        self.set_pa_config(pa_select=1,max_power=0,output_power=0x0F) # 50mW

        self.set_mode(MODE.TX)

    def udp_broadcast(self,data):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST, 1)
        try:
            s.sendto(json.dumps(data), ('<broadcast>', self.udp_broadcast_port))
        except socket.error:
            s.sendto(json.dumps(data), ('127.0.0.1', self.udp_broadcast_port))
        s.close()

    def udp_send_rx(self,payload,snr,rssi,pkt_flags,freq_error):
        pkt_dict = {
            "type"      :   "RXPKT",
            "timestamp" : datetime.utcnow().isoformat(),
            "payload"   :  payload,
            "snr"       :   snr,
            "rssi"      :   rssi,
            "pkt_flags" :    pkt_flags,
            "freq_error": freq_error

        }
        print(pkt_dict)
        self.udp_broadcast(pkt_dict)

    def on_rx_done(self):
        self.BOARD.led_on()
#        print("\nRxDone")
        pkt_flags = self.get_irq_flags()
        snr = self.get_pkt_snr_value()
        rssi = self.get_pkt_rssi_value()
        fei = self.get_fei()
        freq_error = -1*int(((fei&0x0FFFFF) * 2**24.0 / 32e6)*(125e6/500e6))
#        print("Packet SNR: %.1f dB, RSSI: %d dB" % (snr, rssi))
        rxdata = self.read_payload(nocheck=True)
        print("RX Packet!")

        self.set_mode(MODE.SLEEP)
        self.reset_ptr_rx()
        self.BOARD.led_off()
        # Go back into RX mode.
        self.set_rx_mode()

        self.udp_send_rx(rxdata,snr,rssi,pkt_flags,freq_error)

        # TX-After-RX Logic.
        # We only transmit if:
        #   - CRC is OK
        #   - Payload type is a telemetry packet.
        #   - Payload ID is the same as our destination. 

        if (self.tx_after_rx.full()) and (pkt_flags['crc_error'] == 0): # CRC is OK, and we have something we might want to transmit.
            print("Do we want to transmit now?")
            if decode_payload_type(rxdata) == HORUS_PACKET_TYPES.PAYLOAD_TELEMETRY:
                print("Packet is telemetry...")
                # Grab the packet information to be transmitted off the tx-after-rx queue.
                (tx_packet, dest_id, timeout) = self.tx_after_rx.get_nowait()

                if decode_payload_id(rxdata) == dest_id:
                    # Do stuff here.
                    print("TX after RX time!")
                    time.sleep(TX_AFTER_RX_DELAY)
                    self.tx_packet(tx_packet)
                else:
                    # Push packet back onto queue.
                    print("Not our destination ID: %d" % decode_payload_id(rxdata))
                    if time.time() > timeout:
                        print("TX Packet has timed out.")
                        self.udp_broadcast({'type':'ERROR', 'str': 'TX-after-RX packed timed-out.'})
                    else:
                        self.tx_after_rx.put_nowait((tx_packet,dest_id,timeout))

        # Uplink timeslot request logic
        # Send a timeslot request packet if:
        #   - My timeslot is -1 (i.e. we don't have a timeslot yet)
        #   - My callsign is not 'blank' (i.e. a callsign has been set by the user)
        #   - The received packet is a telemetry packet, from the user-defined destination, and the CRC is OK.
        #   - The telemetry packet indicates a current slot of 0.
        #   - The slot_request_holdoff value is 0.
        #        (If we get this far, and the holdoff value is <0, decrement it)

        elif (self.my_uplink_timeslot == -1) and (pkt_flags['crc_error'] == 0) and (self.my_callsign != 'blank'):
            if decode_payload_type(rxdata) == HORUS_PACKET_TYPES.PAYLOAD_TELEMETRY:
                if decode_payload_id(rxdata) == self.low_priority_destination:
                    # Decode the telemetry packet.
                    telemetry_packet = decode_horus_payload_telemetry(rxdata)
                    if telemetry_packet['current_timeslot'] == 0:
                        if self.slot_request_holdoff == 0:
                            #  Create and transmit the slot request packet!
                            slot_request_packet = create_slot_request_packet(destination=self.low_priority_destination, callsign=self.my_callsign)
                            time.sleep(LOW_PRIORITY_DELAY)
                            self.tx_packet(slot_request_packet)
                            # Set the slot request holdoff to 2, so we don't keep on requesting a slot
                            # if we don't receive a response for some reason.
                            self.slot_request_holdoff = 2
                        else:
                            print("Waiting %d more cycle(s) before requesting a slot." % self.slot_request_holdoff)
                            self.slot_request_holdoff -= 1
                    else:
                        print("Not in uplink slot zero.")
                else:
                    print("Not from our destination payload - not sending slot request.")
            pass

        # 'Low Priority' Packet Transmission Logic
        # Transmitted if:
        #   We didn't have a higher priority packet to send (i.e. we didn't do anything above)
        #   I have a valid timeslot number (not -1)
        #   CRC is OK
        #   Payload type is a telemetry packet
        #   Payload ID is the same as the defined destination
        #   Indicated number of in-use timeslots is >= my timeslot number.
        #   The current uplink timeslot is my timeslot.
        elif (self.my_uplink_timeslot != -1) and (self.low_priority_destination != -1) and (len(self.low_priority_packet) != 0) and (pkt_flags['crc_error'] == 0):
            print("We have a valid low priority packet.")
            if (decode_payload_type(rxdata) == HORUS_PACKET_TYPES.PAYLOAD_TELEMETRY) and (decode_payload_id(rxdata) == self.low_priority_destination):
                print("Packet is Telemetry, and is our destination.")
                # Decode the telemetry packet.
                telemetry = decode_horus_payload_telemetry(rxdata)
                if (telemetry['used_timeslots'] < self.my_uplink_timeslot):
                    print("My timeslot is greater than the reported number of used timeslots! Did the payload reset?")
                    # Set my timeslot ID back to -1 to trigger the request-timeslot logic.
                    self.my_uplink_timeslot = -1
                elif (telemetry['current_timeslot'] == self.my_uplink_timeslot):
                    # Sleep, then transmit packet.
                    time.sleep(LOW_PRIORITY_DELAY)
                    self.tx_packet(self.low_priority_packet)
                else:
                    print("Not my timeslot.")
            else:
                print("Not telemetry, or wrong destination.")

        else:
            pass

        # Peek into the packet (if the CRC is ok) and see if we need to do anything with it.
        if (pkt_flags['crc_error'] == 0):
            # Slot request response.
            if (decode_payload_type(rxdata) == HORUS_PACKET_TYPES.SLOT_REQUEST) and (decode_payload_id(rxdata) == self.low_priority_destination):
                # Decode and check if it a response to a request from us.
                slot_response = decode_slot_request_packet(rxdata)
                if (slot_response['callsign'] == self.my_callsign) and slot_response['is_response']:
                    # A response to our slot request!
                    self.my_uplink_timeslot = slot_response['slot_id']
                    print("Got an uplink timeslot! (%d)" % self.my_uplink_timeslot)
                else:
                    print("Not a response for me.")
                    # If we are still in a state where we are trying to request a slot, and this response wasn't for us
                    # it suggests that other users are also trying to request a slot.
                    # Set the backoff value to a random number between 0 and 3 (inclusive), which forces us to wait a few more cycles before
                    # trying again.
                    self.slot_request_holdoff = int(random.random()*3)+1
            

    def on_tx_done(self):
        print("\nTxDone")
        print(self.get_irq_flags())

    def tx_packet(self,data):
        # Clip payload to max_paload length.
        if len(data)>self.max_payload:
            data = data[:self.max_payload]


        #print("Transmitting: %s" % data)
        # Write payload into fifo.
        self.set_mode(MODE.STDBY)
        self.set_lna_gain(GAIN.G6)
        self.set_pa_config(pa_select=1,max_power=0,output_power=0x0F) # 50mW
        self.set_dio_mapping([1,0,0,0,0,0])
        self.set_fifo_tx_base_addr(0x00)
        self.set_payload_length(len(data))
        self.write_payload(list(bytearray(data)))
        #print(self.get_payload_length())
        # Transmit!
        tx_timestamp = datetime.utcnow().isoformat()
        #print(datetime.utcnow().isoformat())
        self.clear_irq_flags()
        self.set_mode(MODE.TX)
        # Busy-wait until tx_done is raised.
        #print "Waiting for transmit to finish..."
        # For some reason, if we start reading the IRQ flags immediately, the TX can
        # abort prematurely. Dunno why yet.
        time.sleep(self.tx_delay_fudge)
        # Can probably fix this by, y'know, using interrupt lines properly.
        #while(self.get_irq_flags()["tx_done"]==False):
        while(self.BOARD.read_gpio()[0] == 0):
        #    print("Waiting..")
            pass
        #self.set_mode(MODE.STDBY)
        self.clear_irq_flags()
        self.set_rx_mode()
        
        #print(datetime.utcnow().isoformat())
        # Broadast a UDP packet indicating we have just transmitted.
        tx_indication = {
            'type'  : "TXDONE",
            'timestamp' : tx_timestamp,
            'payload' : list(bytearray(data)),
            'txqueuesize' : self.txqueue.qsize()
        }
        self.udp_broadcast(tx_indication)
        print("Transmitted: %s" % udp_packet_to_string(tx_indication))
        
        print("Done.")

    # Perform some checks to see if the channel is free, then TX immediately.
    def attemptTX(self, check_times = 0):
        # Check modem status a few times to be sure we aren't about to stomp on anyone.
        for x in range(check_times):
            status = self.get_modem_status()
            if status['signal_detected'] == 1:
                # Signal detected? Immediately return. Try again later.
                print("Channel busy")
                return
            else:
                time.sleep(random.random()*0.2) # Wait a random length of time.

        # If we get this far, we'll assume the channel is clear, and transmit.
        try:
            data = self.txqueue.get_nowait()
        except:
            return
        # Transmit!
        self.tx_packet(data)

    # Handle a settings update request. This is currently only used to update
    # the operating frequency of the LoRa module at runtime.
    # Could also use this to switch into a CW 'beacon' mode for DFing the car...
    def updateSettings(self):
        (parameter, value) = self.settings_changes.get_nowait()

        if parameter == "frequency":
            if (value <450.0) and (value > 430.0):
                self.set_mode(MODE.STDBY)
                self.set_freq(value)
                self.set_rx_mode()
                self.frequency = value
                print("Frequency changed.")
            else:
                self.udp_broadcast({'type':'ERROR', 'str': 'Invalid operating frequency.'})


    # Process UDP datagram contents in here, to avoid tying up the UDP listen thread.
    def udp_process(self):
        self.udp_process_running = True
        print("Started UDP Processing Thread.")
        while self.udp_process_running:
            time.sleep(0.1)
            try:
                udp_datagram = self.udprxqueue.get_nowait()
            except Exception as e:
                pass
            else:
                try:
                    m_data = json.loads(udp_datagram)
                    # Packet to be transmitted.
                    if m_data['type'] == 'TXPKT':
                        # Switch based on if we have a 'destination' field.
                        if 'destination' in m_data.keys():
                            dest_id = m_data['destination']
                            if 'timeout' in m_data.keys():
                                tx_timeout = time.time() + int(m_data['timeout'])
                            else:
                                tx_timeout = time.time() + self.default_tx_timeout
                            try:
                                self.tx_after_rx.put_nowait((m_data['payload'],dest_id,tx_timeout))
                            except:
                                self.udp_broadcast({'type':'ERROR', 'str': 'TX-after-RX Queue is full.'})
                                continue
                        else:
                            self.txqueue.put_nowait(m_data['payload']) # TODO: Data type checking.

                        tx_timestamp = datetime.utcnow().isoformat()
                        tx_indication = {
                            'type'  : "TXQUEUED",
                            'timestamp' : tx_timestamp,
                            'payload' : list(bytearray(m_data['payload'])),
                            'txqueuesize' : self.txqueue.qsize()
                        }
                        self.udp_broadcast(tx_indication)
                        print("Queued: %s" % udp_packet_to_string(m_data))
                    # Just a check to see if we are alive. Respond immediately.
                    elif m_data['type'] == 'PING':
                            ping_response = {
                                'type'  : "PONG",
                                'data' : m_data['data']
                            }
                            self.udp_broadcast(ping_response)
                    elif m_data['type'] == 'RF':
                        if 'frequency' in m_data.keys():
                            new_freq = float(m_data['frequency'])
                            self.settings_changes.put_nowait(('frequency',new_freq))
                    elif m_data['type'] == 'LOWPRIORITY':
                        # It will probably be useful for the user to be able to update
                        # a subset of fields at a time, so only try and read a field if it exists.
                        if 'destination' in m_data.keys():
                            self.low_priority_destination = int(m_data['destination'])

                        if 'payload' in m_data.keys():
                            self.low_priority_packet = m_data['payload']

                        if 'callsign' in m_data.keys():
                            self.my_callsign = str(m_data['callsign'])

                        if 'reset' in m_data.keys():
                            # A client including this field triggers a re-request for a timeslot.
                            # Since this is likely to be used mid-flight, we consider it safe to 
                            # attempt to request a slot at the next opportunity, hence we set the holdoff
                            # value to 0.
                            self.my_uplink_timeslot = -1
                            self.slot_request_holdoff = 0

                    else:
                        pass
                except Exception as e:
                    print(e)
                    print("ERROR: ")
                    traceback.print_exc()
                    
        print("Shutting down UDP Processing Thread.")

    # Continuously listen on a UDP port for json data.
    # If a valid packet is received, put it in the transmit queue.
    # This function should be run in a separate thread.
    def udp_listen(self):
        s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        s.settimeout(1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except:
            pass
        s.bind(('',self.udp_broadcast_port))
        print("Started UDP Listener Thread.")
        self.udp_listener_running = True
        while self.udp_listener_running:
            try:
                m = s.recvfrom(MAX_JSON_LEN)
            except:
                m = None

            if m != None:
                self.udprxqueue.put_nowait(m[0])
        #
        print("Closing UDP Listener")
        s.close()

    def start(self):
        # Start up UDP listener thread.
        udplistenthread = Thread(target=self.udp_listen)
        udplistenthread.start()

        udpprocessthread = Thread(target=self.udp_process)
        udpprocessthread.start()



        # Startup LoRa hardware
        self.reset_ptr_rx()
        self.set_common()
        self.set_rx_mode()
        # Main loop
        while True:
            time.sleep(0.05)
            rssi_value = self.get_rssi_value()
            status = self.get_modem_status()

            # Don't flood the users with status packets. 
            self.status_counter += 1
            if self.status_counter % self.status_throttle == 0:
                # Generate dictionary to broadcast
                status_dict = {
                    'type'  : "STATUS",
                    "timestamp" : datetime.utcnow().isoformat(),
                    'rssi'  : rssi_value,
                    'status': status,
                    'txqueuesize': self.txqueue.qsize(),
                    'frequency' : self.frequency,
                    'uplink_callsign'  : self.my_callsign,
                    'uplink_slot_id' : self.my_uplink_timeslot,
                    'uplink_destination': self.low_priority_destination,
                    'uplink_holdoff': self.slot_request_holdoff
                }
                self.udp_broadcast(status_dict)

            #sys.stdout.flush()
            #sys.stdout.write("\r%d %d %d" % (rssi_value, status['rx_ongoing'], status['signal_detected']))

            #if(self.get_irq_flags()["rx_done"]==True):
            if(self.BOARD.read_gpio()[0] == 1):
                self.on_rx_done()

            if(self.txqueue.qsize()>0):
                # Something in the queue to be transmitted.
                self.attemptTX()

            if(self.settings_changes.qsize()>0):
                self.updateSettings()

            # Check if the tx_after_rx packet has timed out
            if self.tx_after_rx.qsize()>0:
                (tx_packet, dest_id, timeout) = self.tx_after_rx.get_nowait()
                if time.time() > timeout:
                    print("TX-after-RX Packet automatically timed out.")
                    self.udp_broadcast({'type':'ERROR', 'str': 'TX-after-RX packed timed-out.'})
                else:
                    self.tx_after_rx.put_nowait((tx_packet,dest_id,timeout))


# Main Script

parser = argparse.ArgumentParser()
group = parser.add_mutually_exclusive_group()
group.add_argument("--rpishield", action="store_true", help="Use a PiLoraGateway RPI Shield.")
group.add_argument("--spibridge", action="store_true", help="Use a Arduino+LoRa Shield running SPIBridge Firmware.")
parser.add_argument("-d" ,"--device", default="1", help="Hardware Device, either a serial port (i.e. /dev/ttyUSB0 or COM5) or SPI device number (i.e. 1)")
parser.add_argument("-f", "--frequency",type=float,default=431.650,help="Operating Frequency (MHz)")
parser.add_argument("-m", "--mode",type=int,default=0,help="Transmit Mode: 0 = Slow, 1 = Fast, 2 = Really Fast")
parser.add_argument("--callsign", default="blank", help="OPTIONAL: Callsign used for automatic uplink slot requesting.")
parser.add_argument("--payload_id", default=-1, type=int, help="OPTIONAL: Payload ID to automatically request slot from.")
args = parser.parse_args()

mode = int(args.mode)
frequency = float(args.frequency)
my_callsign = args.callsign
payload_id = args.payload_id


# Perform hardware interactions in an overall loop, to try and recover from hardware faults.
while True:
    if args.spibridge:
        from SX127x.hardware_spibridge import HardwareInterface
        hw = HardwareInterface(port=args.device)
    elif args.rpishield:
        from SX127x.hardware_piloragateway import HardwareInterface
        hw = HardwareInterface(int(args.device))
    else:
        print >>sys.stderr, "Please provide a hardware interface argument"
        sys.exit(1)

    try:
        lora = LoRaTxRxCont(hw,verbose=False,mode=mode,frequency=frequency, callsign=my_callsign, low_priority_destination=payload_id)
        lora.start()
    except KeyboardInterrupt:
        sys.stdout.flush()
        print("")
        sys.stderr.write("KeyboardInterrupt\n")
        break
    except:
        traceback.print_exc()
        try:
            print("Attempting to restart.")
            lora.set_mode(MODE.SLEEP)
            lora.udp_listener_running = False
            lora.udp_process_running = False
            hw.teardown()
        except:
            traceback.print_exc()
            print("Issues re-starting...")
            continue

sys.stdout.flush()
print("")
lora.set_mode(MODE.SLEEP)
lora.udp_listener_running = False
lora.udp_process_running = False
print(lora)
print("Shutting down hardware interface...")
hw.teardown()
print("Done.")


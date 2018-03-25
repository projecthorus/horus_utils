#!/usr/bin/env python2.7
#
#   Project Horus - Packet Handlers & UDP Communication
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#
import crcmod
import json
import time
import socket
import struct
from datetime import datetime
from . import *
from .wenet import *

MAX_JSON_LEN = 2048
TX_QUEUE_SIZE = 32

# Timing Settings
TX_AFTER_RX_DELAY   = 0.2
LOW_PRIORITY_DELAY  = 2.35

# Packet Payload Types
class HORUS_PACKET_TYPES:
    PAYLOAD_TELEMETRY     = 0
    TEXT_MESSAGE          = 1
    CUTDOWN_COMMAND       = 2
    PARAMETER_CHANGE      = 3
    COMMAND_ACK           = 4
    SHORT_TELEMETRY       = 5
    SLOT_REQUEST          = 6
    CAR_TELEMETRY         = 7
    # Accept SSDV packets 'as-is'. https://ukhas.org.uk/guides:ssdv
    SSDV_FEC              = 0x66
    SSDV_NOFEC            = 0x67

class HORUS_PAYLOAD_PARAMS:
    PING                  = 0
    LISTEN_TIME           = 1
    TDMA_MODE             = 2 # Currently unused
    TDMA_SLOT             = 3 # Currently unused
    PAYLOAD_ID            = 4
    NUM_PAYLOADS          = 5
    RESET_SLOTS           = 6


def decode_payload_type(packet):
    # This expects the payload as an integer list. Convert it to one if it isn't already
    packet = list(bytearray(packet))

    # First byte of every packet is the payload type.
    payload_type = packet[0]

    return payload_type

def decode_payload_id(packet):
    # This expects the payload as an integer list. Convert it to one if it isn't already
    packet = list(bytearray(packet))

    # 3rd byte is the payload ID.
    payload_id = packet[2]

    return payload_id

def decode_payload_flags(packet):
    # This expects the payload as an integer list. Convert it to one if it isn't already
    packet = list(bytearray(packet))

    # Payload flags is always the second byte.
    payload_flags_byte = packet[1]
    payload_flags = {
        'repeater_id'    : payload_flags_byte >> 4,     # Repeating payload inserts a unique ID in here
        'is_repeated' : payload_flags_byte >> 0 & 0x01,   # Indicates a packet repeated off a payload.
    }
    return payload_flags


# TEXT MESSAGE PACKET
# Payload Format:
# Byte 0 - Packet Type ID
# Byte 1 - Payload Flags
# Byte 2 - Destination ID (the payload that will repeat this packet)
# Byte 3-10 - Callsign (Max 8 chars. Padded to 8 characters if shorter.)
# Bytes 11-64 - Message (Max 54 characters. Not padded!)
TEXT_MESSAGE_MAX_LENGTH = 32
def create_text_message_packet(source="N0CALL", message="CQ CQ CQ", destination=0):
    # Sanitise input
    if len(source)>8:
        source = source[:8]

    if len(message)>TEXT_MESSAGE_MAX_LENGTH:
        message = message[:TEXT_MESSAGE_MAX_LENGTH]

    # Pad data if required.
    if len(source)<8:
        source = source + "\x00"*(8-len(source))

    packet = [HORUS_PACKET_TYPES.TEXT_MESSAGE,0,destination] + list(bytearray(source)) + list(bytearray(message))
    return packet

def read_text_message_packet(packet):
    # Convert packet into a string, if it isn't one already.
    packet = str(bytearray(packet))
    source = packet[3:10].rstrip(' \t\r\n\0')
    message = packet[11:].rstrip('\n\0')
    return (source,message)

# SSDV Packets
# Generally we will just send this straight out to ssdv.habhub.org
def read_ssdv_packet_info(packet):
    packet = list(bytearray(packet))
    # Check packet is actually a SSDV packet.
    if len(packet) != 255:
        return "SSDV: Invalid Length"


    # We got this far, may as well try and extract the packet info.
    callsign = "???"
    packet_type = "FEC" if (packet[0]==0x66) else "No-FEC"
    image_id = packet[5]
    packet_id = (packet[6]<<8) + packet[7]
    width = packet[8]*16
    height = packet[9]*16

    return "SSDV: %s, Img:%d, Pkt:%d, %dx%d" % (packet_type,image_id,packet_id,width,height)


# SHORT TELEMETRY PACKET
# As used by SwarmTrackerLoRa
# Again, payload format is in a bit of flux.
# Payload Format:
# struct TBinaryPacket
# {
#   uint8_t   PacketType;
#     uint8_t     PayloadID;
#     uint8_t   hour;
#   uint8_t   minute;
#   uint8_t   second;
#     float       Latitude;
#     float       Longitude;
#   uint8_t   Speed; // Speed in Knots (1-255 knots)
#   uint8_t   BattVoltage; // 0 = 0.5v, 255 = 2.0V, linear steps in-between.
#   uint8_t   Sats;
# };  //  __attribute__ ((packed));

def decode_short_payload_telemetry(packet):
    packet = str(bytearray(packet))

    horus_format_struct = "<BBBBBffBBB"
    try:
        unpacked = struct.unpack(horus_format_struct, packet)
    except:
        print "Wrong string length. Packet contents:"
        print ":".join("{:02x}".format(ord(c)) for c in packet)
        return {}

    telemetry = {}
    telemetry['packet_type'] = unpacked[0]
    telemetry['payload_id'] = unpacked[1]
    telemetry['hour'] = unpacked[2]
    telemetry['minute'] = unpacked[3]
    telemetry['second'] = unpacked[4]
    telemetry['latitude'] = unpacked[5]
    telemetry['longitude'] = unpacked[6]
    telemetry['speed'] = unpacked[7]
    telemetry['sats'] = unpacked[9]
    telemetry['batt_voltage_raw'] = unpacked[8]

    # Convert some of the fields into more useful units.
    telemetry['time'] = "%02d:%02d:%02d" % (telemetry['hour'],telemetry['minute'],telemetry['second'])
    telemetry['batt_voltage'] = 0.5 + 1.5*telemetry['batt_voltage_raw']/255.0

    return telemetry

# PAYLOAD TELEMETRY PACKET
# This one is in a bit of flux at the moment.
# Payload Format:
# struct TBinaryPacket
# {
#   uint8_t   PacketType;
#   uint8_t   PayloadFlags;
#   uint8_t   PayloadIDs;
#   uint16_t  Counter;
#   uint8_t   Hour;  // Updated 2018-02-07
#   uint8_t   Minute;
#   uint8_t   Second;
#   float     Latitude;
#   float     Longitude;
#   uint16_t  Altitude;
#   uint8_t   Speed; // Speed in Knots (1-255 knots)
#   uint8_t   Sats;
#   uint8_t   Temp; // Twos Complement Temp value.
#   uint8_t   BattVoltage; // 0 = 0.5v, 255 = 2.0V, linear steps in-between.
#   uint8_t   PyroVoltage; // 0 = 0v, 255 = 5.0V, linear steps in-between.
#   uint8_t   rxPktCount; // RX Packet Count.
#   uint8_t   rxRSSI; // Ambient RSSI value, measured just before transmission.
#   uint8_t   uplinkSlots; // High Nibble: Uplink timeslots in use; Low Nibble: Current uplink timeslot.
# };  //  __attribute__ ((packed));


def decode_horus_payload_telemetry(packet):
    packet = str(bytearray(packet))

    horus_format_struct = "<BBBHBBBffHBBBBBBBB"
    try:
        unpacked = struct.unpack(horus_format_struct, packet)
    except:
        print "Wrong string length. Packet contents:"
        print ":".join("{:02x}".format(ord(c)) for c in packet)
        return {}

    telemetry = {}
    telemetry['packet_type'] = unpacked[0]
    telemetry['payload_flags'] = unpacked[1]
    telemetry['payload_id'] = unpacked[2]
    telemetry['counter'] = unpacked[3]
    telemetry['hour'] = unpacked[4]
    telemetry['minute'] = unpacked[5]
    telemetry['second'] = unpacked[6]
    telemetry['latitude'] = unpacked[7]
    telemetry['longitude'] = unpacked[8]
    telemetry['altitude'] = unpacked[9]
    telemetry['speed'] = unpacked[10]
    telemetry['sats'] = unpacked[11]
    telemetry['temp'] = unpacked[12]
    telemetry['batt_voltage_raw'] = unpacked[13]
    telemetry['pyro_voltage_raw'] = unpacked[14]
    telemetry['rxPktCount'] = unpacked[15]
    telemetry['RSSI'] = unpacked[16]-164
    telemetry['uplinkSlots'] = unpacked[17]
    # Uplink timeslot stuff.
    telemetry['used_timeslots'] = (0xF0&unpacked[17])>>4 # High Nibble
    telemetry['current_timeslot'] = (0x0F & unpacked[17]) # Low Nibble

    # Convert some of the fields into more useful units.
    telemetry['time'] = "%02d:%02d:%02d" % (telemetry['hour'],telemetry['minute'],telemetry['second'])
    telemetry['seconds_in_day'] = telemetry['hour']*3600 + telemetry['minute']*60 + telemetry['second']
    telemetry['batt_voltage'] = 0.5 + 1.5*telemetry['batt_voltage_raw']/255.0
    telemetry['pyro_voltage'] = 5.0*telemetry['pyro_voltage_raw']/255.0

    return telemetry

# Convert telemetry dictionary to a Habitat-compatible telemetry string.
# The below is compatible with genpayload doc ID# f18a873592a77ed01ea432c3bcc16d0f
def telemetry_to_sentence(telemetry, payload_callsign="HORUSLORA", payload_id = None):
    payload_id_str = "" if payload_id == None else str(payload_id)
    sentence = "$$%s%s,%d,%s,%.5f,%.5f,%d,%d,%d,%.2f,%.2f,%d,%d" % (payload_callsign,payload_id_str,telemetry['counter'],telemetry['time'],telemetry['latitude'],
        telemetry['longitude'],telemetry['altitude'],telemetry['speed'],telemetry['sats'],telemetry['batt_voltage'],
        telemetry['pyro_voltage'],telemetry['RSSI'],telemetry['rxPktCount'])

    checksum = crc16_ccitt(sentence[2:])
    output = sentence + "*" + checksum + "\n"
    return output

# CRC16 function for the above.
def crc16_ccitt(data):
    """
    Calculate the CRC16 CCITT checksum of *data*.
    
    (CRC16 CCITT: start 0xFFFF, poly 0x1021)
    """
    crc16 = crcmod.predefined.mkCrcFun('crc-ccitt-false')
    return hex(crc16(data))[2:].upper().zfill(4)

# Command ACK Packet. Sent by the payload to acknowledge a command (i.e. cutdown or param change) has been executed.
def decode_command_ack(packet):
    packet = list(bytearray(packet))
    if len(packet) != 8:
        print "Invalid length for Command ACK."
        return {}

    ack_packet = {}
    ack_packet['payload_id'] = packet[2]
    ack_packet['rssi'] = packet[3] - 164
    ack_packet['snr'] = struct.unpack('b',str(bytearray([packet[4]])))[0]/4.
    if packet[5] == HORUS_PACKET_TYPES.CUTDOWN_COMMAND:
        ack_packet['command'] = "Cutdown"
        ack_packet['argument'] = "%d Seconds." % packet[6]
    elif packet[5] == HORUS_PACKET_TYPES.PARAMETER_CHANGE:
        ack_packet['command'] = "Param Change"
        ack_packet['argument'] = "%d %d" % (packet[6], packet[7])
        ack_packet['param'] = packet[6]
        ack_packet['value'] = packet[7]

    return ack_packet

def create_cutdown_packet(time=4,passcode="zzz", destination = 0):
    if len(passcode)<3: # Pad out passcode. This will probably cause the payload not to accept it though.
        passcode = passcode + "   "

    # Sanitize cut time.
    if time>10:
        time = 10
    if time<0:
        time = 0

    # TODO: Sanitise destination field input.

    cutdown_packet = [HORUS_PACKET_TYPES.CUTDOWN_COMMAND,0,0,0,0,0,0,0]
    cutdown_packet[2] = destination
    cutdown_packet[3] = ord(passcode[0])
    cutdown_packet[4] = ord(passcode[1])
    cutdown_packet[5] = ord(passcode[2])
    cutdown_packet[6] = time

    return cutdown_packet

def create_param_change_packet(param = HORUS_PAYLOAD_PARAMS.PING, value = 10, passcode = "zzz", destination = 0):
    if len(passcode)<3: # Pad out passcode. This will probably cause the payload not to accept it though.
        passcode = passcode + "   "
    # Sanitize parameter and value inputs.
    if param>255:
        param = 255

    if value>255:
        value = 255

    # TODO: Sanitise destination field input.

    param_packet = [HORUS_PACKET_TYPES.PARAMETER_CHANGE,0,0,0,0,0,0,0]
    param_packet[2] = destination
    param_packet[3] = ord(passcode[0])
    param_packet[4] = ord(passcode[1])
    param_packet[5] = ord(passcode[2])
    param_packet[6] = param
    param_packet[7] = value

    return param_packet

CAR_TELEMETRY_CALLSIGN_LENGTH = 9
CAR_TELEMETRY_MESSAGE_LENGTH = 20
def create_car_telemetry_packet(destination=0,callsign="N0CALL", latitude=-34.5, longitude=138.0, speed=1, message=" "):
    # Sanitise Inputs

    # Convert speed to an integer, and clip to 0 - 110 kph.
    speed = int(speed)
    if speed > 110:
        speed = 110
    elif speed < 0:
        speed = 0
    else:
        pass

    if len(message) > CAR_TELEMETRY_MESSAGE_LENGTH:
        message = message[:CAR_TELEMETRY_MESSAGE_LENGTH]
    elif len(message) == 0:
        message = " "
    else:
        pass

    telem_packet = struct.pack(">BBB9sffB",
        HORUS_PACKET_TYPES.CAR_TELEMETRY,
        0,
        destination,
        callsign,
        latitude,
        longitude,
        speed)

    # Add on capped-length message field at end.
    telem_packet += message

    return telem_packet

CAR_TELEMETRY_BODY_LENGTH = 21
def decode_car_telemetry_packet(packet):
    packet = str(bytearray(packet))

    if len(packet) < (CAR_TELEMETRY_BODY_LENGTH+1):
        print("Wrong string length")
        return {}

    if decode_payload_type(packet) != HORUS_PACKET_TYPES.CAR_TELEMETRY:
        print("Not a Car Telemetry Packet")
        return {}

    try:
        unpacked = struct.unpack(">BBB9sffB", packet[:CAR_TELEMETRY_BODY_LENGTH])
    except:
        print("Wrong string length. Packet contents:")
        print(":".join("{:02x}".format(ord(c)) for c in packet))
        return {}

    car_telem = {}
    car_telem['packet_type']    = unpacked[0]
    car_telem['payload_flags']  = unpacked[1]
    car_telem['source_id']      = unpacked[2]
    car_telem['callsign']       = unpacked[3].rstrip(' \t\r\n\0')
    car_telem['latitude']       = unpacked[4]
    car_telem['longitude']      = unpacked[5]
    car_telem['speed']          = unpacked[6]
    car_telem['message']        = packet[CAR_TELEMETRY_BODY_LENGTH:].rstrip('\t\r\n\0')

    return car_telem

def car_telem_to_string(packet):
    car_telem = decode_car_telemetry_packet(packet)

    car_telem_string = ""

    if len(car_telem.keys()) == 0:
        car_telem_string =  "Car Telemetry: Invalid Packet"
    else:
        if decode_payload_flags(packet)['is_repeated']:
            car_telem_string =  "Car Telemetry (via #%d): " % (car_telem['source_id'])
        else:
            car_telem_string = "Car Telemetry (direct): "

        car_telem_string += "%s %.5f,%.5f %d kph [%s]" % (car_telem['callsign'],car_telem['latitude'],car_telem['longitude'],car_telem['speed'],car_telem['message'])

    return car_telem_string


def create_slot_request_packet(destination=0,callsign="N0CALL"):
    telem_packet = struct.pack(">BBB9sB",
        HORUS_PACKET_TYPES.SLOT_REQUEST,
        0,
        destination,
        callsign,
        0)

    return telem_packet

def decode_slot_request_packet(packet):
    packet = str(bytearray(packet))

    if decode_payload_type(packet) != HORUS_PACKET_TYPES.SLOT_REQUEST:
        print("Not a Slot Request Packet")
        return {}

    try:
        unpacked = struct.unpack(">BBB9sB", packet)
    except:
        print("Wrong string length. Packet contents:")
        print(":".join("{:02x}".format(ord(c)) for c in packet))
        return {}

    slot_request = {}
    slot_request['packet_type']    = unpacked[0]
    slot_request['payload_flags']  = unpacked[1]
    slot_request['source_id']      = unpacked[2]
    slot_request['callsign']       = unpacked[3].rstrip(' \t\r\n\0')
    slot_request['slot_id']        = unpacked[4]
    slot_request['is_response']    = slot_request['slot_id'] != 0

    return slot_request

def slot_request_to_string(packet):
    slot_request = decode_slot_request_packet(packet)
    # Sanity check we were able to decode the packet.
    if len(slot_request.keys()) == 0:
        return "Slot Request: Invalid Packet"
    else:
        if slot_request['slot_id'] == 0:
            return "Slot Request: %s requested a slot from #%d" % (slot_request['callsign'],slot_request['source_id'])
        else:
            return "Slot Response: %s was given slot ID %d from #%d" % (slot_request['callsign'],slot_request['slot_id'],slot_request['source_id'])

# Update the LoRaUDPServer with low priority callsign and destination data,
# so it triggers an uplink slot request.
def update_low_priority_settings(callsign="blank", destination=-1):
    packet = {
        'type' : 'LOWPRIORITY',
        'callsign': callsign,
        'destination': destination,
        'reset': 'reset'
    }
    print(packet)

    # Set up our UDP socket
    s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    s.settimeout(1)
    # Set up socket for broadcast, and allow re-use of the address
    s.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except:
        pass
    s.bind(('',HORUS_UDP_PORT))
    try:
        s.sendto(json.dumps(packet), ('<broadcast>', HORUS_UDP_PORT))
    except socket.error:
        s.sendto(json.dumps(packet), ('127.0.0.1', HORUS_UDP_PORT))

# Resets the uplink slot ID on the ground station, triggering an uplink slot request, if we
# already had a slot. Otherwise, does nothing.
def reset_low_priority_slot():
    packet = {
        'type' : 'LOWPRIORITY',
        'reset': 'reset'
    }

    # Set up our UDP socket
    s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    s.settimeout(1)
    # Set up socket for broadcast, and allow re-use of the address
    s.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except:
        pass
    s.bind(('',HORUS_UDP_PORT))
    try:
        s.sendto(json.dumps(packet), ('<broadcast>', HORUS_UDP_PORT))
    except socket.error:
        s.sendto(json.dumps(packet), ('127.0.0.1', HORUS_UDP_PORT))

# Updates the payload stored in the low priority packet buffer.
# This is what is uplinked in the low priority packet slot.
def set_low_priority_payload(payload):
    packet = {
        'type' : 'LOWPRIORITY',
        'payload': list(bytearray(payload))
    }

    # Set up our UDP socket
    s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    s.settimeout(1)
    # Set up socket for broadcast, and allow re-use of the address
    s.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except:
        pass
    s.bind(('',HORUS_UDP_PORT))
    try:
        s.sendto(json.dumps(packet), ('<broadcast>', HORUS_UDP_PORT))
    except socket.error:
        s.sendto(json.dumps(packet), ('127.0.0.1', HORUS_UDP_PORT))

# Transmit packet via UDP Broadcast
def tx_packet(payload, blocking=False, timeout=4, destination=None, tx_timeout=15):
    packet = {
        'type' : 'TXPKT',
        'payload' : list(bytearray(payload)),
    }
    # Add in destination field if we have been given one.
    if destination != None:
        packet['destination'] = destination
        packet['timeout'] = tx_timeout

    # Print some info about the packet.
    print(packet)
    print(len(json.dumps(packet)))
    # Set up our UDP socket
    s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    s.settimeout(1)
    # Set up socket for broadcast, and allow re-use of the address
    s.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except:
        pass
    s.bind(('',HORUS_UDP_PORT))
    try:
        s.sendto(json.dumps(packet), ('<broadcast>', HORUS_UDP_PORT))
    except socket.error as e:
        print(str(e))
        s.sendto(json.dumps(packet), ('127.0.0.1', HORUS_UDP_PORT))

    if blocking:
        start_time = time.time() # Start time for our timeout.

        while (time.time()-start_time) < timeout:
            try:
                print("Waiting for UDP")
                (m,a) = s.recvfrom(MAX_JSON_LEN)
            except socket.timeout:
                m = None
            
            if m != None:
                try:
                    packet = json.loads(m)
                    if packet['type'] == 'TXDONE':
                        if packet['payload'] == list(bytearray(payload)):
                            print("Packet Transmitted Successfuly!")
                            s.close()
                            return
                        else:
                            print("Not our payload!")
                    else:
                        print("Wrong Packet: %s" % packet['type'])
                except Exception as e:
                    print("Error: %s" % e)
            else:
                print("Got no packet")
        print("TX Timeout!")

    else:
        s.close()

# Set new operating frequency on the UDP-LoRa bridge.
def update_frequency(freq=431.650):
    packet = {
        'type' : 'RF',
        'frequency': freq
    }

    # Set up our UDP socket
    s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    s.settimeout(1)
    # Set up socket for broadcast, and allow re-use of the address
    s.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except:
        pass
    s.bind(('',HORUS_UDP_PORT))
    try:
        s.sendto(json.dumps(packet), ('<broadcast>', HORUS_UDP_PORT))
    except socket.error:
        s.sendto(json.dumps(packet), ('127.0.0.1', HORUS_UDP_PORT))


# Produce short string representation of packet payload contents.
def payload_to_string(packet):
    payload_type = decode_payload_type(packet)

    if payload_type == HORUS_PACKET_TYPES.PAYLOAD_TELEMETRY:
        telemetry = decode_horus_payload_telemetry(packet)
        data = "Balloon #%d Telemetry: %s,%d,%.5f,%.5f,%d,%d,%.2f,%.2f,%d,%d" % (telemetry['payload_id'], telemetry['time'],telemetry['counter'],
            telemetry['latitude'],telemetry['longitude'],telemetry['altitude'],telemetry['sats'],telemetry['batt_voltage'],telemetry['pyro_voltage'],telemetry['rxPktCount'],telemetry['RSSI'])
        return data
    elif payload_type == HORUS_PACKET_TYPES.SHORT_TELEMETRY:
        telemetry = decode_short_payload_telemetry(packet)
        data = "Short Telemetry: ID:%d %s,%.6f,%.6f,%d,%d" % (telemetry['payload_id'],telemetry['time'],
            telemetry['latitude'],telemetry['longitude'],telemetry['sats'],telemetry['batt_voltage'])
        return data
    elif payload_type == HORUS_PACKET_TYPES.TEXT_MESSAGE:
        (source, message) = read_text_message_packet(packet)
        flags = decode_payload_flags(packet)
        if flags['is_repeated']:
            data = "Repeated Text Message: <%s> %s" % (source,message)
        else:
            data = "Text Message: <%s> %s" % (source,message)
        return data
    elif payload_type == HORUS_PACKET_TYPES.CUTDOWN_COMMAND:
        return "Cutdown Command"

    elif payload_type == HORUS_PACKET_TYPES.COMMAND_ACK:
        ack = decode_command_ack(packet)
        data = "Command ACK, Payload #%d : [R: %d dBm, S:%.1fdB] %s %s" % (ack['payload_id'],ack['rssi'], ack['snr'], ack['command'], ack['argument'])
        return data
    elif payload_type == HORUS_PACKET_TYPES.PARAMETER_CHANGE:
        return "Parameter Change"
    elif (payload_type == HORUS_PACKET_TYPES.SSDV_FEC) or (payload_type == HORUS_PACKET_TYPES.SSDV_NOFEC):
        return read_ssdv_packet_info(packet)
    elif payload_type == HORUS_PACKET_TYPES.SLOT_REQUEST:
        return slot_request_to_string(packet)
    elif payload_type == HORUS_PACKET_TYPES.CAR_TELEMETRY:
        return car_telem_to_string(packet)
    else:
        return "Unknown Payload"

def udp_packet_to_string(udp_packet):
    try:
        pkt_type = udp_packet['type']
    except Exception as e:
        return "Unknown UDP Packet"

    if pkt_type == "RXPKT":
        timestamp = udp_packet['timestamp']
        rssi = float(udp_packet['rssi'])
        snr = float(udp_packet['snr'])

        freq_error = float(udp_packet['freq_error'])
        crc_ok = udp_packet['pkt_flags']['crc_error'] == 0
        if crc_ok:
            payload_str = payload_to_string(udp_packet['payload'])
        else:
            payload_str = "CRC Fail!"
        return "%s RXPKT \tRSSI: %.1f SNR: %.1f FERR: %.1f \tPayload:[%s]" % (timestamp,rssi,snr,freq_error,payload_str)
    elif pkt_type == "STATUS":
        timestamp = udp_packet['timestamp']
        rssi = float(udp_packet['rssi'])
        txqueuesize = udp_packet['txqueuesize']
        frequency = udp_packet['frequency']
        uplink_callsign = udp_packet['uplink_callsign']
        uplink_slot_id = udp_packet['uplink_slot_id']
        uplink_holdoff = udp_packet['uplink_holdoff']
        # Insert Modem Status decoding code here.
        return "%s STATUS \t%.3f MHz \tRSSI: %.1f \tUplink: %s, Slot %d, Holdoff: %d" % (timestamp,frequency,rssi,uplink_callsign, uplink_slot_id, uplink_holdoff)
    elif pkt_type == "TXPKT":
        timestamp = datetime.utcnow().isoformat()
        payload_str = payload_to_string(udp_packet['payload'])
        return "%s TXPKT \tPayload:[%s]" % (timestamp,payload_str)
    elif pkt_type == "TXDONE":
        timestamp = udp_packet['timestamp']
        txqueuesize = udp_packet['txqueuesize']
        payload_str = payload_to_string(udp_packet['payload'])
        return "%s TXDONE \tPayload:[%s] \tQUEUE: %d" % (timestamp,payload_str,txqueuesize)
    elif pkt_type == "TXQUEUED":
        timestamp = udp_packet['timestamp']
        txqueuesize = udp_packet['txqueuesize']
        payload_str = payload_to_string(udp_packet['payload'])
        return "%s TXQUEUED \tPayload:[%s] \tQUEUE: %d" % (timestamp,payload_str,txqueuesize)
    elif pkt_type == "ERROR":
        timestamp = datetime.utcnow().isoformat()
        error_str = udp_packet['str']
        return "%s ERROR \t%s" % (timestamp,error_str)
    elif pkt_type == "GPS":
        timestamp = datetime.utcnow().isoformat()
        return "%s Local GPS: %.4f,%.4f %d kph %d m" % (timestamp,udp_packet['latitude'], udp_packet['longitude'], udp_packet['speed'], udp_packet['altitude'])
    elif pkt_type == "PAYLOAD_SUMMARY":
        timestamp = datetime.utcnow().isoformat()
        return "%s Payload Summary Status: %.5f, %.5f, %d" % (timestamp, udp_packet['latitude'], udp_packet['longitude'], udp_packet['altitude'])
    elif pkt_type == "OZIMUX":
        timestamp = datetime.utcnow().isoformat()
        return "%s OziMux Broadcast: Source = %s, Pos: %.5f, %.5f, %d, Comment: %s" % (timestamp, udp_packet['source_name'], udp_packet['latitude'], udp_packet['longitude'], udp_packet['altitude'], udp_packet['comment'])
    elif pkt_type == "WENET":
        timestamp = datetime.utcnow().isoformat()
        return "%s %s" % (timestamp, wenet_packet_to_string(udp_packet['packet']))
    elif pkt_type == "LOWPRIORITY":
        if 'payload' in udp_packet.keys():
            if udp_packet['payload'] == []:
                return "Low Priority Packet Update: TX Inhibited."
            else:
                return "Low Priority Packet Update: %s" % payload_to_string(udp_packet['payload'])
        else:
            return "Low Priority Setting Change"
    else:
        return "Not Implemented"



# Send an update on the core payload telemetry statistics into the network via UDP broadcast.
# This can be used by other devices hanging off the network to display vital stats about the payload.
def send_payload_summary(callsign, latitude, longitude, altitude, speed=-1, heading=-1, short_time=None):
    packet = {
        'type' : 'PAYLOAD_SUMMARY',
        'callsign' : callsign,
        'latitude' : latitude,
        'longitude' : longitude,
        'altitude' : altitude,
        'speed' : speed,
        'heading': heading,
    }

    # Optionally add in a time field, which should always be of the form HH:MM:SS
    if short_time != None:
        packet['time'] = short_time

    # Set up our UDP socket
    s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    s.settimeout(1)
    # Set up socket for broadcast, and allow re-use of the address
    s.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except:
        pass
    s.bind(('',HORUS_UDP_PORT))
    try:
        s.sendto(json.dumps(packet), ('<broadcast>', HORUS_UDP_PORT))
    except socket.error:
        s.sendto(json.dumps(packet), ('127.0.0.1', HORUS_UDP_PORT))


# A quick add-on which allows OziMux to broadcast everything it is seeing into the local network via broadcast
# This is used for a 'launch check' device which hangs off the network and needs to see *all* traffic.
def send_ozimux_broadcast_packet(source_name, latitude, longitude, altitude, short_time=None, comment=""):
    packet = {
        'type' : 'OZIMUX',
        'source_name' : source_name,
        'latitude' : latitude,
        'longitude' : longitude,
        'altitude' : altitude,
        'comment' : comment
    }

    # Optionally add in a time field, which should always be of the form HH:MM:SS
    if short_time != None:
        packet['time'] = short_time

    # Set up our UDP socket
    s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    s.settimeout(1)
    # Set up socket for broadcast, and allow re-use of the address
    s.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except:
        pass
    s.bind(('',HORUS_UDP_PORT))
    try:
        s.sendto(json.dumps(packet), ('<broadcast>', HORUS_UDP_PORT))
    except socket.error:
        s.sendto(json.dumps(packet), ('127.0.0.1', HORUS_UDP_PORT))


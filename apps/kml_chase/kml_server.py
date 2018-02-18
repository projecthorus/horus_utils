#!/usr/bin/env python

import time, argparse, math
from datetime import datetime
from dateutil.parser import parse
from horuslib.listener import OziListener, UDPListener
from horuslib.geometry import *
from flask import Flask
app = Flask(__name__)

# Objects which store our track data.
_payload_track = GenericTrack()
_payload_data_valid = False
_car_track = GenericTrack()
_car_data_valid = False

# Global settings
absolute_tracks = True
no_labels = False

# Prediction Tracks
_predictor = None # Predictor object, instantiated later on, if we are using the predictor.
burst_alt = 30000.0
descent_rate = 5.0
_flight_prediction = []
_abort_prediction = []

# Generate a KML File based on the above datasets.
@app.route('/')
def serve_kml():
    ''' Generate a KML file, and pass it to the client '''
    global _payload_track, _payload_data_valid, _car_track, _car_data_valid
    # If we have no data, return nothing.
    if (_payload_data_valid == False) and (_car_data_valid == False):
        return ""

    # Array for storing payload/car track geometery data.
    _geom_data = []

    # Generate Payload positon data.
    if _payload_data_valid:
        _latest_payload_position = _payload_track.get_latest_state()
        _payload_placemark = new_placemark(_latest_payload_position['lat'],
                                            _latest_payload_position['lon'],
                                            _latest_payload_position['alt'],
                                            name="" if no_labels else "Payload",
                                            absolute=absolute_tracks,
                                            icon="http://maps.google.com/mapfiles/kml/shapes/track.png",
                                            heading=_latest_payload_position['heading'])
        _payload_track_ls = flight_path_to_geometry(_payload_track.to_line_string(),
                                            name="Flight Path",
                                            absolute=absolute_tracks)
        _geom_data.append(_payload_placemark)
        _geom_data.append(_payload_track_ls)

    # Generate Car Position Data.
    if _car_data_valid:
        _latest_car_position = _car_track.get_latest_state()
        _car_placemark = new_placemark(_latest_car_position['lat'],
                                            _latest_car_position['lon'],
                                            _latest_car_position['alt'],
                                            name="" if no_labels else "Car",
                                            absolute=absolute_tracks,
                                            icon="http://maps.google.com/mapfiles/kml/shapes/track.png",
                                            heading=_latest_car_position['heading'])
        _car_track_ls = flight_path_to_geometry(_car_track.to_line_string(),
                                            name="Car Track",
                                            absolute=absolute_tracks)
        _geom_data.append(_car_placemark)
        _geom_data.append(_car_track_ls)

    return generate_kml(_geom_data)


# These callbacks pass data on to the different GenericTrack objects, for plotting on demand.
def ozi_listener_callback(data):
    ''' Handle a telemetry dictionary from an OziListener Object '''
    global _payload_track, _payload_data_valid
    # Already in the right format, pass it into the payload_track object.
    _state = _payload_track.add_telemetry(data)
    _payload_data_valid = True
    print(data)


def udp_listener_summary_callback(data):
    ''' Handle a Payload Summary Message from UDPListener '''
    global _payload_track, _payload_data_valid
    # Extract the fields we need.
    print("SUMMARY:" + str(data))
    _lat = data['latitude']
    _lon = data['longitude']
    _alt = data['altitude']
    _comment = data['callsign']

    # Process the 'short time' value if we have been provided it.
    if 'time' in data.keys():
        _full_time = datetime.utcnow().strftime("%Y-%m-%dT") + data['time'] + "Z"
        _time_dt = parse(_full_time)
    else:
        # Otherwise use the current UTC time.
        _time_dt = datetime.utcnow()

    _payload_position_update = {
        'time'  :   _time_dt,
        'lat'   :   _lat,
        'lon'   :   _lon,
        'alt'   :   _alt,
        'comment':  _comment
    }
    
    _payload_track.add_telemetry(_payload_position_update)
    _payload_data_valid = True


def udp_listener_car_callback(data):
    ''' Handle car position data '''
    global _car_track, _car_data_valid
    print("CAR:" + str(data))
    _lat = data['latitude']
    _lon = data['longitude']
    _alt = data['altitude']
    _comment = "Car"
    _time_dt = datetime.utcnow()

    _car_position_update = {
        'time'  :   _time_dt,
        'lat'   :   _lat,
        'lon'   :   _lon,
        'alt'   :   _alt,
        'comment':  _comment
    }

    _car_track.add_telemetry(_car_position_update)
    _car_data_valid = True



if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--ozimux", action="store_true", default=False, help="Take payload input via OziMux (listen on port 8942).")
    group.add_argument("--summary", action="store_true", default=False, help="Take payload input data via Payload Summary Broadcasts.")
    parser.add_argument("--clamp", action="store_false", default=True, help="Clamp all tracks to ground.")
    parser.add_argument("--nolabels", action="store_true", default=False, help="Inhibit labels on placemarks.")
    parser.add_argument("--predict", action="store_true", help="Enable Flight Path Predictions.")
    parser.add_argument("--burst_alt", type=float, default=30000.0, help="Expected Burst Altitude.")
    parser.add_argument("--descent_rate", type=float, default=5.0, help="Expected Descent Rate (m/s)")
    args = parser.parse_args()

    # Set some global variables
    absolute_tracks = args.clamp
    no_labels = args.nolabels
    burst_alt = args.burst_alt
    descent_rate = math.fabs(args.descent_rate)

    # Start up OziMux Listener Callback, if enabled.
    if args.ozimux:
        print("Using OziMux Data.")
        _listener = OziListener(telemetry_callback=ozi_listener_callback)

    # Start up UDP Broadcast Listener (which we use for car positions even if not for the payload)
    if args.summary:
        print("Using Payload Summary Messages.")
        _broadcast_listener = UDPListener(summary_callback=udp_listener_summary_callback,
                                            gps_callback=udp_listener_car_callback)
    else:
        _broadcast_listener = UDPListener(summary_callback=None,
                                            gps_callback=udp_listener_car_callback)

    _broadcast_listener.start()

    # Start the Flask application.
    app.run()

    # Clean up threads.
    try:
        _listener.close()
        _broadcast_listener.close()
    except:
        pass
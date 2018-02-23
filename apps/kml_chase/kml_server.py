#!/usr/bin/env python

import time, argparse, math, traceback, json
from datetime import datetime
from dateutil.parser import parse
from horuslib.listener import OziListener, UDPListener
from horuslib.geometry import *
from shapely.geometry import Point, LineString, asShape, mapping
from flask import Flask
from threading import Thread

# Create flask app
app = Flask(__name__, static_url_path='')

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
_run_abort_prediction = False
burst_alt = 30000.0
descent_rate = 5.0
last_prediction = 0
prediction_rate = 15
_flight_prediction = []
_flight_prediction_valid = False
_abort_prediction = []
_abort_prediction_valid = False


# FLASK Server Functions
# Route / to index.html in static/
@app.route('/')
def server_index():
    return app.send_static_file('index.html')

@app.route('/payload.json')
def serve_geojson_payload():
    ''' Generate a GeoJSON blob containing the track data '''
    global _payload_track, _payload_data_valid

    #return json.dumps({'features':[{'geometry':null, 'type':'Feature', 'properties':{'name':'Payload Track'}}]})

    if _payload_data_valid == False:
        return json.dumps({})

    # Otherwise, compile a Feature containing the track and latest position.
    _latest = _payload_track.get_latest_state()
    _latest_point = Point(_latest['lon'], _latest['lat'], _latest['alt'])

    _payload_mapping = mapping(_payload_track.to_line_string())

    _features = {'features':[{  'geometry': mapping(_payload_track.to_line_string()),
                                'type': 'Feature',
                                'properties': {
                                    'name': 'Payload Track'
                                }}]}

    return json.dumps(_features)

@app.route('/prediction.json')
def serve_geojson_prediction():
    ''' Generate a GeoJSON blob containing the flight prediction data '''
    global _flight_prediction, _flight_prediction_valid

    if _flight_prediction_valid == False:
        return json.dumps({})

    # Otherwise, compile a Feature containing the track and latest position.
    _pred_ls = flight_path_to_linestring(_flight_prediction)


    _features = {'features':[{  'geometry': mapping(_pred_ls),
                                'type': 'Feature',
                                'properties': {
                                    'name': 'Flight Prediction'
                                }}]}

    return json.dumps(_features)


# On request, generate a KML File based on the above datasets.
@app.route('/track.kml')
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
                                            absolute=absolute_tracks,
                                            track_color="ab02ff00")
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


    if _flight_prediction_valid:
        _flight_pred_ls = flight_path_to_linestring(_flight_prediction)
        _flight_pred_geom = flight_path_to_geometry(_flight_pred_ls,
                                            name="Prediction",
                                            absolute=absolute_tracks,
                                            track_color="ab0073ff")
        _geom_data.append(_flight_pred_geom)

    if _abort_prediction_valid:
        _abort_pred_ls = flight_path_to_linestring(_abort_prediction)
        _abort_pred_geom = flight_path_to_geometry(_abort_pred_ls,
                                            name="Abort Prediction",
                                            absolute=absolute_tracks,
                                            track_color="ab0009ff")
        _geom_data.append(_abort_pred_geom)

    return generate_kml(_geom_data)


def run_prediction():
    ''' Run a Flight Path prediction '''
    global _predictor, _payload_track, descent_rate, burst_alt, _flight_prediction, _flight_prediction_valid, _run_abort_prediction
    global _abort_prediction, _abort_prediction_valid

    if _predictor == None:
        return

    _current_pos = _payload_track.get_latest_state()
    _current_pos_list = [0,_current_pos['lat'], _current_pos['lon'], _current_pos['alt']]

    if _current_pos['is_descending']:
        _desc_rate = _current_pos['landing_rate']
    else:
        _desc_rate = descent_rate

    if _current_pos['alt'] > burst_alt:
        _burst_alt = _current_pos['alt'] + 100
    else:
        _burst_alt = burst_alt

    print("Running Predictor... ")
    _pred_path = _predictor.predict(
            launch_lat=_current_pos['lat'],
            launch_lon=_current_pos['lon'],
            launch_alt=_current_pos['alt'],
            ascent_rate=_current_pos['ascent_rate'],
            descent_rate=_desc_rate,
            burst_alt=_burst_alt,
            launch_time=_current_pos['time'],
            descent_mode=_current_pos['is_descending'])

    if len(_pred_path) > 1:
        _pred_path.insert(0,_current_pos_list)
        _flight_prediction = _pred_path
        _flight_prediction_valid = True
        print("Prediction Updated, %d points." % len(_pred_path))
    else:
        print("Prediction Failed.")

    if _run_abort_prediction and (_current_pos['alt'] < burst_alt) and (_current_pos['is_descending'] == False):
        print("Running Abort Prediction... ")
        _pred_path = _predictor.predict(
                launch_lat=_current_pos['lat'],
                launch_lon=_current_pos['lon'],
                launch_alt=_current_pos['alt'],
                ascent_rate=_current_pos['ascent_rate'],
                descent_rate=_desc_rate,
                burst_alt=_current_pos['alt']+200,
                launch_time=_current_pos['time'])

        if len(_pred_path) > 1:
            _pred_path.insert(0,_current_pos_list)
            _abort_prediction = _pred_path
            _abort_prediction_valid = True
            print("Abort Prediction Updated, %d points." % len(_pred_path))
        else:
            print("Prediction Failed.")
    else:
        _abort_prediction_valid = False

    # If have been asked to run an abort prediction, but we are descent, set the is_valid
    # flag to false, so the abort prediction is not plotted.
    if _run_abort_prediction and _current_pos['is_descending']:
        _abort_prediction_valid == False


def spawn_predictor():
    global last_prediction, prediction_rate
    if (time.time() - last_prediction) >= prediction_rate:
        last_prediction = time.time()
        pred_thread = Thread(target=run_prediction)
        pred_thread.start()


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

    spawn_predictor()


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
    parser.add_argument("--predict_binary", type=str, default="./pred", help="Location of the CUSF predictor binary. Defaut = ./pred")
    parser.add_argument("--burst_alt", type=float, default=30000.0, help="Expected Burst Altitude (m). Default = 30000")
    parser.add_argument("--descent_rate", type=float, default=5.0, help="Expected Descent Rate (m/s, positive value). Default = 5.0")
    parser.add_argument("--abort", action="store_true", default=False, help="Enable 'Abort' Predictions.")
    parser.add_argument("--predict_rate", type=int, default=15, help="Run predictions every X seconds. Default = 15 seconds.")
    args = parser.parse_args()

    # Set some global variables
    absolute_tracks = args.clamp
    no_labels = args.nolabels
    burst_alt = args.burst_alt
    descent_rate = math.fabs(args.descent_rate)
    _run_abort_prediction = args.abort
    prediction_rate = args.predict_rate

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

    if args.predict:
        try:
            from cusfpredict.predict import Predictor
            _predictor = Predictor(bin_path=args.predict_binary, gfs_path='./gfs')
        except:
            print("Loading Predictor failed.")
            traceback.print_exc()
            _predictor = None


    # Start the Flask application.
    app.run()

    # Clean up threads.
    try:
        _broadcast_listener.close()
        _listener.close()
    except:
        pass
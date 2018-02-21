#!/usr/bin/env python2.7
#
#   Project Horus - Flight Data to Geometry
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#
import traceback
import logging
import fastkml
import numpy as np
from .atmosphere import *
from .earthmaths import position_info
from shapely.geometry import Point, LineString


class GenericTrack(object):
    """
    A Generic 'track' object, which stores track positions for a payload or chase car.
    Telemetry is added using the add_telemetry method, which takes a dictionary with time/lat/lon/alt keys (at minimum).
    This object performs a running average of the ascent/descent rate, and calculates the predicted landing rate if the payload
    is in descent.
    The track history can be exported to a LineString using the to_line_string method.
    """

    def __init__(self,
        ascent_averaging = 6,
        landing_rate = 5.0):
        ''' Create a GenericTrack Object. '''

        # Averaging rate.
        self.ASCENT_AVERAGING = ascent_averaging
        # Payload state.
        self.landing_rate = landing_rate
        self.ascent_rate = 5.0
        self.is_descending = False

        # Internal store of track history data.
        # Data is stored as a list-of-lists, with elements of [datetime, lat, lon, alt, comment]
        self.track_history = []


    def add_telemetry(self,data_dict):
        ''' 
        Accept telemetry data as a dictionary with fields 
        datetime, lat, lon, alt, comment
        '''

        try:
            _datetime = data_dict['time']
            _lat = data_dict['lat']
            _lon = data_dict['lon']
            _alt = data_dict['alt']
            if 'comment' in data_dict.keys():
                _comment = data_dict['comment']
            else:
                _comment = ""

            self.track_history.append([_datetime, _lat, _lon, _alt, _comment])
            self.update_states()
            return self.get_latest_state()
        except:
            logging.error("Error reading input data: %s" % traceback.format_exc())


    def get_latest_state(self):
        ''' Get the latest position of the payload '''

        if len(self.track_history) == 0:
            return None
        else:
            _latest_position = self.track_history[-1]
            _state = {
                'time'  : _latest_position[0],
                'lat'   : _latest_position[1],
                'lon'   : _latest_position[2],
                'alt'   : _latest_position[3],
                'ascent_rate': self.ascent_rate,
                'is_descending': self.is_descending,
                'landing_rate': self.landing_rate,
                'heading': self.heading
            }
            return _state


    def calculate_ascent_rate(self):
        ''' Calculate the ascent/descent rate of the payload based on the available data '''
        if len(self.track_history) <= 1:
            return 5.0
        elif len(self.track_history) == 2:
            # Basic ascent rate case - only 2 samples.
            _time_delta = (self.track_history[-1][0] - self.track_history[-2][0]).total_seconds()
            _altitude_delta = self.track_history[-1][3] - self.track_history[-2][3]
            return _altitude_delta/_time_delta

        else:
            _num_samples = min(len(self.track_history), self.ASCENT_AVERAGING)
            _asc_rates = []

            for _i in range(-1*(_num_samples-1), 0):
                _time_delta = (self.track_history[_i][0] - self.track_history[_i-1][0]).total_seconds()
                _altitude_delta = self.track_history[_i][3] - self.track_history[_i-1][3]
                _asc_rates.append(_altitude_delta/_time_delta)

            return np.mean(_asc_rates)

    def calculate_heading(self):
        ''' Calculate the heading of the payload '''
        if len(self.track_history) <= 1:
            return 0.0
        else:
            _pos_1 = self.track_history[-2]
            _pos_2 = self.track_history[-1]

            _pos_info = position_info((_pos_1[1],_pos_1[2],_pos_1[3]), (_pos_2[1],_pos_2[2],_pos_2[3]))

            return _pos_info['bearing']


    def update_states(self):
        ''' Update internal states based on the current data '''
        self.ascent_rate = self.calculate_ascent_rate()
        self.heading = self.calculate_heading()
        self.is_descending = self.ascent_rate < 0.0

        if self.is_descending:
            _current_alt = self.track_history[-1][3]
            self.landing_rate = seaLevelDescentRate(self.ascent_rate, _current_alt)


    def to_line_string(self):
        ''' Generate and return a LineString object representation of the track history '''

        # Copy array into a numpy representation for easier slicing.
        if len(self.track_history) == 0:
            return None
        elif len(self.track_history) == 1:
            # LineStrings need at least 2 points. If we only have a single point,
            # fudge it by duplicating the single point.
            _track_data_np = np.array([self.track_history[0], self.track_history[0]])
        else:
            _track_data_np = np.array(self.track_history)
        # Produce new array with required ordering: lon, lat, alt (thanks KML...)
        _track_points = np.column_stack((_track_data_np[:,2], _track_data_np[:,1], _track_data_np[:,3]))

        return LineString(_track_points.tolist())


# Geometry-to-KML methods
ns = '{http://www.opengis.net/kml/2.2}'

def flight_path_to_linestring(flight_path):
    ''' Convert a predicted flight path to a LineString geometry object '''

    track_points = []
    for _point in flight_path:
        # Flight path array is in lat,lon,alt order, needs to be in lon,lat,alt
        track_points.append([_point[2],_point[1],_point[3]])

    return LineString(track_points)



def flight_path_to_geometry(flight_path,
    placemark_id="Flight Path ID",
    name="Flight Path Name",
    track_color="aaffffff",
    poly_color="20000000",
    track_width=2.0,
    absolute = True,
    extrude = True,
    tessellate = True):
    ''' Produce a fastkml geometry object from a flight path LineString (i.e. exported from above) '''

    # Handle selection of absolute altitude mode
    if absolute:
        _alt_mode = 'absolute'
    else:
        _alt_mode = 'clampToGround'

    # Define the Line and Polygon styles, which are used for the flight path, and the extrusions (if enabled)
    flight_track_line_style = fastkml.styles.LineStyle(
        ns=ns,
        color=track_color,
        width=track_width)

    flight_extrusion_style = fastkml.styles.PolyStyle(
        ns=ns,
        color=poly_color)

    flight_track_style = fastkml.styles.Style(
        ns=ns,
        styles=[flight_track_line_style, flight_extrusion_style])

    # Generate the Placemark which will contain the track data.
    flight_line = fastkml.kml.Placemark(
        ns=ns,
        id=placemark_id,
        name=name,
        styles=[flight_track_style])

    # Add the track data to the Placemark
    flight_line.geometry = fastkml.geometry.Geometry(
        ns=ns,
        geometry=flight_path,
        altitude_mode=_alt_mode,
        extrude=extrude,
        tessellate=tessellate)

    return flight_line



def new_placemark(lat, lon, alt,
    placemark_id="Placemark ID",
    name="Placemark Name",
    absolute = False,
    icon = "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png",
    scale = 1.0,
    heading = 0):
    """ Generate a generic placemark object """

    if absolute:
        _alt_mode = 'absolute'
    else:
        _alt_mode = 'clampToGround'

    flight_icon_style = fastkml.styles.IconStyle(
        ns=ns, 
        icon_href=icon, 
        scale=scale,
        heading=heading)

    flight_style = fastkml.styles.Style(
        ns=ns,
        styles=[flight_icon_style])

    flight_placemark = fastkml.kml.Placemark(
        ns=ns, 
        id=placemark_id,
        name=name,
        description="",
        styles=[flight_style])

    flight_placemark.geometry = fastkml.geometry.Geometry(
        ns=ns,
        geometry=Point(lon, lat, alt),
        altitude_mode=_alt_mode)

    return flight_placemark


def generate_kml(geom_objects,
                comment=""):
    """ Generate a KML file from a list of geometry objects. """

    kml_root = fastkml.kml.KML()
    kml_doc = fastkml.kml.Document(
        ns=ns,
        name=comment)

    if type(geom_objects) is not list:
        geom_objects = [geom_objects]

    for _flight in geom_objects:
        kml_doc.append(_flight)

    return kml_doc.to_string()



def write_kml(geom_objects,
                filename="output.kml",
                comment=""):
    """ Write out flight path geometry objects to a kml file. """

    with open(filename,'w') as kml_file:
        kml_file.write(generate_kml(geom_objects,comment))
        kml_file.close()

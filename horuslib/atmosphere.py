#!/usr/bin/env python2.7
#
#   Project Horus - Atmosphere / Descent Rate Modelling
#
#	Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#	Released under GNU GPL v3 or later
#
import math

def getDensity(altitude):
	''' 
	Calculate the atmospheric density for a given altitude in metres.
	This is a direct port of the oziplotter Atmosphere class
	'''

	#Constants
	airMolWeight = 28.9644 	# Molecular weight of air
	densitySL = 1.225 	# Density at sea level [kg/m3]
	pressureSL = 101325  	# Pressure at sea level [Pa]
	temperatureSL = 288.15 	# Temperature at sea level [deg K]
	gamma = 1.4
	gravity	= 9.80665	# Acceleration of gravity [m/s2]
	tempGrad = -0.0065	# Temperature gradient [deg K/m]
	RGas = 8.31432 	# Gas constant [kg/Mol/K]
	R = 287.053  
	deltaTemperature = 0.0; 

	# Lookup Tables
	altitudes = [0, 11000, 20000, 32000, 47000, 51000, 71000, 84852]
	pressureRels = [1, 2.23361105092158e-1, 5.403295010784876e-2, 8.566678359291667e-3, 1.0945601337771144e-3, 6.606353132858367e-4, 3.904683373343926e-5, 3.6850095235747942e-6]
	temperatures = [288.15, 216.65, 216.65, 228.65, 270.65, 270.65, 214.65, 186.946]
	tempGrads = [-6.5, 0, 1, 2.8, 0, -2.8, -2, 0]
	gMR = gravity * airMolWeight / RGas;

	# Pick a region to work in
	i = 0
	if(altitude > 0):
		while (altitude > altitudes[i+1]):
			i = i + 1
	

	# Lookup based on region
	baseTemp = temperatures[i]
	tempGrad = tempGrads[i] / 1000.0
	pressureRelBase	= pressureRels[i]
	deltaAltitude = altitude - altitudes[i]
	temperature	= baseTemp + tempGrad * deltaAltitude

	# Calculate relative pressure
	if(math.fabs(tempGrad) < 1e-10):
		pressureRel = pressureRelBase * math.exp(-1 *gMR * deltaAltitude / 1000.0 / baseTemp)
	else:
		pressureRel = pressureRelBase * math.pow(baseTemp / temperature, gMR / tempGrad / 1000.0)
	

	# Add temperature offset
	temperature = temperature + deltaTemperature

	# Finally, work out the density...
	speedOfSound = math.sqrt(gamma * R * temperature)
	pressure = pressureRel * pressureSL
	density = densitySL * pressureRel * temperatureSL / temperature

	return density

def seaLevelDescentRate(descent_rate, altitude):
	''' Calculate the descent rate at sea level, for a given descent rate at altitude '''

	rho = getDensity(altitude)
	return math.sqrt((rho / 1.22) * math.pow(descent_rate, 2))


if __name__ == '__main__':
	# Test Cases
	_altitudes = [1000, 10000, 30000, 1000, 10000, 30000]
	_rates = [-10.0, -10.0, -10.0, -30.0, -30.0, -30.0]

	for i in range(len(_altitudes)):
		print("Altitude: %d m,  Rate: %.2f m/s" % (_altitudes[i], _rates[i]))
		print("Density: %.5f" % getDensity(_altitudes[i]))
		print("Sea Level Descent Rate: %.2f m/s" % seaLevelDescentRate(_rates[i], _altitudes[i]))
		print("")

Project Horus - Ground Station & Chase Car Utilities for High Altitude Balloon Tracking
=======================================================================================

This repository contains various libraries & utilities used for:

* Routing of payload telemetry data from various data sources into the [OziPlotter offline mapping & prediction system.](https://github.com/projecthorus/oziplotter)
* Uploading of chase-car positions & payload telemetry to the [Habitat Tracker](https://tracker.habhub.org/)
* Handling of telemetry data from the Project Horus LoRa ['Mission Control'](https://github.com/projecthorus/FlexTrack-Horus) high-altitude balloon payload.

In the context of this repository, the term 'telemetry' generally refers to position (latitude/longitude/altitude) data from a high-altitude balloon payload, but can also include command & control messages, for example those send to/from the mission control payload.

In essence, these utilities provide the 'glue' that connects the telemetry sources (LoRa receivers, fldigi, radiosonde receivers) with the mapping applications (OziPlotter, Habitat).

The main use-cases for these utilities are:
* Management of telemetry on a High Altitude Balloon Chase-Car PC
* Headless reception of Mission Control Payload telemetry using a Raspberry Pi.

All the applications mentioned within this documentation are provided as Python scripts (within the `apps` directory), which are (mostly) cross-platform.

Related repositories include [radiosonde_auto_rx](https://github.com/projecthorus/radiosonde_auto_rx) (a source of payload telemetry data, in this case from radiosondes), and [OziPlotter](https://github.com/projecthorus/oziplotter) (for offline mapping of payload positions).

Refer to the [wiki pages](https://github.com/projecthorus/horus_utils/wiki) for further documentation.
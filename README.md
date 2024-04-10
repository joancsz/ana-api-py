# ANA Data Access Class

This Python class, ANA, provides functionality to access data from the HidroWeb system provided by the Brazilian National Water Agency (ANA). It facilitates retrieving various types of hydrological data including river information, station information, and time series data.

## Installation

To use this class, simply clone the repository and import the `ANA` class into your Python scripts. Ensure you have Python installed on your system.

```bash
git clone https://github.com/joancsz/ana-api-py.git
```
## Environment 

To be able to run the code you will need to install both requests and pandas libraries.

```bash
pip install requests pandas
```
If you are using conda:

```bash
conda install requests pandas
```
It is important to note that you'll need at least Python 3.8 and pandas 1.3 to be able to use this code.

## Usage

Here's a basic example of how to use the ANA class to access data:

```python
from src.ana_api import ANA

# Create an instance of the ANA class
ana = ANA()

# List all rivers
rivers_df = ana.list_rivers()
print("List of Rivers:")
print(rivers_df)

# List all states
states_df = ana.list_states()
print("List of States:")
print(states_df)

# List all telemetric stations
telemetric_stations_df = ana.list_telemetric_stations()
print("List of Telemetric Stations:")
print(telemetric_stations_df)

# Get time series data for a specific station
station_code = '47000'  # Example station code
time_series_df = ana.get_station_time_series(station_code, data_info='P')
print("Precipitation Time Series Data for Station:")
print(time_series_df)
```

## Functionality

The ANA class provides methods to:

- List rivers.
- List states.
- List telemetric stations.
- Get information about stations based on various criteria.
- Get time series data for a specific station.

For detailed usage instructions and parameter descriptions, refer to the method docstrings in the source code.

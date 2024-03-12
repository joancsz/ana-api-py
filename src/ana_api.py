import requests
import xml.etree.ElementTree as et
import pandas as pd

from error.error import NotFoundError

class ANA:

    url = "http://telemetriaws1.ana.gov.br/ServiceANA.asmx"

    def __init__(self) -> None:
        self.base_url = ANA.url

    def list_all_stations(self, station_code:str = '', station_type:str = '',
                           station_data:str = '', state:str = '',
                           agent_in_charge:str = '', river_name:str = '') -> pd.DataFrame:
        """
        Method that returns all the stations

        Parameters
        station_code:str
            Eight digit code of the station, unique identifier (Ex: 00047000, 90300000)
        station_type:str
            Type of the station, can be either F for fluviometric stations and P for pluviometric stations, if not passed returns all
        station_data:str
            Data gathering type of the station, can be either T for telemetric stations and M for manual stations, if not passed returns all
        state:str
            State where the stations are located
        agent_in_charge:str
            Agent responsible for the station
        river_name:str
            Name of the river that the station is located

        Returns
            Pandas Dataframe with stations information
        """ 
        station_code = str(station_code) if type(station_code) == int else station_code
        if len(station_code) < 8:
            station_code = (8 - len(station_code)) * '0' + station_code
        if not station_data == '' and station_data in ['F','P']:
            station_data = '1' if station_data == 'F' else '2'
        else:
            station_data = ''

        if not station_type == '' and station_type in ['T','M']:
            station_type = '1' if station_type == 'T' else '0'
        else:
            station_type = ''

        url = f"{self.base_url}/HidroInventario?codEstDE={station_code}&codEstATE=&tpEst={station_data}&nmEst=&nmRio={river_name}&codSubBacia=&codBacia=&nmMunicipio=&nmEstado={state}&sgResp={agent_in_charge}&sgOper=&telemetrica={station_type}"
        response = requests.get(url=url)

        if response.status_code == 404:
            raise NotFoundError("Response <404>: File was not found in the url")
        
        tree = et.ElementTree(et.fromstring(response.content))
        root = tree.getroot()

        stations_list = []
        for station in root.iter("Table"):
            data = {
                'codigo': [station.find("Codigo").text],
                'nome': [station.find("Nome").text],
                'latitude': [station.find('Latitude').text],
                'longitude': [station.find('Longitude').text],
                'altitude': [station.find('Altitude').text],
                'area': [station.find('AreaDrenagem').text],
                'estado': [station.find('nmEstado').text],
                'municipio': [station.find('nmMunicipio').text],
                'rio': [station.find('RioNome').text],
                'tipo': [station.find('TipoEstacao').text],
                'responsavel': [station.find('ResponsavelSigla').text],
                'ultima_alteracao':[station.find('UltimaAtualizacao').text],
                'inicio_telemetria':[station.find('PeriodoTelemetricaInicio').text],
                "fim_telemetria": [station.find("PeriodoTelemetricaFim").text]
            }
            df = pd.DataFrame.from_dict(data)
            df = df.set_index('codigo', drop=True)
            stations_list.append(df)

        request_df = pd.concat(stations_list)
        return request_df             


        




import requests
import xml.etree.ElementTree as et
import pandas as pd

from error.error import NotFoundError

class ANA:

    url = "http://telemetriaws1.ana.gov.br/ServiceANA.asmx"

    def __init__(self) -> None:
        self.base_url = ANA.url

    def list_rivers(self, river_code: str = '') -> pd.DataFrame:
        """
        Method that returns all rivers

        Parameters
        ----------
        river_code : str
            Eight digit code of the station, unique identifier (Ex: 00047000, 90300000)

        Returns
        -------
        Pandas DataFrame with states
        """
        url = f"{self.base_url}/HidroRio?codRio={river_code}"
        response = requests.get(url=url)
        
        df = pd.read_xml(response.content, xpath=".//Table")
        
        df = df.rename(columns={
            "Nome": "nome",
            "Codigo": "codigo_rio",
            "BaciaCodigo": "codigo_bacia",
            "SubBaciaCodigo": "codigo_sub_bacia"
        })
        df = df[['nome','codigo_rio','codigo_bacia','codigo_sub_bacia']]
        df = df.set_index('nome', drop=True)
        return df
    
    def list_states(self, state_code:str = '') -> pd.DataFrame:
        """
        Method that returns all states

        Parameters
        state_code:str
            State unique code

        Returns
            Pandas Dataframe with states
        """
        url = f"{self.base_url}/HidroEstado?codUf={state_code}"
        response = requests.get(url=url)

        df = pd.read_xml(response.content, xpath=".//Table")
        
        df = df.rename(columns={
            "Nome": "nome",
            "Sigla": "sigla",
            "Codigo": "codigo",
            "CodigoIBGE": "codigo_IGBE"
        })
        df = df[['nome','codigo_rio','codigo_bacia','codigo_sub_bacia']]
        df = df.set_index('nome', drop=True)
        return df
    
    def list_stations(self, station_code:str = '', station_type:str = '',
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
        if len(station_code) < 8 and station_code != '':
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
        
        df = pd.read_xml(response.content, xpath=".//Table")
        
        df = df.rename(columns={
            "Codigo": "codigo",
            "Nome": "nome",
            "Latitude": "latitude",
            "Longitude": "longitude",
            "Altitude": "altitude",
            "AreaDrenagem": "area",
            "nmEstado": "estado",
            "nmMunicipio": "municipio",
            "RioNome": "rio",
            "TipoEstacao": "tipo",
            "ResponsavelSigla": "responsavel",
            "UltimaAtualizacao": "ultima_atualização",
            "PeriodoTelemetricaInicio": "inicio_telemetria",
            "PeriodoTelemetricaFim": "fim_telemetria",
        })
        df = df[['codigo','nome','latitude','longitude', 'altitude', 'area', 'estado', 'municipio', 'rio', 'tipo', 'responsavel', 'ultima_atualização', 'inicio_telemetria', 'fim_telemetria']]
        df = df.set_index('nome', drop=True)

        return df             


        




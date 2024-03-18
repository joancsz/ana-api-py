import requests
import pandas as pd
import datetime
from typing import Optional, Union, Literal

from error.error import *


class ANA:

    url = "http://telemetriaws1.ana.gov.br/ServiceANA.asmx"

    def __init__(self) -> None:
        self.base_url = ANA.url

    def list_rivers(self, river_code: Optional[str] = "") -> pd.DataFrame:
        """
        Method that returns all rivers

        Parameters
        ----------
        river_code : str
            Eight digit code of the station, unique identifier (Ex: 00047000, 90300000)

        Returns
        -------
        Pandas DataFrame with river
        """
        url = f"{self.base_url}/HidroRio?codRio={river_code}"
        response = requests.get(url=url)

        ResponseApiCheck(response)

        df = pd.read_xml(response.content, xpath=".//Table")
        df = df[["Nome", "Codigo", "BaciaCodigo", "SubBaciaCodigo"]]
        df = df.set_index("nome", drop=True)
        return df

    def list_states(self, state_code: Optional[str] = "") -> pd.DataFrame:
        """
        Method that returns all states

        Parameters
        ----------
        state_code:str
            State unique code

        Returns
        -------
            Pandas Dataframe with states
        """
        url = f"{self.base_url}/HidroEstado?codUf={state_code}"
        response = requests.get(url=url)

        ResponseApiCheck(response)

        df = pd.read_xml(response.content, xpath=".//Table")
        df = df[["Nome", "Sigla", "Codigo", "CodigoIBGE"]]
        df = df.set_index("Nome", drop=True)
        return df

    def list_telemetric_stations(self, active: Optional[bool] = "") -> pd.DataFrame:
        """
        Method that returns all the stations

        Parameters
        ----------
        active:bool
             If the station is active or inactive, if not passed returns all

        Returns
        -------
            Pandas Dataframe with telemetric stations
        """
        if active != "" and active == type(bool) or active in [0, 1]:
            active = 0 if active == True else 1
        else:
            active = ""

        url = (
            f"{self.base_url}/ListaEstacoesTelemetricas?statusEstacoes={active}&origem="
        )
        response = requests.get(url=url)

        ResponseApiCheck(response)

        df = pd.read_xml(response.content, xpath=".//Table")
        df = df[
            [
                "NomeEstacao",
                "CodEstacao",
                "Bacia",
                "SubBacia",
                "Operadora",
                "Responsavel",
                "Municipio-UF",
                "Latitude",
                "Longitude",
                "Altitude",
                "CodRio",
                "NomeRio",
                "Origem",
                "StatusEstacao",
            ]
        ]

        df = df.set_index("NomeEstacao", drop=True)
        return df

    def list_stations(
        self,
        station_code: Optional[Union[str, int]] = "",
        station_type: Optional[Literal["F", "P"]] = "",
        state: Optional[str] = "",
        agent_in_charge: Optional[str] = "",
        river_name: Optional[str] = "",
        telemetric: Optional[bool] = "",
    ) -> pd.DataFrame:
        """
        Method that returns all the stations

        Parameters
        ----------
        station_code: Union[str, int]
            Eight digit code of the station, unique identifier (Ex: 00047000, 90300000)
        station_type: str
            Type of the station, can be either F for fluviometric stations and P for pluviometric stations, if not passed returns all
        state: str
            State where the stations are located
        agent_in_charge: str
            Agent responsible for the station
        river_name: str
            Name of the river that the station is located
        telemetric: bool
            Data gathering type of the station, can be either T for telemetric stations and M for manual stations, if not passed returns all
        Returns
        -------
            Pandas Dataframe with stations information
        """
        if not station_type == "" and station_type in ["F", "P"]:
            station_type = "1" if station_type == "F" else "2"
        else:
            station_type = ""

        if telemetric != "" and telemetric == type(bool) or telemetric in [0, 1]:
            telemetric = 0 if telemetric == True else 1
        else:
            telemetric = ""

        url = f"{self.base_url}/HidroInventario?codEstDE={station_code}&codEstATE=&tpEst={station_type}&nmEst=&nmRio={river_name}&codSubBacia=&codBacia=&nmMunicipio=&nmEstado={state}&sgResp={agent_in_charge}&sgOper=&telemetrica={telemetric}"
        response = requests.get(url=url)

        ResponseApiCheck(response)

        df = pd.read_xml(response.content, xpath=".//Table")
        df = df[
            [
                "Codigo",
                "Nome",
                "Latitude",
                "Longitude",
                "Altitude",
                "AreaDrenagem",
                "nmEstado",
                "nmMunicipio",
                "RioNome",
                "TipoEstacao",
                "ResponsavelSigla",
                "UltimaAtualizacao",
                "PeriodoTelemetricaInicio",
                "PeriodoTelemetricaFim",
            ]
        ]
        date_columns = [
            "UltimaAtualizacao",
            "PeriodoTelemetricaInicio",
            "PeriodoTelemetricaFim",
        ]
        df[date_columns] = pd.to_datetime(df[date_columns])
        df = df.set_index("Nome", drop=True)

        return df

    def get_station_time_series(
        self,
        station_code: str,
        data_info: Literal["P", "I", "L"],
        process_level: Optional[Literal["R", "P"]] = "",
        start_date: Optional[Union[str, datetime.date, pd.Timestamp]] = "",
        end_date: Optional[Union[str, datetime.date, pd.Timestamp]] = "",
    ) -> pd.DataFrame:
        """
        Parameters
        ----------

        start_date: Union[str, datetime.date, pd.Timestamp]
            Start of the period, string date in format YYYY-MM-DD. Datetime and Timestamp objects can be passed, if not passed returns from the first date
        end_date: Union[str, datetime.date, pd.Timestamp]
            End of the period, string date in format YYYY-MM-DD. Datetime and Timestamp objects can be passed, if not passed returns until the end
        station_code: str
            Eight digit code of the station, unique identifier (Ex: 00047000, 90300000)
        data_info: Literal["P", "I", "L"]
            Data needed for the station, 'P' for Precipitation, 'I' for Inflows and 'L' for Level
        process_level: Literal["R", "P"]
            Level of consistensy of the data, can either be 'R' for Raw and 'P' for processed, if not passed returns all

        Returns
        -------
            Pandas dataframe with all the information avaiable in the station for the desired period
        """

        if type(start_date) == datetime.date or type(start_date) == pd.Timestamp:
            start_date = start_date.strftime("%Y-%m-%d")
        if type(end_date) == datetime.date or type(end_date) == pd.Timestamp:
            end_date = end_date.strftime("%Y-%m-%d")

        if data_info.upper() == "L":
            data_info = 1
        elif data_info.upper() == "I":
            data_info = 3
        else:
            data_info = 2
        process_level = 1 if process_level.upper() == "R" else 2

        url = f"{self.base_url}/HidroSerieHistorica?codEstacao={station_code}&dataInicio={start_date}&dataFim={end_date}&tipoDados={data_info}&nivelConsistencia={process_level}"

        response = requests.get(url=url)
        
        ResponseApiCheck(response)

        df = pd.read_xml(response.content, xpath=".//SerieHistorica")
        if data_info == 1:
            columns = [
                "EstacaoCodigo", "NivelConsistencia", "DataHora",
                "MediaDiaria", "Maxima", "Minima",
                "Media", "DiaMaxima", "DiaMinima",
                "Cota01", "Cota02", "Cota03",
                "Cota04", "Cota05", "Cota06",
                "Cota07", "Cota08", "Cota09",
                "Cota10", "Cota11", "Cota12",
                "Cota13", "Cota14", "Cota15",
                "Cota16", "Cota17", "Cota18",
                "Cota19", "Cota20", "Cota21",
                "Cota22", "Cota23", "Cota24",
                "Cota25", "Cota26", "Cota27",
                "Cota28", "Cota29", "Cota30",
                "Cota31", "DataIns",
            ]

        elif data_info == 3:
            columns = [
                "EstacaoCodigo", "NivelConsistencia", "DataHora",
                "MediaDiaria", "Maxima", "Minima",
                "Media", "DiaMaxima", "DiaMinima",
                "MediaAnual", "Vazao01", "Vazao02",
                "Vazao03", "Vazao04", "Vazao05",
                "Vazao06", "Vazao07", "Vazao08",
                "Vazao09", "Vazao10", "Vazao11",
                "Vazao12", "Vazao13", "Vazao14",
                "Vazao15", "Vazao16", "Vazao17",
                "Vazao18", "Vazao19", "Vazao20",
                "Vazao21", "Vazao22", "Vazao23",
                "Vazao24", "Vazao25", "Vazao26",
                "Vazao27", "Vazao28", "Vazao29",
                "Vazao30", "Vazao31",
            ]

        else:
            columns = [
                "DataHora", "Maxima", "Total",
                "DiaMaxima", "NumDiasDeChuva", "TotalAnual",
                "Chuva01", "Chuva02", "Chuva03",
                "Chuva04", "Chuva05", "Chuva06",
                "Chuva07", "Chuva08", "Chuva09",
                "Chuva10", "Chuva11", "Chuva12",
                "Chuva13", "Chuva14", "Chuva15",
                "Chuva16", "Chuva17", "Chuva18",
                "Chuva19", "Chuva20", "Chuva21",
                "Chuva22", "Chuva23", "Chuva24",
                "Chuva25", "Chuva26", "Chuva27",
                "Chuva28", "Chuva29", "Chuva30",
                "Chuva31", "DataIns",
            ]


        df = df[columns]
        df["DataHora"] = pd.to_datetime(df["DataHora"])
        return df

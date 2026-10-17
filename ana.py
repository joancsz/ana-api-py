"""
Access hydrological data from ANA's HidroWeb (Agência Nacional de Águas, Brazil).

Two backends are supported:

- REST HidroWebService (https://www.ana.gov.br/hidrowebservice), used when credentials
  are found in a YAML file (see ``ana.example.yaml``).
- Legacy SOAP service (http://telemetriaws1.ana.gov.br/ServiceANA.asmx), used otherwise.
  No credentials needed.

Example
-------
>>> from ana import ANA
>>> ana = ANA()
>>> ana.download("14990000", "L", "out/manaus.csv", melt_data=True)

Network calls share one ``requests.Session`` that retries connection errors, timeouts and
429/5xx responses with exponential backoff. Files are written atomically with a ``.sha256``
sidecar (check with ``verify``).
"""

import asyncio
import datetime
import hashlib
import io
import os
import re
import tempfile
import xml.etree.ElementTree as et
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal, Optional, Union

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

__all__ = ["ANA", "save", "verify", "NotFoundError", "NoDataAvailable", "AuthError"]

DateLike = Union[str, datetime.date, pd.Timestamp]


class NotFoundError(Exception):
    def __init__(self, info="Response <404>: File was not found in the url"):
        self.info = info
        super().__init__(self.info)


class NoDataAvailable(Exception):
    def __init__(self, info="No data available"):
        self.info = info
        super().__init__(self.info)


class AuthError(Exception):
    pass


def _fmt_date(date: Optional[DateLike]) -> str:
    return pd.Timestamp(date).strftime("%Y-%m-%d") if date else ""


def _session(retries: int, pool_size: int) -> requests.Session:
    """Session with connection pooling and retries (Retry-After is honoured on 429)."""
    retry = Retry(
        total=retries, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",), raise_on_status=False,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=pool_size)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _load_credentials(path: Optional[Union[str, Path]] = None) -> Optional[dict]:
    """Return {'identificador', 'senha'} from the YAML config, or None if there is no config file."""
    path = Path(path or os.environ.get("ANA_CONFIG") or "ana.yaml")
    if not path.is_file():
        return None
    try:
        import yaml
    except ImportError as e:
        raise ImportError(f"{path} found but PyYAML is missing: pip install 'ana-api[rest]'") from e
    creds = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not creds.get("identificador") or not creds.get("senha"):
        raise AuthError(f"{path} must define 'identificador' and 'senha'")
    return creds


class _Legacy:
    """Legacy SOAP service. Returns raw DataFrames with the service column names."""

    url = "http://telemetriaws1.ana.gov.br/ServiceANA.asmx"

    def __init__(self, session: requests.Session, timeout: float):
        self.session, self.timeout = session, timeout

    def _get(self, method: str, xpath: str = ".//Table", **params) -> pd.DataFrame:
        response = self.session.get(f"{self.url}/{method}", params=params, timeout=self.timeout)
        if response.status_code == 404:
            raise NotFoundError
        response.raise_for_status()
        for table in et.fromstring(response.content).iter("ErrorTable"):
            raise NoDataAvailable(table.findtext("Error") or "No data available")
        try:
            return pd.read_xml(io.BytesIO(response.content), xpath=xpath, parser="etree")
        except ValueError as e:  # empty result without an ErrorTable
            raise NoDataAvailable from e

    def rivers(self, code):
        return self._get("HidroRio", codRio=code)

    def states(self, code):
        return self._get("HidroEstado", codUf=code)

    def telemetric_stations(self, status):
        return self._get("ListaEstacoesTelemetricas", statusEstacoes=status, origem="")

    def stations(self, station_code="", station_type="", state="", agent_in_charge="", river_name="", telemetric=""):
        return self._get(
            "HidroInventario",
            codEstDE=station_code, codEstATE="", tpEst=station_type, nmEst="", nmRio=river_name,
            codSubBacia="", codBacia="", nmMunicipio="", nmEstado=state, sgResp=agent_in_charge,
            sgOper="", telemetrica=telemetric,
        )

    def series(self, station_code, data_info, start, end):
        tipo = {"L": 1, "P": 2, "I": 3}[data_info]
        return self._get(
            "HidroSerieHistorica", xpath=".//SerieHistorica", codEstacao=station_code,
            dataInicio=start, dataFim=end, tipoDados=tipo, nivelConsistencia="",
        )


class _Rest:
    """REST HidroWebService. Renames fields to the legacy column names so post-processing is shared."""

    url = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas"
    max_days = 366  # API limit per series request
    # shortcut: field names guessed from ANA docs, not checked against a real response; fix after first authenticated call
    rename = {
        "Data_Hora_Dado": "DataHora",
        "Nivel_Consistencia": "NivelConsistencia",
        "codigoestacao": "EstacaoCodigo",
        "Estacao_Codigo": "EstacaoCodigo",
    }

    def __init__(self, identificador: str, senha: str, session: requests.Session, timeout: float, workers: int):
        self.identificador, self.senha = identificador, senha
        self.session, self.timeout, self.workers = session, timeout, workers
        self._token = None

    def _auth(self) -> str:
        response = self.session.get(
            f"{self.url}/OAUth/v1",
            headers={"Identificador": str(self.identificador), "Senha": str(self.senha)},
            timeout=self.timeout,
        )
        body = response.json()
        if response.status_code != 200 or not body.get("items"):
            raise AuthError(body.get("message", response.text))
        return body["items"]["tokenautenticacao"]

    def _get(self, endpoint: str, **params) -> pd.DataFrame:
        for retry in (True, False):
            self._token = self._token or self._auth()
            response = self.session.get(
                f"{self.url}/{endpoint}/v1", params=params,
                headers={"Authorization": f"Bearer {self._token}"}, timeout=self.timeout,
            )
            if response.status_code == 401 and retry:
                self._token = None  # token expired, get a new one once
                continue
            break
        if response.status_code == 404:
            raise NotFoundError
        response.raise_for_status()
        items = response.json().get("items") or []
        if not items:
            raise NoDataAvailable(response.json().get("message", "No data available"))
        df = pd.DataFrame(items)
        df.columns = [self.rename.get(c, re.sub(r"_(\d{2})$", r"\1", c)) for c in df.columns]
        return df

    def rivers(self, code):
        return self._get("HidroRio", **{"Código do Rio": code})

    def states(self, code):
        return self._get("HidroUF", **{"Código da UF": code})

    def stations(self, station_code="", state="", **unsupported):
        if any(unsupported.values()):
            raise NotImplementedError(f"REST backend does not filter by {[k for k, v in unsupported.items() if v]}")
        if not (station_code or state):
            raise ValueError("REST backend needs station_code or state")
        return self._get("HidroInventarioEstacoes", **{"Código da Estação": station_code, "Unidade Federativa": state})

    def series(self, station_code, data_info, start, end):
        if not start:
            raise ValueError("REST backend needs start_date (series are fetched in 366-day chunks)")
        endpoint = {"L": "HidroSerieCotas", "P": "HidroSerieChuva", "I": "HidroSerieVazao"}[data_info]
        windows = []
        cursor, stop = pd.Timestamp(start), pd.Timestamp(end or pd.Timestamp.today().normalize())
        while cursor <= stop:
            chunk_end = min(cursor + pd.Timedelta(days=self.max_days - 1), stop)
            windows.append((cursor, chunk_end))
            cursor = chunk_end + pd.Timedelta(days=1)

        def fetch(window):
            try:
                return self._get(endpoint, **{
                    "Código da Estação": station_code, "Tipo Filtro Data": "DATA_LEITURA",
                    "Data Inicial (yyyy-MM-dd)": _fmt_date(window[0]), "Data Final (yyyy-MM-dd)": _fmt_date(window[1]),
                })
            except NoDataAvailable:
                return None  # gaps in a long period are normal

        self._token = self._token or self._auth()  # authenticate once before fanning out
        with ThreadPoolExecutor(self.workers) as pool:
            chunks = [c for c in pool.map(fetch, windows) if c is not None]
        if not chunks:
            raise NoDataAvailable
        return pd.concat(chunks, ignore_index=True)


def _pick(df: pd.DataFrame, columns: list, index: str) -> pd.DataFrame:
    # tolerant selection: REST responses may lack some legacy columns
    df = df[[c for c in columns if c in df.columns]].copy()
    return df.set_index(index) if index in df.columns else df


def save(df: pd.DataFrame, path: Union[str, Path]) -> Path:
    """
    Write a DataFrame to disk, format chosen by file suffix.

    The file is written to a temporary name and renamed into place, so a crash never leaves a
    half-written file. A ``<path>.sha256`` sidecar is written next to it (``sha256sum -c`` format).

    Parameters
    ----------
    df: pd.DataFrame
        Data to write
    path: str | Path
        Output file: ``.csv`` (always available), ``.xlsx`` (needs openpyxl) or ``.parquet`` (needs pyarrow)

    Returns
    -------
        The written path
    """
    path = Path(path)
    writers = {".csv": (df.to_csv, None), ".xlsx": (df.to_excel, "excel"), ".parquet": (df.to_parquet, "parquet")}
    if path.suffix not in writers:
        raise ValueError(f"Unsupported format {path.suffix!r}, use one of {list(writers)}")
    writer, extra = writers[path.suffix]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(suffix=path.suffix, dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        writer(tmp)
        digest = _sha256(tmp)
        os.replace(tmp, path)
    except ImportError as e:
        raise ImportError(f"Writing {path.suffix} needs an extra dependency: pip install 'ana-api[{extra}]'") from e
    finally:
        tmp.unlink(missing_ok=True)
    Path(f"{path}.sha256").write_bytes(f"{digest}  {path.name}\n".encode())  # LF only, so sha256sum -c works on Windows
    return path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify(path: Union[str, Path]) -> bool:
    """
    Check a file written by ``save`` against its ``.sha256`` sidecar.

    Returns
    -------
        True if the file matches, False if it was changed or corrupted. Raises FileNotFoundError
        if the file or its sidecar is missing.
    """
    path = Path(path)
    expected = Path(f"{path}.sha256").read_text(encoding="utf-8").split()[0]
    return _sha256(path) == expected


class ANA:
    """
    Client for HidroWeb data.

    Parameters
    ----------
    config: str | Path
        YAML file with REST credentials (``identificador``, ``senha``). Defaults to env ``ANA_CONFIG``
        or ``./ana.yaml``. Without a config file the legacy service is used.
    timeout: float
        Seconds to wait for each HTTP request
    retries: int
        Retries per request on connection errors, timeouts and 429/5xx responses (backoff 1s, 2s, 4s, ...)
    workers: int
        Parallel requests used by download_many and REST chunked series
    """

    def __init__(
        self, config: Optional[Union[str, Path]] = None, timeout: float = 60, retries: int = 3, workers: int = 4
    ) -> None:
        self.session = _session(retries, pool_size=workers)
        self.workers = workers
        self._legacy = _Legacy(self.session, timeout)
        creds = _load_credentials(config)
        self._api = (
            _Rest(creds["identificador"], creds["senha"], self.session, timeout, workers) if creds else self._legacy
        )
        self.backend = "rest" if creds else "legacy"

    def list_rivers(self, river_code: str = "") -> pd.DataFrame:
        """
        Return all rivers, or one river.

        Parameters
        ----------
        river_code: str
            River code, if not passed returns all

        Returns
        -------
            Pandas DataFrame with rivers indexed by name
        """
        return _pick(self._api.rivers(river_code), ["Nome", "Codigo", "BaciaCodigo", "SubBaciaCodigo"], "Nome")

    def list_states(self, state_code: str = "") -> pd.DataFrame:
        """
        Return all states, or one state.

        Parameters
        ----------
        state_code: str
            State code, if not passed returns all

        Returns
        -------
            Pandas DataFrame with states indexed by name
        """
        return _pick(self._api.states(state_code), ["Nome", "Sigla", "Codigo", "CodigoIBGE"], "Nome")

    def list_telemetric_stations(self, active: Optional[bool] = None) -> pd.DataFrame:
        """
        Return telemetric stations. Always uses the legacy service (no REST equivalent).

        Parameters
        ----------
        active: bool
            True for active stations, False for stations in maintenance, if not passed returns all

        Returns
        -------
            Pandas DataFrame with telemetric stations indexed by name
        """
        status = "" if active is None else (0 if active else 1)
        columns = [
            "NomeEstacao", "CodEstacao", "Bacia", "SubBacia", "Operadora", "Responsavel", "Municipio-UF",
            "Latitude", "Longitude", "Altitude", "CodRio", "NomeRio", "Origem", "StatusEstacao",
        ]
        return _pick(self._legacy.telemetric_stations(status), columns, "NomeEstacao")

    def list_stations(
        self,
        station_code: Union[str, int] = "",
        station_type: Literal["F", "P", ""] = "",
        state: str = "",
        agent_in_charge: str = "",
        river_name: str = "",
        telemetric: Optional[bool] = None,
    ) -> pd.DataFrame:
        """
        Return the station inventory. With the REST backend only station_code and state are supported,
        and at least one of them is required.

        Parameters
        ----------
        station_code: str | int
            Eight digit code of the station, unique identifier (Ex: 00047000, 90300000)
        station_type: str
            'F' for fluviometric or 'P' for pluviometric stations, if not passed returns all
        state: str
            State where the stations are located
        agent_in_charge: str
            Acronym of the agent responsible for the station
        river_name: str
            Name of the river where the station is located
        telemetric: bool
            True for telemetric, False for manual stations, if not passed returns all

        Returns
        -------
            Pandas DataFrame with stations information indexed by name
        """
        df = self._api.stations(
            station_code=str(station_code),
            state=state,
            station_type={"F": "1", "P": "2"}.get(station_type, ""),
            agent_in_charge=agent_in_charge,
            river_name=river_name,
            telemetric="" if telemetric is None else str(int(telemetric)),
        )
        date_columns = ["UltimaAtualizacao", "PeriodoTelemetricaInicio", "PeriodoTelemetricaFim"]
        columns = [
            "Codigo", "Nome", "Latitude", "Longitude", "Altitude", "AreaDrenagem", "nmEstado", "nmMunicipio",
            "RioNome", "TipoEstacao", "ResponsavelSigla", *date_columns,
        ]
        df = _pick(df, columns, "Nome")
        present = [c for c in date_columns if c in df.columns]
        df[present] = df[present].apply(pd.to_datetime)
        return df

    def get_station_time_series(
        self,
        station_code: str,
        data_info: Literal["P", "I", "L"],
        process_level: Literal["R", "P", ""] = "",
        start_date: Optional[DateLike] = "",
        end_date: Optional[DateLike] = "",
        melt_data: bool = False,
    ) -> pd.DataFrame:
        """
        Return the historical series of a station, one row per month.

        Parameters
        ----------
        station_code: str
            Eight digit code of the station, unique identifier (Ex: 00047000, 90300000)
        data_info: Literal["P", "I", "L"]
            'P' for precipitation, 'I' for discharge (vazão) and 'L' for level (cota)
        process_level: Literal["R", "P"]
            Consistency level, 'R' for raw and 'P' for processed (consisted), if not passed returns all
        start_date: str | datetime.date | pd.Timestamp
            Start of the period (YYYY-MM-DD). Legacy: if not passed returns from the first date. Required on REST.
        end_date: str | datetime.date | pd.Timestamp
            End of the period (YYYY-MM-DD), if not passed returns until the last date
        melt_data: bool
            Return a daily time series instead (see melt_to_time_series)

        Returns
        -------
            Pandas DataFrame with all the information available in the station for the period
        """
        kind = data_info.upper()
        df = self._api.series(station_code, kind, _fmt_date(start_date), _fmt_date(end_date))

        if process_level:
            level = 1 if process_level.upper() == "R" else 2
            df = df[pd.to_numeric(df["NivelConsistencia"]) == level]

        days = [f"{d:02d}" for d in range(1, 32)]
        columns = {
            "L": ["EstacaoCodigo", "NivelConsistencia", "DataHora", "MediaDiaria", "Maxima", "Minima", "Media",
                  "DiaMaxima", "DiaMinima", *(f"Cota{d}" for d in days), "DataIns"],
            "I": ["EstacaoCodigo", "NivelConsistencia", "DataHora", "MediaDiaria", "Maxima", "Minima", "Media",
                  "DiaMaxima", "DiaMinima", "MediaAnual", *(f"Vazao{d}" for d in days)],
            "P": ["EstacaoCodigo", "NivelConsistencia", "DataHora", "Maxima", "Total", "DiaMaxima",
                  "NumDiasDeChuva", "TotalAnual", *(f"Chuva{d}" for d in days), "DataIns"],
        }[kind]
        df = df[[c for c in columns if c in df.columns]].copy()
        df["DataHora"] = pd.to_datetime(df["DataHora"])

        if melt_data:
            if df.empty:
                raise NoDataAvailable
            df = self.melt_to_time_series(df)
        return df

    @staticmethod
    def melt_to_time_series(df: pd.DataFrame) -> pd.DataFrame:
        """
        Turn the monthly rows of get_station_time_series into a daily series.

        If both consistency levels are present, only processed (2) data is kept.

        Parameters
        ----------
        df: pd.DataFrame
            DataFrame obtained from get_station_time_series

        Returns
        -------
            Pandas DataFrame indexed by date with one column named after the variable (Cota, Vazao or Chuva)
        """
        if df["NivelConsistencia"].nunique() != 1:
            df = df[pd.to_numeric(df["NivelConsistencia"]) == 2]

        day_columns = [c for c in df.columns if c[-2:].isdigit()]
        var_name = day_columns[0][:-2]
        df = df.melt(id_vars="DataHora", value_vars=day_columns, var_name="var", value_name=var_name)

        month = df["DataHora"].copy()
        df["DataHora"] = month + pd.to_timedelta(df["var"].str[-2:].astype(int) - 1, unit="D")
        df = df[df["DataHora"].dt.month == month.dt.month]  # drop Feb 30, Apr 31, ...

        df[var_name] = pd.to_numeric(df[var_name], errors="coerce")
        df = df[["DataHora", var_name]].drop_duplicates(subset=["DataHora"])
        return df.set_index("DataHora").sort_index()

    def download(
        self, station_code: str, data_info: Literal["P", "I", "L"], path: Union[str, Path], **kwargs
    ) -> Path:
        """
        Fetch a station series and write it to disk.

        Parameters
        ----------
        station_code: str
            Eight digit code of the station
        data_info: Literal["P", "I", "L"]
            See get_station_time_series
        path: str | Path
            Output file (.csv, .xlsx or .parquet), parent folders are created
        **kwargs
            Passed to get_station_time_series (process_level, start_date, end_date, melt_data)

        Returns
        -------
            The written path
        """
        return save(self.get_station_time_series(station_code, data_info, **kwargs), path)

    def download_many(
        self,
        station_codes: list,
        data_info: Literal["P", "I", "L"],
        out_dir: Union[str, Path],
        fmt: Literal["csv", "xlsx", "parquet"] = "csv",
        **kwargs,
    ) -> dict:
        """
        Download several stations in parallel (``workers`` threads), one file per station.

        A failing station does not stop the others.

        Parameters
        ----------
        station_codes: list
            Station codes
        data_info: Literal["P", "I", "L"]
            See get_station_time_series
        out_dir: str | Path
            Folder for the files, named ``<code>_<data_info>.<fmt>``
        fmt: str
            Output format
        **kwargs
            Passed to get_station_time_series

        Returns
        -------
            Dict mapping each station code to its written Path, or to the exception it raised
        """
        def one(code):
            try:
                return self.download(code, data_info, Path(out_dir) / f"{code}_{data_info.upper()}.{fmt}", **kwargs)
            except Exception as e:  # reported per station, the batch goes on
                return e

        with ThreadPoolExecutor(self.workers) as pool:
            return dict(zip(station_codes, pool.map(one, station_codes)))

    async def adownload_many(self, *args, **kwargs) -> dict:
        """Async version of download_many for use inside an event loop (runs in a worker thread)."""
        return await asyncio.to_thread(self.download_many, *args, **kwargs)

# ana-api-py

A single Python module, `ana.py`, that **fetches, downloads and writes** hydrological data from
[HidroWeb](https://www.snirh.gov.br/hidroweb), the system run by Brazil's National Water Agency (ANA, Agência Nacional de Águas).

It provides river and state lists, the station inventory, telemetric stations, and monthly or daily series of
precipitation, discharge and water level.

## Installation

Requires Python ≥ 3.9.

```bash
pip install "git+https://github.com/joancsz/ana-api-py"            # core: requests + pandas
pip install "ana-api[all] @ git+https://github.com/joancsz/ana-api-py"  # + REST, Excel and Parquet support
```

| Extra     | Adds       | Needed for                 |
|-----------|------------|----------------------------|
| `rest`    | `pyyaml`   | the REST backend (`ana.yaml`) |
| `excel`   | `openpyxl` | writing `.xlsx`            |
| `parquet` | `pyarrow`  | writing `.parquet`         |

The module imports and writes CSV without any extra. A missing extra only fails when you use it, and the error
tells you what to install.

## Backends

`ANA()` picks the backend on its own. Check which one it chose with `ana.backend`.

| Backend  | When                          | Notes |
|----------|-------------------------------|-------|
| `rest`   | a credentials file is found   | [HidroWebService](https://www.ana.gov.br/hidrowebservice) with current data. Series need `start_date` and are fetched in 366-day chunks. `list_stations` filters only by `station_code` / `state`. |
| `legacy` | otherwise                     | `telemetriaws1.ana.gov.br` SOAP service, no login needed. **Historical series may stop years ago** (e.g. Manaus 14990000 ends in 2014). |

The credentials file is looked up in this order: `ANA(config="path.yaml")`, then env `ANA_CONFIG`, then `./ana.yaml`.
Copy [`ana.example.yaml`](ana.example.yaml) to `ana.yaml`, which is git-ignored:

```yaml
identificador: "your CPF/CNPJ"
senha: "your password"
```

`list_telemetric_stations` has no REST equivalent and always uses the legacy service.

## Usage

```python
from ana import ANA, save

ana = ANA()

ana.list_rivers()
ana.list_states()
ana.list_telemetric_stations(active=True)
ana.list_stations(station_code="00047000")

# Monthly rows (one column per day)
df = ana.get_station_time_series("14990000", data_info="L", start_date="2010-01-01", end_date="2010-12-31")

# Daily series
daily = ana.get_station_time_series("14990000", data_info="L", process_level="P", melt_data=True)

# Fetch + write in one step (.csv, .xlsx or .parquet)
ana.download("14990000", "L", "out/manaus.parquet", melt_data=True)

# Or write any DataFrame
save(daily, "out/manaus.xlsx")

# Many stations in parallel; a failing station doesn't stop the batch
result = ana.download_many(["14990000", "00047000"], "P", "out/", fmt="parquet", start_date="2010-01-01")
# {'14990000': Path('out/14990000_P.parquet'), '00047000': NoDataAvailable(...)}

# Same from async code
result = await ana.adownload_many(["14990000"], "L", "out/")
```

### Reliability

- **Retries:** connection errors, timeouts and HTTP 429/500/502/503/504 are retried with exponential backoff
  (1 s, 2 s, 4 s …), and `Retry-After` is honoured. Tune with `ANA(retries=3, timeout=60)`.
- **Concurrency:** `download_many` and REST series chunks run on `ANA(workers=4)` threads over one pooled session.
- **Integrity:** `save` writes to a temporary file and renames it into place, so an interrupted run never leaves
  a half-written file. Each output gets a `<file>.sha256` sidecar, which you can check with `ana.verify(path)` or
  `sha256sum -c out/file.csv.sha256`.

### Codes

| Parameter       | Value | Meaning                     |
|-----------------|-------|-----------------------------|
| `data_info`     | `P`   | precipitation (chuva)       |
|                 | `I`   | discharge (vazão)           |
|                 | `L`   | water level (cota)          |
| `process_level` | `R`   | raw (bruto)                 |
|                 | `P`   | processed (consistido)      |
| `station_type`  | `F`   | fluviometric                |
|                 | `P`   | pluviometric                |

Errors: `NoDataAvailable` (no data for the request), `NotFoundError` (HTTP 404) and `AuthError` (bad REST credentials).

## Development

```bash
python -m venv .venv && .venv/Scripts/pip install -e ".[all,test]"   # use .venv/bin on Linux/macOS
.venv/Scripts/python -m pytest
```

The tests are offline because HTTP is mocked.

## License

[MIT](LICENSE) © 2024 Joan Souza

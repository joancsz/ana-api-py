import asyncio

import pandas as pd
import pytest

import ana
from ana import ANA, NoDataAvailable, save, verify


class FakeResponse:
    def __init__(self, content=b"", json=None, status_code=200):
        self.content, self._json, self.status_code = content, json, status_code
        self.text = content.decode() if content else ""

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def xml(rows_tag, rows):
    body = "".join(f"<{rows_tag}>" + "".join(f"<{k}>{v}</{k}>" for k, v in r.items()) + f"</{rows_tag}>" for r in rows)
    return f"<DataTable><DocumentElement>{body}</DocumentElement></DataTable>".encode()


def month_row(date, level=2):
    return {"EstacaoCodigo": 1, "NivelConsistencia": level, "DataHora": date, **{f"Chuva{d:02d}": d for d in range(1, 32)}}


@pytest.fixture
def legacy(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no ana.yaml here -> legacy backend
    monkeypatch.delenv("ANA_CONFIG", raising=False)
    calls = []

    def use(content):
        monkeypatch.setattr(ana.requests.Session, "get", lambda self, url, **kw: calls.append((url, kw)) or FakeResponse(content))
        return calls

    return use


def test_no_config_uses_legacy(legacy):
    legacy(b"")
    assert ANA().backend == "legacy"


def test_list_rivers(legacy):
    legacy(xml("Table", [{"Nome": "RIO X", "Codigo": 1, "BaciaCodigo": 2, "SubBaciaCodigo": 3, "Extra": 0}]))
    df = ANA().list_rivers()
    assert list(df.columns) == ["Codigo", "BaciaCodigo", "SubBaciaCodigo"]
    assert df.index.tolist() == ["RIO X"]


def test_error_table_raises(legacy):
    legacy(b"<DataTable><DocumentElement><ErrorTable><Error>Sem dados</Error></ErrorTable></DocumentElement></DataTable>")
    with pytest.raises(NoDataAvailable, match="Sem dados"):
        ANA().get_station_time_series("1", "P")


def test_melt_drops_impossible_days(legacy):
    legacy(xml("SerieHistorica", [month_row("2021-02-01"), month_row("2021-03-01"), month_row("2021-03-01", level=1)]))
    df = ANA().get_station_time_series("1", "P", melt_data=True)
    assert len(df) == 28 + 31
    assert df.loc["2021-02-28", "Chuva"] == 28
    assert df.loc["2021-03-01", "Chuva"] == 1


def test_rest_chunks_and_renames(monkeypatch, tmp_path):
    pytest.importorskip("yaml")
    cfg = tmp_path / "ana.yaml"
    cfg.write_text("identificador: u\nsenha: p\n")
    calls = []

    def fake_get(self, url, params=None, **kw):
        calls.append(params)
        if url.endswith("OAUth/v1"):
            return FakeResponse(json={"items": {"tokenautenticacao": "t"}})
        item = {"Data_Hora_Dado": params["Data Inicial (yyyy-MM-dd)"], "Nivel_Consistencia": "2", "Chuva_01": "5"}
        return FakeResponse(json={"items": [item]})

    monkeypatch.setattr(ana.requests.Session, "get", fake_get)
    client = ANA(config=cfg)
    assert client.backend == "rest"
    df = client.get_station_time_series("1", "P", start_date="2020-01-01", end_date="2021-12-31")
    assert len(calls) == 1 + 2  # token + two 366-day chunks
    assert {"DataHora", "NivelConsistencia", "Chuva01"} <= set(df.columns)


def test_save_csv_roundtrip(tmp_path):
    df = pd.DataFrame({"a": [1, 2]})
    path = save(df, tmp_path / "sub" / "x.csv")
    assert pd.read_csv(path)["a"].tolist() == [1, 2]


def test_save_unknown_suffix(tmp_path):
    with pytest.raises(ValueError):
        save(pd.DataFrame(), tmp_path / "x.json")


def test_save_parquet_without_engine(tmp_path, monkeypatch):
    def no_engine(*a, **k):
        raise ImportError("no pyarrow")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", no_engine)
    with pytest.raises(ImportError, match=r"ana-api\[parquet\]"):
        save(pd.DataFrame({"a": [1]}), tmp_path / "x.parquet")


def test_session_retries_configured(legacy):
    legacy(b"")
    retry = ANA(retries=5).session.get_adapter("https://x").max_retries
    assert retry.total == 5 and 503 in retry.status_forcelist


def test_save_writes_checksum_and_verify_detects_tampering(tmp_path):
    path = save(pd.DataFrame({"a": [1]}), tmp_path / "x.csv")
    assert verify(path)
    path.write_text("tampered")
    assert not verify(path)


def test_save_is_atomic_on_failure(tmp_path, monkeypatch):
    path = save(pd.DataFrame({"a": [1]}), tmp_path / "x.csv")
    before = path.read_bytes()

    def crash(self, target, *a, **k):
        open(target, "w").write("partial")
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_csv", crash)
    with pytest.raises(OSError):
        save(pd.DataFrame({"a": [2]}), path)
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.csv", "x.csv.sha256"]  # no temp file left


def test_download_many_reports_failures_per_station(monkeypatch, legacy, tmp_path):
    ok = xml("SerieHistorica", [month_row("2021-02-01")])
    err = b"<DataTable><ErrorTable><Error>Sem dados</Error></ErrorTable></DataTable>"
    legacy(b"")
    fake = lambda self, url, params=None, **kw: FakeResponse(ok if params["codEstacao"] == "1" else err)  # noqa: E731
    monkeypatch.setattr(ana.requests.Session, "get", fake)
    result = asyncio.run(ANA().adownload_many(["1", "2"], "P", tmp_path))
    assert result["1"] == tmp_path / "1_P.csv" and verify(result["1"])
    assert isinstance(result["2"], NoDataAvailable)

"""Tests de l'ingestion temps réel nationale (Pôle P1) — API simulée, aucun appel réseau réel."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pandas as pd
import pytest

from anomalies_elec.config import AppConfig, StorageConfig
from anomalies_elec.ingestion.realtime import (
    drop_unpublished_tail,
    resolve_end,
    run_catch_up,
    run_incremental,
    window_where,
)
from anomalies_elec.storage.parquet_store import ParquetStore

TZ = "Europe/Paris"


class FakeOdsApi:
    """Simule `/records` du jeu temps réel : filtre sur la fenêtre `where`, publication progressive."""

    def __init__(self, day_utc: str = "2026-11-26") -> None:
        # Comme le vrai jeu : toutes les lignes de la journée existent déjà (prévisions), consommation vide.
        self.rows = {
            ds: {"consommation": None, "prevision_j1": 60000, "prevision_j": 60100}
            for ds in pd.date_range(f"{day_utc} 00:00", f"{day_utc} 23:45", freq="15min", tz="UTC")
        }
        self.calls: list[httpx.Request] = []

    def publish_until(self, until: str, value: float = 60000.0) -> None:
        for ds, row in self.rows.items():
            if ds <= pd.Timestamp(until) and row["consommation"] is None:
                row["consommation"] = value + ds.hour * 100 + ds.minute

    def set(self, ds: str, value: float | None) -> None:
        self.rows[pd.Timestamp(ds)]["consommation"] = value

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        start, end = re.findall(r"'([^']+)'", request.url.params["where"])
        results = []
        for ds, row in sorted(self.rows.items()):
            if pd.Timestamp(start) <= ds <= pd.Timestamp(end):
                local = ds.tz_convert(TZ)
                results.append(
                    {
                        "date_heure": ds.isoformat(),
                        "date": f"{local:%Y-%m-%d}",
                        "heure": f"{local:%H:%M}",
                        "nature": "Données temps réel",
                        **row,
                    }
                )
        return httpx.Response(200, json={"results": results}, headers={"X-RateLimit-dataset-Remaining": "49900"})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture()
def cfg(tmp_path: Path) -> AppConfig:
    return AppConfig(storage=StorageConfig(data_dir=tmp_path))


def _stored(cfg: AppConfig) -> pd.DataFrame:
    return ParquetStore(cfg.storage.data_dir).read_series(layer="processed", name="national_tr")


def test_window_where_is_bounded_and_fits_one_call() -> None:
    end = pd.Timestamp("2026-11-26 10:20Z")
    where = window_where(end, hours=6)
    assert "'2026-11-26T04:20:00+00:00'" in where and "'2026-11-26T10:20:00+00:00'" in where
    with pytest.raises(ValueError, match="lignes par appel"):
        window_where(end, hours=30)  # 121 lignes > 100


def test_resolve_end_falls_back_to_now_for_manual_airflow_runs() -> None:
    assert resolve_end("None").tzinfo is not None
    assert resolve_end("2026-11-26T10:20:00+01:00") == pd.Timestamp("2026-11-26 09:20Z")


def test_drop_unpublished_tail_keeps_interior_gaps_only() -> None:
    ds = pd.date_range("2026-11-26 09:00", periods=6, freq="15min", tz="UTC")
    series = pd.DataFrame({"ds": ds, "y": [1.0, None, 3.0, 4.0, None, None]})
    out = drop_unpublished_tail(series, now=pd.Timestamp("2026-11-26 10:00Z"))
    # 10:15 est dans le futur ; 10:00 n'est pas encore publié ; 09:15 vide mais suivi de valeurs → conservé
    assert out["ds"].tolist() == list(ds[:4])
    assert out["y"].isna().sum() == 1


def test_incremental_absorbs_late_and_revised_points_without_duplicates(cfg: AppConfig) -> None:
    api = FakeOdsApi()
    api.publish_until("2026-11-26 10:00Z")

    with api.client() as http:
        first = run_incremental(end="2026-11-26T10:20:00+00:00", config=cfg, http_client=http)
        assert first["last_ds"] == "2026-11-26T10:00:00+00:00"

        api.publish_until("2026-11-26 10:15Z")  # publié en retard
        api.set("2026-11-26 10:00Z", 61234.0)  # valeur révisée par RTE
        run_incremental(end="2026-11-26T10:35:00+00:00", config=cfg, http_client=http)
        run_incremental(end="2026-11-26T10:35:00+00:00", config=cfg, http_client=http)  # rejeu

    stored = _stored(cfg)
    assert stored["ds"].is_unique
    assert stored["ds"].max() == pd.Timestamp("2026-11-26 10:15Z")
    assert stored.loc[stored["ds"] == pd.Timestamp("2026-11-26 10:00Z"), "y"].item() == 61234.0
    assert len(api.calls) == 3  # 1 appel API par exécution
    assert api.calls[0].url.params["timezone"] == "UTC"


def test_context_rows_do_not_overwrite_flags_computed_with_history(cfg: AppConfig) -> None:
    api = FakeOdsApi()
    api.publish_until("2026-11-26 12:00Z")
    del api.rows[pd.Timestamp("2026-11-26 08:00Z")]  # point jamais publié → trou avant 08:15

    with api.client() as http:
        run_incremental(end="2026-11-26T12:00:00+00:00", config=cfg, http_client=http)
        # 2 h plus tard, 08:15 tombe dans les premières lignes de la fenêtre (sans historique)
        api.publish_until("2026-11-26 14:00Z")
        run_incremental(end="2026-11-26T14:00:00+00:00", config=cfg, http_client=http)

    stored = _stored(cfg)
    flag = stored.loc[stored["ds"] == pd.Timestamp("2026-11-26 08:15Z"), "quality_flag"].item()
    assert flag == "MISSING_GAP"


def test_each_call_is_archived_raw_before_cleaning(cfg: AppConfig) -> None:
    api = FakeOdsApi()
    api.publish_until("2026-11-26 10:00Z")
    with api.client() as http:
        summary = run_incremental(end="2026-11-26T10:15:00+00:00", config=cfg, http_client=http)
        run_incremental(end="2026-11-26T10:30:00+00:00", config=cfg, http_client=http)

    lines = Path(summary["raw_archive"]).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    entry = json.loads(lines[0])
    assert entry["n"] == len(entry["results"]) == 25  # 6 h incluses = 25 lignes, futur compris
    assert entry["results"][-1]["consommation"] is None  # brut : rien n'est retiré à l'archivage
    assert summary["quota_remaining"] == 49900


def test_catch_up_from_local_export_stores_only_published_points(cfg: AppConfig, tmp_path: Path) -> None:
    ds = pd.date_range("2026-08-31 22:00", periods=8, freq="15min", tz="UTC")
    local = ds.tz_convert(TZ)
    export = pd.DataFrame(
        {
            "date_heure": ds,
            "date": local.strftime("%Y-%m-%d"),
            "heure": local.strftime("%H:%M"),
            "nature": "Données temps réel",
            "consommation": [50000.0, 50100.0, 50200.0, 50300.0, 50400.0, 50500.0, None, None],
            "prevision_j1": 50000,
            "prevision_j": 50000,
        }
    )
    export_file = tmp_path / "export_tr.parquet"
    export.to_parquet(export_file, index=False)

    summary = run_catch_up(input_path=export_file, config=cfg)

    stored = _stored(cfg)
    assert summary["written_rows"] == len(stored) == 6  # 2 derniers points pas encore publiés
    assert summary["quota_remaining"] is None  # aucun appel API
    assert str(stored["ds"].dt.tz) == "UTC"

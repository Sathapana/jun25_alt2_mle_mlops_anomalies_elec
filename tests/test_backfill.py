"""Tests du backfill historique éCO2mix (Pôle P1) — aucun appel réseau réel."""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pandas as pd
import pytest

from anomalies_elec.config import AppConfig, StorageConfig
from anomalies_elec.ingestion.backfill import (
    analyze_time_step,
    download_export,
    normalize_export,
    read_partitions,
    run_backfill,
    write_partitions,
)

TZ = "Europe/Paris"


def _rows_from_utc(ds_utc: pd.DatetimeIndex, nature: str = "Données définitives") -> pd.DataFrame:
    """Reproduit le format de l'export : heure locale (date/heure) + date_heure UTC, mesure aux :00/:30."""
    local = ds_utc.tz_convert(TZ)
    measured = ds_utc.minute.isin([0, 30])
    return pd.DataFrame(
        {
            "date": local.strftime("%Y-%m-%d"),
            "heure": local.strftime("%H:%M"),
            "date_heure": ds_utc,
            "nature": nature,
            "consommation": pd.Series(range(len(ds_utc)), dtype="float64").where(measured, None) + 40000.0,
            "prevision_j1": 39000,
            "prevision_j": 39500,
            "nucleaire": pd.Series(30000.0, index=range(len(ds_utc))).where(measured, None),
        }
    )


@pytest.fixture()
def source_like_export() -> pd.DataFrame:
    """Deux journées de changement d'heure avec les défauts constatés dans la source RTE.

    - printemps (2023-03-26) : lignes fantômes aux heures locales inexistantes 02:00–02:45,
      converties vers les mêmes instants UTC que 03:00–03:45 (doublons) ;
    - automne (2023-10-29) : la première occurrence de 02:00–02:45 manque (trou de 1 h en UTC).
    """
    spring = _rows_from_utc(pd.date_range("2023-03-25 22:00", "2023-03-26 03:45", freq="15min", tz="UTC"))
    phantoms = spring[spring["heure"].isin(["03:00", "03:15", "03:30", "03:45"])].copy()
    phantoms["heure"] = phantoms["heure"].str.replace("03:", "02:", regex=False)
    phantoms["prevision_j1"] = 1  # valeur de remplissage, distincte de la vraie ligne

    autumn_utc = pd.date_range("2023-10-28 21:00", "2023-10-29 03:45", freq="15min", tz="UTC")
    autumn_utc = autumn_utc[~((autumn_utc >= "2023-10-29 00:00Z") & (autumn_utc < "2023-10-29 01:00Z"))]
    autumn = _rows_from_utc(autumn_utc)

    return pd.concat([spring, phantoms, autumn], ignore_index=True).sample(frac=1.0, random_state=0)


def test_normalize_drops_dst_phantoms_and_keeps_utc(source_like_export: pd.DataFrame) -> None:
    clean, dropped = normalize_export(source_like_export, timezone=TZ)

    assert len(dropped) == 4
    assert set(dropped["heure"]) == {"02:00", "02:15", "02:30", "02:45"}
    assert clean["ds"].is_unique
    assert str(clean["ds"].dt.tz) == "UTC"
    assert clean["ds"].is_monotonic_increasing
    # La vraie ligne 03:00 (et non la fantôme) est conservée
    kept = clean.loc[clean["ds"] == pd.Timestamp("2023-03-26 01:00Z")]
    assert kept["heure"].item() == "03:00"
    assert kept["prevision_j1"].item() == 39000


def test_analyze_time_step_reports_effective_step_and_gaps(source_like_export: pd.DataFrame) -> None:
    clean, _ = normalize_export(source_like_export, timezone=TZ)
    report = analyze_time_step(clean)

    assert report["row_step"] == "15min"
    assert report["duplicate_ds"] == 0
    assert report["effective_step"]["consommation"]["step"] == "30min"
    assert report["effective_step"]["prevision_j1"]["step"] == "15min"
    # Trou d'automne (1 h manquante) + saut entre les deux journées synthétiques
    durations = {g["duration"] for g in report["gaps"]}
    assert "75min" in durations


def test_write_partitions_is_idempotent_and_applies_revisions(tmp_path: Path) -> None:
    ds = pd.date_range("2025-12-31 23:00", periods=8, freq="15min", tz="UTC")
    df = _rows_from_utc(ds, nature="Données consolidées")
    df["ds"] = df["date_heure"]

    write_partitions(df, tmp_path)
    write_partitions(df, tmp_path)
    first = read_partitions(tmp_path)
    assert len(first) == len(df)
    assert sorted(p.parent.name for p in tmp_path.glob("year=*/data.parquet")) == ["year=2025", "year=2026"]

    # RTE révise les données : consolidées -> définitives, valeur corrigée
    revised = df.assign(nature="Données définitives", consommation=df["consommation"] + 1.0)
    write_partitions(revised, tmp_path)
    second = read_partitions(tmp_path)
    assert len(second) == len(df)
    assert set(second["nature"]) == {"Données définitives"}
    assert not list(tmp_path.glob("year=*/*.tmp"))


def test_download_export_uses_single_bulk_call_in_utc(tmp_path: Path) -> None:
    payload = io.BytesIO()
    pd.DataFrame({"a": [1, 2]}).to_parquet(payload)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=payload.getvalue(), headers={"X-RateLimit-dataset-Remaining": "49999"})

    dest = tmp_path / "export.parquet"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = download_export("eco2mix-national-cons-def", dest, client=client)

    assert len(calls) == 1
    assert calls[0].url.path.endswith("/eco2mix-national-cons-def/exports/parquet")
    assert calls[0].url.params["timezone"] == "UTC"
    assert result.quota_remaining == 49999
    assert pd.read_parquet(dest)["a"].tolist() == [1, 2]
    assert not list(tmp_path.glob("*.part"))


def test_run_backfill_from_local_file_is_rerunnable(tmp_path: Path, source_like_export: pd.DataFrame) -> None:
    export_file = tmp_path / "export.parquet"
    source_like_export.to_parquet(export_file, index=False)
    cfg = AppConfig(storage=StorageConfig(data_dir=tmp_path / "data"))

    first = run_backfill(input_path=export_file, config=cfg)
    second = run_backfill(input_path=export_file, config=cfg)

    out_root = tmp_path / "data" / "raw" / "eco2mix_national_cons_def"
    assert first["rows"] == second["rows"] == len(read_partitions(out_root))
    assert len(second["dropped_dst_phantom_rows"]) == 4
    assert (out_root / "_time_step_report.json").exists()

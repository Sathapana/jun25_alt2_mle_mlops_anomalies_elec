"""Tests unitaires pour le pôle P1 (Data Quality, Calendrier français, Stockage Parquet/DuckDB)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pandas as pd
import pytest

from anomalies_elec.config import AppConfig, StorageConfig, WeatherConfig, WeatherLocationConfig
from anomalies_elec.features.calendar_fr import enrich_french_calendar
from anomalies_elec.ingestion.eco2mix_client import Eco2MixClient, QuotaExceededError
from anomalies_elec.ingestion.quality import apply_quality_checks
from anomalies_elec.ingestion.weather_client import (
    align_weather_to_15min_utc,
    backfill_weather,
    compute_population_weighted_national,
    join_weather_to_series,
)
from anomalies_elec.storage.parquet_store import ParquetStore


def test_quota_guard_raises_when_limit_reached() -> None:
    client = Eco2MixClient(api_calls_used=50000)
    with pytest.raises(QuotaExceededError):
        client._check_and_increment_quota()


def test_quality_checks_detect_bounds_missing_and_frozen(
    synthetic_eco2mix_df: pd.DataFrame,
) -> None:
    df = synthetic_eco2mix_df.copy()
    df.loc[5, "y"] = 5000.0  # Sous la borne minimale (15 000 MW)
    df.loc[10:15, "y"] = 55000.0  # Capteur figé sur 6 pas
    df.loc[25, "y"] = float("nan")  # Valeur manquante

    checked = apply_quality_checks(df)
    assert checked.loc[5, "quality_flag"] == "OUT_OF_BOUNDS"
    assert checked.loc[15, "quality_flag"] == "FROZEN_SENSOR"
    assert checked.loc[25, "quality_flag"] == "MISSING_VALUE"
    assert checked.loc[0, "quality_flag"] == "OK"


def test_french_calendar_detects_holiday_and_bridge_day() -> None:
    # Jeudi 14 août 2025 (ouvré), Vendredi 15 août 2025 (Assomption - férié),
    # Jeudi 29 mai 2025 (Ascension - férié), Vendredi 30 mai 2025 (Pont de l'Ascension)
    ds = pd.to_datetime(
        [
            "2025-08-14 10:00:00+00:00",
            "2025-08-15 10:00:00+00:00",
            "2025-05-29 10:00:00+00:00",
            "2025-05-30 10:00:00+00:00",
        ],
        utc=True,
    )
    df = pd.DataFrame({"unique_id": "FR", "ds": ds, "y": [50000.0] * 4})
    enriched = enrich_french_calendar(df)

    assert not bool(enriched.loc[0, "is_holiday_fr"])
    assert bool(enriched.loc[1, "is_holiday_fr"])
    assert bool(enriched.loc[2, "is_holiday_fr"])
    assert bool(enriched.loc[3, "is_bridge_day"])


def test_parquet_store_upsert_is_idempotent(
    tmp_path: Path,
    synthetic_eco2mix_df: pd.DataFrame,
) -> None:
    store = ParquetStore(tmp_path)
    batch1 = synthetic_eco2mix_df.iloc[:20].copy()
    batch2 = synthetic_eco2mix_df.iloc[10:30].copy()
    batch2["y"] = batch2["y"] + 100.0

    store.upsert_series(batch1, name="test_series")
    store.upsert_series(batch2, name="test_series")

    loaded = store.read_series(name="test_series", unique_id="FR")
    assert len(loaded) == 30
    assert float(loaded.iloc[15]["y"]) == pytest.approx(float(batch2.iloc[5]["y"]))


def test_align_weather_to_15min_utc_interpolates_and_extends_last_hour() -> None:
    hourly = pd.DataFrame(
        {
            "unique_id": ["11", "11"],
            "ds": pd.to_datetime(["2025-01-15 00:00:00+00:00", "2025-01-15 01:00:00+00:00"], utc=True),
            "temperature_2m": [10.0, 14.0],
        }
    )
    aligned = align_weather_to_15min_utc(hourly)
    assert len(aligned) == 8
    assert str(aligned["ds"].dt.tz) == "UTC"
    assert set(aligned["ds"].dt.minute.unique()).issubset({0, 15, 30, 45})
    assert aligned["temperature_2m"].tolist() == pytest.approx([10.0, 11.0, 12.0, 13.0, 14.0, 14.0, 14.0, 14.0])


def test_compute_population_weighted_national() -> None:
    ds = pd.to_datetime(["2025-01-15 00:00:00+00:00"], utc=True)
    locs = [
        WeatherLocationConfig(unique_id="11", name="Paris", latitude=48.85, longitude=2.35, weight=0.75),
        WeatherLocationConfig(unique_id="84", name="Lyon", latitude=45.76, longitude=4.83, weight=0.25),
    ]
    regional = pd.DataFrame({"unique_id": ["11", "84"], "ds": [ds[0], ds[0]], "temperature_2m": [10.0, 14.0]})
    fr = compute_population_weighted_national(regional, locs)
    assert len(fr) == 1
    assert fr.iloc[0]["unique_id"] == "FR"
    assert float(fr.iloc[0]["temperature_2m"]) == pytest.approx(11.0)


def test_backfill_weather_mocked_http_persists_fr_and_regions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locs = [
        WeatherLocationConfig(unique_id="11", name="Paris", latitude=48.8566, longitude=2.3522, weight=0.6),
        WeatherLocationConfig(unique_id="84", name="Lyon", latitude=45.7640, longitude=4.8357, weight=0.4),
    ]
    cfg = AppConfig(
        storage=StorageConfig(backend="parquet", data_dir=tmp_path),
        weather=WeatherConfig(locations=locs, max_days_per_chunk=365),
    )

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict]:
            return [
                {
                    "hourly": {
                        "time": ["2025-01-15T00:00", "2025-01-15T01:00"],
                        "temperature_2m": [8.0, 12.0],
                    }
                },
                {
                    "hourly": {
                        "time": ["2025-01-15T00:00", "2025-01-15T01:00"],
                        "temperature_2m": [13.0, 17.0],
                    }
                },
            ]

    monkeypatch.setattr(httpx.Client, "get", lambda self, url, params=None: _FakeResponse())

    result = backfill_weather(
        start_date="2025-01-15",
        end_date="2025-01-15",
        include_extra_windows=False,
        config=cfg,
    )
    assert set(result["unique_id"].unique()) == {"FR", "11", "84"}
    assert len(result) == 24  # 3 series * 8 15-min steps

    store = ParquetStore(tmp_path)
    loaded_fr = store.read_weather(unique_id="FR")
    assert len(loaded_fr) == 8
    # At 00:00: 0.6*8.0 + 0.4*13.0 = 4.8 + 5.2 = 10.0
    assert float(loaded_fr.iloc[0]["temperature_2m"]) == pytest.approx(10.0)


def test_join_weather_to_series_with_and_without_unique_id() -> None:
    ds = pd.to_datetime(["2025-01-15 00:00:00+00:00", "2025-01-15 00:30:00+00:00"], utc=True)
    weather_df = pd.DataFrame(
        {
            "unique_id": ["FR", "FR", "11", "11"],
            "ds": [ds[0], ds[1], ds[0], ds[1]],
            "temperature_2m": [5.0, 5.5, 4.0, 4.5],
        }
    )

    # Cas 1 : DataFrame traité avec unique_id
    processed_df = pd.DataFrame({"unique_id": ["11", "FR"], "ds": [ds[0], ds[1]], "y": [10000.0, 70000.0]})
    joined_with_uid = join_weather_to_series(processed_df, weather_df)
    assert joined_with_uid["temperature_2m"].tolist() == pytest.approx([4.0, 5.5])

    # Cas 2 : DataFrame brut national sans colonne unique_id (ex: eco2mix_national_cons_def)
    raw_df = pd.DataFrame({"ds": ds, "y": [71000.0, 70500.0]})
    joined_without_uid = join_weather_to_series(raw_df, weather_df)
    assert joined_without_uid["temperature_2m"].tolist() == pytest.approx([5.0, 5.5])

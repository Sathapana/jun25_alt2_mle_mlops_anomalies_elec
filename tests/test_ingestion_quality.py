"""Tests unitaires pour le pôle P1 (Data Quality, Calendrier français, Stockage Parquet/DuckDB)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from anomalies_elec.features.calendar_fr import enrich_french_calendar
from anomalies_elec.ingestion.eco2mix_client import Eco2MixClient, QuotaExceededError
from anomalies_elec.ingestion.quality import apply_quality_checks
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

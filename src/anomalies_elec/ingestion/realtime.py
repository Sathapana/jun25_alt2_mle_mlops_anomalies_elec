"""Ingestion temps réel nationale éCO2mix (`eco2mix-national-tr`) — rattrapage et incrémental (P1).

Deux modes :
- **rattrapage** (`--catch-up`) : tout le contenu du jeu temps réel en 1 appel `/exports`.
  Le jeu ne garde qu'une fenêtre glissante (il démarre là où s'arrête l'historique consolidé),
  il faut donc l'archiver nous-mêmes ;
- **incrémental** (défaut, DAG Airflow toutes les 15 min) : relit les `realtime_window_hours`
  dernières heures en 1 appel `/records`. Cette fenêtre de recouvrement absorbe les retards de
  publication (~20 min constatés) et les valeurs révisées ; l'upsert sur `(source, unique_id, ds)`
  évite les doublons.

Chaque réponse brute est archivée telle quelle (couche raw) avant tout nettoyage.

Usage :
    uv run python -m anomalies_elec.ingestion.realtime                 # incrémental
    uv run python -m anomalies_elec.ingestion.realtime --catch-up      # rattrapage (1 appel export)
    uv run python -m anomalies_elec.ingestion.realtime --catch-up --input export.parquet   # sans API
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from anomalies_elec.config import AppConfig, load_config
from anomalies_elec.features.calendar_fr import enrich_french_calendar
from anomalies_elec.ingestion.backfill import download_export, normalize_export
from anomalies_elec.ingestion.eco2mix_client import Eco2MixClient
from anomalies_elec.ingestion.quality import apply_quality_checks
from anomalies_elec.storage.base import get_store

logger = logging.getLogger(__name__)

DATASET_KEY = "national_tr"
# Pas natif du flux temps réel (consommation publiée toutes les 15 min), indépendant du pas de
# modélisation choisi par P2 (`project.freq`) : les contrôles qualité portent sur la donnée brute.
NATIVE_FREQ = "15min"
STEPS_PER_HOUR = 4


def resolve_end(end: str | datetime | pd.Timestamp | None) -> pd.Timestamp:
    """Borne haute de la fenêtre, en UTC. `None` / "" / "None" (run manuel Airflow) → maintenant."""
    if end is None or (isinstance(end, str) and end.strip() in {"", "None"}):
        return pd.Timestamp(datetime.now(UTC))
    ts = pd.Timestamp(end)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def window_where(end: pd.Timestamp, hours: int, page_size: int = 100) -> str:
    """Clause ODSQL `date_heure` ∈ [end - hours, end]. Vérifie que la fenêtre tient en 1 appel."""
    expected_rows = hours * STEPS_PER_HOUR + 1
    if expected_rows > page_size:
        raise ValueError(
            f"Fenêtre de {hours} h = {expected_rows} lignes > {page_size} lignes par appel : réduire la fenêtre."
        )
    start = end - pd.Timedelta(hours=hours)
    return f"date_heure >= '{start.isoformat()}' and date_heure <= '{end.isoformat()}'"


def archive_raw_records(records: list[dict[str, Any]], root: Path, fetched_at: pd.Timestamp, query: str) -> Path:
    """Ajoute la réponse brute de l'API, telle quelle, au journal du jour (`fetched/date=YYYY-MM-DD.jsonl`).

    Un fichier par jour (et non par appel) évite des dizaines de milliers de petits fichiers.
    Conserver chaque réponse permet de savoir ce que l'on savait à un instant donné (audit M+1).
    """
    target = root / "fetched" / f"date={fetched_at:%Y-%m-%d}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {"fetched_at": fetched_at.isoformat(), "query": query, "n": len(records), "results": records},
        ensure_ascii=False,
        default=str,
    )
    with target.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return target


def drop_unpublished_tail(series: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """Retire les points futurs et les derniers points pas encore publiés.

    Le jeu temps réel contient déjà les lignes du reste de la journée (prévisions seules, consommation
    vide). Ces points ne sont pas « manquants » mais « pas encore publiés » : on les écarte au lieu de
    les marquer `MISSING_VALUE`. Une consommation vide *suivie* de valeurs publiées est, elle, conservée.
    """
    past = series.loc[series["ds"] <= now]
    published = past.loc[past["y"].notna(), "ds"]
    if published.empty:
        return past.iloc[0:0]
    return past.loc[past["ds"] <= published.max()].reset_index(drop=True)


def records_to_series(
    raw: pd.DataFrame, now: pd.Timestamp, unique_id: str = "FR", timezone: str = "Europe/Paris"
) -> pd.DataFrame:
    """Brut (export ou `/records`) → contrat série P1 (`unique_id`, `ds`, `y`, prévisions), points publiés."""
    if raw.empty:
        return pd.DataFrame(columns=["unique_id", "ds", "y", "prevision_j1", "prevision_j"])
    clean, _ = normalize_export(raw, timezone=timezone)  # ds UTC + lignes fantômes DST retirées
    series = pd.DataFrame(
        {
            "unique_id": unique_id,
            "ds": clean["ds"],
            "y": pd.to_numeric(clean["consommation"], errors="coerce"),
            "prevision_j1": pd.to_numeric(clean.get("prevision_j1"), errors="coerce"),
            "prevision_j": pd.to_numeric(clean.get("prevision_j"), errors="coerce"),
        }
    )
    return drop_unpublished_tail(series, now)


def check_and_store(series: pd.DataFrame, cfg: AppConfig, context_rows: int = 0) -> pd.DataFrame:
    """Contrôle qualité + calendrier sur toute la fenêtre, puis upsert des lignes évaluées avec contexte.

    Les contrôles « trou » et « capteur figé » comparent chaque point aux précédents. Les
    `context_rows` premiers points de la fenêtre n'ont pas d'historique suffisant : on les évalue
    mais on ne les réécrit pas, pour ne pas écraser un `quality_flag` calculé correctement lors
    d'une exécution précédente (où ils étaient plus loin dans la fenêtre).
    """
    if series.empty:
        return series
    checked = apply_quality_checks(series, config=cfg.ingestion, expected_freq=NATIVE_FREQ)
    enriched = enrich_french_calendar(checked, timezone=cfg.project.timezone)
    to_write = enriched.iloc[context_rows:].reset_index(drop=True)
    if not to_write.empty:
        get_store(cfg.storage).upsert_series(to_write, layer=cfg.storage.processed_subdir, name=DATASET_KEY)
    return to_write


def _raw_root(cfg: AppConfig) -> Path:
    dataset_id = cfg.ingestion.datasets[DATASET_KEY]
    return Path(cfg.storage.data_dir) / cfg.storage.raw_subdir / dataset_id.replace("-", "_")


def _summary(mode: str, fetched: int, written: pd.DataFrame, quota: int | None, archive: Path | None) -> dict:
    return {
        "mode": mode,
        "fetched_rows": fetched,
        "written_rows": len(written),
        "first_ds": written["ds"].min().isoformat() if not written.empty else None,
        "last_ds": written["ds"].max().isoformat() if not written.empty else None,
        "quality_flags": dict(Counter(written["quality_flag"])) if not written.empty else {},
        "quota_remaining": quota,
        "raw_archive": str(archive) if archive else None,
    }


def run_incremental(
    end: str | datetime | pd.Timestamp | None = None,
    config: AppConfig | None = None,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Une exécution incrémentale : 1 appel `/records` sur la fenêtre de recouvrement."""
    cfg = config or load_config()
    window_end = resolve_end(end)
    where = window_where(window_end, cfg.ingestion.realtime_window_hours, cfg.ingestion.page_size)

    client = Eco2MixClient(cfg.ingestion, http_client=http_client)
    records = client.fetch_raw_records(DATASET_KEY, where=where, limit=cfg.ingestion.page_size)
    fetched_at = pd.Timestamp(datetime.now(UTC))
    archive = archive_raw_records(records, _raw_root(cfg), fetched_at, where)
    logger.info("%d lignes reçues, quota restant : %s", len(records), client.last_quota_remaining)

    series = records_to_series(
        pd.DataFrame(records), now=window_end, unique_id=cfg.project.default_unique_id, timezone=cfg.project.timezone
    )
    written = check_and_store(series, cfg, context_rows=cfg.ingestion.max_frozen_steps)
    return _summary("incremental", len(records), written, client.last_quota_remaining, archive)


def run_catch_up(
    input_path: Path | None = None,
    config: AppConfig | None = None,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Rattrapage : tout le jeu temps réel en 1 appel `/exports` (ou depuis un export local)."""
    cfg = config or load_config()
    now = pd.Timestamp(datetime.now(UTC))
    quota = None
    if input_path is None:
        dest = _raw_root(cfg) / "exports" / f"{cfg.ingestion.datasets[DATASET_KEY]}_{now:%Y%m%dT%H%M%SZ}.parquet"
        result = download_export(cfg.ingestion.datasets[DATASET_KEY], dest, cfg.ingestion, client=http_client)
        input_path, quota = result.path, result.quota_remaining

    raw = pd.read_parquet(input_path)
    series = records_to_series(raw, now=now, unique_id=cfg.project.default_unique_id, timezone=cfg.project.timezone)
    written = check_and_store(series, cfg, context_rows=0)  # début du jeu : pas d'historique à préserver
    return _summary("catch_up", len(raw), written, quota, Path(input_path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingestion temps réel nationale éCO2mix (eco2mix-national-tr).")
    parser.add_argument("--catch-up", action="store_true", help="Rattrapage complet via /exports (1 appel)")
    parser.add_argument("--input", type=Path, default=None, help="Avec --catch-up : export local, aucun appel API")
    parser.add_argument("--end", default=None, help="Incrémental : borne haute UTC de la fenêtre (défaut : maintenant)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.input and not args.catch_up:
        parser.error("--input ne s'utilise qu'avec --catch-up")
    summary = run_catch_up(input_path=args.input) if args.catch_up else run_incremental(end=args.end)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

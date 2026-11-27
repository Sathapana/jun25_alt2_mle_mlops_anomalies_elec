"""Backfill de l'historique éCO2mix via l'endpoint d'export en masse Opendatasoft (P1).

Pourquoi l'export et pas `/records` :
- `/records` renvoie au plus 100 lignes par appel et plafonne `offset + limit` à 10 000 ;
  l'historique national (~514 000 lignes) est donc inatteignable par pagination ;
- `/exports/parquet` renvoie tout le jeu de données en **un seul appel** (quota : 50 000/mois).

Le script est rejouable : chaque exécution télécharge l'historique complet et **réécrit**
chaque partition annuelle de façon atomique. Les données « consolidées » récentes,
révisées ensuite en « définitives » par RTE, sont ainsi mises à jour sans doublon.

Usage :
    uv run python -m anomalies_elec.ingestion.backfill                      # télécharge puis écrit
    uv run python -m anomalies_elec.ingestion.backfill --input export.parquet  # sans appel API
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd

from anomalies_elec.config import AppConfig, IngestionConfig, load_config

logger = logging.getLogger(__name__)

PARTITION_FILE = "data.parquet"
REPORT_FILE = "_time_step_report.json"
# Colonnes dont on analyse le pas de temps effectif (instants où la valeur est renseignée).
DEFAULT_STEP_COLUMNS = ("consommation", "prevision_j1", "prevision_j", "nucleaire")


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    quota_remaining: int | None


def export_url(config: IngestionConfig, dataset_id: str, fmt: str = "parquet") -> str:
    return f"{config.base_url}/{dataset_id}/exports/{fmt}"


def download_export(
    dataset_id: str,
    dest: Path,
    config: IngestionConfig | None = None,
    client: httpx.Client | None = None,
    timeout_seconds: float = 600.0,
) -> DownloadResult:
    """Télécharge l'export Parquet complet (1 appel API) vers `dest`, de façon atomique.

    Le fichier est d'abord écrit en `.part` puis renommé : une coupure réseau ne laisse
    jamais un fichier tronqué à la place d'un export valide.
    """
    cfg = config or IngestionConfig()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    owns_client = client is None
    http = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
    try:
        with http.stream("GET", export_url(cfg, dataset_id), params={"timezone": "UTC"}) as response:
            response.raise_for_status()
            remaining = response.headers.get("X-RateLimit-dataset-Remaining")
            with tmp.open("wb") as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)
        os.replace(tmp, dest)
    finally:
        if owns_client:
            http.close()
        tmp.unlink(missing_ok=True)

    quota = int(remaining) if remaining is not None and remaining.isdigit() else None
    logger.info("Export %s téléchargé (%d octets), quota restant : %s", dataset_id, dest.stat().st_size, quota)
    return DownloadResult(path=dest, quota_remaining=quota)


def normalize_export(raw: pd.DataFrame, timezone: str = "Europe/Paris") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Ajoute `ds` (UTC) et supprime les lignes fantômes du passage à l'heure d'été.

    Constaté dans la source : le jour du passage à l'heure d'été, RTE publie aussi les heures
    locales inexistantes 02:00–02:45, que l'API convertit vers les mêmes instants UTC que
    03:00–03:45 → doublons de `date_heure`. Ces lignes fantômes sont retirées ; les vraies
    (03:xx) sont conservées.

    Retourne `(données propres triées par ds, lignes supprimées)`.
    """
    df = raw.copy()
    df["ds"] = pd.to_datetime(df["date_heure"], utc=True)

    local_naive = pd.to_datetime(df["date"].astype(str) + " " + df["heure"].astype(str), format="%Y-%m-%d %H:%M")
    localized = local_naive.dt.tz_localize(
        timezone,
        nonexistent="NaT",
        ambiguous=np.ones(len(df), dtype=bool),  # les heures ambiguës ne sont pas le sujet ici
    )
    nonexistent_local = localized.isna().to_numpy()
    duplicated_ds = df["ds"].duplicated(keep=False).to_numpy()
    phantom = nonexistent_local & duplicated_ds

    dropped = df.loc[phantom].copy()
    clean = df.loc[~phantom]

    remaining_dups = clean["ds"].duplicated(keep="last")
    if remaining_dups.any():
        logger.warning("%d doublons de ds inattendus : conservation de la dernière occurrence", remaining_dups.sum())
        dropped = pd.concat([dropped, clean.loc[remaining_dups]])
        clean = clean.loc[~remaining_dups]

    clean = clean.sort_values("ds").reset_index(drop=True)
    return clean, dropped.sort_values("ds").reset_index(drop=True)


def _mode_step(ds: pd.Series) -> pd.Timedelta | None:
    diffs = ds.sort_values().diff().dropna()
    return None if diffs.empty else diffs.mode().iloc[0]


def _fmt(td: pd.Timedelta | None) -> str | None:
    return None if td is None else f"{int(td.total_seconds() // 60)}min"


def analyze_time_step(df: pd.DataFrame, value_columns: tuple[str, ...] = DEFAULT_STEP_COLUMNS) -> dict[str, Any]:
    """Analyse le pas de temps sur tout l'historique.

    - pas des lignes (`ds`) : valeurs observées, pas dominant par année, trous, doublons ;
    - pas *effectif* de chaque colonne : écart entre instants où la valeur est renseignée
      (une ligne peut exister toutes les 15 min alors que la mesure n'est publiée que toutes les 30 min).
    """
    ds = df["ds"].sort_values().reset_index(drop=True)
    diffs = ds.diff()
    nominal = _mode_step(ds)

    gap_mask = diffs > nominal if nominal is not None else pd.Series(False, index=ds.index)
    gaps = [
        {"after": ds[i - 1].isoformat(), "before": ds[i].isoformat(), "duration": _fmt(diffs[i])}
        for i in ds.index[gap_mask.fillna(False)]
    ]

    by_year = {}
    for year, part in df.groupby(df["ds"].dt.year):
        by_year[str(year)] = {
            "rows": len(part),
            "row_step": _fmt(_mode_step(part["ds"])),
            **{
                f"{col}_step": _fmt(_mode_step(part.loc[part[col].notna(), "ds"]))
                for col in value_columns
                if col in part.columns
            },
        }

    def changes(key: str) -> list[dict[str, str | None]]:
        out, previous = [], None
        for year, stats in by_year.items():
            if stats.get(key) != previous and previous is not None:
                out.append({"year": year, "from": previous, "to": stats.get(key)})
            previous = stats.get(key)
        return out

    effective = {}
    for col in value_columns:
        if col not in df.columns:
            continue
        present = df.loc[df[col].notna(), "ds"]
        effective[col] = {
            "step": _fmt(_mode_step(present)),
            "non_null": int(df[col].notna().sum()),
            "null": int(df[col].isna().sum()),
            "changes_by_year": changes(f"{col}_step"),
        }

    return {
        "rows": len(df),
        "start": ds.iloc[0].isoformat() if len(ds) else None,
        "end": ds.iloc[-1].isoformat() if len(ds) else None,
        "row_step": _fmt(nominal),
        "row_step_counts": {_fmt(k): int(v) for k, v in diffs.dropna().value_counts().items()},
        "row_step_changes_by_year": changes("row_step"),
        "duplicate_ds": int(ds.duplicated().sum()),
        "gaps": gaps,
        "effective_step": effective,
        "by_year": by_year,
    }


def write_partitions(df: pd.DataFrame, root: Path) -> list[Path]:
    """Écrit une partition Parquet par année UTC (`root/year=YYYY/data.parquet`).

    Chaque partition est entièrement réécrite (fichier temporaire puis renommage atomique) :
    relancer le backfill remplace les données au lieu de les dupliquer.
    """
    written = []
    for year, part in df.groupby(df["ds"].dt.year):
        part_dir = root / f"year={year}"
        part_dir.mkdir(parents=True, exist_ok=True)
        target = part_dir / PARTITION_FILE
        tmp = part_dir / (PARTITION_FILE + ".tmp")
        part.to_parquet(tmp, index=False)
        os.replace(tmp, target)
        written.append(target)
    return written


def read_partitions(root: Path) -> pd.DataFrame:
    """Relit toutes les partitions annuelles, triées par `ds`."""
    files = sorted(root.glob(f"year=*/{PARTITION_FILE}"))
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True).sort_values("ds").reset_index(drop=True)


def run_backfill(
    dataset_key: str = "national_cons_def",
    input_path: Path | None = None,
    config: AppConfig | None = None,
) -> dict[str, Any]:
    """Chaîne complète : export (ou fichier local) -> normalisation -> partitions -> rapport."""
    cfg = config or load_config()
    dataset_id = cfg.ingestion.datasets.get(dataset_key, dataset_key)
    raw_root = Path(cfg.storage.data_dir) / cfg.storage.raw_subdir
    out_root = raw_root / dataset_id.replace("-", "_")

    quota = None
    if input_path is None:
        result = download_export(dataset_id, raw_root / "_downloads" / f"{dataset_id}.parquet", cfg.ingestion)
        input_path, quota = result.path, result.quota_remaining

    raw = pd.read_parquet(input_path)
    clean, dropped = normalize_export(raw, timezone=cfg.project.timezone)
    written = write_partitions(clean, out_root)

    report = analyze_time_step(clean)
    report["dataset_id"] = dataset_id
    report["source_rows"] = len(raw)
    report["dropped_dst_phantom_rows"] = [
        {"date": r["date"], "heure": r["heure"], "ds": r["ds"].isoformat()} for _, r in dropped.iterrows()
    ]
    report["nature_by_year"] = {
        str(y): {str(k): int(v) for k, v in g.value_counts().items()}
        for y, g in clean.groupby(clean["ds"].dt.year)["nature"]
    }
    report["partitions"] = [str(p.relative_to(out_root)) for p in written]
    report["api_quota_remaining"] = quota
    (out_root / REPORT_FILE).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def _summary(report: dict[str, Any]) -> str:
    eff = report["effective_step"]
    lines = [
        f"Jeu de données : {report['dataset_id']}",
        f"Lignes source : {report['source_rows']} -> stockées : {report['rows']} "
        f"({len(report['dropped_dst_phantom_rows'])} lignes fantômes DST supprimées)",
        f"Période (UTC) : {report['start']} -> {report['end']}",
        f"Pas des lignes : {report['row_step']} | doublons restants : {report['duplicate_ds']} "
        f"| trous : {len(report['gaps'])}",
        "Pas effectif par colonne : " + ", ".join(f"{c}={v['step']}" for c, v in eff.items()),
        f"Partitions écrites : {len(report['partitions'])} | quota API restant : {report['api_quota_remaining']}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill de l'historique éCO2mix (export Opendatasoft -> Parquet).")
    parser.add_argument("--dataset-key", default="national_cons_def", help="Clé de configs/default.yaml (datasets)")
    parser.add_argument("--input", type=Path, default=None, help="Export Parquet local (aucun appel API)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    report = run_backfill(dataset_key=args.dataset_key, input_path=args.input)
    print(_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

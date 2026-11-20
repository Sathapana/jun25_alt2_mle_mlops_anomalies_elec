"""Audit différé (Niveau 3) : confrontation des alertes Temps Réel (TR) aux données Consolidées (M+1)."""

from __future__ import annotations

from typing import Any

import pandas as pd


def audit_realtime_vs_consolidated(
    realtime_alerts_df: pd.DataFrame,
    consolidated_df: pd.DataFrame,
    revision_tolerance_mw: float = 500.0,
) -> dict[str, Any]:
    """Compare les alertes émises sur le flux temps réel avec les mesures consolidées M+1."""
    if realtime_alerts_df.empty or consolidated_df.empty:
        return {
            "audited_alerts": 0,
            "confirmed_anomalies": 0,
            "telemetry_revision_artifacts": 0,
        }

    rt = realtime_alerts_df.copy()
    cons = consolidated_df[["unique_id", "ds", "y"]].rename(columns={"y": "y_consolidated"}).copy()
    rt["ds"] = pd.to_datetime(rt["ds"], utc=True)
    cons["ds"] = pd.to_datetime(cons["ds"], utc=True)

    merged = rt.merge(cons, on=["unique_id", "ds"], how="inner")
    if merged.empty:
        return {
            "audited_alerts": 0,
            "confirmed_anomalies": 0,
            "telemetry_revision_artifacts": 0,
        }

    revision_delta = (merged["y"] - merged["y_consolidated"]).abs()
    is_artifact = revision_delta > revision_tolerance_mw

    return {
        "audited_alerts": len(merged),
        "confirmed_anomalies": int((~is_artifact).sum()),
        "telemetry_revision_artifacts": int(is_artifact.sum()),
    }

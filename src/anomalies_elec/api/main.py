"""Service REST FastAPI de détection d'anomalies et de qualification d'alertes."""

from __future__ import annotations

import pandas as pd
from fastapi import FastAPI, HTTPException

from anomalies_elec import __version__
from anomalies_elec.api.schemas import (
    AlertItem,
    DetectRequest,
    DetectResponse,
    QualifyAlertRequest,
)
from anomalies_elec.config import load_config
from anomalies_elec.features.calendar_fr import enrich_french_calendar
from anomalies_elec.ingestion.quality import apply_quality_checks
from anomalies_elec.pipelines.detect_flow import run_detection_pipeline
from anomalies_elec.storage.parquet_store import ParquetStore

app = FastAPI(
    title="éCO2mix Anomaly Detection API",
    description="Service MLOps de surveillance du réseau électrique français (RTE éCO2mix)",
    version=__version__,
)


@app.get("/health")
def health() -> dict[str, str]:
    cfg = load_config()
    return {
        "status": "ok",
        "version": __version__,
        "default_scope": cfg.project.default_scope,
    }


def _row_to_alert_item(row: pd.Series) -> AlertItem:
    raw_qual = row.get("qualification")
    qual = None if pd.isna(raw_qual) else str(raw_qual)
    return AlertItem(
        alert_id=str(row["alert_id"]),
        unique_id=str(row["unique_id"]),
        ds=row["ds"],
        y=float(row["y"]),
        y_hat=float(row["y_hat"]),
        residual=float(row["residual"]),
        ewma_error=float(row["ewma_error"]),
        threshold_eps=float(row["threshold_eps"]),
        anomaly_score=float(row["anomaly_score"]),
        is_anomaly=bool(row["is_anomaly"]),
        detector_name=str(row["detector_name"]),
        quality_flag=str(row.get("quality_flag", "OK")),
        qualification=qual,
    )


@app.post("/detect", response_model=DetectResponse)
def detect_anomalies(payload: DetectRequest) -> DetectResponse:
    cfg = load_config()
    raw_df = pd.DataFrame([obs.model_dump() for obs in payload.observations])
    checked_df = apply_quality_checks(raw_df, config=cfg.ingestion, expected_freq=cfg.project.freq)
    enriched_df = enrich_french_calendar(checked_df, timezone=cfg.project.timezone)

    scored_df = run_detection_pipeline(
        enriched_df,
        detector_type=payload.detector_type,
        config=cfg,
        persist_alerts=True,
    )

    anom_df = scored_df.loc[scored_df["is_anomaly"]].copy()
    alerts = [_row_to_alert_item(row) for _, row in anom_df.iterrows()]
    return DetectResponse(
        total_points=len(scored_df),
        anomalies_detected=len(alerts),
        alerts=alerts,
    )


@app.get("/alerts", response_model=list[AlertItem])
def list_alerts(unique_id: str | None = None) -> list[AlertItem]:
    cfg = load_config()
    store = ParquetStore(cfg.storage.data_dir)
    df = store.read_alerts()
    if df.empty:
        return []
    if unique_id:
        df = df.loc[df["unique_id"] == unique_id]

    return [_row_to_alert_item(row) for _, row in df.iterrows()]


@app.post("/alerts/{alert_id}/qualify", response_model=AlertItem)
def qualify_alert(alert_id: str, payload: QualifyAlertRequest) -> AlertItem:
    cfg = load_config()
    store = ParquetStore(cfg.storage.data_dir)
    df = store.read_alerts()
    if df.empty or alert_id not in df["alert_id"].values:
        raise HTTPException(status_code=404, detail=f"Alerte '{alert_id}' introuvable.")

    df["qualification"] = df["qualification"].astype(object)
    df.loc[df["alert_id"] == alert_id, "qualification"] = payload.qualification
    store.upsert_alerts(df)

    row = df.loc[df["alert_id"] == alert_id].iloc[0]
    return _row_to_alert_item(row)

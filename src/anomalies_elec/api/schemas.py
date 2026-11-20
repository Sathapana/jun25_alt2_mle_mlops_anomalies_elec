"""Schémas Pydantic pour l'API FastAPI."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

QualificationLabel = Literal[
    "true_positive",
    "false_positive",
    "seasonal_regime",
    "sensor_fault",
]


class ObservationInput(BaseModel):
    unique_id: str = "FR"
    ds: datetime
    y: float
    prevision_j1: float | None = None
    prevision_j: float | None = None


class DetectRequest(BaseModel):
    detector_type: Literal["mstl", "baseline_rte", "baseline_j7"] = "mstl"
    observations: list[ObservationInput] = Field(min_length=1)


class AlertItem(BaseModel):
    alert_id: str
    unique_id: str
    ds: datetime
    y: float
    y_hat: float
    residual: float
    ewma_error: float
    threshold_eps: float
    anomaly_score: float
    is_anomaly: bool
    detector_name: str
    quality_flag: str = "OK"
    qualification: str | None = None


class DetectResponse(BaseModel):
    total_points: int
    anomalies_detected: int
    alerts: list[AlertItem]


class QualifyAlertRequest(BaseModel):
    qualification: QualificationLabel
    comment: str | None = None

"""Tests d'intégration pour l'API FastAPI (Pôle P3)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from anomalies_elec.api.main import app


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    cfg_file = tmp_path / "test_config.yaml"
    cfg_file.write_text(
        f"storage:\n  data_dir: '{tmp_path.as_posix()}'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ANOMALIES_ELEC_CONFIG_PATH", str(cfg_file))
    return TestClient(app)


def test_health_endpoint(api_client: TestClient) -> None:
    response = api_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_detect_and_qualify_alert_flow(
    api_client: TestClient,
    synthetic_eco2mix_df: pd.DataFrame,
) -> None:
    subset = synthetic_eco2mix_df.iloc[100:180].copy()
    observations = [
        {
            "unique_id": str(row["unique_id"]),
            "ds": row["ds"].isoformat(),
            "y": float(row["y"]),
            "prevision_j1": float(row["prevision_j1"]),
            "prevision_j": float(row["prevision_j"]),
        }
        for _, row in subset.iterrows()
    ]

    resp = api_client.post(
        "/detect",
        json={"detector_type": "baseline_rte", "observations": observations},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_points"] == 80
    assert body["anomalies_detected"] >= 1

    alert_id = body["alerts"][0]["alert_id"]

    # Qualification humaine de l'alerte (Niveau 3)
    qual_resp = api_client.post(
        f"/alerts/{alert_id}/qualify",
        json={"qualification": "true_positive", "comment": "Pic validé par l'opérateur"},
    )
    assert qual_resp.status_code == 200
    assert qual_resp.json()["qualification"] == "true_positive"

    # Vérification via GET /alerts
    list_resp = api_client.get("/alerts")
    assert list_resp.status_code == 200
    assert any(a["alert_id"] == alert_id and a["qualification"] == "true_positive" for a in list_resp.json())

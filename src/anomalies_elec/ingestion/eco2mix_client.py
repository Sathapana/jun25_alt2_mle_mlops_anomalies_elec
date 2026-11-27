"""Client HTTP pour l'API Opendatasoft éCO2mix v2.1 avec garde-fou de quota."""

from __future__ import annotations

from typing import Any

import httpx
import pandas as pd

from anomalies_elec.config import IngestionConfig


class QuotaExceededError(RuntimeError):
    """Erreur levée lorsque le budget d'appels API mensuel est atteint."""


class Eco2MixClient:
    """Client d'ingestion des jeux de données éCO2mix (temps réel & consolidé)."""

    def __init__(
        self,
        config: IngestionConfig | None = None,
        api_calls_used: int = 0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config or IngestionConfig()
        self.api_calls_used = api_calls_used
        # Client HTTP injectable (tests : httpx.MockTransport) ; sinon un client est créé à chaque appel.
        self.http_client = http_client
        self.last_quota_remaining: int | None = None

    def _check_and_increment_quota(self) -> None:
        if self.api_calls_used >= self.config.monthly_quota_limit:
            raise QuotaExceededError(f"Quota mensuel Opendatasoft atteint ({self.config.monthly_quota_limit} appels).")
        self.api_calls_used += 1

    def fetch_records(
        self,
        dataset_key: str = "national_tr",
        where: str | None = None,
        limit: int | None = None,
        unique_id: str = "FR",
    ) -> pd.DataFrame:
        """Récupère une page d'enregistrements éCO2mix et normalise au contrat P1."""
        results = self.fetch_raw_records(dataset_key=dataset_key, where=where, limit=limit)
        return self.normalize_records(results, default_unique_id=unique_id)

    def fetch_raw_records(
        self,
        dataset_key: str = "national_tr",
        where: str | None = None,
        limit: int | None = None,
        select: str | None = None,
    ) -> list[dict[str, Any]]:
        """Récupère une page brute de `/records` (1 appel API), horodatages en UTC, sans transformation.

        Le quota restant renvoyé par l'API est conservé dans `last_quota_remaining`.
        """
        self._check_and_increment_quota()
        dataset_id = self.config.datasets.get(dataset_key, dataset_key)
        url = f"{self.config.base_url}/{dataset_id}/records"
        params: dict[str, Any] = {
            "limit": limit or self.config.page_size,
            "order_by": "date_heure ASC",
            "timezone": "UTC",
        }
        if where:
            params["where"] = where
        if select:
            params["select"] = select

        if self.http_client is not None:
            response = self.http_client.get(url, params=params)
        else:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, params=params)
        response.raise_for_status()

        remaining = response.headers.get("X-RateLimit-dataset-Remaining")
        self.last_quota_remaining = int(remaining) if remaining and remaining.isdigit() else None
        return list(response.json().get("results", []))

    @staticmethod
    def normalize_records(
        records: list[dict[str, Any]],
        default_unique_id: str = "FR",
    ) -> pd.DataFrame:
        """Transforme les dictionnaires JSON Opendatasoft au schéma standardisé P1 -> P2."""
        if not records:
            return pd.DataFrame(columns=["unique_id", "ds", "y", "prevision_j1", "prevision_j"])

        raw_df = pd.DataFrame(records)
        df = pd.DataFrame()
        if "code_insee_region" in raw_df.columns:
            df["unique_id"] = raw_df["code_insee_region"].fillna(default_unique_id).astype(str)
        else:
            df["unique_id"] = default_unique_id

        df["ds"] = pd.to_datetime(raw_df["date_heure"], utc=True)
        df["y"] = pd.to_numeric(raw_df.get("consommation"), errors="coerce")
        df["prevision_j1"] = pd.to_numeric(raw_df.get("prevision_j1"), errors="coerce")
        df["prevision_j"] = pd.to_numeric(raw_df.get("prevision_j"), errors="coerce")

        return df.sort_values(["unique_id", "ds"]).reset_index(drop=True)

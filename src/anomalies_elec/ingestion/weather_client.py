"""Client Open-Meteo, alignement 15 min UTC, agrégation pondérée et backfill historique."""

from __future__ import annotations

import argparse
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pandas as pd

from anomalies_elec.config import AppConfig, WeatherConfig, WeatherLocationConfig, load_config
from anomalies_elec.storage.base import get_store

_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _parse_iso_date(value: str | date) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value)[:10])


def _extract_max_allowed_date(reason: str) -> date | None:
    """Extrait la date maximale autorisée depuis un message d'erreur 400 Open-Meteo."""
    matches = _DATE_RE.findall(reason or "")
    if not matches:
        return None
    return _parse_iso_date(matches[-1])


class OpenMeteoClient:
    """Client HTTP pour l'API Archive d'Open-Meteo (sans clé API)."""

    def __init__(self, config: WeatherConfig | None = None) -> None:
        self.config = config or WeatherConfig()

    @staticmethod
    def _split_date_chunks(
        start_date: str | date,
        end_date: str | date,
        max_days: int = 365,
    ) -> list[tuple[str, str]]:
        """Découpe un intervalle de dates inclusif en sous-fenêtres de `max_days` jours max."""
        start = _parse_iso_date(start_date)
        end = _parse_iso_date(end_date)
        if start > end:
            return []

        step = max(1, int(max_days))
        chunks: list[tuple[str, str]] = []
        cursor = start
        while cursor <= end:
            chunk_end = min(end, cursor + timedelta(days=step - 1))
            chunks.append((cursor.isoformat(), chunk_end.isoformat()))
            cursor = chunk_end + timedelta(days=1)
        return chunks

    @staticmethod
    def _parse_archive_payload(
        payload: dict[str, Any] | list[dict[str, Any]],
        locations: list[WeatherLocationConfig],
    ) -> pd.DataFrame:
        """Convertit la réponse JSON Open-Meteo (mono ou multi-villes) en DataFrame normalisé."""
        items = [payload] if isinstance(payload, dict) else list(payload)
        frames: list[pd.DataFrame] = []
        for idx, item in enumerate(items):
            if idx >= len(locations):
                break
            loc = locations[idx]
            hourly = item.get("hourly") or {}
            times = hourly.get("time") or []
            temps = hourly.get("temperature_2m") or []
            if not times or not temps:
                continue
            df = pd.DataFrame(
                {
                    "unique_id": loc.unique_id,
                    "ds": pd.to_datetime(times, utc=True),
                    "temperature_2m": pd.to_numeric(temps, errors="coerce"),
                }
            ).dropna(subset=["temperature_2m"])
            if not df.empty:
                frames.append(df)

        if not frames:
            return pd.DataFrame(columns=["unique_id", "ds", "temperature_2m"])
        return pd.concat(frames, ignore_index=True)

    def _request_chunk(
        self,
        client: httpx.Client,
        chunk_start: str,
        chunk_end: str,
        locations: list[WeatherLocationConfig],
    ) -> tuple[dict[str, Any] | list[dict[str, Any]] | None, date | None]:
        """Exécute une requête chunk vers Open-Meteo avec gestion de la borne max_date (HTTP 400)."""
        params = {
            "latitude": ",".join(f"{loc.latitude:.4f}" for loc in locations),
            "longitude": ",".join(f"{loc.longitude:.4f}" for loc in locations),
            "start_date": chunk_start,
            "end_date": chunk_end,
            "hourly": "temperature_2m",
            "timezone": "UTC",
        }
        response = client.get(self.config.archive_url, params=params)
        if response.status_code == 400:
            reason = ""
            try:
                reason = str(response.json().get("reason", ""))
            except Exception:
                reason = response.text
            max_date = _extract_max_allowed_date(reason)
            if max_date is not None:
                start_d = _parse_iso_date(chunk_start)
                if start_d > max_date:
                    return None, max_date
                clamped_end = min(_parse_iso_date(chunk_end), max_date).isoformat()
                if clamped_end != chunk_end:
                    params["end_date"] = clamped_end
                    retry_resp = client.get(self.config.archive_url, params=params)
                    retry_resp.raise_for_status()
                    return retry_resp.json(), max_date
        response.raise_for_status()
        return response.json(), None

    def fetch_hourly_archive(
        self,
        start_date: str | date,
        end_date: str | date,
        locations: list[WeatherLocationConfig] | None = None,
    ) -> pd.DataFrame:
        """Collecte les températures horaires UTC depuis Open-Meteo Archive pour les villes configurées."""
        locs = locations or self.config.locations
        if not locs:
            return pd.DataFrame(columns=["unique_id", "ds", "temperature_2m"])

        chunks = self._split_date_chunks(start_date, end_date, max_days=self.config.max_days_per_chunk)
        if not chunks:
            return pd.DataFrame(columns=["unique_id", "ds", "temperature_2m"])

        frames: list[pd.DataFrame] = []
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            for chunk_start, chunk_end in chunks:
                payload, max_date = self._request_chunk(client, chunk_start, chunk_end, locs)
                if payload is not None:
                    parsed = self._parse_archive_payload(payload, locs)
                    if not parsed.empty:
                        frames.append(parsed)
                if max_date is not None and _parse_iso_date(chunk_end) >= max_date:
                    break

        if not frames:
            return pd.DataFrame(columns=["unique_id", "ds", "temperature_2m"])

        combined = pd.concat(frames, ignore_index=True)
        return (
            combined.drop_duplicates(subset=["unique_id", "ds"], keep="last")
            .sort_values(["unique_id", "ds"])
            .reset_index(drop=True)
        )


def align_weather_to_15min_utc(hourly_df: pd.DataFrame, freq: str = "15min") -> pd.DataFrame:
    """Aligne les températures horaires sur la grille 15 min UTC par interpolation linéaire temporelle."""
    if hourly_df.empty:
        return pd.DataFrame(columns=["unique_id", "ds", "temperature_2m"])

    df = hourly_df[["unique_id", "ds", "temperature_2m"]].copy()
    df["unique_id"] = df["unique_id"].astype(str)
    df["ds"] = pd.to_datetime(df["ds"], utc=True)
    df["temperature_2m"] = pd.to_numeric(df["temperature_2m"], errors="coerce")
    df = df.dropna(subset=["ds", "temperature_2m"])
    if df.empty:
        return pd.DataFrame(columns=["unique_id", "ds", "temperature_2m"])

    aligned_parts: list[pd.DataFrame] = []
    for uid, group in df.groupby("unique_id", sort=True):
        series_df = group.sort_values("ds").drop_duplicates(subset=["ds"], keep="last").set_index("ds")
        min_ds = series_df.index.min()
        max_ds = series_df.index.max() + pd.Timedelta(minutes=45)
        grid = pd.date_range(start=min_ds, end=max_ds, freq=freq, tz="UTC")
        upsampled = series_df[["temperature_2m"]].reindex(grid).interpolate(method="time").ffill().bfill()
        aligned_parts.append(
            pd.DataFrame(
                {
                    "unique_id": str(uid),
                    "ds": grid,
                    "temperature_2m": upsampled["temperature_2m"].to_numpy(dtype=float),
                }
            )
        )

    return pd.concat(aligned_parts, ignore_index=True).sort_values(["unique_id", "ds"]).reset_index(drop=True)


def compute_population_weighted_national(
    regional_15min_df: pd.DataFrame,
    locations: list[WeatherLocationConfig],
    national_unique_id: str = "FR",
) -> pd.DataFrame:
    """Calcule la température nationale pondérée par la population à partir des séries régionales."""
    if regional_15min_df.empty or not locations:
        return pd.DataFrame(columns=["unique_id", "ds", "temperature_2m"])

    weights_map = {loc.unique_id: float(loc.weight) for loc in locations if loc.weight > 0}
    df = regional_15min_df.copy()
    df["ds"] = pd.to_datetime(df["ds"], utc=True)
    df["weight"] = df["unique_id"].map(weights_map)
    df = df.dropna(subset=["weight", "temperature_2m"])
    if df.empty:
        return pd.DataFrame(columns=["unique_id", "ds", "temperature_2m"])

    df["weighted_temp"] = df["temperature_2m"] * df["weight"]
    grouped = df.groupby("ds", as_index=False)[["weighted_temp", "weight"]].sum()
    grouped["temperature_2m"] = grouped["weighted_temp"] / grouped["weight"]
    grouped["unique_id"] = national_unique_id
    return grouped[["unique_id", "ds", "temperature_2m"]].sort_values("ds").reset_index(drop=True)


def join_weather_to_series(
    series_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    default_unique_id: str = "FR",
) -> pd.DataFrame:
    """Effectue une jointure gauche de `temperature_2m` sur `(unique_id, ds)` ou `ds` UTC."""
    if series_df.empty:
        out = series_df.copy()
        if "temperature_2m" not in out.columns:
            out["temperature_2m"] = pd.Series(dtype="float64")
        return out

    left = series_df.copy()
    left["ds"] = pd.to_datetime(left["ds"], utc=True)
    if weather_df.empty:
        left["temperature_2m"] = float("nan")
        return left

    if "unique_id" in left.columns:
        right = weather_df[["unique_id", "ds", "temperature_2m"]].copy()
        right["ds"] = pd.to_datetime(right["ds"], utc=True)
        right = right.drop_duplicates(subset=["unique_id", "ds"], keep="last")
        return left.merge(right, on=["unique_id", "ds"], how="left")

    right = weather_df.copy()
    if "unique_id" in right.columns:
        right = right.loc[right["unique_id"] == default_unique_id]
    right = right[["ds", "temperature_2m"]].copy()
    right["ds"] = pd.to_datetime(right["ds"], utc=True)
    right = right.drop_duplicates(subset=["ds"], keep="last")
    return left.merge(right, on=["ds"], how="left")


def backfill_weather(
    start_date: str | None = None,
    end_date: str | None = None,
    include_extra_windows: bool = True,
    config: AppConfig | None = None,
) -> pd.DataFrame:
    """Backfill historique Open-Meteo (FR pondéré + 12 régions), aligné 15 min UTC et stocké."""
    cfg = config or load_config()
    client = OpenMeteoClient(cfg.weather)
    store = get_store(cfg.storage)

    today_utc = datetime.now(UTC).date().isoformat()
    windows: list[tuple[str, str]] = []
    if start_date is None and end_date is None:
        if include_extra_windows:
            windows.extend((w[0], w[1]) for w in cfg.weather.extra_windows)
        windows.append((cfg.weather.default_start_date, today_utc))
    else:
        windows.append((start_date or cfg.weather.default_start_date, end_date or today_utc))

    all_frames: list[pd.DataFrame] = []
    for win_start, win_end in windows:
        hourly_df = client.fetch_hourly_archive(win_start, win_end, locations=cfg.weather.locations)
        if hourly_df.empty:
            continue
        regional_15m = align_weather_to_15min_utc(hourly_df, freq=cfg.project.freq)
        national_15m = compute_population_weighted_national(
            regional_15m,
            locations=cfg.weather.locations,
            national_unique_id=cfg.project.default_unique_id,
        )
        combined = pd.concat([national_15m, regional_15m], ignore_index=True)
        store.upsert_weather(combined, layer=cfg.storage.processed_subdir, name="weather")
        all_frames.append(combined)

    if not all_frames:
        return pd.DataFrame(columns=["unique_id", "ds", "temperature_2m"])

    return (
        pd.concat(all_frames, ignore_index=True)
        .drop_duplicates(subset=["unique_id", "ds"], keep="last")
        .sort_values(["unique_id", "ds"])
        .reset_index(drop=True)
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Backfill historique Open-Meteo (15 min UTC).")
    parser.add_argument("--start-date", default=None, help="Date de début (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=None, help="Date de fin (YYYY-MM-DD)")
    parser.add_argument(
        "--no-extra-windows",
        action="store_true",
        help="Ne pas inclure les fenêtres historiques supplémentaires (ex: vague de froid 2012)",
    )
    parser.add_argument("--config", default=None, help="Chemin vers le fichier YAML de configuration")
    args = parser.parse_args(argv)

    cfg = load_config(args.config) if args.config else load_config()
    df = backfill_weather(
        start_date=args.start_date,
        end_date=args.end_date,
        include_extra_windows=not args.no_extra_windows,
        config=cfg,
    )
    if df.empty:
        print("Aucune donnée météo collectée.")
        return

    print(
        f"Backfill météo terminé : {len(df)} lignes, "
        f"{df['unique_id'].nunique()} séries ({sorted(df['unique_id'].unique())}), "
        f"plage UTC {df['ds'].min()} -> {df['ds'].max()}."
    )


if __name__ == "__main__":
    main()

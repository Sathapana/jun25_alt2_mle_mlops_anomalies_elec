"""Enrichissement calendaire français (jours fériés, ponts, changements d'heure)."""

from __future__ import annotations

from datetime import date, timedelta

import holidays
import pandas as pd


def enrich_french_calendar(
    df: pd.DataFrame,
    timezone: str = "Europe/Paris",
) -> pd.DataFrame:
    """Ajoute les indicateurs calendaires français (`is_holiday_fr`, `is_bridge_day`, `is_dst_transition`)."""
    if df.empty:
        out = df.copy()
        out["is_holiday_fr"] = pd.Series(dtype=bool)
        out["is_bridge_day"] = pd.Series(dtype=bool)
        out["is_dst_transition"] = pd.Series(dtype=bool)
        return out

    out = df.copy()
    ds_utc = pd.to_datetime(out["ds"], utc=True)
    ds_local = ds_utc.dt.tz_convert(timezone)

    years = sorted(ds_local.dt.year.unique().tolist())
    fr_holidays = holidays.country_holidays("FR", years=years)
    holiday_dates: set[date] = set(fr_holidays.keys())

    local_dates = ds_local.dt.date
    out["is_holiday_fr"] = local_dates.isin(holiday_dates)

    # Jour de pont : Lundi si Mardi est férié, ou Vendredi si Jeudi est férié (et non férié lui-même)
    weekdays = ds_local.dt.day_of_week  # 0=Lundi ... 4=Vendredi
    next_day_is_holiday = local_dates.map(lambda d: (d + timedelta(days=1)) in holiday_dates)
    prev_day_is_holiday = local_dates.map(lambda d: (d - timedelta(days=1)) in holiday_dates)

    is_monday_bridge = (weekdays == 0) & next_day_is_holiday & (~out["is_holiday_fr"])
    is_friday_bridge = (weekdays == 4) & prev_day_is_holiday & (~out["is_holiday_fr"])
    out["is_bridge_day"] = is_monday_bridge | is_friday_bridge

    # Changement d'heure été/hiver : jour local où le décalage UTC change par rapport à la veille
    utc_offsets = ds_local.map(lambda ts: ts.utcoffset())
    day_offsets = pd.DataFrame({"local_date": local_dates, "offset": utc_offsets}).drop_duplicates(
        subset=["local_date"]
    )
    day_offsets["offset_changed"] = day_offsets["offset"] != day_offsets["offset"].shift(1)
    if not day_offsets.empty:
        day_offsets.iloc[0, day_offsets.columns.get_loc("offset_changed")] = False

    # Aussi détecter si plusieurs offsets coexistent sur la même date locale
    offsets_per_day = (
        pd.DataFrame({"local_date": local_dates, "offset": utc_offsets}).groupby("local_date")["offset"].nunique()
    )
    dst_dates = set(offsets_per_day[offsets_per_day > 1].index).union(
        set(day_offsets.loc[day_offsets["offset_changed"], "local_date"])
    )
    out["is_dst_transition"] = local_dates.isin(dst_dates)

    return out

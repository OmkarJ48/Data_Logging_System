"""Shared parsing and filename helpers for report generation."""

from __future__ import annotations

import re

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype


LEGACY_REPORT_DATETIME_FORMAT = "%d/%m/%Y %H:%M:%S.%f"
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')


def coerce_report_datetimes(values) -> pd.Series:
    """Parse report datetimes from mixed legacy and ISO-style inputs."""

    if isinstance(values, pd.Series):
        series = values.copy()
    else:
        series = pd.Series(values)

    if is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce").astype("datetime64[ns]")

    parsed = pd.to_datetime(
        series,
        format=LEGACY_REPORT_DATETIME_FORMAT,
        errors="coerce",
        dayfirst=True,
    ).astype("datetime64[ns]")

    non_empty = series.notna() & series.astype(str).str.strip().ne("")
    fallback_mask = parsed.isna() & non_empty
    if fallback_mask.any():
        parsed.loc[fallback_mask] = pd.to_datetime(
            series.loc[fallback_mask],
            format="ISO8601",
            errors="coerce",
        ).astype("datetime64[ns]")

    fallback_mask = parsed.isna() & non_empty
    if fallback_mask.any():
        parsed.loc[fallback_mask] = pd.to_datetime(
            series.loc[fallback_mask],
            errors="coerce",
            dayfirst=True,
        ).astype("datetime64[ns]")

    return parsed


def coerce_report_datetime(value) -> pd.Timestamp:
    """Parse a single report datetime value."""

    return coerce_report_datetimes(pd.Series([value])).iloc[0]


def sanitise_report_filename_component(value, *, default: str) -> str:
    """Return a Windows-safe filename component for generated reports."""

    text = "" if value is None else str(value).strip()
    text = INVALID_FILENAME_CHARS.sub("_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or default

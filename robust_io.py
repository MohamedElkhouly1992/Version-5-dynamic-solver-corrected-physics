from __future__ import annotations

"""Robust tabular I/O helpers for cloud and DesignBuilder-origin files.

These helpers intentionally do not modify model equations or validation logic.
They only make ingestion deterministic across common CSV encodings/delimiters and
record detected parsing metadata in ``DataFrame.attrs``.
"""

from io import BytesIO
from pathlib import Path
from typing import Any
import csv

import pandas as pd

ENCODINGS = ("utf-8-sig", "utf-8", "utf-16", "utf-16-le", "utf-16-be", "cp1252", "latin1")
DELIMITERS = (",", ";", "\t", "|")


def _read_bytes(source: Any) -> bytes:
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    if hasattr(source, "getvalue"):
        value = source.getvalue()
        return value if isinstance(value, bytes) else str(value).encode("utf-8")
    if hasattr(source, "read"):
        try:
            source.seek(0)
        except Exception:
            pass
        value = source.read()
        try:
            source.seek(0)
        except Exception:
            pass
        return value if isinstance(value, bytes) else str(value).encode("utf-8")
    raise TypeError(f"Unsupported tabular input type: {type(source).__name__}")


def _candidate_delimiters(text: str) -> list[str]:
    sample = text[:65536]
    guessed: list[str] = []
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=DELIMITERS)
        guessed.append(dialect.delimiter)
    except Exception:
        pass
    for delim in DELIMITERS:
        if delim not in guessed:
            guessed.append(delim)
    return guessed


def read_csv_robust(source: Any, *, return_metadata: bool = False, **kwargs):
    """Read a CSV/text table with encoding and delimiter fallbacks.

    Parameters accepted by ``pandas.read_csv`` can be passed in ``kwargs``.
    If ``sep``/``delimiter`` is supplied, delimiter auto-detection is skipped.
    The returned DataFrame stores ``csv_encoding`` and ``csv_delimiter`` attrs.
    """
    raw = _read_bytes(source)
    last_error: Exception | None = None
    requested_sep = kwargs.pop("sep", kwargs.pop("delimiter", None))

    for enc in ENCODINGS:
        try:
            text = raw.decode(enc)
        except Exception as exc:
            last_error = exc
            continue
        delimiters = [requested_sep] if requested_sep is not None else _candidate_delimiters(text)
        for delim in delimiters:
            try:
                local_kwargs = dict(kwargs)
                # Python parser is more tolerant for exported engineering tables.
                local_kwargs.setdefault("engine", "python")
                df = pd.read_csv(BytesIO(raw), encoding=enc, sep=delim, **local_kwargs)
                # Reject obvious one-column mis-parses when another delimiter is likely.
                if requested_sep is None and df.shape[1] <= 1:
                    continue
                df.attrs["csv_encoding"] = enc
                df.attrs["csv_delimiter"] = "TAB" if delim == "\t" else str(delim)
                meta = {"encoding": enc, "delimiter": df.attrs["csv_delimiter"]}
                return (df, meta) if return_metadata else df
            except Exception as exc:
                last_error = exc

    # Final permissive fallback: latin1 cannot fail decoding; allow a one-column table.
    try:
        df = pd.read_csv(BytesIO(raw), encoding="latin1", sep=requested_sep or None, engine="python", **kwargs)
        df.attrs["csv_encoding"] = "latin1"
        df.attrs["csv_delimiter"] = str(requested_sep or "auto")
        meta = {"encoding": "latin1", "delimiter": df.attrs["csv_delimiter"]}
        return (df, meta) if return_metadata else df
    except Exception as exc:
        last_error = exc
    raise ValueError(f"Could not parse CSV/text file with supported encodings and delimiters. Last error: {last_error}")


def read_table_auto(source: Any, filename: str | None = None, **kwargs) -> pd.DataFrame:
    name = (filename or getattr(source, "name", "")).lower()
    if name.endswith(".xlsx"):
        if hasattr(source, "seek"):
            source.seek(0)
        return pd.read_excel(source, **kwargs)
    if name.endswith(".parquet"):
        if hasattr(source, "seek"):
            source.seek(0)
        return pd.read_parquet(source, **kwargs)
    return read_csv_robust(source, **kwargs)

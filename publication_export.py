from __future__ import annotations

"""Publication-oriented export helpers.

This module packages results without changing any validation procedure or solver
calculation. It preserves raw precision, creates rounded manuscript tables, and
records software/provenance metadata for reproducibility.
"""

from datetime import datetime, timezone
from pathlib import Path
from io import BytesIO
import importlib.metadata as md
import json
import platform
import zipfile

import pandas as pd


def software_manifest(extra: dict | None = None) -> dict:
    pkgs = ["streamlit","numpy","pandas","scipy","scikit-learn","SALib","pyarrow","matplotlib","plotly","shap"]
    versions={}
    for p in pkgs:
        try: versions[p]=md.version(p)
        except Exception: versions[p]="not-installed"
    out={
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": versions,
    }
    if extra: out.update(extra)
    return out


def _safe_sheet(name: str, used: set[str]) -> str:
    base="".join(c if c.isalnum() or c in " _-" else "_" for c in name)[:31] or "Sheet"
    candidate=base; i=2
    while candidate in used:
        suffix=f"_{i}"; candidate=base[:31-len(suffix)]+suffix; i+=1
    used.add(candidate); return candidate


def _round_publication(df: pd.DataFrame, digits: int = 5) -> pd.DataFrame:
    out=df.copy()
    for c in out.select_dtypes(include="number").columns:
        out[c]=out[c].round(digits)
    return out


def make_publication_bundle(tables: dict[str,pd.DataFrame], figures: dict[str,dict[str,bytes]] | None = None,
                            metadata: dict | None = None, parameter_ranges: pd.DataFrame | None = None,
                            rounding_digits: int = 5) -> bytes:
    figures=figures or {}; metadata=metadata or {}
    bio=BytesIO()
    workbook=BytesIO(); used=set()
    with pd.ExcelWriter(workbook, engine="xlsxwriter") as writer:
        for name,df in tables.items():
            if isinstance(df,pd.DataFrame) and not df.empty and len(df)<=1_000_000:
                _round_publication(df,rounding_digits).to_excel(writer,index=False,sheet_name=_safe_sheet(name,used))
        if parameter_ranges is not None and not parameter_ranges.empty:
            parameter_ranges.to_excel(writer,index=False,sheet_name=_safe_sheet("parameter_ranges",used))
    with zipfile.ZipFile(bio,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("publication_results.xlsx", workbook.getvalue())
        for name,df in tables.items():
            if not isinstance(df,pd.DataFrame): continue
            z.writestr(f"tables_raw/{name}.csv", df.to_csv(index=False).encode("utf-8-sig"))
            z.writestr(f"tables_publication/{name}.csv", _round_publication(df,rounding_digits).to_csv(index=False).encode("utf-8-sig"))
        for name,item in figures.items():
            if item.get("png"): z.writestr(f"figures/{name}.png", item["png"])
            if item.get("svg"): z.writestr(f"figures/{name}.svg", item["svg"])
        if parameter_ranges is not None:
            z.writestr("metadata/parameter_ranges.csv", parameter_ranges.to_csv(index=False).encode("utf-8-sig"))
        z.writestr("metadata/run_manifest.json", json.dumps(software_manifest(metadata),indent=2,default=str).encode("utf-8"))
        z.writestr("METHODS_REPRODUCIBILITY_NOTES.md", (
            "# DA-HVAC reproducibility package\n\n"
            "- `tables_raw/` preserves full numeric precision.\n"
            "- `tables_publication/` contains rounded manuscript-facing copies only.\n"
            "- `publication_results.xlsx` combines manageable result tables.\n"
            "- `metadata/run_manifest.json` records the software environment and supplied run metadata.\n"
            "- This export utility does not alter the solver or the project's existing validation strategy.\n"
        ).encode("utf-8"))
    return bio.getvalue()


def bundle_existing_run(folder: str | Path, metadata: dict | None = None, rounding_digits: int = 5) -> bytes:
    folder=Path(folder)
    tables={}
    for p in sorted(folder.rglob("*.csv")):
        if p.stat().st_size > 80*1024*1024: continue
        try: tables[p.stem]=pd.read_csv(p,low_memory=False)
        except Exception: continue
    figures={}
    for p in folder.rglob("*.png"):
        if p.stat().st_size < 30*1024*1024:
            figures.setdefault(p.stem,{})["png"]=p.read_bytes()
    for p in folder.rglob("*.svg"):
        if p.stat().st_size < 30*1024*1024:
            figures.setdefault(p.stem,{})["svg"]=p.read_bytes()
    return make_publication_bundle(tables,figures,metadata=metadata,rounding_digits=rounding_digits)

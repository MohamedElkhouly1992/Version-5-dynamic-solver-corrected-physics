# Patch summary — 2026-08-18

Applied to Version-5 dynamic solver while preserving the existing Model Validation strategy/calculations.

## Applied
- Python 3.12 / Streamlit Cloud dependency hardening with compatible PyArrow pin.
- `packages.txt` with `libgomp1` and `.streamlit/config.toml`.
- Robust CSV/text import across UTF-8/UTF-16/Windows-1252/Latin-1 and comma/semicolon/tab/pipe delimiters.
- Streamlit API migration from deprecated `use_container_width` to `width`.
- Publication-ready result packaging: raw tables, rounded manuscript tables, Excel workbook, figures, software/run manifest.
- Equal-budget optimizer benchmark in Sensitivity Studio: IESS, DE, PSO, CEM with Friedman/Wilcoxon statistics.
- Preflight environment checker.
- Sensitivity Studio PNG figure export increased to 600 dpi while retaining SVG vector export.
- Repaired the missing `examples/demo_sensitivity_adapter.py` packaging path used by the smoke test.
- Removed the stale embedded pre-patch deployment ZIP to avoid accidental deployment of unfixed code.
- Existing Morris/Sobol, robustness, ablation, dynamic solver, degradation logic, strategy tools, and exports retained.

## Explicitly not changed
- Model Validation strategy, validation equations, metric definitions, or validation interpretation.

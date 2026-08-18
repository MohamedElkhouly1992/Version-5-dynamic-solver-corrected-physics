# Version-5 Dynamic Solver — patched deployment

This package preserves the existing solver and **preserves the existing Model Validation strategy/calculations**.

## Streamlit Cloud
- Main file: `streamlit_app.py`
- Python: `3.12`
- Keep `requirements.txt`, `packages.txt`, `.python-version`, and `.streamlit/config.toml` in the repository root.

## Local
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python PRECHECK.py
python -m streamlit run streamlit_app.py
```

## Sensitivity Studio
```bash
python -m streamlit run sensitivity_studio_app.py
```
The studio includes Morris, Sobol, robustness, ablation/connectivity checks, existing optimizer robustness, and the added equal-budget IESS/DE/PSO/CEM benchmark.

## Publication export
- Main app → **Exports** → **Publication-ready reproducibility package**.
- Sensitivity Studio → **Export Center** → **Publication package**.

The package contains raw full-precision tables, rounded manuscript tables, an Excel workbook, PNG/SVG figures, parameter ranges, and a software/run manifest.

## Robust CSV import
External CSV/text uploads now support common UTF-8, UTF-16, Windows-1252/Latin-1 encodings and comma/semicolon/tab/pipe delimiters.

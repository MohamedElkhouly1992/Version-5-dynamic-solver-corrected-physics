# HVAC v3 Sensitivity Studio

A dataset-independent Streamlit system for local sensitivity, global sensitivity, uncertainty, robustness, benchmark, and ablation analysis of the latest HVAC v3 reduced-order model.

## Scientific scope

This package does **not** use `ChillerPlant.csv`, any prepared plant-data cache, or a chiller-plant surrogate. Every analysis calls the user’s current HVAC v3 numerical model through `sensitivity_adapter.py`.

The software includes:

- baseline S0–S3 strategy–severity matrix;
- benchmark cases;
- signed one-at-a-time (OAT) local sensitivity;
- paired Monte Carlo uncertainty and strategy-ranking robustness;
- S3 ablation analysis;
- Morris global screening;
- Sobol first- and total-order global sensitivity indices with bootstrap confidence intervals;
- S3 optimizer seed/population/iteration robustness;
- parameter-connectivity diagnostics;
- separate CSV/JSON downloads for each table;
- separate PNG/SVG downloads for each figure;
- one ZIP containing all generated results.

## Package files

- `sensitivity_studio_app.py` — Streamlit interface.
- `sensitivity_core.py` — analysis engine.
- `sensitivity_adapter_template.py` — adapter to connect the latest HVAC v3 numerical engine.
- `examples/demo_sensitivity_adapter.py` — synthetic software smoke-test only; not a scientific result.
- `requirements.txt` — Python dependencies.
- `run_app.bat` and `run_app.sh` — launch scripts.

## Required model adapter

The app does not assume the signature of your current `run_scenario_model`. Instead, place a small `sensitivity_adapter.py` in the same project as `hvac_v3.py` and its engine modules.

The adapter must define:

```python
def sensitivity_parameter_specs() -> list[dict]:
    ...


def sensitivity_adapter_run(
    parameters: dict[str, float],
    strategy: str,
    severity: str,
    options: dict[str, bool],
    seed: int,
) -> dict[str, float]:
    ...
```

The runner must return scalar summary outputs, for example:

```python
{
    "total_energy_MWh": 10850.2,
    "mean_chiller_COP": 3.91,
    "mean_residual_delta": 0.284,
    "occupied_discomfort_days": 17,
    "filter_replacements": 3,
    "hx_cleanings": 2,
    "maintenance_events": 5,
    "total_cost_USD": 1304024.0,
    "co2_tonne": 5826.5,
}
```

Use `sensitivity_adapter_template.py` as the starting point.

## Recommended HVAC v3 project structure

```text
HVAC_v3_project/
├── hvac_v3.py                    # Streamlit app, if retained
├── hvac_v3_engine.py             # numerical model
├── sensitivity_adapter.py        # completed adapter
├── weather_or_schedule_files/... # only if the model normally requires them
└── other project modules
```

Zip the whole `HVAC_v3_project` directory and upload it through the **Model connection** panel. The app executes uploaded Python code, so only upload trusted files.

## How the analyses work

### Baseline matrix

Runs each selected strategy under each selected severity using the baseline parameter vector.

### Benchmark cases

Runs predefined cases supplied by `sensitivity_benchmark_cases()` in the adapter. Recommended cases are:

1. no-degradation clean reference;
2. nominal operation;
3. severe imposed degradation;
4. high-infiltration load disturbance.

### Local OAT sensitivity

For each parameter, the model is run at:

- its baseline value;
- its lower bound;
- its upper bound.

The exported table includes signed low/high percentage changes, maximum absolute change, and local elasticities. The tornado chart deliberately shows signed responses rather than absolute-only bars.

### Monte Carlo robustness

The software samples all selected uncertain parameters simultaneously using Latin hypercube, Sobol quasi-random, or ordinary random sampling. The same physical parameter realization is used across S0–S3, allowing paired comparisons and strategy-ranking probabilities.

For physical uncertainty, keep **Fix optimizer seed** selected. Analyse optimizer randomness separately in the Optimizer tab.

### Morris screening

Morris analysis calculates:

- `mu`: signed mean elementary effect;
- `mu_star`: overall parameter importance;
- `sigma`: nonlinearity and/or interaction indicator.

Use Morris first when the physical model is expensive. Publication-level starting settings are 20–30 trajectories and 6–8 grid levels.

### Sobol analysis

The software estimates:

- `S1`: first-order/direct sensitivity;
- `ST`: total-order sensitivity including interactions;
- `ST - S1`: interaction gap;
- bootstrap 95% confidence intervals.

The implementation uses an A/B/AB design requiring:

```text
N × (k + 2)
```

model evaluations, where `N` is the base sample and `k` is the number of selected parameters. Apply Sobol analysis only to the most influential Morris-screened parameters when model runtime is high.

Recommended progression:

1. diagnostic `N = 64`;
2. preliminary `N = 256`;
3. publication-level `N = 512` or `1024`, subject to convergence.

### Ablation

The default ablation cases are:

- S0 reactive baseline;
- full S3;
- S3 control only;
- S3 maintenance only;
- S3 without degradation feedback.

The adapter must ensure these flags actually activate/deactivate the intended mechanisms.

### Optimizer robustness

The app varies population size, iteration count, and random seed. This is separate from physical-parameter sensitivity.

### Connectivity diagnostic

Each parameter is strongly perturbed and the software checks whether any selected output changes. A disconnected parameter may indicate:

- an incorrect adapter mapping;
- a variable that is overwritten inside the solver;
- a parameter that is clipped or inactive in the selected scenario;
- an uncertainty range too small to affect outputs.

## What to do before publication

1. Connect the latest numerical engine through the adapter.
2. Run the connectivity test and resolve unexplained inactive parameters.
3. Download the parameter-range template.
4. Replace illustrative bounds with calibration intervals, manufacturer data, field data, or clearly declared assumptions.
5. Run OAT analysis for transparent directional interpretation.
6. Run Morris screening for all candidate parameters.
7. Retain approximately 8–12 influential parameters.
8. Run Sobol analysis separately for key outputs and degradation severities.
9. Run paired Monte Carlo robustness across S0–S3.
10. Run optimizer robustness separately using multiple seeds.
11. Report sample sizes, bounds, distributions, seeds, confidence intervals, and strategy-ranking probabilities.

## Installation and launch

### Windows

Double-click:

```text
run_app.bat
```

or run:

```bash
python -m pip install -r requirements.txt
streamlit run sensitivity_studio_app.py
```

### Linux/macOS

```bash
chmod +x run_app.sh
./run_app.sh
```

## Important interpretation rules

- OAT is a local/one-factor-at-a-time method and does not quantify interactions.
- Morris is a global screening method, not an exact variance decomposition.
- Sobol indices depend on the selected distributions and parameter bounds.
- Sensitivity analysis does not replace model verification or validation.
- Negative or slightly greater-than-one finite-sample Sobol estimates may occur when `N` is too small; increase `N` and inspect confidence intervals rather than manually clipping the values.
- Integer maintenance counts should be reported as both absolute counts and percentages.
- The no-degradation case is an ideal clean-system counterfactual, not an implementable management strategy.

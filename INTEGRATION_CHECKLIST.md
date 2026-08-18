# HVAC v3 Adapter Integration Checklist

Use this checklist when mapping the latest `hvac_v3.py` model into `sensitivity_adapter.py`.

## 1. Import the numerical engine

Import the file containing `run_scenario_model` or equivalent. Avoid importing the Streamlit UI if it executes widgets during import.

## 2. Map every sensitivity parameter

For each entry returned by `sensitivity_parameter_specs()`, verify that its sampled value is assigned to the numerical object actually used during simulation.

Examples:

- `internal_gain_factor` → multiplier on zone/internal loads;
- `infiltration_factor` → multiplier on infiltration flow or ACH;
- `alpha_foul` → fouling kinetic parameter;
- `R_f_star` → maximum/characteristic fouling resistance;
- `m_dot_dust` → dust accumulation rate;
- `K_clog` → filter pressure-drop coefficient;
- `eta` → maintenance recovery efficiency;
- `delta_trigger` → S3 maintenance trigger;
- `optimizer_population` and `optimizer_iterations` → actual search settings.

## 3. Preserve imposed severity versus residual degradation

`severity` should change the imposed degradation intensity, while returned `mean_residual_delta` should represent the state remaining after control and maintenance.

## 4. Implement ablation flags

The adapter passes:

- `enable_degradation`;
- `enable_control`;
- `enable_maintenance`;
- `include_degradation_feedback`;
- `fixed_optimizer_seed`.

These must alter the solver mechanism rather than merely relabel outputs.

## 5. Set stochastic seed

Pass `seed` to every random number generator used by S3. For physical sensitivity, the app normally fixes this seed. For optimizer robustness, it varies the seed.

## 6. Return stable scalar names

Return the same output keys for every strategy, severity, and parameter sample. Do not return arrays or dataframes from the adapter; summarize them first.

## 7. Run connectivity diagnostic

After loading the model in the app, run **Connectivity**. Investigate every parameter that changes no selected output.

## 8. Run baseline consistency checks

Confirm that:

- all four strategies can run under all four severities;
- the no-degradation case produces clean-equipment behaviour;
- S3 control-only does not execute maintenance;
- S3 maintenance-only uses nominal control;
- S3 without degradation feedback retains physical degradation but removes it from the optimizer objective.

"""Template adapter connecting the latest HVAC v3 model to Sensitivity Studio.

Place this file in the same project as ``hvac_v3.py`` and its engine modules.
Edit only the marked integration section so that one call to
``sensitivity_adapter_run`` executes your actual model.

Important
---------
Do not import a Streamlit UI module if it executes the app at import time.
Import the numerical engine that contains ``run_scenario_model`` instead.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# EDIT THIS IMPORT to point to your numerical model, not the Streamlit UI.
# Example:
# from hvac_v3_engine import BuildingSpec, HVACConfig, run_scenario_model
# ---------------------------------------------------------------------------
# from hvac_v3_engine import BuildingSpec, HVACConfig, run_scenario_model


STRATEGIES = ("S0", "S1", "S2", "S3")
SEVERITIES = ("Mild", "Moderate", "Severe", "High")


def sensitivity_parameter_specs() -> list[dict[str, Any]]:
    """Define every uncertain input used by local/global sensitivity analysis.

    Replace the illustrative values with the exact baseline and defensible lower
    and upper bounds used in the manuscript model.
    """
    return [
        {
            "name": "internal_gain_factor",
            "lower": 0.80,
            "baseline": 1.00,
            "upper": 1.20,
            "distribution": "triangular",
            "group": "Building load",
            "integer": False,
            "enabled": True,
            "description": "Multiplier applied to internal sensible and latent gains.",
        },
        {
            "name": "infiltration_factor",
            "lower": 0.80,
            "baseline": 1.00,
            "upper": 1.30,
            "distribution": "triangular",
            "group": "Building load",
            "description": "Multiplier applied to infiltration or uncontrolled outdoor air.",
        },
        {
            "name": "climate_drift_C_per_year",
            "lower": 0.00,
            "baseline": 0.03,
            "upper": 0.08,
            "distribution": "uniform",
            "group": "Climate",
            "description": "Annual outdoor-temperature drift used in long-horizon scenarios.",
        },
        {
            "name": "alpha_foul",
            "lower": 0.70,
            "baseline": 1.00,
            "upper": 1.30,
            "distribution": "triangular",
            "group": "Heat-exchanger fouling",
            "description": "Multiplier on fouling accumulation kinetics.",
        },
        {
            "name": "R_f_star",
            "lower": 4.0e-5,
            "baseline": 7.0e-5,
            "upper": 1.0e-4,
            "distribution": "uniform",
            "group": "Heat-exchanger fouling",
            "description": "Characteristic or asymptotic fouling resistance, m2 K W-1.",
        },
        {
            "name": "m_dot_dust",
            "lower": 0.8,
            "baseline": 1.2,
            "upper": 1.6,
            "distribution": "triangular",
            "group": "Filter clogging",
            "description": "Dust-loading rate, g m-2 day-1.",
        },
        {
            "name": "K_clog",
            "lower": 18.0,
            "baseline": 25.0,
            "upper": 32.0,
            "distribution": "triangular",
            "group": "Filter clogging",
            "description": "Pressure-drop increase per unit dust loading, Pa m2 g-1.",
        },
        {
            "name": "B",
            "lower": 0.80,
            "baseline": 1.00,
            "upper": 1.20,
            "distribution": "uniform",
            "group": "Performance degradation",
            "description": "Multiplier on degradation-related performance penalty.",
        },
        {
            "name": "eta",
            "lower": 0.70,
            "baseline": 0.85,
            "upper": 0.95,
            "distribution": "triangular",
            "group": "Maintenance",
            "description": "Maintenance recovery efficiency.",
        },
        {
            "name": "lambda_age",
            "lower": 0.00,
            "baseline": 0.01,
            "upper": 0.03,
            "distribution": "uniform",
            "group": "Equipment aging",
            "description": "Annual irreversible aging coefficient.",
        },
        {
            "name": "delta_trigger",
            "lower": 0.45,
            "baseline": 0.55,
            "upper": 0.65,
            "distribution": "triangular",
            "group": "Maintenance policy",
            "description": "Composite degradation threshold used by S3.",
        },
        {
            "name": "optimizer_population",
            "lower": 12,
            "baseline": 18,
            "upper": 30,
            "distribution": "uniform",
            "group": "Optimizer",
            "integer": True,
            "description": "Number of candidates evaluated per optimizer iteration.",
        },
        {
            "name": "optimizer_iterations",
            "lower": 5,
            "baseline": 10,
            "upper": 20,
            "distribution": "uniform",
            "group": "Optimizer",
            "integer": True,
            "description": "Number of elite Gaussian search iterations.",
        },
    ]


def sensitivity_adapter_run(
    parameters: dict[str, float],
    strategy: str,
    severity: str,
    options: dict[str, bool],
    seed: int,
) -> dict[str, float]:
    """Run one HVAC v3 scenario and return scalar summary results.

    Required integration steps
    --------------------------
    1. Build or copy the normal BuildingSpec and HVACConfig objects.
    2. Override model fields from ``parameters``.
    3. Apply ``strategy`` and ``severity``.
    4. Pass the five ablation flags in ``options`` into your solver logic.
    5. Set the optimizer random seed.
    6. Run the complete model once.
    7. Return scalar summary metrics only.

    Example skeleton
    ----------------
    building = BuildingSpec(...)
    hvac = HVACConfig(...)

    building.internal_gain_factor = parameters["internal_gain_factor"]
    building.infiltration_factor = parameters["infiltration_factor"]
    hvac.alpha_foul = parameters["alpha_foul"]
    hvac.R_f_star = parameters["R_f_star"]
    hvac.m_dot_dust = parameters["m_dot_dust"]
    hvac.K_clog = parameters["K_clog"]
    hvac.delta_trigger = parameters["delta_trigger"]
    hvac.optimizer_population = int(parameters["optimizer_population"])
    hvac.optimizer_iterations = int(parameters["optimizer_iterations"])
    hvac.random_seed = seed

    daily, summary = run_scenario_model(
        building=building,
        hvac=hvac,
        strategy=strategy,
        severity=severity,
        enable_degradation=options.get("enable_degradation", True),
        enable_control=options.get("enable_control", True),
        enable_maintenance=options.get("enable_maintenance", True),
        include_degradation_feedback=options.get(
            "include_degradation_feedback", True
        ),
    )
    """
    raise NotImplementedError(
        "Edit sensitivity_adapter_run() so it calls the latest HVAC v3 numerical engine."
    )

    # Return keys may use your preferred names, but keep them stable.
    # return {
    #     "total_energy_MWh": float(summary["total_energy_MWh"]),
    #     "mean_chiller_COP": float(summary["mean_chiller_COP"]),
    #     "mean_residual_delta": float(summary["mean_residual_delta"]),
    #     "occupied_discomfort_days": float(summary["occupied_discomfort_days"]),
    #     "filter_replacements": float(summary["filter_replacements"]),
    #     "hx_cleanings": float(summary["hx_cleanings"]),
    #     "total_cost_USD": float(summary["total_cost_USD"]),
    #     "co2_tonne": float(summary["co2_tonne"]),
    # }


def sensitivity_benchmark_cases() -> list[dict[str, Any]]:
    """Benchmark definitions shown in the Benchmarks tab."""
    return [
        {
            "name": "No degradation",
            "severity": "Moderate",
            "parameter_overrides": {},
            "options": {
                "enable_degradation": False,
                "enable_control": True,
                "enable_maintenance": False,
                "include_degradation_feedback": False,
            },
        },
        {"name": "Nominal", "severity": "Moderate", "parameter_overrides": {}, "options": {}},
        {"name": "Severe degradation", "severity": "Severe", "parameter_overrides": {}, "options": {}},
        {
            "name": "High infiltration",
            "severity": "Moderate",
            "parameter_overrides": {"infiltration_factor": 1.30},
            "options": {},
        },
    ]


def sensitivity_ablation_cases() -> list[dict[str, Any]]:
    """Ablation definitions shown in the Ablation tab."""
    return [
        {
            "name": "S0 reactive baseline",
            "strategy": "S0",
            "options": {
                "enable_degradation": True,
                "enable_control": False,
                "enable_maintenance": True,
                "include_degradation_feedback": False,
            },
        },
        {
            "name": "Full S3",
            "strategy": "S3",
            "options": {
                "enable_degradation": True,
                "enable_control": True,
                "enable_maintenance": True,
                "include_degradation_feedback": True,
            },
        },
        {
            "name": "S3 control only",
            "strategy": "S3",
            "options": {
                "enable_degradation": True,
                "enable_control": True,
                "enable_maintenance": False,
                "include_degradation_feedback": True,
            },
        },
        {
            "name": "S3 maintenance only",
            "strategy": "S3",
            "options": {
                "enable_degradation": True,
                "enable_control": False,
                "enable_maintenance": True,
                "include_degradation_feedback": True,
            },
        },
        {
            "name": "S3 without degradation feedback",
            "strategy": "S3",
            "options": {
                "enable_degradation": True,
                "enable_control": True,
                "enable_maintenance": True,
                "include_degradation_feedback": False,
            },
        },
    ]


def sensitivity_metadata() -> dict[str, Any]:
    return {
        "model": "Latest HVAC v3 physical reduced-order model",
        "scope": "Local and global sensitivity analysis without ChillerPlant.csv",
        "note": "Update this metadata after connecting the numerical engine.",
    }

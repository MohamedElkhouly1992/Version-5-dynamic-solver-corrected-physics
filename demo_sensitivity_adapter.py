"""Synthetic deterministic demo used only to test the Sensitivity Studio UI.

This is NOT a validation dataset, an HVAC calibration, or a manuscript result.
"""
from __future__ import annotations

import math
from typing import Any


def sensitivity_parameter_specs() -> list[dict[str, Any]]:
    return [
        {"name": "internal_gain_factor", "lower": 0.8, "baseline": 1.0, "upper": 1.2, "distribution": "triangular", "group": "Building load"},
        {"name": "infiltration_factor", "lower": 0.8, "baseline": 1.0, "upper": 1.3, "distribution": "triangular", "group": "Building load"},
        {"name": "alpha_foul", "lower": 0.7, "baseline": 1.0, "upper": 1.3, "distribution": "uniform", "group": "Fouling"},
        {"name": "m_dot_dust", "lower": 0.8, "baseline": 1.2, "upper": 1.6, "distribution": "uniform", "group": "Filter"},
        {"name": "K_clog", "lower": 18.0, "baseline": 25.0, "upper": 32.0, "distribution": "uniform", "group": "Filter"},
        {"name": "delta_trigger", "lower": 0.45, "baseline": 0.55, "upper": 0.65, "distribution": "uniform", "group": "Maintenance"},
        {"name": "eta", "lower": 0.70, "baseline": 0.85, "upper": 0.95, "distribution": "triangular", "group": "Maintenance"},
        {"name": "optimizer_population", "lower": 12, "baseline": 18, "upper": 30, "distribution": "uniform", "group": "Optimizer", "integer": True},
        {"name": "optimizer_iterations", "lower": 5, "baseline": 10, "upper": 20, "distribution": "uniform", "group": "Optimizer", "integer": True},
    ]


def sensitivity_adapter_run(parameters, strategy, severity, options, seed):
    severity_factor = {"Mild": 0.8, "Moderate": 1.0, "Severe": 1.2, "High": 1.5}.get(severity, 1.0)
    strategy_factor = {"S0": 1.0, "S1": 0.86, "S2": 0.93, "S3": 0.55}.get(strategy, 1.0)
    load = 0.55 * parameters["internal_gain_factor"] + 0.45 * parameters["infiltration_factor"]
    degradation = severity_factor * (
        0.30 * parameters["alpha_foul"]
        + 0.25 * parameters["m_dot_dust"] / 1.2
        + 0.20 * parameters["K_clog"] / 25.0
    )
    if not options.get("enable_degradation", True):
        degradation = 0.0
    trigger = parameters["delta_trigger"]
    recovery = parameters["eta"] if options.get("enable_maintenance", True) else 0.0
    residual = max(0.0, degradation * (1.0 - 0.55 * recovery) + 0.7 * (trigger - 0.55))
    control_factor = strategy_factor if options.get("enable_control", True) else 0.90
    if strategy != "S3":
        control_factor = strategy_factor
    energy = 10000.0 * load * (1.0 + 0.22 * residual) * control_factor
    if strategy == "S3" and not options.get("include_degradation_feedback", True):
        energy *= 1.06
    population = parameters.get("optimizer_population", 18)
    iterations = parameters.get("optimizer_iterations", 10)
    if strategy == "S3":
        energy *= 1.0 + 0.02 / math.sqrt(max(population * iterations, 1))
    cop = 4.5 / (1.0 + 0.35 * residual)
    discomfort = max(0.0, 12.0 * residual + 2.0 * (load - 1.0))
    filter_replacements = max(0.0, round(2.0 * parameters["m_dot_dust"] / 1.2 + 0.03 * (parameters["K_clog"] - 25)))
    hx_cleanings = max(0.0, round(2.0 * residual / max(trigger, 0.01))) if options.get("enable_maintenance", True) else 0.0
    maintenance_events = filter_replacements + hx_cleanings
    return {
        "total_energy_MWh": float(energy),
        "mean_chiller_COP": float(cop),
        "mean_residual_delta": float(residual),
        "occupied_discomfort_days": float(discomfort),
        "filter_replacements": float(filter_replacements),
        "hx_cleanings": float(hx_cleanings),
        "maintenance_events": float(maintenance_events),
        "total_cost_USD": float(energy * 120.0 + maintenance_events * 1000.0),
        "co2_tonne": float(energy * 0.537),
    }


def sensitivity_benchmark_cases():
    return [
        {"name": "No degradation", "severity": "Moderate", "parameter_overrides": {}, "options": {"enable_degradation": False, "enable_maintenance": False}},
        {"name": "Nominal", "severity": "Moderate", "parameter_overrides": {}, "options": {}},
        {"name": "Severe degradation", "severity": "Severe", "parameter_overrides": {}, "options": {}},
        {"name": "High infiltration", "severity": "Moderate", "parameter_overrides": {"infiltration_factor": 1.3}, "options": {}},
    ]


def sensitivity_metadata():
    return {"model": "Synthetic UI test model", "scientific_use": False}

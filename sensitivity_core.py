#!/usr/bin/env python3
"""Core analysis engine for HVAC v3 sensitivity and robustness studies.

This module is dataset-independent. It calls a user-supplied model adapter that
wraps the latest ``hvac_v3.py`` or its numerical engine.

Adapter contract
----------------
The adapter module must define:

``sensitivity_parameter_specs() -> list[dict]``
    Return parameter metadata. Required fields are ``name``, ``lower``,
    ``baseline`` and ``upper``. Optional fields: ``distribution``, ``group``,
    ``integer``, ``enabled`` and ``description``.

``sensitivity_adapter_run(parameters, strategy, severity, options, seed) -> dict``
    Run one complete scenario and return scalar summary outputs.

Optional functions:

``sensitivity_benchmark_cases() -> list[dict]``
``sensitivity_ablation_cases() -> list[dict]``
``sensitivity_metadata() -> dict``

The engine provides local OAT, paired Monte Carlo, Morris screening, Sobol
first/total-order indices, benchmark and ablation studies, and strategy-ranking
robustness.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import math
import os
import sys
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import qmc


DEFAULT_STRATEGIES = ("S0", "S1", "S2", "S3")
DEFAULT_SEVERITIES = ("Mild", "Moderate", "Severe", "High")


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    lower: float
    baseline: float
    upper: float
    distribution: str = "uniform"
    group: str = "Unclassified"
    integer: bool = False
    enabled: bool = True
    description: str = ""
    std: float | None = None

    def validate(self) -> None:
        if not self.name:
            raise ValueError("Parameter name cannot be empty.")
        if not np.isfinite([self.lower, self.baseline, self.upper]).all():
            raise ValueError(f"Non-finite range for {self.name}.")
        if self.lower >= self.upper:
            raise ValueError(f"lower must be smaller than upper for {self.name}.")
        if not self.lower <= self.baseline <= self.upper:
            raise ValueError(f"baseline is outside the bounds for {self.name}.")
        if self.distribution not in {"uniform", "triangular", "normal", "loguniform"}:
            raise ValueError(
                f"Unsupported distribution {self.distribution!r} for {self.name}."
            )
        if self.distribution == "loguniform" and self.lower <= 0:
            raise ValueError(f"loguniform requires a positive lower bound for {self.name}.")


@dataclass(frozen=True)
class RunOptions:
    enable_degradation: bool = True
    enable_control: bool = True
    enable_maintenance: bool = True
    include_degradation_feedback: bool = True
    fixed_optimizer_seed: bool = True


@dataclass
class AnalysisProgress:
    total: int
    completed: int = 0
    callback: Callable[[int, int, str], None] | None = None

    def step(self, message: str = "") -> None:
        self.completed += 1
        if self.callback:
            self.callback(self.completed, self.total, message)


class HVACModelAdapter:
    """Load and call a trusted sensitivity adapter module."""

    def __init__(self, module_path: str | Path):
        self.module_path = Path(module_path).resolve()
        if not self.module_path.exists():
            raise FileNotFoundError(self.module_path)
        unique = hashlib.sha256(str(self.module_path).encode()).hexdigest()[:12]
        module_name = f"hvac_sensitivity_adapter_{unique}_{time.time_ns()}"
        project_root = str(self.module_path.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        spec = importlib.util.spec_from_file_location(module_name, self.module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to import adapter: {self.module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.module = module
        self._runner = getattr(module, "sensitivity_adapter_run", None)
        self._spec_fn = getattr(module, "sensitivity_parameter_specs", None)
        if not callable(self._runner):
            raise AttributeError(
                "Adapter must define sensitivity_adapter_run(parameters, strategy, "
                "severity, options, seed)."
            )
        if not callable(self._spec_fn):
            raise AttributeError("Adapter must define sensitivity_parameter_specs().")

    def parameter_specs(self) -> list[ParameterSpec]:
        raw = self._spec_fn()
        if isinstance(raw, pd.DataFrame):
            raw = raw.to_dict("records")
        if not isinstance(raw, Sequence):
            raise TypeError("sensitivity_parameter_specs() must return a sequence of mappings.")
        specs: list[ParameterSpec] = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise TypeError("Each parameter specification must be a mapping.")
            spec = ParameterSpec(
                name=str(item["name"]),
                lower=float(item["lower"]),
                baseline=float(item["baseline"]),
                upper=float(item["upper"]),
                distribution=str(item.get("distribution", "uniform")).lower(),
                group=str(item.get("group", "Unclassified")),
                integer=bool(item.get("integer", False)),
                enabled=bool(item.get("enabled", True)),
                description=str(item.get("description", "")),
                std=float(item["std"]) if item.get("std") not in (None, "") else None,
            )
            spec.validate()
            specs.append(spec)
        if len({s.name for s in specs}) != len(specs):
            raise ValueError("Parameter names must be unique.")
        return specs

    def run(
        self,
        parameters: Mapping[str, float],
        strategy: str,
        severity: str,
        options: RunOptions | Mapping[str, Any] | None = None,
        seed: int = 42,
    ) -> dict[str, float]:
        if options is None:
            opts = asdict(RunOptions())
        elif isinstance(options, RunOptions):
            opts = asdict(options)
        else:
            opts = dict(options)
        raw = self._runner(
            parameters=dict(parameters),
            strategy=str(strategy),
            severity=str(severity),
            options=opts,
            seed=int(seed),
        )
        if not isinstance(raw, Mapping):
            raise TypeError("sensitivity_adapter_run() must return a mapping.")
        result: dict[str, float] = {}
        for key, value in raw.items():
            if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value):
                result[str(key)] = float(value)
        if not result:
            raise ValueError("Adapter returned no finite scalar outputs.")
        return result

    def benchmark_cases(self) -> list[dict[str, Any]]:
        fn = getattr(self.module, "sensitivity_benchmark_cases", None)
        if callable(fn):
            cases = fn()
            return [dict(x) for x in cases]
        return [
            {"name": "Mild", "severity": "Mild", "parameter_overrides": {}, "options": {}},
            {"name": "Moderate", "severity": "Moderate", "parameter_overrides": {}, "options": {}},
            {"name": "Severe", "severity": "Severe", "parameter_overrides": {}, "options": {}},
            {"name": "High", "severity": "High", "parameter_overrides": {}, "options": {}},
        ]

    def ablation_cases(self) -> list[dict[str, Any]]:
        fn = getattr(self.module, "sensitivity_ablation_cases", None)
        if callable(fn):
            return [dict(x) for x in fn()]
        return [
            {
                "name": "S0 reactive baseline",
                "strategy": "S0",
                "options": asdict(RunOptions(enable_control=False)),
            },
            {
                "name": "Full S3",
                "strategy": "S3",
                "options": asdict(RunOptions()),
            },
            {
                "name": "S3 control only",
                "strategy": "S3",
                "options": asdict(RunOptions(enable_maintenance=False)),
            },
            {
                "name": "S3 maintenance only",
                "strategy": "S3",
                "options": asdict(RunOptions(enable_control=False)),
            },
            {
                "name": "S3 without degradation feedback",
                "strategy": "S3",
                "options": asdict(RunOptions(include_degradation_feedback=False)),
            },
        ]

    def metadata(self) -> dict[str, Any]:
        fn = getattr(self.module, "sensitivity_metadata", None)
        return dict(fn()) if callable(fn) else {}


def safe_extract_zip(data: bytes, destination: str | Path) -> Path:
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if destination not in target.parents and target != destination:
                raise ValueError(f"Unsafe ZIP path: {member.filename}")
        archive.extractall(destination)
    return destination


def specs_to_frame(specs: Sequence[ParameterSpec]) -> pd.DataFrame:
    return pd.DataFrame([asdict(s) for s in specs])


def specs_from_frame(frame: pd.DataFrame) -> list[ParameterSpec]:
    required = {"name", "lower", "baseline", "upper"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Parameter CSV missing columns: {sorted(missing)}")
    specs: list[ParameterSpec] = []
    for row in frame.to_dict("records"):
        def clean_bool(value: Any, default: bool) -> bool:
            if value is None or (isinstance(value, float) and np.isnan(value)):
                return default
            if isinstance(value, str):
                return value.strip().lower() not in {"false", "0", "no", "off", ""}
            return bool(value)

        spec = ParameterSpec(
            name=str(row["name"]),
            lower=float(row["lower"]),
            baseline=float(row["baseline"]),
            upper=float(row["upper"]),
            distribution=str(row.get("distribution", "uniform") or "uniform").lower(),
            group=str(row.get("group", "Unclassified") or "Unclassified"),
            integer=clean_bool(row.get("integer"), False),
            enabled=clean_bool(row.get("enabled"), True),
            description=str(row.get("description", "") or ""),
            std=float(row["std"]) if row.get("std") not in (None, "") and not pd.isna(row.get("std")) else None,
        )
        spec.validate()
        specs.append(spec)
    return specs


def active_specs(specs: Sequence[ParameterSpec], names: Sequence[str] | None = None) -> list[ParameterSpec]:
    name_set = set(names) if names is not None else None
    return [s for s in specs if s.enabled and (name_set is None or s.name in name_set)]


def baseline_parameters(specs: Sequence[ParameterSpec]) -> dict[str, float]:
    return {
        s.name: float(int(round(s.baseline))) if s.integer else float(s.baseline)
        for s in specs
    }


def _transform_unit_samples(unit: np.ndarray, specs: Sequence[ParameterSpec]) -> np.ndarray:
    unit = np.asarray(unit, dtype=float)
    if unit.ndim == 1:
        unit = unit.reshape(1, -1)
    if unit.shape[1] != len(specs):
        raise ValueError("Sample width does not match the number of parameters.")
    out = np.empty_like(unit, dtype=float)
    eps = np.finfo(float).eps
    for j, spec in enumerate(specs):
        u = np.clip(unit[:, j], eps, 1.0 - eps)
        if spec.distribution == "uniform":
            x = spec.lower + u * (spec.upper - spec.lower)
        elif spec.distribution == "triangular":
            c = (spec.baseline - spec.lower) / (spec.upper - spec.lower)
            x = stats.triang.ppf(u, c=c, loc=spec.lower, scale=spec.upper - spec.lower)
        elif spec.distribution == "normal":
            sigma = spec.std if spec.std and spec.std > 0 else (spec.upper - spec.lower) / 6.0
            x = stats.norm.ppf(u, loc=spec.baseline, scale=sigma)
            x = np.clip(x, spec.lower, spec.upper)
        elif spec.distribution == "loguniform":
            x = np.exp(np.log(spec.lower) + u * (np.log(spec.upper) - np.log(spec.lower)))
        else:
            raise AssertionError(spec.distribution)
        if spec.integer:
            x = np.rint(x)
        out[:, j] = x
    return out


def _row_to_parameters(row: Sequence[float], specs: Sequence[ParameterSpec], all_specs: Sequence[ParameterSpec]) -> dict[str, float]:
    params = baseline_parameters(all_specs)
    for value, spec in zip(row, specs):
        params[spec.name] = float(int(round(value))) if spec.integer else float(value)
    return params


def discover_outputs(
    adapter: HVACModelAdapter,
    specs: Sequence[ParameterSpec],
    strategy: str = "S3",
    severity: str = "Moderate",
    seed: int = 42,
) -> dict[str, float]:
    return adapter.run(baseline_parameters(specs), strategy, severity, RunOptions(), seed)


def run_strategy_matrix(
    adapter: HVACModelAdapter,
    specs: Sequence[ParameterSpec],
    strategies: Sequence[str],
    severities: Sequence[str],
    seed: int = 42,
    progress: AnalysisProgress | None = None,
) -> pd.DataFrame:
    params = baseline_parameters(specs)
    rows: list[dict[str, Any]] = []
    for severity in severities:
        for strategy in strategies:
            result = adapter.run(params, strategy, severity, RunOptions(), seed)
            rows.append({"severity": severity, "strategy": strategy, **result})
            if progress:
                progress.step(f"{severity} / {strategy}")
    return pd.DataFrame(rows)


def run_benchmarks(
    adapter: HVACModelAdapter,
    specs: Sequence[ParameterSpec],
    strategies: Sequence[str],
    cases: Sequence[Mapping[str, Any]] | None = None,
    seed: int = 42,
    progress: AnalysisProgress | None = None,
) -> pd.DataFrame:
    cases = list(cases or adapter.benchmark_cases())
    base = baseline_parameters(specs)
    rows: list[dict[str, Any]] = []
    for case in cases:
        name = str(case.get("name", case.get("severity", "Case")))
        severity = str(case.get("severity", "Moderate"))
        params = dict(base)
        params.update({k: float(v) for k, v in dict(case.get("parameter_overrides", {})).items()})
        options = dict(case.get("options", {}))
        for strategy in strategies:
            out = adapter.run(params, strategy, severity, options, seed)
            rows.append({"benchmark_case": name, "severity": severity, "strategy": strategy, **out})
            if progress:
                progress.step(f"{name} / {strategy}")
    return pd.DataFrame(rows)


def run_oat(
    adapter: HVACModelAdapter,
    specs: Sequence[ParameterSpec],
    strategy: str,
    severity: str,
    output_names: Sequence[str],
    parameter_names: Sequence[str] | None = None,
    seed: int = 42,
    progress: AnalysisProgress | None = None,
) -> pd.DataFrame:
    selected = active_specs(specs, parameter_names)
    base_params = baseline_parameters(specs)
    baseline = adapter.run(base_params, strategy, severity, RunOptions(), seed)
    rows: list[dict[str, Any]] = []
    for spec in selected:
        low_params = dict(base_params)
        high_params = dict(base_params)
        low_params[spec.name] = float(int(round(spec.lower))) if spec.integer else spec.lower
        high_params[spec.name] = float(int(round(spec.upper))) if spec.integer else spec.upper
        low = adapter.run(low_params, strategy, severity, RunOptions(), seed)
        if progress:
            progress.step(f"{spec.name} low")
        high = adapter.run(high_params, strategy, severity, RunOptions(), seed)
        if progress:
            progress.step(f"{spec.name} high")
        for output in output_names:
            if output not in baseline or output not in low or output not in high:
                continue
            y0 = baseline[output]
            scale = abs(y0) if abs(y0) > 1e-12 else 1.0
            low_pct = 100.0 * (low[output] - y0) / scale
            high_pct = 100.0 * (high[output] - y0) / scale
            rows.append(
                {
                    "strategy": strategy,
                    "severity": severity,
                    "parameter": spec.name,
                    "group": spec.group,
                    "output": output,
                    "baseline_parameter": spec.baseline,
                    "low_parameter": spec.lower,
                    "high_parameter": spec.upper,
                    "baseline_output": y0,
                    "low_output": low[output],
                    "high_output": high[output],
                    "low_change_pct": low_pct,
                    "high_change_pct": high_pct,
                    "max_abs_change_pct": max(abs(low_pct), abs(high_pct)),
                    "elasticity_low": ((low[output] - y0) / scale) / ((spec.lower - spec.baseline) / (abs(spec.baseline) if abs(spec.baseline) > 1e-12 else 1.0)) if spec.lower != spec.baseline else np.nan,
                    "elasticity_high": ((high[output] - y0) / scale) / ((spec.upper - spec.baseline) / (abs(spec.baseline) if abs(spec.baseline) > 1e-12 else 1.0)) if spec.upper != spec.baseline else np.nan,
                }
            )
    return pd.DataFrame(rows)


def _sample_unit_random(n: int, k: int, seed: int, method: str = "latin_hypercube") -> np.ndarray:
    if method == "latin_hypercube":
        return qmc.LatinHypercube(d=k, seed=seed).random(n)
    if method == "sobol":
        sampler = qmc.Sobol(d=k, scramble=True, seed=seed)
        if n > 0 and (n & (n - 1)) == 0:
            return sampler.random_base2(int(math.log2(n)))
        return sampler.random(n)
    return np.random.default_rng(seed).random((n, k))


def run_monte_carlo(
    adapter: HVACModelAdapter,
    specs: Sequence[ParameterSpec],
    strategies: Sequence[str],
    severity: str,
    n_samples: int,
    output_names: Sequence[str],
    parameter_names: Sequence[str] | None = None,
    seed: int = 42,
    sampling: str = "latin_hypercube",
    fixed_optimizer_seed: bool = True,
    progress: AnalysisProgress | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    selected = active_specs(specs, parameter_names)
    if not selected:
        raise ValueError("At least one active parameter is required.")
    unit = _sample_unit_random(n_samples, len(selected), seed, sampling)
    values = _transform_unit_samples(unit, selected)
    sample_records: list[dict[str, Any]] = []
    output_records: list[dict[str, Any]] = []
    for sample_id, row in enumerate(values):
        params = _row_to_parameters(row, selected, specs)
        sample_records.append({"sample_id": sample_id, **{s.name: params[s.name] for s in selected}})
        for strategy in strategies:
            model_seed = seed if fixed_optimizer_seed else seed + sample_id * 1009 + sum(map(ord, strategy))
            out = adapter.run(params, strategy, severity, RunOptions(fixed_optimizer_seed=fixed_optimizer_seed), model_seed)
            output_records.append(
                {
                    "sample_id": sample_id,
                    "strategy": strategy,
                    "severity": severity,
                    **{name: out.get(name, np.nan) for name in output_names},
                }
            )
            if progress:
                progress.step(f"sample {sample_id + 1}/{n_samples}, {strategy}")
    samples_df = pd.DataFrame(sample_records)
    outputs_df = pd.DataFrame(output_records)
    ranking_rows: list[dict[str, Any]] = []
    for output in output_names:
        subset = outputs_df.dropna(subset=[output])
        if subset.empty:
            continue
        winners = subset.loc[subset.groupby("sample_id")[output].idxmin()]
        counts = winners["strategy"].value_counts(normalize=True)
        for strategy in strategies:
            ranking_rows.append(
                {
                    "severity": severity,
                    "output": output,
                    "strategy": strategy,
                    "probability_lowest": float(counts.get(strategy, 0.0)),
                }
            )
        if "S0" in strategies and "S3" in strategies:
            wide = subset.pivot(index="sample_id", columns="strategy", values=output)
            if {"S0", "S3"}.issubset(wide.columns):
                diff = wide["S0"] - wide["S3"]
                ranking_rows.append(
                    {
                        "severity": severity,
                        "output": output,
                        "strategy": "S3_vs_S0",
                        "probability_lowest": float((diff > 0).mean()),
                        "median_improvement": float(diff.median()),
                        "p05_improvement": float(diff.quantile(0.05)),
                        "p95_improvement": float(diff.quantile(0.95)),
                    }
                )
    return samples_df, outputs_df, pd.DataFrame(ranking_rows)


def run_ablation(
    adapter: HVACModelAdapter,
    specs: Sequence[ParameterSpec],
    severity: str,
    cases: Sequence[Mapping[str, Any]] | None = None,
    seed: int = 42,
    progress: AnalysisProgress | None = None,
) -> pd.DataFrame:
    cases = list(cases or adapter.ablation_cases())
    params = baseline_parameters(specs)
    rows: list[dict[str, Any]] = []
    for case in cases:
        name = str(case.get("name", "Ablation"))
        strategy = str(case.get("strategy", "S3"))
        options = dict(case.get("options", {}))
        overrides = {k: float(v) for k, v in dict(case.get("parameter_overrides", {})).items()}
        local = dict(params)
        local.update(overrides)
        out = adapter.run(local, strategy, severity, options, seed)
        rows.append({"ablation_case": name, "strategy": strategy, "severity": severity, **out})
        if progress:
            progress.step(name)
    return pd.DataFrame(rows)


def _morris_unit_trajectories(k: int, trajectories: int, levels: int, seed: int) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    if levels < 4 or levels % 2 != 0:
        raise ValueError("Morris grid levels must be an even integer >= 4.")
    rng = np.random.default_rng(seed)
    delta = levels / (2.0 * (levels - 1.0))
    grid = np.linspace(0.0, 1.0 - delta, levels // 2)
    points: list[np.ndarray] = []
    step_meta: list[tuple[int, int, int]] = []
    for trajectory_id in range(trajectories):
        x = rng.choice(grid, size=k, replace=True).astype(float)
        orientation = rng.choice([-1.0, 1.0], size=k)
        for j in range(k):
            if orientation[j] < 0:
                x[j] += delta
        order = rng.permutation(k)
        points.append(x.copy())
        for parameter_idx in order:
            old_idx = len(points) - 1
            x = x.copy()
            x[parameter_idx] += orientation[parameter_idx] * delta
            x = np.clip(x, 0.0, 1.0)
            points.append(x.copy())
            new_idx = len(points) - 1
            step_meta.append((old_idx, new_idx, int(parameter_idx)))
    return np.vstack(points), step_meta


def run_morris(
    adapter: HVACModelAdapter,
    specs: Sequence[ParameterSpec],
    strategy: str,
    severity: str,
    output_names: Sequence[str],
    trajectories: int = 20,
    levels: int = 6,
    parameter_names: Sequence[str] | None = None,
    seed: int = 42,
    progress: AnalysisProgress | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    selected = active_specs(specs, parameter_names)
    k = len(selected)
    if k == 0:
        raise ValueError("At least one active parameter is required.")
    unit, steps = _morris_unit_trajectories(k, trajectories, levels, seed)
    transformed = _transform_unit_samples(unit, selected)
    output_rows: list[dict[str, Any]] = []
    y = {name: np.empty(len(unit), dtype=float) for name in output_names}
    for idx, row in enumerate(transformed):
        params = _row_to_parameters(row, selected, specs)
        out = adapter.run(params, strategy, severity, RunOptions(), seed)
        record = {"evaluation_id": idx, **{s.name: params[s.name] for s in selected}}
        for name in output_names:
            value = out.get(name, np.nan)
            y[name][idx] = value
            record[name] = value
        output_rows.append(record)
        if progress:
            progress.step(f"Morris evaluation {idx + 1}/{len(unit)}")
    delta = levels / (2.0 * (levels - 1.0))
    index_rows: list[dict[str, Any]] = []
    ee_rows: list[dict[str, Any]] = []
    for output in output_names:
        effects: dict[int, list[float]] = {i: [] for i in range(k)}
        for start, end, pidx in steps:
            if np.isfinite(y[output][start]) and np.isfinite(y[output][end]):
                ee = (y[output][end] - y[output][start]) / delta
                effects[pidx].append(float(ee))
                ee_rows.append({"output": output, "parameter": selected[pidx].name, "elementary_effect": ee})
        for pidx, spec in enumerate(selected):
            arr = np.asarray(effects[pidx], dtype=float)
            index_rows.append(
                {
                    "strategy": strategy,
                    "severity": severity,
                    "output": output,
                    "parameter": spec.name,
                    "group": spec.group,
                    "mu": float(np.mean(arr)) if arr.size else np.nan,
                    "mu_star": float(np.mean(np.abs(arr))) if arr.size else np.nan,
                    "sigma": float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0,
                    "n_effects": int(arr.size),
                }
            )
    indices = pd.DataFrame(index_rows)
    if not indices.empty:
        indices["rank_mu_star"] = indices.groupby("output")["mu_star"].rank(method="dense", ascending=False)
    return pd.DataFrame(output_rows), pd.DataFrame(ee_rows), indices


def _sobol_base_samples(k: int, n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    sampler = qmc.Sobol(d=2 * k, scramble=True, seed=seed)
    if n > 0 and (n & (n - 1)) == 0:
        raw = sampler.random_base2(int(math.log2(n)))
    else:
        raw = sampler.random(n)
    return raw[:, :k], raw[:, k:]


def _sobol_indices(A: np.ndarray, B: np.ndarray, AB: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    variance = np.var(np.concatenate([A, B]), ddof=1)
    if variance <= 1e-20:
        return np.full(AB.shape[0], np.nan), np.full(AB.shape[0], np.nan)
    s1 = np.mean(B[None, :] * (AB - A[None, :]), axis=1) / variance
    st = 0.5 * np.mean((A[None, :] - AB) ** 2, axis=1) / variance
    return s1, st


def run_sobol(
    adapter: HVACModelAdapter,
    specs: Sequence[ParameterSpec],
    strategy: str,
    severity: str,
    output_names: Sequence[str],
    base_size: int = 256,
    bootstrap: int = 300,
    parameter_names: Sequence[str] | None = None,
    seed: int = 42,
    progress: AnalysisProgress | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected = active_specs(specs, parameter_names)
    k = len(selected)
    if k == 0:
        raise ValueError("At least one active parameter is required.")
    A_u, B_u = _sobol_base_samples(k, base_size, seed)
    A_x = _transform_unit_samples(A_u, selected)
    B_x = _transform_unit_samples(B_u, selected)
    AB_x = np.empty((k, base_size, k), dtype=float)
    for i in range(k):
        AB_x[i] = A_x.copy()
        AB_x[i, :, i] = B_x[:, i]

    matrices: list[tuple[str, int | None, np.ndarray]] = [("A", None, A_x), ("B", None, B_x)]
    matrices.extend(("AB", i, AB_x[i]) for i in range(k))
    outputs: dict[str, dict[str, Any]] = {
        name: {"A": np.empty(base_size), "B": np.empty(base_size), "AB": np.empty((k, base_size))}
        for name in output_names
    }
    eval_rows: list[dict[str, Any]] = []
    evaluation_id = 0
    for matrix_name, pidx, matrix in matrices:
        for row_idx, row in enumerate(matrix):
            params = _row_to_parameters(row, selected, specs)
            out = adapter.run(params, strategy, severity, RunOptions(), seed)
            record = {
                "evaluation_id": evaluation_id,
                "matrix": matrix_name,
                "parameter_index": pidx,
                "row_index": row_idx,
                **{s.name: params[s.name] for s in selected},
            }
            for name in output_names:
                value = out.get(name, np.nan)
                if matrix_name == "AB":
                    outputs[name]["AB"][int(pidx), row_idx] = value
                else:
                    outputs[name][matrix_name][row_idx] = value
                record[name] = value
            eval_rows.append(record)
            evaluation_id += 1
            if progress:
                progress.step(f"Sobol evaluation {evaluation_id}/{base_size * (k + 2)}")

    rng = np.random.default_rng(seed + 991)
    index_rows: list[dict[str, Any]] = []
    for output in output_names:
        YA = outputs[output]["A"]
        YB = outputs[output]["B"]
        YAB = outputs[output]["AB"]
        valid = np.isfinite(YA) & np.isfinite(YB) & np.all(np.isfinite(YAB), axis=0)
        YA, YB, YAB = YA[valid], YB[valid], YAB[:, valid]
        if len(YA) < 8:
            continue
        s1, st = _sobol_indices(YA, YB, YAB)
        boot_s1 = np.empty((bootstrap, k))
        boot_st = np.empty((bootstrap, k))
        for b in range(bootstrap):
            idx = rng.integers(0, len(YA), len(YA))
            boot_s1[b], boot_st[b] = _sobol_indices(YA[idx], YB[idx], YAB[:, idx])
        for i, spec in enumerate(selected):
            index_rows.append(
                {
                    "strategy": strategy,
                    "severity": severity,
                    "output": output,
                    "parameter": spec.name,
                    "group": spec.group,
                    "S1": float(s1[i]),
                    "S1_ci_low": float(np.nanquantile(boot_s1[:, i], 0.025)),
                    "S1_ci_high": float(np.nanquantile(boot_s1[:, i], 0.975)),
                    "ST": float(st[i]),
                    "ST_ci_low": float(np.nanquantile(boot_st[:, i], 0.025)),
                    "ST_ci_high": float(np.nanquantile(boot_st[:, i], 0.975)),
                    "interaction_gap": float(st[i] - s1[i]),
                    "base_size": int(base_size),
                    "valid_samples": int(len(YA)),
                }
            )
    indices = pd.DataFrame(index_rows)
    if not indices.empty:
        indices["rank_ST"] = indices.groupby("output")["ST"].rank(method="dense", ascending=False)
    return pd.DataFrame(eval_rows), indices


def run_optimizer_robustness(
    adapter: HVACModelAdapter,
    specs: Sequence[ParameterSpec],
    severity: str,
    output_names: Sequence[str],
    seeds: Sequence[int],
    population_values: Sequence[int] | None = None,
    iteration_values: Sequence[int] | None = None,
    population_parameter: str = "optimizer_population",
    iteration_parameter: str = "optimizer_iterations",
    progress: AnalysisProgress | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    params0 = baseline_parameters(specs)
    populations = list(population_values or [int(params0.get(population_parameter, 18))])
    iterations = list(iteration_values or [int(params0.get(iteration_parameter, 10))])
    rows: list[dict[str, Any]] = []
    for pop in populations:
        for iters in iterations:
            for seed in seeds:
                params = dict(params0)
                if population_parameter in params:
                    params[population_parameter] = int(pop)
                if iteration_parameter in params:
                    params[iteration_parameter] = int(iters)
                out = adapter.run(
                    params,
                    "S3",
                    severity,
                    RunOptions(fixed_optimizer_seed=False),
                    int(seed),
                )
                rows.append(
                    {
                        "severity": severity,
                        "population": pop,
                        "iterations": iters,
                        "seed": seed,
                        **{name: out.get(name, np.nan) for name in output_names},
                    }
                )
                if progress:
                    progress.step(f"pop={pop}, iter={iters}, seed={seed}")
    raw = pd.DataFrame(rows)
    summaries: list[dict[str, Any]] = []
    for (pop, iters), group in raw.groupby(["population", "iterations"]):
        for output in output_names:
            values = group[output].dropna()
            if values.empty:
                continue
            mean = values.mean()
            summaries.append(
                {
                    "severity": severity,
                    "population": pop,
                    "iterations": iters,
                    "output": output,
                    "n_seeds": len(values),
                    "mean": mean,
                    "median": values.median(),
                    "std": values.std(ddof=1) if len(values) > 1 else 0.0,
                    "cv_pct": 100.0 * values.std(ddof=1) / abs(mean) if len(values) > 1 and abs(mean) > 1e-12 else 0.0,
                    "minimum": values.min(),
                    "maximum": values.max(),
                    "p05": values.quantile(0.05),
                    "p95": values.quantile(0.95),
                }
            )
    return raw, pd.DataFrame(summaries)


def parameter_connectivity_test(
    adapter: HVACModelAdapter,
    specs: Sequence[ParameterSpec],
    strategy: str,
    severity: str,
    output_names: Sequence[str],
    perturbation_fraction: float = 0.50,
    parameter_names: Sequence[str] | None = None,
    seed: int = 42,
    progress: AnalysisProgress | None = None,
) -> pd.DataFrame:
    base_params = baseline_parameters(specs)
    baseline = adapter.run(base_params, strategy, severity, RunOptions(), seed)
    rows: list[dict[str, Any]] = []
    for spec in active_specs(specs, parameter_names):
        params = dict(base_params)
        candidate = spec.baseline * (1.0 + perturbation_fraction)
        if abs(spec.baseline) < 1e-12:
            candidate = spec.lower + 0.75 * (spec.upper - spec.lower)
        candidate = min(spec.upper, max(spec.lower, candidate))
        if spec.integer:
            candidate = int(round(candidate))
        params[spec.name] = candidate
        out = adapter.run(params, strategy, severity, RunOptions(), seed)
        for output in output_names:
            if output in baseline and output in out:
                rows.append(
                    {
                        "parameter": spec.name,
                        "group": spec.group,
                        "output": output,
                        "baseline_parameter": spec.baseline,
                        "perturbed_parameter": candidate,
                        "baseline_output": baseline[output],
                        "perturbed_output": out[output],
                        "absolute_difference": out[output] - baseline[output],
                        "connected": not np.isclose(out[output], baseline[output], rtol=1e-9, atol=1e-12),
                    }
                )
        if progress:
            progress.step(spec.name)
    return pd.DataFrame(rows)


# ---------- Plot helpers ----------

def plot_grouped_bars(frame: pd.DataFrame, category: str, series: str, value: str, title: str) -> plt.Figure:
    pivot = frame.pivot_table(index=category, columns=series, values=value, aggfunc="mean")
    fig, ax = plt.subplots(figsize=(10, 5.8))
    pivot.plot(kind="bar", ax=ax)
    ax.set_title(title)
    ax.set_ylabel(value.replace("_", " "))
    ax.set_xlabel(category.replace("_", " "))
    ax.tick_params(axis="x", rotation=25)
    ax.legend(title=series)
    fig.tight_layout()
    return fig


def plot_oat_tornado(frame: pd.DataFrame, output: str, title: str | None = None) -> plt.Figure:
    data = frame[frame["output"] == output].copy().sort_values("max_abs_change_pct")
    fig, ax = plt.subplots(figsize=(9, max(4.5, 0.42 * len(data) + 1.8)))
    y = np.arange(len(data))
    ax.barh(y, data["low_change_pct"], label="Lower bound")
    ax.barh(y, data["high_change_pct"], label="Upper bound")
    ax.axvline(0.0, linewidth=1.0)
    ax.set_yticks(y, data["parameter"])
    ax.set_xlabel(f"Change in {output} relative to baseline (%)")
    ax.set_title(title or f"OAT sensitivity — {output}")
    ax.legend()
    fig.tight_layout()
    return fig


def plot_boxplot(frame: pd.DataFrame, output: str, title: str | None = None) -> plt.Figure:
    strategies = list(dict.fromkeys(frame["strategy"].tolist()))
    values = [frame.loc[frame["strategy"] == s, output].dropna().to_numpy() for s in strategies]
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    ax.boxplot(values, tick_labels=strategies, showfliers=True)
    ax.set_ylabel(output.replace("_", " "))
    ax.set_title(title or f"Monte Carlo robustness — {output}")
    fig.tight_layout()
    return fig


def plot_morris(frame: pd.DataFrame, output: str, title: str | None = None) -> plt.Figure:
    data = frame[frame["output"] == output].copy()
    fig, ax = plt.subplots(figsize=(8.5, 6.0))
    ax.scatter(data["mu_star"], data["sigma"])
    for _, row in data.iterrows():
        ax.annotate(row["parameter"], (row["mu_star"], row["sigma"]), xytext=(4, 3), textcoords="offset points", fontsize=8)
    ax.set_xlabel(r"$\mu^*$ (overall effect)")
    ax.set_ylabel(r"$\sigma$ (nonlinearity / interaction)")
    ax.set_title(title or f"Morris screening — {output}")
    fig.tight_layout()
    return fig


def plot_sobol(frame: pd.DataFrame, output: str, title: str | None = None) -> plt.Figure:
    data = frame[frame["output"] == output].copy().sort_values("ST")
    fig, ax = plt.subplots(figsize=(9, max(4.5, 0.42 * len(data) + 1.8)))
    y = np.arange(len(data))
    ax.barh(y - 0.18, data["S1"], height=0.36, label="First-order S1")
    ax.barh(y + 0.18, data["ST"], height=0.36, label="Total-order ST")
    ax.set_yticks(y, data["parameter"])
    ax.set_xlabel("Sobol sensitivity index")
    ax.set_title(title or f"Sobol indices — {output}")
    ax.legend()
    fig.tight_layout()
    return fig


def figure_png_bytes(fig: plt.Figure, dpi: int = 600) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=dpi, bbox_inches="tight")
    return buffer.getvalue()


def figure_svg_bytes(fig: plt.Figure) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()


def frame_csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")


def json_bytes(data: Any) -> bytes:
    return json.dumps(data, indent=2, ensure_ascii=False, default=str).encode("utf-8")


def create_results_zip(files: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()

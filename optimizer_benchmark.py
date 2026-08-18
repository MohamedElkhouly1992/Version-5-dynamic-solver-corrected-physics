from __future__ import annotations

"""Equal-budget stochastic optimizer benchmark for the HVAC sensitivity adapter.

The benchmark is additive and does not replace the project's existing optimizer or
validation strategy. It evaluates IESS, DE, PSO, and CEM with the same objective-
evaluation budget and independent seeds, then reports Friedman/Wilcoxon tests.
"""

from dataclasses import dataclass
from typing import Sequence
import math

import numpy as np
import pandas as pd
from scipy.stats import friedmanchisquare, wilcoxon


@dataclass
class BenchSpec:
    name: str
    lower: float
    upper: float
    integer: bool = False


def _specs(selected_specs) -> list[BenchSpec]:
    return [BenchSpec(s.name, float(s.lower), float(s.upper), bool(getattr(s, "integer", False))) for s in selected_specs]


def _clip_cast(x: np.ndarray, specs: Sequence[BenchSpec]) -> np.ndarray:
    out = np.asarray(x, dtype=float).copy()
    for j, s in enumerate(specs):
        out[j] = np.clip(out[j], s.lower, s.upper)
        if s.integer:
            out[j] = round(out[j])
    return out


def _make_objective(adapter, base_params: dict, specs: Sequence[BenchSpec], strategy: str, severity: str, output_name: str, seed: int):
    counter = {"n": 0}
    def objective(x):
        xx = _clip_cast(np.asarray(x, dtype=float), specs)
        params = dict(base_params)
        params.update({s.name: float(xx[j]) if not s.integer else int(xx[j]) for j, s in enumerate(specs)})
        out = adapter.run(params, strategy, severity, seed=seed)
        counter["n"] += 1
        val = float(out.get(output_name, np.nan))
        return val if np.isfinite(val) else 1e100
    return objective, counter


def _init_population(rng, specs, n):
    lo = np.array([s.lower for s in specs], float)
    hi = np.array([s.upper for s in specs], float)
    return lo + rng.random((n, len(specs))) * (hi - lo)


def _run_de(objective, specs, budget, pop_size, rng):
    pop_size = max(4, min(pop_size, budget))
    pop = _init_population(rng, specs, pop_size)
    fit = np.array([objective(x) for x in pop])
    used = pop_size
    while used < budget:
        for i in range(pop_size):
            if used >= budget: break
            pool = [j for j in range(pop_size) if j != i]
            a, b, c = rng.choice(pool, 3, replace=False)
            mutant = pop[a] + 0.8 * (pop[b] - pop[c])
            mask = rng.random(len(specs)) < 0.9
            mask[rng.integers(0, len(specs))] = True
            trial = np.where(mask, mutant, pop[i])
            trial = _clip_cast(trial, specs)
            f = objective(trial); used += 1
            if f <= fit[i]: pop[i], fit[i] = trial, f
    k = int(np.argmin(fit)); return pop[k], float(fit[k])


def _run_pso(objective, specs, budget, pop_size, rng):
    pop_size = max(3, min(pop_size, budget))
    lo = np.array([s.lower for s in specs], float); hi = np.array([s.upper for s in specs], float)
    x = _init_population(rng, specs, pop_size)
    v = rng.uniform(-0.1, 0.1, size=x.shape) * (hi - lo)
    fit = np.array([objective(xx) for xx in x]); used = pop_size
    pbest, pfit = x.copy(), fit.copy(); g = int(np.argmin(pfit)); gbest = pbest[g].copy(); gfit = float(pfit[g])
    while used < budget:
        for i in range(pop_size):
            if used >= budget: break
            r1, r2 = rng.random(len(specs)), rng.random(len(specs))
            v[i] = 0.72*v[i] + 1.49*r1*(pbest[i]-x[i]) + 1.49*r2*(gbest-x[i])
            x[i] = _clip_cast(x[i] + v[i], specs)
            f = objective(x[i]); used += 1
            if f < pfit[i]:
                pbest[i], pfit[i] = x[i].copy(), f
                if f < gfit: gbest, gfit = x[i].copy(), float(f)
    return gbest, gfit


def _run_cem(objective, specs, budget, pop_size, rng):
    pop_size = max(4, min(pop_size, budget)); d = len(specs)
    lo = np.array([s.lower for s in specs], float); hi = np.array([s.upper for s in specs], float)
    mean = 0.5*(lo+hi); std = np.maximum((hi-lo)/3.0, 1e-9)
    best, best_f, used = mean.copy(), math.inf, 0
    while used < budget:
        n = min(pop_size, budget-used)
        pop = rng.normal(mean, std, size=(n,d)); pop = np.array([_clip_cast(x,specs) for x in pop])
        fit = np.array([objective(x) for x in pop]); used += n
        k = int(np.argmin(fit))
        if fit[k] < best_f: best, best_f = pop[k].copy(), float(fit[k])
        elite_n = max(2, int(math.ceil(0.2*n)))
        elite = pop[np.argsort(fit)[:elite_n]]
        mean = 0.7*mean + 0.3*elite.mean(axis=0)
        std = np.maximum(0.7*std + 0.3*elite.std(axis=0, ddof=0), 1e-6*np.maximum(hi-lo,1.0))
    return best, best_f


def _run_iess(objective, specs, budget, pop_size, rng):
    pop_size = max(5, min(pop_size, budget)); d = len(specs)
    lo = np.array([s.lower for s in specs], float); hi = np.array([s.upper for s in specs], float)
    span = np.maximum(hi-lo, 1e-12)
    pop = _init_population(rng, specs, pop_size); fit = np.array([objective(x) for x in pop]); used = pop_size
    best_i = int(np.argmin(fit)); best, best_f = pop[best_i].copy(), float(fit[best_i])
    initial_budget = max(budget, 1)
    while used < budget:
        order = np.argsort(fit); elite_n = max(3, int(math.ceil(0.25*len(pop)))); elite = pop[order[:elite_n]]
        cov = np.cov(elite, rowvar=False) if elite_n > 1 else np.diag((0.15*span)**2)
        if d == 1: cov = np.array([[float(np.atleast_1d(cov)[0])]])
        cov = np.asarray(cov, float) + np.diag((1e-6*span)**2)
        try: L = np.linalg.cholesky(cov)
        except np.linalg.LinAlgError: L = np.diag(np.maximum(elite.std(axis=0), 1e-6*span))
        progress = used/initial_budget; alpha = max(0.08, (1-progress)**1.5); beta = 0.35 + 0.45*progress
        new_pop=[]; new_fit=[]
        for _ in range(min(pop_size, budget-used)):
            anchor = elite[rng.integers(0, elite_n)]
            cand = anchor + alpha*(L @ rng.normal(size=d)) + beta*(best-anchor)
            if rng.random() < 0.12: cand = lo + rng.random(d)*span
            cand = _clip_cast(cand, specs); f = objective(cand); used += 1
            new_pop.append(cand); new_fit.append(f)
            if f < best_f: best, best_f = cand.copy(), float(f)
        pool = np.vstack([pop, np.asarray(new_pop)]); pool_fit = np.r_[fit, np.asarray(new_fit)]
        keep = np.argsort(pool_fit)[:pop_size]; pop, fit = pool[keep], pool_fit[keep]
    return best, best_f


def run_equal_budget_benchmark(adapter, all_specs, parameter_names: Sequence[str], strategy: str, severity: str, output_name: str,
                               evaluation_budget: int = 400, runs: int = 10, population_size: int = 20, seed: int = 42):
    chosen = [s for s in all_specs if s.name in set(parameter_names) and getattr(s, "enabled", True)]
    if not chosen: raise ValueError("Select at least one enabled parameter for optimizer benchmarking.")
    specs = _specs(chosen)
    base_params = {s.name: getattr(s, "baseline") for s in all_specs}
    algorithms = {"IESS": _run_iess, "DE": _run_de, "PSO": _run_pso, "CEM": _run_cem}
    rows=[]
    for run in range(int(runs)):
        for ai,(name,fn) in enumerate(algorithms.items()):
            run_seed = int(seed + 1009*run + 97*ai)
            rng = np.random.default_rng(run_seed)
            obj, counter = _make_objective(adapter, base_params, specs, strategy, severity, output_name, run_seed)
            xbest, fbest = fn(obj, specs, int(evaluation_budget), int(population_size), rng)
            row={"run":run+1,"seed":run_seed,"algorithm":name,"best_objective":fbest,"evaluations":counter["n"],"strategy":strategy,"severity":severity,"output":output_name}
            row.update({f"x_{s.name}": float(xbest[j]) for j,s in enumerate(specs)})
            rows.append(row)
    raw=pd.DataFrame(rows)
    summary=(raw.groupby("algorithm", as_index=False).agg(
        count=("best_objective","count"), mean=("best_objective","mean"), median=("best_objective","median"),
        std=("best_objective","std"), minimum=("best_objective","min"), maximum=("best_objective","max")
    ))
    stats=[]
    pivot=raw.pivot(index="run", columns="algorithm", values="best_objective")
    if all(a in pivot for a in algorithms) and len(pivot)>=3:
        try:
            test=friedmanchisquare(*[pivot[a].values for a in algorithms])
            stats.append({"test":"Friedman","comparison":"all algorithms","statistic":float(test.statistic),"p_value":float(test.pvalue)})
        except Exception: pass
        if "IESS" in pivot:
            for other in [a for a in algorithms if a!="IESS"]:
                try:
                    w=wilcoxon(pivot["IESS"].values,pivot[other].values,zero_method="zsplit")
                    stats.append({"test":"Wilcoxon paired","comparison":f"IESS vs {other}","statistic":float(w.statistic),"p_value":float(w.pvalue)})
                except Exception: pass
    return raw, summary, pd.DataFrame(stats)

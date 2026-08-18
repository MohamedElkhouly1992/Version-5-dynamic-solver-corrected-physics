from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

import sensitivity_core as core
from robust_io import read_csv_robust
from publication_export import make_publication_bundle
from optimizer_benchmark import run_equal_budget_benchmark


st.set_page_config(
    page_title="HVAC v3 Sensitivity Studio",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("HVAC v3 — Local and Global Sensitivity Studio")
st.caption(
    "Dataset-independent analysis connected directly to the latest HVAC v3 model through a small adapter. "
    "Includes OAT local sensitivity, Monte Carlo robustness, Morris screening, Sobol indices, benchmarks, "
    "ablation, optimizer robustness, and separate downloads for every result."
)


DEFAULTS = {
    "adapter": None,
    "adapter_path": None,
    "specs": None,
    "outputs": None,
    "metadata": {},
    "results": {},
    "figures": {},
    "project_hash": None,
}
for key, value in DEFAULTS.items():
    st.session_state.setdefault(key, value)


RESULT_DIR = Path(tempfile.gettempdir()) / "hvac_v3_sensitivity_projects"
RESULT_DIR.mkdir(parents=True, exist_ok=True)


def add_result(name: str, frame: pd.DataFrame) -> None:
    results = dict(st.session_state.results)
    results[name] = frame.copy()
    st.session_state.results = results


def add_figure(name: str, fig: plt.Figure) -> None:
    figures = dict(st.session_state.figures)
    figures[name] = {
        "png": core.figure_png_bytes(fig),
        "svg": core.figure_svg_bytes(fig),
    }
    st.session_state.figures = figures
    plt.close(fig)


def progress_callback(progress_bar, status_box):
    def callback(done: int, total: int, message: str) -> None:
        progress_bar.progress(min(done / max(total, 1), 1.0))
        status_box.caption(message)
    return callback


def show_table_downloads(name: str, frame: pd.DataFrame) -> None:
    c1, c2 = st.columns([1, 1])
    with c1:
        st.download_button(
            "Download CSV",
            data=core.frame_csv_bytes(frame),
            file_name=f"{name}.csv",
            mime="text/csv",
            key=f"dl_csv_{name}",
            width="stretch",
        )
    with c2:
        st.download_button(
            "Download JSON",
            data=core.json_bytes(frame.to_dict("records")),
            file_name=f"{name}.json",
            mime="application/json",
            key=f"dl_json_{name}",
            width="stretch",
        )


def show_figure_downloads(name: str) -> None:
    item = st.session_state.figures.get(name)
    if not item:
        return
    c1, c2 = st.columns([1, 1])
    with c1:
        st.download_button(
            "Download PNG",
            data=item["png"],
            file_name=f"{name}.png",
            mime="image/png",
            key=f"dl_png_{name}",
            width="stretch",
        )
    with c2:
        st.download_button(
            "Download SVG",
            data=item["svg"],
            file_name=f"{name}.svg",
            mime="image/svg+xml",
            key=f"dl_svg_{name}",
            width="stretch",
        )


def load_uploaded_project(zip_bytes: bytes, adapter_relative_path: str) -> tuple[core.HVACModelAdapter, Path, str]:
    digest = hashlib.sha256(zip_bytes).hexdigest()[:16]
    project_root = RESULT_DIR / digest
    if project_root.exists():
        shutil.rmtree(project_root)
    core.safe_extract_zip(zip_bytes, project_root)
    direct = project_root / adapter_relative_path
    if direct.exists():
        adapter_path = direct
    else:
        matches = list(project_root.rglob(Path(adapter_relative_path).name))
        if len(matches) != 1:
            raise FileNotFoundError(
                f"Could not uniquely locate {adapter_relative_path!r} in the uploaded ZIP. "
                f"Found {len(matches)} matching files."
            )
        adapter_path = matches[0]
    return core.HVACModelAdapter(adapter_path), adapter_path, digest


def app_ready() -> bool:
    return st.session_state.adapter is not None and st.session_state.specs is not None


with st.sidebar:
    st.header("Model connection")
    source_mode = st.radio(
        "Adapter source",
        ["Upload HVAC v3 project ZIP", "Use adapter already beside this app", "Use bundled demo adapter"],
        help="Uploaded and local Python code is executed. Use only trusted files.",
    )

    adapter_relative = "sensitivity_adapter.py"
    uploaded_zip = None
    local_path = None
    if source_mode == "Upload HVAC v3 project ZIP":
        uploaded_zip = st.file_uploader(
            "Upload the HVAC v3 project ZIP",
            type=["zip"],
            help="Include hvac_v3.py or its engine files plus sensitivity_adapter.py.",
        )
        adapter_relative = st.text_input("Adapter path inside ZIP", "sensitivity_adapter.py")
    elif source_mode == "Use adapter already beside this app":
        local_path = st.text_input("Adapter file path", "sensitivity_adapter.py")
    else:
        local_path = str(Path(__file__).parent / "demo_sensitivity_adapter.py")
        st.warning("The demo backend is only for checking the software workflow; it is not a scientific HVAC result.")

    parameter_upload = st.file_uploader(
        "Optional revised parameter-range CSV",
        type=["csv"],
        help="Use the downloadable template after first loading the model.",
    )

    connect = st.button("Load model adapter", type="primary", width="stretch")
    if connect:
        try:
            if source_mode == "Upload HVAC v3 project ZIP":
                if uploaded_zip is None:
                    raise ValueError("Upload the project ZIP first.")
                adapter, path, digest = load_uploaded_project(uploaded_zip.getvalue(), adapter_relative)
            else:
                path = Path(local_path).expanduser().resolve()
                adapter = core.HVACModelAdapter(path)
                digest = hashlib.sha256(str(path).encode()).hexdigest()[:16]
            specs = adapter.parameter_specs()
            if parameter_upload is not None:
                specs = core.specs_from_frame(read_csv_robust(io.BytesIO(parameter_upload.getvalue())))
            baseline = core.discover_outputs(adapter, specs)
            st.session_state.adapter = adapter
            st.session_state.adapter_path = str(path)
            st.session_state.specs = specs
            st.session_state.outputs = list(baseline.keys())
            st.session_state.metadata = adapter.metadata()
            st.session_state.results = {}
            st.session_state.figures = {}
            st.session_state.project_hash = digest
            st.success("HVAC v3 adapter loaded successfully.")
        except Exception as exc:
            st.error(f"Model loading failed: {exc}")

    if app_ready():
        st.success("Model ready")
        st.caption(st.session_state.adapter_path)
        spec_frame = core.specs_to_frame(st.session_state.specs)
        st.download_button(
            "Download parameter-range template",
            data=core.frame_csv_bytes(spec_frame),
            file_name="sensitivity_parameter_ranges.csv",
            mime="text/csv",
            width="stretch",
        )

    st.divider()
    st.header("Common analysis settings")
    strategy = st.selectbox("Primary strategy", core.DEFAULT_STRATEGIES, index=3)
    severity = st.selectbox("Severity", core.DEFAULT_SEVERITIES, index=1)
    seed = st.number_input("Random seed", min_value=0, max_value=2_000_000_000, value=42, step=1)


if not app_ready():
    st.info(
        "Connect the latest HVAC v3 model using a trusted project ZIP containing `sensitivity_adapter.py`. "
        "The package includes an adapter template and integration guide."
    )
    st.stop()

adapter: core.HVACModelAdapter = st.session_state.adapter
specs: list[core.ParameterSpec] = st.session_state.specs
all_outputs: list[str] = st.session_state.outputs

with st.expander("Connected model, outputs, and parameter ranges", expanded=False):
    st.write("**Adapter:**", st.session_state.adapter_path)
    st.json(st.session_state.metadata)
    st.write("**Discovered scalar outputs:**", all_outputs)
    st.dataframe(core.specs_to_frame(specs), width="stretch")

selected_outputs = st.multiselect(
    "Outputs to analyse",
    all_outputs,
    default=all_outputs[: min(5, len(all_outputs))],
    help="Select only scientifically relevant scalar summary outputs to reduce runtime.",
)
selected_parameters = st.multiselect(
    "Parameters to vary",
    [s.name for s in specs if s.enabled],
    default=[s.name for s in specs if s.enabled],
)

if not selected_outputs:
    st.warning("Select at least one output.")
    st.stop()
if not selected_parameters:
    st.warning("Select at least one parameter.")
    st.stop()


tabs = st.tabs(
    [
        "Baseline Matrix",
        "Benchmarks",
        "Local OAT",
        "Monte Carlo",
        "Ablation",
        "Morris",
        "Sobol",
        "Optimizer",
        "Connectivity",
        "Export Center",
        "Equal-Budget Optimizer Benchmark",
    ]
)


with tabs[0]:
    st.subheader("Baseline strategy–severity matrix")
    strategies = st.multiselect("Strategies", core.DEFAULT_STRATEGIES, default=list(core.DEFAULT_STRATEGIES), key="base_strategies")
    severities = st.multiselect("Severity levels", core.DEFAULT_SEVERITIES, default=list(core.DEFAULT_SEVERITIES), key="base_severities")
    if st.button("Run baseline matrix", type="primary", key="run_base"):
        total = len(strategies) * len(severities)
        bar, status = st.progress(0.0), st.empty()
        prog = core.AnalysisProgress(total, callback=progress_callback(bar, status))
        frame = core.run_strategy_matrix(adapter, specs, strategies, severities, int(seed), prog)
        add_result("baseline_strategy_severity_matrix", frame)
        bar.progress(1.0)
        status.caption("Complete")
    frame = st.session_state.results.get("baseline_strategy_severity_matrix")
    if frame is not None:
        st.dataframe(frame, width="stretch")
        show_table_downloads("baseline_strategy_severity_matrix", frame)
        output = st.selectbox("Plot output", [x for x in selected_outputs if x in frame.columns], key="base_plot_output")
        fig = core.plot_grouped_bars(frame, "severity", "strategy", output, f"{output} by strategy and severity")
        st.pyplot(fig)
        add_figure(f"baseline_{output}", fig)
        show_figure_downloads(f"baseline_{output}")


with tabs[1]:
    st.subheader("Benchmark cases")
    cases = adapter.benchmark_cases()
    st.json(cases)
    strategies = st.multiselect("Benchmark strategies", core.DEFAULT_STRATEGIES, default=list(core.DEFAULT_STRATEGIES), key="bench_strategies")
    if st.button("Run benchmarks", type="primary", key="run_bench"):
        bar, status = st.progress(0.0), st.empty()
        prog = core.AnalysisProgress(len(cases) * len(strategies), callback=progress_callback(bar, status))
        frame = core.run_benchmarks(adapter, specs, strategies, cases, int(seed), prog)
        add_result("benchmark_results", frame)
        bar.progress(1.0)
    frame = st.session_state.results.get("benchmark_results")
    if frame is not None:
        st.dataframe(frame, width="stretch")
        show_table_downloads("benchmark_results", frame)
        output = st.selectbox("Benchmark plot output", [x for x in selected_outputs if x in frame.columns], key="bench_plot_output")
        fig = core.plot_grouped_bars(frame, "benchmark_case", "strategy", output, f"Benchmark cases — {output}")
        st.pyplot(fig)
        add_figure(f"benchmarks_{output}", fig)
        show_figure_downloads(f"benchmarks_{output}")


with tabs[2]:
    st.subheader("One-at-a-time local sensitivity")
    st.caption("Each selected parameter is moved to its lower and upper bound while all other inputs remain at baseline.")
    if st.button("Run OAT sensitivity", type="primary", key="run_oat"):
        total = 2 * len(selected_parameters)
        bar, status = st.progress(0.0), st.empty()
        prog = core.AnalysisProgress(total, callback=progress_callback(bar, status))
        frame = core.run_oat(
            adapter, specs, strategy, severity, selected_outputs, selected_parameters, int(seed), prog
        )
        add_result(f"oat_{strategy}_{severity}", frame)
        bar.progress(1.0)
    oat_name = f"oat_{strategy}_{severity}"
    frame = st.session_state.results.get(oat_name)
    if frame is not None:
        st.dataframe(frame, width="stretch")
        show_table_downloads(oat_name, frame)
        output = st.selectbox("OAT tornado output", sorted(frame["output"].unique()), key="oat_output")
        fig = core.plot_oat_tornado(frame, output, f"OAT sensitivity — {strategy} — {severity} — {output}")
        st.pyplot(fig)
        fig_name = f"oat_tornado_{strategy}_{severity}_{output}"
        add_figure(fig_name, fig)
        show_figure_downloads(fig_name)


with tabs[3]:
    st.subheader("Paired Monte Carlo uncertainty and strategy robustness")
    c1, c2, c3 = st.columns(3)
    with c1:
        mc_samples = st.number_input("Samples", 20, 10000, 300, 20)
    with c2:
        mc_sampling = st.selectbox("Sampling", ["latin_hypercube", "sobol", "random"])
    with c3:
        fixed_opt_seed = st.checkbox("Fix optimizer seed", value=True, help="Recommended when studying physical parameter uncertainty.")
    mc_strategies = st.multiselect("Monte Carlo strategies", core.DEFAULT_STRATEGIES, default=list(core.DEFAULT_STRATEGIES), key="mc_strategies")
    if st.button("Run Monte Carlo", type="primary", key="run_mc"):
        total = int(mc_samples) * len(mc_strategies)
        bar, status = st.progress(0.0), st.empty()
        prog = core.AnalysisProgress(total, callback=progress_callback(bar, status))
        samples, outputs, ranking = core.run_monte_carlo(
            adapter,
            specs,
            mc_strategies,
            severity,
            int(mc_samples),
            selected_outputs,
            selected_parameters,
            int(seed),
            mc_sampling,
            fixed_opt_seed,
            prog,
        )
        add_result(f"monte_carlo_samples_{severity}", samples)
        add_result(f"monte_carlo_outputs_{severity}", outputs)
        add_result(f"strategy_ranking_{severity}", ranking)
        bar.progress(1.0)
    mc_output_name = f"monte_carlo_outputs_{severity}"
    outputs = st.session_state.results.get(mc_output_name)
    if outputs is not None:
        ranking = st.session_state.results[f"strategy_ranking_{severity}"]
        st.write("**Strategy-ranking robustness**")
        st.dataframe(ranking, width="stretch")
        show_table_downloads(f"strategy_ranking_{severity}", ranking)
        with st.expander("Raw Monte Carlo outputs"):
            st.dataframe(outputs, width="stretch")
            show_table_downloads(mc_output_name, outputs)
            samples = st.session_state.results[f"monte_carlo_samples_{severity}"]
            show_table_downloads(f"monte_carlo_samples_{severity}", samples)
        output = st.selectbox("Monte Carlo boxplot output", [x for x in selected_outputs if x in outputs.columns], key="mc_output")
        fig = core.plot_boxplot(outputs, output, f"Monte Carlo robustness — {severity} — {output}")
        st.pyplot(fig)
        fig_name = f"monte_carlo_boxplot_{severity}_{output}"
        add_figure(fig_name, fig)
        show_figure_downloads(fig_name)


with tabs[4]:
    st.subheader("S3 ablation study")
    cases = adapter.ablation_cases()
    st.json(cases)
    if st.button("Run ablation", type="primary", key="run_ablation"):
        bar, status = st.progress(0.0), st.empty()
        prog = core.AnalysisProgress(len(cases), callback=progress_callback(bar, status))
        frame = core.run_ablation(adapter, specs, severity, cases, int(seed), prog)
        add_result(f"ablation_{severity}", frame)
        bar.progress(1.0)
    frame = st.session_state.results.get(f"ablation_{severity}")
    if frame is not None:
        st.dataframe(frame, width="stretch")
        show_table_downloads(f"ablation_{severity}", frame)
        output = st.selectbox("Ablation plot output", [x for x in selected_outputs if x in frame.columns], key="ablation_output")
        fig, ax = plt.subplots(figsize=(10, 5.5))
        ax.bar(frame["ablation_case"], frame[output])
        ax.set_title(f"Ablation study — {severity} — {output}")
        ax.set_ylabel(output.replace("_", " "))
        ax.tick_params(axis="x", rotation=25)
        fig.tight_layout()
        st.pyplot(fig)
        fig_name = f"ablation_{severity}_{output}"
        add_figure(fig_name, fig)
        show_figure_downloads(fig_name)


with tabs[5]:
    st.subheader("Morris global screening")
    c1, c2 = st.columns(2)
    with c1:
        trajectories = st.number_input("Trajectories", 4, 200, 20, 1)
    with c2:
        levels = st.selectbox("Grid levels", [4, 6, 8, 10], index=1)
    estimated = int(trajectories) * (len(selected_parameters) + 1)
    st.info(f"Expected model evaluations: {estimated:,}")
    if st.button("Run Morris screening", type="primary", key="run_morris"):
        bar, status = st.progress(0.0), st.empty()
        prog = core.AnalysisProgress(estimated, callback=progress_callback(bar, status))
        evaluations, effects, indices = core.run_morris(
            adapter,
            specs,
            strategy,
            severity,
            selected_outputs,
            int(trajectories),
            int(levels),
            selected_parameters,
            int(seed),
            prog,
        )
        add_result(f"morris_evaluations_{strategy}_{severity}", evaluations)
        add_result(f"morris_effects_{strategy}_{severity}", effects)
        add_result(f"morris_indices_{strategy}_{severity}", indices)
        bar.progress(1.0)
    name = f"morris_indices_{strategy}_{severity}"
    indices = st.session_state.results.get(name)
    if indices is not None:
        st.dataframe(indices, width="stretch")
        show_table_downloads(name, indices)
        with st.expander("Raw Morris evaluations and elementary effects"):
            show_table_downloads(f"morris_evaluations_{strategy}_{severity}", st.session_state.results[f"morris_evaluations_{strategy}_{severity}"])
            show_table_downloads(f"morris_effects_{strategy}_{severity}", st.session_state.results[f"morris_effects_{strategy}_{severity}"])
        output = st.selectbox("Morris plot output", sorted(indices["output"].unique()), key="morris_output")
        fig = core.plot_morris(indices, output, f"Morris screening — {strategy} — {severity} — {output}")
        st.pyplot(fig)
        fig_name = f"morris_{strategy}_{severity}_{output}"
        add_figure(fig_name, fig)
        show_figure_downloads(fig_name)


with tabs[6]:
    st.subheader("Sobol first- and total-order global sensitivity")
    c1, c2 = st.columns(2)
    with c1:
        base_size = st.selectbox("Base sample N", [64, 128, 256, 512, 1024], index=2)
    with c2:
        bootstrap = st.number_input("Bootstrap repetitions", 50, 3000, 300, 50)
    estimated = int(base_size) * (len(selected_parameters) + 2)
    st.info(f"Expected model evaluations: {estimated:,}. Start with fewer Morris-screened parameters for expensive models.")
    if st.button("Run Sobol analysis", type="primary", key="run_sobol"):
        bar, status = st.progress(0.0), st.empty()
        prog = core.AnalysisProgress(estimated, callback=progress_callback(bar, status))
        evaluations, indices = core.run_sobol(
            adapter,
            specs,
            strategy,
            severity,
            selected_outputs,
            int(base_size),
            int(bootstrap),
            selected_parameters,
            int(seed),
            prog,
        )
        add_result(f"sobol_evaluations_{strategy}_{severity}", evaluations)
        add_result(f"sobol_indices_{strategy}_{severity}", indices)
        bar.progress(1.0)
    name = f"sobol_indices_{strategy}_{severity}"
    indices = st.session_state.results.get(name)
    if indices is not None:
        st.dataframe(indices, width="stretch")
        show_table_downloads(name, indices)
        with st.expander("Raw Sobol evaluations"):
            show_table_downloads(f"sobol_evaluations_{strategy}_{severity}", st.session_state.results[f"sobol_evaluations_{strategy}_{severity}"])
        output = st.selectbox("Sobol plot output", sorted(indices["output"].unique()), key="sobol_output")
        fig = core.plot_sobol(indices, output, f"Sobol indices — {strategy} — {severity} — {output}")
        st.pyplot(fig)
        fig_name = f"sobol_{strategy}_{severity}_{output}"
        add_figure(fig_name, fig)
        show_figure_downloads(fig_name)


with tabs[7]:
    st.subheader("S3 optimizer robustness")
    seed_text = st.text_input("Seeds", "1,2,3,4,5,6,7,8,9,10")
    pop_text = st.text_input("Population values", "12,18,24,30")
    iter_text = st.text_input("Iteration values", "5,10,15,20")
    pop_param = st.text_input("Population parameter name", "optimizer_population")
    iter_param = st.text_input("Iteration parameter name", "optimizer_iterations")
    try:
        seeds = [int(x.strip()) for x in seed_text.split(",") if x.strip()]
        pops = [int(x.strip()) for x in pop_text.split(",") if x.strip()]
        iters = [int(x.strip()) for x in iter_text.split(",") if x.strip()]
    except ValueError:
        st.error("Seeds, populations, and iterations must be comma-separated integers.")
        seeds, pops, iters = [], [], []
    estimated = len(seeds) * len(pops) * len(iters)
    st.info(f"Expected S3 evaluations: {estimated:,}")
    if st.button("Run optimizer robustness", type="primary", key="run_opt", disabled=not seeds or not pops or not iters):
        bar, status = st.progress(0.0), st.empty()
        prog = core.AnalysisProgress(estimated, callback=progress_callback(bar, status))
        raw, summary = core.run_optimizer_robustness(
            adapter,
            specs,
            severity,
            selected_outputs,
            seeds,
            pops,
            iters,
            pop_param,
            iter_param,
            prog,
        )
        add_result(f"optimizer_raw_{severity}", raw)
        add_result(f"optimizer_summary_{severity}", summary)
        bar.progress(1.0)
    summary = st.session_state.results.get(f"optimizer_summary_{severity}")
    if summary is not None:
        st.dataframe(summary, width="stretch")
        show_table_downloads(f"optimizer_summary_{severity}", summary)
        with st.expander("Raw optimizer repetitions"):
            show_table_downloads(f"optimizer_raw_{severity}", st.session_state.results[f"optimizer_raw_{severity}"])


with tabs[8]:
    st.subheader("Parameter-connectivity diagnostic")
    perturb = st.slider("Perturbation fraction", 0.10, 1.00, 0.50, 0.05)
    st.caption("Use this before publication to detect parameters that are defined in the interface but not actually connected to the numerical model.")
    if st.button("Run connectivity test", type="primary", key="run_connect"):
        bar, status = st.progress(0.0), st.empty()
        prog = core.AnalysisProgress(len(selected_parameters), callback=progress_callback(bar, status))
        frame = core.parameter_connectivity_test(
            adapter, specs, strategy, severity, selected_outputs, float(perturb), selected_parameters, int(seed), prog
        )
        add_result(f"connectivity_{strategy}_{severity}", frame)
        bar.progress(1.0)
    frame = st.session_state.results.get(f"connectivity_{strategy}_{severity}")
    if frame is not None:
        st.dataframe(frame, width="stretch")
        show_table_downloads(f"connectivity_{strategy}_{severity}", frame)
        disconnected = frame.groupby("parameter")["connected"].any()
        disconnected = disconnected[~disconnected].index.tolist()
        if disconnected:
            st.warning("No selected output changed for: " + ", ".join(disconnected))
        else:
            st.success("Every tested parameter affected at least one selected output.")


with tabs[9]:
    st.subheader("Export center")
    st.caption("Every table and figure can be downloaded separately here, in addition to the buttons on its analysis tab.")
    if not st.session_state.results and not st.session_state.figures:
        st.info("Run at least one analysis to populate the export center.")
    else:
        files: dict[str, bytes] = {}
        st.write("### Tables")
        for name, frame in st.session_state.results.items():
            c1, c2, c3 = st.columns([3, 1, 1])
            c1.write(name)
            csv_data = core.frame_csv_bytes(frame)
            json_data = core.json_bytes(frame.to_dict("records"))
            c2.download_button("CSV", csv_data, f"{name}.csv", "text/csv", key=f"export_csv_{name}")
            c3.download_button("JSON", json_data, f"{name}.json", "application/json", key=f"export_json_{name}")
            files[f"tables/{name}.csv"] = csv_data
            files[f"tables/{name}.json"] = json_data
        st.write("### Figures")
        for name, item in st.session_state.figures.items():
            c1, c2, c3 = st.columns([3, 1, 1])
            c1.write(name)
            c2.download_button("PNG", item["png"], f"{name}.png", "image/png", key=f"export_png_{name}")
            c3.download_button("SVG", item["svg"], f"{name}.svg", "image/svg+xml", key=f"export_svg_{name}")
            files[f"figures/{name}.png"] = item["png"]
            files[f"figures/{name}.svg"] = item["svg"]
        files["metadata/model_metadata.json"] = core.json_bytes(st.session_state.metadata)
        files["metadata/parameter_ranges.csv"] = core.frame_csv_bytes(core.specs_to_frame(specs))
        st.download_button(
            "Download all generated results as ZIP",
            data=core.create_results_zip(files),
            file_name="hvac_v3_sensitivity_results.zip",
            mime="application/zip",
            type="primary",
            width="stretch",
        )


with tabs[10]:
    st.subheader("Equal-budget optimizer benchmark")
    st.caption("Compares IESS, differential evolution, PSO, and cross-entropy search using the same objective-evaluation budget and independent seeds. This is an additive benchmark and does not replace the existing optimizer or validation strategy.")
    bench_output = st.selectbox("Objective output to minimize", selected_outputs, key="eqbench_output")
    bench_params = st.multiselect("Decision parameters", selected_parameters, default=selected_parameters[: min(6, len(selected_parameters))], key="eqbench_params")
    c1,c2,c3=st.columns(3)
    budget=int(c1.number_input("Evaluations per algorithm/run", min_value=40, max_value=100000, value=400, step=40, key="eqbench_budget"))
    runs=int(c2.number_input("Independent runs", min_value=3, max_value=100, value=10, step=1, key="eqbench_runs"))
    pop=int(c3.number_input("Population/sample size", min_value=4, max_value=500, value=20, step=1, key="eqbench_pop"))
    if st.button("Run equal-budget benchmark", type="primary", key="run_eqbench", disabled=not bench_params):
        try:
            raw, summary, stats = run_equal_budget_benchmark(adapter, specs, bench_params, strategy, severity, bench_output, budget, runs, pop, int(seed))
            add_result(f"equal_budget_optimizer_raw_{strategy}_{severity}", raw)
            add_result(f"equal_budget_optimizer_summary_{strategy}_{severity}", summary)
            add_result(f"equal_budget_optimizer_stats_{strategy}_{severity}", stats)
            st.success("Equal-budget optimizer benchmark completed.")
        except Exception as exc:
            st.exception(exc)
    for suffix,title in [("summary","Summary"),("stats","Statistical tests"),("raw","Independent-run results")]:
        frame=st.session_state.results.get(f"equal_budget_optimizer_{suffix}_{strategy}_{severity}")
        if frame is not None:
            st.markdown(f"### {title}")
            st.dataframe(frame, width="stretch")
            show_table_downloads(f"equal_budget_optimizer_{suffix}_{strategy}_{severity}", frame)

# Publication-grade package is also available from the existing Export Center.
with tabs[9]:
    st.divider()
    st.subheader("Publication package")
    st.caption("Exports raw/full-precision tables, rounded manuscript tables, figures, parameter ranges, and a software/run manifest. It does not change any validation calculation.")
    rounding=int(st.number_input("Manuscript table decimal places", min_value=2, max_value=10, value=5, step=1, key="pub_rounding"))
    pub_meta={
        "project_hash": st.session_state.get("project_hash"),
        "adapter_path": st.session_state.get("adapter_path"),
        "strategy": strategy,
        "severity": severity,
        "random_seed": int(seed),
        "selected_outputs": selected_outputs,
        "selected_parameters": selected_parameters,
        "model_metadata": st.session_state.get("metadata", {}),
    }
    package=make_publication_bundle(st.session_state.results, st.session_state.figures, pub_meta, core.specs_to_frame(specs), rounding)
    st.download_button("Download publication-ready reproducibility package", data=package, file_name="DA_HVAC_publication_results.zip", mime="application/zip", type="primary", width="stretch")

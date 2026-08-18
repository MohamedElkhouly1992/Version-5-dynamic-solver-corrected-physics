from pathlib import Path
import sensitivity_core as core


def main() -> None:
    adapter = core.HVACModelAdapter(Path(__file__).parent / "examples" / "demo_sensitivity_adapter.py")
    specs = adapter.parameter_specs()
    core.discover_outputs(adapter, specs)
    core.run_oat(
        adapter,
        specs,
        "S3",
        "Moderate",
        ["total_energy_MWh"],
        ["internal_gain_factor", "delta_trigger"],
    )
    core.run_morris(
        adapter,
        specs,
        "S3",
        "Moderate",
        ["total_energy_MWh"],
        trajectories=4,
        levels=4,
        parameter_names=["internal_gain_factor", "delta_trigger"],
    )
    core.run_sobol(
        adapter,
        specs,
        "S3",
        "Moderate",
        ["total_energy_MWh"],
        base_size=16,
        bootstrap=10,
        parameter_names=["internal_gain_factor", "delta_trigger"],
    )
    print("Core smoke test passed.")


if __name__ == "__main__":
    main()

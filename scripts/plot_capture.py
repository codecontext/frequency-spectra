#!/usr/bin/env python3
"""Plot waveform and FFT records captured from the Frequency Spectra Zephyr app.

The input is a text log containing FREQSPEC,WAVE, FREQSPEC,SPECTRUM,
FREQSPEC,RESULT, and FREQSPEC,SUITE CSV records. QEMU boot output is ignored;
detector results and the suite summary must indicate success before plotting.
"""

import argparse
from pathlib import Path

import matplotlib
import numpy as np


def parse_capture(path: Path) -> dict[str, dict[str, object]]:
    """Read and validate waveform and spectrum records from a UART capture."""
    cases: dict[str, dict[str, object]] = {}

    for line_number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
        fields = line.strip().split(",")
        if len(fields) < 6 or fields[0] != "FREQSPEC":
            continue

        record_type = fields[1]
        if record_type not in {"WAVE", "SPECTRUM"}:
            continue

        try:
            metadata = dict(field.split("=", 1) for field in fields[2:5])
            case_name = metadata["case"]
            sample_rate_hz = int(metadata["rate_hz"])
            sample_count = int(metadata["sample_count"])
            values = [int(value) for value in fields[5:]]
        except (KeyError, ValueError) as error:
            raise ValueError(f"invalid {record_type} record on line {line_number}") from error

        expected_count = sample_count if record_type == "WAVE" else sample_count // 2 - 1
        if len(values) != expected_count:
            raise ValueError(
                f"{record_type} record for {case_name} on line {line_number} "
                f"has {len(values)} values; expected {expected_count}"
            )

        case = cases.setdefault(case_name, {})
        previous_rate = case.setdefault("sample_rate_hz", sample_rate_hz)
        previous_count = case.setdefault("sample_count", sample_count)
        if previous_rate != sample_rate_hz or previous_count != sample_count:
            raise ValueError(f"inconsistent frame metadata for case {case_name}")
        case[record_type.lower()] = values

    if not cases:
        raise ValueError(f"no FREQSPEC waveform or spectrum records found in {path}")

    for case_name, case in cases.items():
        if "wave" not in case or "spectrum" not in case:
            raise ValueError(f"case {case_name} is missing waveform or spectrum data")

    return cases


def validate_results(path: Path) -> None:
    """Require every reported case and the complete DSP suite to pass."""
    result_cases: dict[str, dict[str, str]] = {}
    suite_summary: dict[str, str] | None = None

    for line_number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
        fields = line.strip().split(",")
        if len(fields) < 3 or fields[0] != "FREQSPEC":
            continue

        record_type = fields[1]
        if record_type not in {"RESULT", "SUITE"}:
            continue

        try:
            values = dict(field.split("=", 1) for field in fields[2:])
            if record_type == "RESULT":
                case_name = values["case"]
                values["expected"]
                values["detected"]
                values["pass"]
                if case_name in result_cases:
                    raise ValueError(f"duplicate RESULT record for {case_name}")
                result_cases[case_name] = values
            else:
                if suite_summary is not None:
                    raise ValueError("duplicate SUITE record")
                suite_summary = values
        except (KeyError, ValueError) as error:
            raise ValueError(f"invalid {record_type} record on line {line_number}: {error}") from error

    if not result_cases:
        raise ValueError(f"no FREQSPEC RESULT records found in {path}")
    if suite_summary is None:
        raise ValueError("missing FREQSPEC SUITE record")

    try:
        passed_count = int(suite_summary["passed"])
        total_count = int(suite_summary["total"])
    except (KeyError, ValueError) as error:
        raise ValueError("invalid FREQSPEC SUITE summary") from error

    if total_count != len(result_cases) or passed_count != total_count:
        raise ValueError(
            f"DSP suite failed: {passed_count}/{total_count} cases passed, "
            f"{len(result_cases)} RESULT records found"
        )

    for case_name, result in result_cases.items():
        if result["pass"] != "1" or result["expected"] != result["detected"]:
            raise ValueError(
                f"DSP case {case_name} failed: expected {result['expected']}, "
                f"detected {result['detected']}, pass={result['pass']}"
            )


def plot_capture(cases: dict[str, dict[str, object]], output: Path, show: bool) -> None:
    """Render waveform and one-sided spectrum panels and save them to disk."""
    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(len(cases), 2, figsize=(12, 4 * len(cases)), squeeze=False)
    for row, (case_name, case) in enumerate(cases.items()):
        sample_rate_hz = int(case["sample_rate_hz"])
        sample_count = int(case["sample_count"])
        waveform = np.asarray(case["wave"], dtype=np.float64) / 1000.0
        spectrum = np.asarray(case["spectrum"], dtype=np.float64) / 1000.0
        time_ms = np.arange(sample_count) * 1000.0 / sample_rate_hz
        frequencies_hz = np.arange(1, len(spectrum) + 1) * sample_rate_hz / sample_count

        axes[row, 0].plot(time_ms, waveform, linewidth=1.0, color="#176b87")
        axes[row, 0].set_title(f"{case_name.capitalize()} waveform")
        axes[row, 0].set_xlabel("Time (ms)")
        axes[row, 0].set_ylabel("Amplitude")
        axes[row, 0].grid(True, alpha=0.25)

        axes[row, 1].plot(frequencies_hz, spectrum, linewidth=1.0, color="#d16b32")
        axes[row, 1].set_title(f"{case_name.capitalize()} spectrum")
        axes[row, 1].set_xlabel("Frequency (Hz)")
        axes[row, 1].set_ylabel("Magnitude (normalized)")
        axes[row, 1].set_xlim(0, sample_rate_hz / 2)
        axes[row, 1].grid(True, alpha=0.25)

    figure.tight_layout()
    figure.savefig(output, dpi=150)
    print(f"Saved plot: {output}")
    if show:
        plt.show()
    plt.close(figure)


def main() -> int:
    """Parse command-line options and generate the requested plot."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="captured QEMU/UART text log")
    parser.add_argument(
        "--output", type=Path, default=Path("frequency_spectra.png"), help="output PNG path"
    )
    parser.add_argument("--show", action="store_true", help="also open an interactive plot window")
    args = parser.parse_args()

    try:
        validate_results(args.input)
        cases = parse_capture(args.input)
        plot_capture(cases, args.output, args.show)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

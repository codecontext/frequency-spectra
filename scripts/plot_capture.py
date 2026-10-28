#!/usr/bin/env python3
"""Plot waveform and FFT records captured from the Frequency Spectra Zephyr app.

The input is a text log containing FREQSPEC,WAVE, FREQSPEC,SPECTRUM,
FREQSPEC,RESULT, and FREQSPEC,SUITE CSV records. QEMU boot output is ignored;
detector results and the suite summary must indicate success before plotting.
"""

import argparse
import queue
import sys
import threading
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

PLOT_BACKGROUND = "#f4f7f8"
NORMAL_HEADER_COLOR = "#263238"
NORMAL_CLASS_COLOR = "#188038"
FAULT_HEADER_COLOR = "#b3261e"
LIVE_WAVEFORM_LIMITS = (-1.5, 1.5)
LIVE_SPECTRUM_LIMITS = (0.0, 1.2)


def header_color_for_detection(detected: str) -> str:
    """Return the live status-header color for a detector classification."""
    if detected == "fault":
        return FAULT_HEADER_COLOR
    return NORMAL_CLASS_COLOR


def class_label_for_detection(detected: str) -> str:
    """Return the display label for a detector classification."""
    return "Fault" if detected == "fault" else "Normal"


def input_frequency_label(result: dict[str, str]) -> str:
    """Format the generated signal components for the waveform panel."""
    fundamental_hz = int(result["input_fundamental_hz"])
    harmonic_hz = int(result["input_harmonic_hz"])
    if harmonic_hz:
        return f"Input: {fundamental_hz} Hz + {harmonic_hz} Hz harmonic"
    return f"Input: {fundamental_hz} Hz"


def output_frequency_label(result: dict[str, str]) -> str:
    """Format the measured fundamental and harmonic-band peak for the spectrum."""
    fundamental_hz = int(result["fundamental_hz"])
    harmonic_hz = int(result["harmonic_hz"])
    return f"FFT peaks: {fundamental_hz} Hz fundamental, {harmonic_hz} Hz harmonic band"


def parse_vector_record(line: str, line_number: int = 1) -> dict[str, Any] | None:
    """Parse one waveform/spectrum line, returning None for other UART output."""
    fields = line.strip().split(",")
    if len(fields) < 6 or fields[0] != "FREQSPEC":
        return None

    record_type = fields[1]
    if record_type not in {"WAVE", "SPECTRUM"}:
        return None

    try:
        metadata: dict[str, str] = {}
        value_start = 2
        while value_start < len(fields) and "=" in fields[value_start]:
            key, value = fields[value_start].split("=", 1)
            metadata[key] = value
            value_start += 1

        case_name = metadata["case"]
        frame_id = int(metadata["frame_id"]) if "frame_id" in metadata else None
        sample_rate_hz = int(metadata["rate_hz"])
        sample_count = int(metadata["sample_count"])
        values = [int(value) for value in fields[value_start:]]
    except (KeyError, ValueError) as error:
        raise ValueError(f"invalid {record_type} record on line {line_number}") from error

    expected_count = sample_count if record_type == "WAVE" else sample_count // 2 - 1
    if sample_rate_hz <= 0 or sample_count < 4 or sample_count % 2 != 0:
        raise ValueError(f"invalid frame dimensions on line {line_number}")
    if len(values) != expected_count:
        raise ValueError(
            f"{record_type} record for {case_name} on line {line_number} "
            f"has {len(values)} values; expected {expected_count}"
        )

    return {
        "type": record_type.lower(),
        "case": case_name,
        "frame_id": frame_id,
        "sample_rate_hz": sample_rate_hz,
        "sample_count": sample_count,
        "values": values,
    }


def parse_capture(path: Path) -> dict[str, dict[str, object]]:
    """Read and validate waveform and spectrum records from a UART capture."""
    cases: dict[str, dict[str, object]] = {}

    for line_number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
        record = parse_vector_record(line, line_number)
        if record is None:
            continue

        case_name = record["case"]
        case = cases.setdefault(case_name, {})
        previous_rate = case.setdefault("sample_rate_hz", record["sample_rate_hz"])
        previous_count = case.setdefault("sample_count", record["sample_count"])
        if previous_rate != record["sample_rate_hz"] or previous_count != record["sample_count"]:
            raise ValueError(f"inconsistent frame metadata for case {case_name}")
        case[record["type"]] = record["values"]

    if not cases:
        raise ValueError(f"no FREQSPEC waveform or spectrum records found in {path}")

    for case_name, case in cases.items():
        if "wave" not in case or "spectrum" not in case:
            raise ValueError(f"case {case_name} is missing waveform or spectrum data")

    return cases


class LiveFrameBuffer:
    """Pair vectors and the classification result by case and frame ID.

    @details
    UART lines can arrive in any record order. Frames are keyed by both case
    and ID, and are released only after waveform, spectrum, and result records
    all arrive. This keeps the GUI from displaying mixed or partial frames.
    """

    def __init__(self) -> None:
        self.pending: dict[tuple[str, int], dict[str, Any]] = {}

    def add_line(self, line: str) -> dict[str, Any] | None:
        """Return a complete frame after vectors and its result have arrived."""
        fields = line.strip().split(",")
        if len(fields) >= 3 and fields[0] == "FREQSPEC" and fields[1] == "RESULT":
            try:
                result = dict(field.split("=", 1) for field in fields[2:])
                record: dict[str, Any] = {
                    "type": "result",
                    "case": result["case"],
                    "frame_id": int(result["frame_id"]),
                    "result": result,
                }
            except (KeyError, ValueError) as error:
                raise ValueError("invalid live RESULT record") from error
        else:
            record = parse_vector_record(line)
            if record is None:
                return None
            if record["frame_id"] is None:
                raise ValueError("live vector record is missing frame_id")

        key = (record["case"], record["frame_id"])
        frame = self.pending.setdefault(key, {"case": record["case"], "frame_id": record["frame_id"]})
        if record["type"] in {"wave", "spectrum"}:
            if "sample_rate_hz" in frame and (
                frame["sample_rate_hz"], frame["sample_count"]
            ) != (record["sample_rate_hz"], record["sample_count"]):
                del self.pending[key]
                raise ValueError(f"inconsistent live frame metadata for {key[0]} frame {key[1]}")
            frame["sample_rate_hz"] = record["sample_rate_hz"]
            frame["sample_count"] = record["sample_count"]
            frame[record["type"]] = record["values"]
        else:
            frame["result"] = record["result"]
        if all(record_type in frame for record_type in ("wave", "spectrum", "result")):
            del self.pending[key]
            return frame
        return None


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


def run_live_plot() -> None:
    """Read UART records from stdin and update a live waveform/spectrum plot.

    @details A background reader consumes the potentially blocking input stream;
    Matplotlib polls a thread-safe queue on its GUI thread and draws only the
    most recent complete frame.
    """
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    updates: queue.Queue[dict[str, Any]] = queue.Queue()
    frame_buffer = LiveFrameBuffer()

    def read_stream() -> None:
        for line_number, line in enumerate(sys.stdin, start=1):
            try:
                frame = frame_buffer.add_line(line)
            except ValueError as error:
                print(f"Ignoring invalid live record {line_number}: {error}", file=sys.stderr)
                continue
            if frame is not None:
                updates.put(frame)

    reader = threading.Thread(target=read_stream, name="uart-reader", daemon=True)
    reader.start()

    figure, (wave_axis, spectrum_axis) = plt.subplots(2, 1, figsize=(10, 7))
    figure.set_facecolor(PLOT_BACKGROUND)
    wave_axis.set_facecolor(PLOT_BACKGROUND)
    spectrum_axis.set_facecolor(PLOT_BACKGROUND)
    (wave_line,) = wave_axis.plot([], [], color="#176b87", linewidth=1.2)
    (spectrum_line,) = spectrum_axis.plot([], [], color="#d16b32", linewidth=1.2)
    wave_axis.set_title("Input waveform", loc="left")
    wave_axis.set_xlabel("Time (ms)")
    wave_axis.set_ylabel("Amplitude")
    wave_axis.set_ylim(*LIVE_WAVEFORM_LIMITS)
    wave_axis.grid(True, alpha=0.25)
    spectrum_axis.set_title("Magnitude spectrum", loc="left")
    spectrum_axis.set_xlabel("Frequency (Hz)")
    spectrum_axis.set_ylabel("Magnitude (normalized)")
    spectrum_axis.set_ylim(*LIVE_SPECTRUM_LIMITS)
    spectrum_axis.grid(True, alpha=0.25)
    input_frequency_text = wave_axis.text(
        1.0, 1.02, "Input: waiting", transform=wave_axis.transAxes,
        ha="right", va="bottom", fontsize=9, clip_on=False,
    )
    output_frequency_text = spectrum_axis.text(
        1.0, 1.02, "FFT peaks: waiting", transform=spectrum_axis.transAxes,
        ha="right", va="bottom", fontsize=9, clip_on=False,
    )
    status_axis = figure.add_axes([0.125, 0.945, 0.85, 0.04])
    status_axis.set_axis_off()
    status_prefix_text = status_axis.text(
        0.0,
        0.5,
        "Waiting for signal frames",
        ha="left",
        va="center",
        fontsize=12,
        fontweight="semibold",
    )
    status_class_text = status_axis.text(
        0.0,
        0.5,
        "",
        ha="left",
        va="center",
        fontsize=12,
        fontweight="semibold",
    )
    figure.subplots_adjust(top=0.91, hspace=0.38)
    axes_initialized = False

    def update_plot(_frame_number: int) -> tuple[Any, Any]:
        nonlocal axes_initialized

        latest: dict[str, Any] | None = None
        while True:
            try:
                latest = updates.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            return wave_line, spectrum_line

        sample_count = latest["sample_count"]
        sample_rate_hz = latest["sample_rate_hz"]
        waveform = np.asarray(latest["wave"], dtype=np.float64) / 1000.0
        spectrum = np.asarray(latest["spectrum"], dtype=np.float64) / 1000.0
        time_ms = np.arange(sample_count) * 1000.0 / sample_rate_hz
        frequencies_hz = np.arange(1, len(spectrum) + 1) * sample_rate_hz / sample_count

        wave_line.set_data(time_ms, waveform)
        spectrum_line.set_data(frequencies_hz, spectrum)
        if not axes_initialized:
            wave_axis.set_xlim(0, time_ms[-1])
            spectrum_axis.set_xlim(0, sample_rate_hz / 2)
            axes_initialized = True
        result = latest["result"]
        input_frequency_text.set_text(input_frequency_label(result))
        output_frequency_text.set_text(output_frequency_label(result))
        status_prefix_text.set_text(f"Frame {latest['frame_id']}: ")
        status_class_text.set_text(class_label_for_detection(result["detected"]))
        status_class_text.set_color(header_color_for_detection(result["detected"]))
        renderer = figure.canvas.get_renderer()
        prefix_bbox = status_prefix_text.get_window_extent(renderer=renderer)
        class_x, _ = status_axis.transAxes.inverted().transform(
            (prefix_bbox.x1, prefix_bbox.y0)
        )
        status_class_text.set_position((class_x, 0.5))
        return (
            wave_line,
            spectrum_line,
            status_prefix_text,
            status_class_text,
            input_frequency_text,
            output_frequency_text,
        )

    animation = FuncAnimation(figure, update_plot, interval=100, cache_frame_data=False)
    figure._live_animation = animation
    plt.show()


def main() -> int:
    """Parse command-line options and generate the requested plot."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="captured QEMU/UART text log")
    parser.add_argument(
        "--output", type=Path, default=Path("frequency_spectra.png"), help="output PNG path"
    )
    parser.add_argument("--show", action="store_true", help="also open an interactive plot window")
    parser.add_argument(
        "--live", action="store_true", help="read frame-numbered UART records continuously from stdin"
    )
    args = parser.parse_args()

    if args.live:
        run_live_plot()
        return 0
    if args.input is None:
        parser.error("--input is required unless --live is selected")

    try:
        validate_results(args.input)
        cases = parse_capture(args.input)
        plot_capture(cases, args.output, args.show)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

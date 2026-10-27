# Frequency Spectra

A Zephyr application for validating synthetic signal analysis on QEMU's
emulated Cortex-A53. It currently tests noisy normal and fault-like synthetic
signals using a Hann window, CMSIS-DSP real FFT, and a harmonic-ratio detector.
It emits waveform and spectrum vectors over UART for host-side visualization.

## Architecture

```text
Zephyr guest: synthetic signal generator
    |
    v
CMSIS-DSP: window + FFT + peak checks
    |
    v
Prefixed records over emulated UART
    |
    v
Ubuntu host: capture and plotting script
```

The normal case contains a 64 Hz fundamental with deterministic low-level
noise; the fault-like case adds a 128 Hz harmonic. The guest emits one
`FREQSPEC,WAVE` and one `FREQSPEC,SPECTRUM` CSV record per case, followed by its
classification record. The host script plots the captured waveform and
spectrum. QEMU provides functional execution and UART emulation, not physical
sampling or timing evidence. PCIe offload is intentionally out of scope. An
anomaly model may be considered later, after the DSP baseline is validated,
and will not replace the signal-processing detector.

## Tools

Verified in the development environment:

- Ubuntu Linux host.
- Zephyr 3.7.0 and `west`.
- Zephyr SDK 0.16.8 with the AArch64 cross-compiler.
- QEMU 8.2.2 with the `qemu_cortex_a53` board and Cortex-A53 CPU model.
- CMSIS-DSP module checked out; its moving-average sample builds and runs on this target.
- System Python packages: NumPy, SciPy, scikit-learn, Matplotlib, and pyserial.

The normal case contains a 64 Hz fundamental and deterministic low-level noise.
The fault-like case adds a 128 Hz harmonic. A 20% harmonic-to-fundamental
threshold is used as a simple demonstrator, not a physical diagnostic rule.
Noise is deterministic so expected checks are repeatable in QEMU.

## Run the demo

Follow these steps on the Ubuntu host. Start in the root of your Zephyr
workspace. The example assumes this repository is a sibling directory named
`frequency-spectra`; change `APP_DIR` to the correct relative path if your
checkout is elsewhere. Keep the commands in the same terminal so the variables
remain set.

### 1. Configure the workspace

Set the relative application path and activate the Zephyr Python environment:

```sh
APP_DIR=../frequency-spectra
BUILD_DIR=build/frequency-spectra
CAPTURE_LOG=build/frequency-spectra-uart.log
source .venv/bin/activate
```

### 2. Build the application

Build for the QEMU Cortex-A53 board:

```sh
west build -b qemu_cortex_a53 \
    -d "$BUILD_DIR" \
    "$APP_DIR"
```

### 3. Run QEMU and capture output

Save the console output to a log file:

```sh
west build -d "$BUILD_DIR" -t run 2>&1 \
    | tee "$CAPTURE_LOG"
```

Wait for `FREQSPEC,SUITE,passed=2,total=2`, then stop QEMU by pressing
`Ctrl+A`, followed by `X`. The capture remains in `$CAPTURE_LOG`.

### 4. Generate the plot

In the same terminal, run the plotter with the host Python environment that has
NumPy and Matplotlib installed. Leave the Zephyr virtual environment first so
`python3` resolves to the host environment:

```sh
deactivate
python3 "$APP_DIR/scripts/plot_capture.py" \
    --input "$CAPTURE_LOG" \
    --output "$BUILD_DIR/frequency_spectra.png"
```

Open `$BUILD_DIR/frequency_spectra.png`. Change the `--output` value to choose
another location, or add `--show` to open an interactive plot window.

The UART output includes `FREQSPEC,BOOT,...`, waveform and spectrum vectors,
per-case results, and the suite summary. This validates the DSP flow on
synthetic data only; it does not demonstrate real-time performance or physical
fault diagnosis.
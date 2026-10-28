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

From the application repository root, build and start live plotting with:

```sh
./scripts/run_demo.sh
```

The script automatically locates the neighboring Zephyr workspace, builds the
live configuration, selects a host Python with Matplotlib, and starts QEMU
with the live plot. No environment setup or extra flags are needed for the
standard directory layout. Set `ZEPHYR_WORKSPACE` if Zephyr is located
elsewhere, or `HOST_PYTHON` if the host Python with Matplotlib is not found
automatically.

### Live plotting

Live plotting is the default. To run the finite two-case DSP test instead, use:

```sh
./scripts/run_demo.sh --finite
```

The live mode chooses normal or fault-like input pseudo-randomly each frame, so
the same class may appear on consecutive frames. The selection sequence is
seeded at startup; it is pseudo-random, not a physical random source. The
finite mode builds and runs the one-shot test without opening a plot.

### Run the host parser tests

From the application repository root, run the regression tests with the host
Python environment:

```sh
deactivate
python3 -m unittest discover -s tests -v
```

The UART output includes `FREQSPEC,BOOT,...`, waveform and spectrum vectors,
per-case results, and the suite summary. This validates the DSP flow on
synthetic data only; it does not demonstrate real-time performance or physical
fault diagnosis.
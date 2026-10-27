# Frequency Spectra

A Zephyr application for validating synthetic signal analysis on QEMU's
emulated Cortex-A53. It currently tests noisy normal and fault-like synthetic
signals using a Hann window, CMSIS-DSP real FFT, and a harmonic-ratio detector.
Host-side capture and visualization will be added in a follow-up.

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

The first signal source is generated in software inside the Zephyr application,
with normal and fault-like synthetic cases planned. The DSP detector will
report spectral peaks or a simple anomaly indicator; the host-side script will
plot the input waveform and spectrum from captured UART output. QEMU provides
functional execution and UART emulation, not physical sampling or timing
evidence. PCIe offload is intentionally out of scope. An anomaly model may be
considered later, after the DSP baseline is validated, and will not replace the
signal-processing detector.

## Tools

Verified in the development environment:

- Ubuntu Linux host.
- Zephyr 3.7.0 and `west` from `/home/dask/work/zephyrproject`.
- Zephyr SDK 0.16.8 with the AArch64 cross-compiler.
- QEMU 8.2.2 with the `qemu_cortex_a53` board and Cortex-A53 CPU model.
- CMSIS-DSP module checked out; its moving-average sample builds and runs on this target.
- System Python packages: NumPy, SciPy, scikit-learn, Matplotlib, and pyserial.

The normal case contains a 64 Hz fundamental and deterministic low-level noise.
The fault-like case adds a 128 Hz harmonic. A 20% harmonic-to-fundamental
threshold is used as a simple demonstrator, not a physical diagnostic rule.
Noise is deterministic so expected checks are repeatable in QEMU. The capture
script and plots are not implemented yet.

## Build and run

Run these commands from the Zephyr workspace with its Python environment
active. Replace `/path/to/frequency-spectra` with this repository's path.

```sh
west build -b qemu_cortex_a53 \
  -d /tmp/frequency-spectra-build \
  /path/to/frequency-spectra
west build -d /tmp/frequency-spectra-build -t run
```

The application prints `FREQSPEC,BOOT,...` and `FREQSPEC,RESULT,...` records on
the emulated UART. This is functional algorithm validation only; it makes no
real-time or physical fault-diagnosis claims.
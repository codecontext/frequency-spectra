/**
 * @file main.c
 * @brief Synthetic vibration-spectrum analysis demo.
 *
 * @details
 * The application generates repeatable normal and fault-like sample frames,
 * processes each frame with a Hann window and CMSIS-DSP real FFT, and reports
 * a simple harmonic-ratio classification over the emulated UART. The normal
 * frame contains a 64 Hz fundamental plus low-level deterministic noise. The
 * fault-like frame adds a 128 Hz harmonic.
 *
 * The analysis path is:
 * @code
 * samples -> Hann window -> real FFT -> magnitude bins
 *         -> harmonic/fundamental ratio -> UART result record
 * @endcode
 *
 * This validates algorithm flow and expected synthetic results only. The
 * threshold is illustrative; QEMU does not model physical sensors, mechanical
 * faults, or real-time performance.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <zephyr/sys/printk.h>

#include <stdbool.h>
#include <stdint.h>

#include "arm_math.h"

/** Number of time-domain samples in each analysis frame. */
#define SAMPLE_COUNT 256U

/** Synthetic sampling rate, in samples per second. */
#define SAMPLE_RATE_HZ 1024U

/** Expected fundamental component, in hertz. */
#define FUNDAMENTAL_HZ 64U

/** Fault-like second harmonic component, in hertz. */
#define HARMONIC_HZ 128U

/** Number of adjacent FFT bins searched on either side of a target bin. */
#define BIN_SEARCH_RADIUS 1U

/** Peak amplitude of the deterministic uniform noise added to each sample. */
#define NOISE_AMPLITUDE 0.05f

/** Amplitude of the second harmonic in the fault-like frame. */
#define FAULT_HARMONIC_AMPLITUDE 0.35f

/** Classification threshold expressed as a ratio multiplied by 1000. */
#define FAULT_RATIO_THRESHOLD_MILLI 200U

/** Converts a floating-point magnitude ratio to thousandths. */
#define MAGNITUDE_SCALE 1000.0f

/** First magnitude bin after the DC component, which is excluded from output. */
#define FIRST_NON_DC_BIN 1U

/** Last searched bin before Nyquist. */
#define LAST_NON_NYQUIST_BIN ((SAMPLE_COUNT / 2U) - 1U)

/** Synthetic signal configuration used by one test case. */
struct signal_case {
	/** Label printed in the machine-readable UART result. */
	const char *name;
	/** Initial state for the repeatable pseudo-random noise sequence. */
	uint32_t noise_seed;
	/** Whether the second-harmonic component is included in the signal. */
	bool includes_fault_harmonic;
};

/** Normal and fault-like frames used to exercise both detector outcomes. */
static const struct signal_case test_cases[] = {
	{ .name = "normal", .noise_seed = 0x13579BDFU, .includes_fault_harmonic = false },
	{ .name = "fault", .noise_seed = 0x2468ACE1U, .includes_fault_harmonic = true },
};

/** Time-domain input frame, overwritten for each signal case. */
static float32_t samples[SAMPLE_COUNT];

/** Hann window coefficients shared by all cases. */
static float32_t window[SAMPLE_COUNT];

/** Packed output buffer from the CMSIS-DSP real FFT. */
static float32_t spectrum[SAMPLE_COUNT];

/** Magnitudes for bins 1 through the bin before Nyquist. */
static float32_t magnitudes[(SAMPLE_COUNT / 2U) - 1U];

/**
 * @brief Generate the next deterministic noise sample.
 *
 * @param state Mutable state for the linear-congruential generator.
 * @return Noise value in the range [-NOISE_AMPLITUDE, NOISE_AMPLITUDE].
 */
static float32_t next_noise(uint32_t *state)
{
	*state = (*state * 1664525U) + 1013904223U;
	return (((float32_t)(*state >> 16) / 65535.0f) * 2.0f - 1.0f) * NOISE_AMPLITUDE;
}

/**
 * @brief Find the strongest magnitude near a target frequency bin.
 *
 * @param expected_bin Target bin derived from frequency and sample rate.
 * @param peak_magnitude Receives the magnitude of the strongest local bin.
 * @return Absolute FFT bin number of the local maximum.
 *
 * @details CMSIS-DSP's packed real-FFT output begins with the DC and Nyquist
 * values. Magnitudes are computed starting at `spectrum[2]`, so magnitude index
 * zero corresponds to FFT bin one; this function translates between those
 * indices when reading the local search window.
 */
static uint32_t find_peak_bin(uint32_t expected_bin, float32_t *peak_magnitude)
{
	uint32_t first_bin = expected_bin - BIN_SEARCH_RADIUS;
	uint32_t last_bin = expected_bin + BIN_SEARCH_RADIUS;
	uint32_t peak_offset;

	if (first_bin < FIRST_NON_DC_BIN) {
		first_bin = FIRST_NON_DC_BIN;
	}
	if (last_bin > LAST_NON_NYQUIST_BIN) {
		last_bin = LAST_NON_NYQUIST_BIN;
	}

	arm_max_f32(&magnitudes[first_bin - FIRST_NON_DC_BIN],
		    last_bin - first_bin + 1U, peak_magnitude, &peak_offset);

	return first_bin + peak_offset;
}

/**
 * @brief Generate, analyze, and classify one synthetic signal case.
 *
 * @param fft Initialized CMSIS-DSP real-FFT instance.
 * @param test_case Signal composition and deterministic noise seed.
 * @return true when the detected bins and class agree with this test case.
 *
 * @details The reported harmonic ratio is
 * `harmonic_magnitude / fundamental_magnitude`, scaled by 1000 to keep the
 * UART record integer-only. A ratio at or above the configured threshold is
 * classified as fault-like; this is a demonstration rule, not a diagnosis.
 */
static bool analyze_case(const arm_rfft_fast_instance_f32 *fft,
			             const struct signal_case *test_case)
{
	uint32_t noise_state = test_case->noise_seed;
	uint32_t fundamental_bin = FUNDAMENTAL_HZ * SAMPLE_COUNT / SAMPLE_RATE_HZ;
	uint32_t harmonic_bin = HARMONIC_HZ * SAMPLE_COUNT / SAMPLE_RATE_HZ;
	float32_t fundamental_magnitude;
	float32_t harmonic_magnitude;
	uint32_t detected_fundamental_bin;
	uint32_t detected_harmonic_bin;
	uint32_t harmonic_ratio_milli;
	bool detected_fault;
	bool passed;

	for (uint32_t sample_index = 0U; sample_index < SAMPLE_COUNT; sample_index++) {
		float32_t fundamental_phase = 2.0f * PI * FUNDAMENTAL_HZ * sample_index /
				      SAMPLE_RATE_HZ;
		float32_t sample = arm_sin_f32(fundamental_phase);

		if (test_case->includes_fault_harmonic) {
			float32_t harmonic_phase = 2.0f * PI * HARMONIC_HZ * sample_index /
					  SAMPLE_RATE_HZ;

			sample += FAULT_HARMONIC_AMPLITUDE * arm_sin_f32(harmonic_phase);
		}
		samples[sample_index] = sample + next_noise(&noise_state);
	}

	arm_mult_f32(samples, window, samples, SAMPLE_COUNT);
	arm_rfft_fast_f32(fft, samples, spectrum, 0U);
	arm_cmplx_mag_f32(&spectrum[2], magnitudes,
			  (SAMPLE_COUNT / 2U) - 1U);

	detected_fundamental_bin = find_peak_bin(fundamental_bin, &fundamental_magnitude);
	detected_harmonic_bin = find_peak_bin(harmonic_bin, &harmonic_magnitude);
	/* Integer thousandths keep the UART record simple to parse. */
	harmonic_ratio_milli = (uint32_t)(harmonic_magnitude * MAGNITUDE_SCALE /
					  fundamental_magnitude);
	detected_fault = harmonic_ratio_milli >= FAULT_RATIO_THRESHOLD_MILLI;
	passed = (detected_fundamental_bin == fundamental_bin) &&
		 (!test_case->includes_fault_harmonic || detected_harmonic_bin == harmonic_bin) &&
		 (detected_fault == test_case->includes_fault_harmonic);

	printk("FREQSPEC,RESULT,case=%s,expected=%s,detected=%s,fundamental_hz=%u,"
	       "harmonic_hz=%u,harmonic_ratio_milli=%u,pass=%u\n",
	       test_case->name, test_case->includes_fault_harmonic ? "fault" : "normal",
	       detected_fault ? "fault" : "normal",
	       detected_fundamental_bin * SAMPLE_RATE_HZ / SAMPLE_COUNT,
	       detected_harmonic_bin * SAMPLE_RATE_HZ / SAMPLE_COUNT,
	       harmonic_ratio_milli, passed);

	return passed;
}

/**
 * @brief Run every synthetic spectrum test and print a suite summary.
 *
 * @return Zero after reporting the results over UART.
 */
int main(void)
{
	arm_rfft_fast_instance_f32 fft;
	uint32_t passed_cases = 0U;

	printk("FREQSPEC,BOOT,version=1,target=qemu_cortex_a53\n");

	if (arm_rfft_fast_init_f32(&fft, SAMPLE_COUNT) != ARM_MATH_SUCCESS) {
		printk("FREQSPEC,ERROR,code=fft_init\n");
		return 0;
	}

	arm_hanning_f32(window, SAMPLE_COUNT);
	for (uint32_t case_index = 0U;
	     case_index < sizeof(test_cases) / sizeof(test_cases[0]); case_index++) {
		passed_cases += analyze_case(&fft, &test_cases[case_index]);
	}

	printk("FREQSPEC,SUITE,passed=%u,total=%u\n", passed_cases,
	       (uint32_t)(sizeof(test_cases) / sizeof(test_cases[0])));

	return 0;
}
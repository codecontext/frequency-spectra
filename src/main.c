/* SPDX-License-Identifier: Apache-2.0 */

#include <zephyr/sys/printk.h>

#include "arm_math.h"

#define SAMPLE_COUNT 256U
#define SAMPLE_RATE_HZ 1024U
#define TEST_FREQUENCY_HZ 64U
#define FIRST_NON_DC_BIN 1U
#define LAST_NON_NYQUIST_BIN ((SAMPLE_COUNT / 2U) - 1U)

static float32_t samples[SAMPLE_COUNT];
static float32_t window[SAMPLE_COUNT];
static float32_t spectrum[SAMPLE_COUNT];
static float32_t magnitudes[(SAMPLE_COUNT / 2U) - 1U];

int main(void)
{
	arm_rfft_fast_instance_f32 fft;
	float32_t peak_magnitude;
	uint32_t peak_index;
	uint32_t detected_bin;
	uint32_t detected_frequency_hz;
	uint32_t expected_bin = TEST_FREQUENCY_HZ * SAMPLE_COUNT / SAMPLE_RATE_HZ;
	uint32_t pass;

	printk("FREQSPEC,BOOT,version=1,target=qemu_cortex_a53\n");

	for (uint32_t sample_index = 0U; sample_index < SAMPLE_COUNT; sample_index++) {
		float32_t phase = 2.0f * PI * TEST_FREQUENCY_HZ * sample_index /
				  SAMPLE_RATE_HZ;

		samples[sample_index] = arm_sin_f32(phase);
	}

	arm_hanning_f32(window, SAMPLE_COUNT);
	arm_mult_f32(samples, window, samples, SAMPLE_COUNT);

	if (arm_rfft_fast_init_f32(&fft, SAMPLE_COUNT) != ARM_MATH_SUCCESS) {
		printk("FREQSPEC,RESULT,case=tone,pass=0,error=fft_init\n");
		return 0;
	}

	arm_rfft_fast_f32(&fft, samples, spectrum, 0U);
	arm_cmplx_mag_f32(&spectrum[2], magnitudes,
			  (SAMPLE_COUNT / 2U) - 1U);
	arm_max_f32(magnitudes, LAST_NON_NYQUIST_BIN, &peak_magnitude, &peak_index);

	detected_bin = peak_index + FIRST_NON_DC_BIN;
	detected_frequency_hz = detected_bin * SAMPLE_RATE_HZ / SAMPLE_COUNT;
	pass = detected_bin == expected_bin;

	printk("FREQSPEC,RESULT,case=tone,expected_hz=%u,detected_hz=%u,"
	       "peak_bin=%u,pass=%u\n",
	       TEST_FREQUENCY_HZ, detected_frequency_hz, detected_bin, pass);

	return 0;
}
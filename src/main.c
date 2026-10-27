/* SPDX-License-Identifier: Apache-2.0 */

#include <zephyr/sys/printk.h>

int main(void)
{
	printk("FREQSPEC,BOOT,version=1,target=qemu_cortex_a53\n");
	return 0;
}
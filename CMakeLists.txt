# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(frequency_spectra)

target_sources(app PRIVATE src/main.c)

option(FREQSPEC_LIVE "Continuously stream synthetic signal frames at one frame per second" OFF)
if(FREQSPEC_LIVE)
	target_compile_definitions(app PRIVATE FREQSPEC_LIVE=1)
endif()
"""Tests for parsing Frequency Spectra UART captures."""

import tempfile
import unittest
from pathlib import Path

from scripts.plot_capture import (
    FAULT_HEADER_COLOR,
    NORMAL_CLASS_COLOR,
    LiveFrameBuffer,
    header_color_for_detection,
    class_label_for_detection,
    input_frequency_label,
    output_frequency_label,
    parse_capture,
    validate_results,
)


class ParseCaptureTests(unittest.TestCase):
    """Verify valid capture records and malformed frame handling."""

    def parse_text(self, text: str) -> dict[str, dict[str, object]]:
        """Parse temporary capture text using the production parser."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            capture_path = Path(temporary_directory) / "capture.log"
            capture_path.write_text(text)
            return parse_capture(capture_path)

    def validate_text(self, text: str) -> None:
        """Validate temporary result records using the production validator."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            capture_path = Path(temporary_directory) / "capture.log"
            capture_path.write_text(text)
            validate_results(capture_path)

    def test_header_color_tracks_detection(self) -> None:
        self.assertEqual(header_color_for_detection("normal"), NORMAL_CLASS_COLOR)
        self.assertEqual(header_color_for_detection("fault"), FAULT_HEADER_COLOR)
        self.assertEqual(class_label_for_detection("normal"), "Normal")
        self.assertEqual(class_label_for_detection("fault"), "Fault")

    def test_frequency_labels_show_generated_and_detected_values(self) -> None:
        normal_result = {
            "input_fundamental_hz": "64",
            "input_harmonic_hz": "0",
            "fundamental_hz": "64",
            "harmonic_hz": "129",
        }
        fault_result = {
            "input_fundamental_hz": "64",
            "input_harmonic_hz": "128",
            "fundamental_hz": "64",
            "harmonic_hz": "128",
        }

        self.assertEqual(input_frequency_label(normal_result), "Input: 64 Hz")
        self.assertEqual(
            input_frequency_label(fault_result), "Input: 64 Hz + 128 Hz harmonic"
        )
        self.assertEqual(
            output_frequency_label(fault_result),
            "FFT peaks: 64 Hz fundamental, 128 Hz harmonic band",
        )

    def test_pairs_live_vectors_by_case_and_frame_id(self) -> None:
        frame_buffer = LiveFrameBuffer()
        waveform = "FREQSPEC,WAVE,case=normal,frame_id=12,rate_hz=8,sample_count=8,0,1,2,3,4,5,6,7"
        spectrum = "FREQSPEC,SPECTRUM,case=normal,frame_id=12,rate_hz=8,sample_count=8,10,20,30"
        result = "FREQSPEC,RESULT,case=normal,frame_id=12,expected=normal,detected=normal,pass=1"

        self.assertIsNone(frame_buffer.add_line(waveform))
        self.assertIsNone(frame_buffer.add_line(result))
        frame = frame_buffer.add_line(spectrum)

        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertEqual(frame["frame_id"], 12)
        self.assertEqual(frame["wave"], [0, 1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(frame["spectrum"], [10, 20, 30])
        self.assertEqual(frame["result"]["detected"], "normal")

    def test_live_vectors_with_different_ids_do_not_pair(self) -> None:
        frame_buffer = LiveFrameBuffer()
        waveform = "FREQSPEC,WAVE,case=normal,frame_id=1,rate_hz=8,sample_count=8,0,1,2,3,4,5,6,7"
        spectrum = "FREQSPEC,SPECTRUM,case=normal,frame_id=2,rate_hz=8,sample_count=8,10,20,30"
        result = "FREQSPEC,RESULT,case=normal,frame_id=1,expected=normal,detected=normal,pass=1"

        self.assertIsNone(frame_buffer.add_line(waveform))
        self.assertIsNone(frame_buffer.add_line(spectrum))
        self.assertIsNone(frame_buffer.add_line(result))

    def test_live_mode_requires_frame_id(self) -> None:
        frame_buffer = LiveFrameBuffer()
        waveform = "FREQSPEC,WAVE,case=normal,rate_hz=8,sample_count=8,0,1,2,3,4,5,6,7"

        with self.assertRaisesRegex(ValueError, "missing frame_id"):
            frame_buffer.add_line(waveform)

    def test_parses_two_cases_and_ignores_other_uart_records(self) -> None:
        capture = """\
*** Booting Zephyr OS ***
FREQSPEC,WAVE,case=normal,rate_hz=8,sample_count=8,0,1,2,3,4,5,6,7
FREQSPEC,SPECTRUM,case=normal,rate_hz=8,sample_count=8,10,20,30
FREQSPEC,WAVE,case=fault,rate_hz=8,sample_count=8,7,6,5,4,3,2,1,0
FREQSPEC,SPECTRUM,case=fault,rate_hz=8,sample_count=8,30,20,10
FREQSPEC,RESULT,case=fault,expected=fault,detected=fault,pass=1
FREQSPEC,RESULT,case=normal,expected=normal,detected=normal,pass=1
FREQSPEC,SUITE,passed=2,total=2
"""

        cases = self.parse_text(capture)
        self.validate_text(capture)

        self.assertEqual(cases["normal"]["wave"], [0, 1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(cases["fault"]["spectrum"], [30, 20, 10])
        self.assertEqual(cases["normal"]["sample_rate_hz"], 8)

    def test_rejects_vector_with_wrong_number_of_values(self) -> None:
        capture = "FREQSPEC,WAVE,case=normal,rate_hz=8,sample_count=8,1,2\n"

        with self.assertRaisesRegex(ValueError, "expected 8"):
            self.parse_text(capture)

    def test_rejects_case_missing_one_vector(self) -> None:
        capture = "FREQSPEC,WAVE,case=normal,rate_hz=8,sample_count=8,0,1,2,3,4,5,6,7\n"

        with self.assertRaisesRegex(ValueError, "missing waveform or spectrum"):
            self.parse_text(capture)

    def test_rejects_inconsistent_frame_metadata(self) -> None:
        capture = """\
FREQSPEC,WAVE,case=normal,rate_hz=8,sample_count=8,0,1,2,3,4,5,6,7
FREQSPEC,SPECTRUM,case=normal,rate_hz=10,sample_count=8,1,2,3
"""

        with self.assertRaisesRegex(ValueError, "inconsistent frame metadata"):
            self.parse_text(capture)

    def test_rejects_failed_case_even_when_suite_summary_passes(self) -> None:
        capture = """\
FREQSPEC,RESULT,case=fault,expected=fault,detected=normal,pass=0
FREQSPEC,SUITE,passed=0,total=1
"""

        with self.assertRaisesRegex(ValueError, "DSP suite failed"):
            self.validate_text(capture)

    def test_rejects_case_with_mismatched_detection(self) -> None:
        capture = """\
FREQSPEC,RESULT,case=fault,expected=fault,detected=normal,pass=1
FREQSPEC,SUITE,passed=1,total=1
"""

        with self.assertRaisesRegex(ValueError, "DSP case fault failed"):
            self.validate_text(capture)

    def test_rejects_missing_suite_summary(self) -> None:
        capture = "FREQSPEC,RESULT,case=normal,expected=normal,detected=normal,pass=1\n"

        with self.assertRaisesRegex(ValueError, "missing FREQSPEC SUITE"):
            self.validate_text(capture)


if __name__ == "__main__":
    unittest.main()
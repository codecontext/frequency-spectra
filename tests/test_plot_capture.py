"""Tests for parsing Frequency Spectra UART captures."""

import tempfile
import unittest
from pathlib import Path

from scripts.plot_capture import parse_capture


class ParseCaptureTests(unittest.TestCase):
    """Verify valid capture records and malformed frame handling."""

    def parse_text(self, text: str) -> dict[str, dict[str, object]]:
        """Parse temporary capture text using the production parser."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            capture_path = Path(temporary_directory) / "capture.log"
            capture_path.write_text(text)
            return parse_capture(capture_path)

    def test_parses_two_cases_and_ignores_other_uart_records(self) -> None:
        capture = """\
*** Booting Zephyr OS ***
FREQSPEC,RESULT,case=normal,pass=1
FREQSPEC,WAVE,case=normal,rate_hz=8,sample_count=8,0,1,2,3,4,5,6,7
FREQSPEC,SPECTRUM,case=normal,rate_hz=8,sample_count=8,10,20,30
FREQSPEC,WAVE,case=fault,rate_hz=8,sample_count=8,7,6,5,4,3,2,1,0
FREQSPEC,SPECTRUM,case=fault,rate_hz=8,sample_count=8,30,20,10
"""

        cases = self.parse_text(capture)

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


if __name__ == "__main__":
    unittest.main()
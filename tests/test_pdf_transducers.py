import sys
import unittest
from pathlib import Path

import pandas as pd

CHART_GENERATION_PATH = Path(__file__).resolve().parents[1] / "shared" / "chart_generation"
sys.path.insert(0, str(CHART_GENERATION_PATH))

from pdf_helpers import build_torque_and_stamp_positions, prepare_transducer_dataframe


class PdfTransducerTests(unittest.TestCase):
    def test_torque_transducer_is_not_repeated_in_general_transducers(self):
        transducer_codes = pd.DataFrame(
            [
                {"channel": "Torque", "transducer": "TQ-123"},
                {"channel": "Pressure", "transducer": "PT-456"},
                {"channel": "Position", "transducer": ""},
            ]
        )
        gauge_codes = pd.DataFrame(
            [
                {"channel": "Torque", "gauge": ""},
                {"channel": "Pressure", "gauge": "PG-789"},
                {"channel": "Position", "gauge": ""},
            ]
        )

        used_transducers, used_gauges = prepare_transducer_dataframe(
            transducer_codes,
            gauge_codes,
            ["Torque", "Pressure", "Position"],
        )

        self.assertNotIn("TQ-123", used_transducers.iloc[:, 0].tolist())
        self.assertIn("PT-456", used_transducers.iloc[:, 0].tolist())
        self.assertIn("PG-789", used_gauges.iloc[:, 0].tolist())

    def test_torque_transducer_lookup_ignores_case_and_whitespace(self):
        transducer_codes = pd.DataFrame(
            [{"channel": " torque ", "transducer": "TQ-123"}]
        )

        positions = build_torque_and_stamp_positions(
            transducer_codes,
            {},
            light_blue=None,
            black=None,
        )

        self.assertEqual(positions[1][2], "TQ-123")


if __name__ == "__main__":
    unittest.main()

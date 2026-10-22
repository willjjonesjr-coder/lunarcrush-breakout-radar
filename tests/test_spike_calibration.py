import unittest

from spike_calibration import HORIZONS, MODELS


class SpikeCalibrationTests(unittest.TestCase):
    def test_calibration_variants_and_horizons_are_available(self):
        self.assertEqual(MODELS, {"trend_only": 0.0, "production_50": 0.5, "spike_75": 0.75})
        self.assertEqual(HORIZONS, (7, 14, 30))


if __name__ == "__main__":
    unittest.main()

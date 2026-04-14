"""Unit tests for brc_tools.verify.deterministic."""

import numpy as np
import pytest

from brc_tools.verify.deterministic import bias, correlation, mae, rmse


class TestScalarMetrics:
    def test_bias_zero(self):
        fc = np.array([1.0, 2.0, 3.0])
        ob = np.array([1.0, 2.0, 3.0])
        assert bias(fc, ob) == pytest.approx(0.0)

    def test_bias_positive(self):
        fc = np.array([3.0, 4.0, 5.0])
        ob = np.array([1.0, 2.0, 3.0])
        assert bias(fc, ob) == pytest.approx(2.0)

    def test_bias_negative(self):
        fc = np.array([1.0, 2.0, 3.0])
        ob = np.array([3.0, 4.0, 5.0])
        assert bias(fc, ob) == pytest.approx(-2.0)

    def test_mae_zero(self):
        fc = np.array([1.0, 2.0, 3.0])
        assert mae(fc, fc) == pytest.approx(0.0)

    def test_mae_known(self):
        fc = np.array([1.0, 3.0, 5.0])
        ob = np.array([2.0, 2.0, 2.0])
        # |1-2| + |3-2| + |5-2| = 1 + 1 + 3 = 5/3
        assert mae(fc, ob) == pytest.approx(5.0 / 3.0)

    def test_rmse_zero(self):
        fc = np.array([1.0, 2.0, 3.0])
        assert rmse(fc, fc) == pytest.approx(0.0)

    def test_rmse_known(self):
        # Errors: [1, -1, 1, -1], MSE = 1, RMSE = 1
        fc = np.array([2.0, 1.0, 4.0, 3.0])
        ob = np.array([1.0, 2.0, 3.0, 4.0])
        assert rmse(fc, ob) == pytest.approx(1.0)

    def test_correlation_perfect(self):
        fc = np.array([1.0, 2.0, 3.0, 4.0])
        assert correlation(fc, fc) == pytest.approx(1.0)

    def test_correlation_inverse(self):
        fc = np.array([1.0, 2.0, 3.0, 4.0])
        ob = np.array([4.0, 3.0, 2.0, 1.0])
        assert correlation(fc, ob) == pytest.approx(-1.0)


class TestNanHandling:
    def test_nan_in_forecast(self):
        fc = np.array([1.0, np.nan, 3.0])
        ob = np.array([1.0, 2.0, 3.0])
        # Should drop the NaN pair and compute on [1,3] vs [1,3]
        assert rmse(fc, ob) == pytest.approx(0.0)

    def test_all_nan(self):
        fc = np.array([np.nan, np.nan])
        ob = np.array([1.0, 2.0])
        assert np.isnan(rmse(fc, ob))

    def test_empty(self):
        assert np.isnan(bias(np.array([]), np.array([])))

    def test_too_few_for_correlation(self):
        fc = np.array([1.0, 2.0])
        ob = np.array([3.0, 4.0])
        assert np.isnan(correlation(fc, ob))

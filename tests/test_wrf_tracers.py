"""Tests for brc_tools.nwp.wrf_tracers -- passive-tracer source attribution.

The failure mode these guard is specific and quiet: the attribution is a RATIO,
so dividing 1e-12 by 4e-12 gives a confident-looking 25 % share of nothing.  Most
of a domain is untagged air, so without a floor an origin figure is an argmax over
advection noise everywhere outside the plume -- and it draws a crisp, entirely
spurious pattern rather than looking broken.
"""

from __future__ import annotations

import numpy as np
import pytest
from _wrf_synthetic import make_synthetic_wrf

from brc_tools.nwp import wrf_tracers as wt


@pytest.fixture
def ds():
    return make_synthetic_wrf(tracers=3)


class TestDiscovery:
    def test_it_finds_the_tracers_a_run_wrote(self, ds):
        assert wt.tracer_variables(ds) == ["tr17_1", "tr17_2", "tr17_3"]

    def test_a_run_without_tracers_returns_nothing(self):
        assert wt.tracer_variables(make_synthetic_wrf()) == []

    def test_stacking_a_run_without_tracers_says_why(self):
        with pytest.raises(KeyError, match="tracer_opt"):
            wt.tracer_stack(make_synthetic_wrf())

    def test_ordering_is_numeric_not_lexical(self):
        """`tr17_10` sorting between `tr17_1` and `tr17_2` would permute the
        stack against the source labels a caller pairs with it -- which mislabels
        every panel and cannot be seen in the figure."""
        ds = make_synthetic_wrf(tracers=2)
        ds = ds.assign({"tr17_10": ds["tr17_1"]})
        assert wt.tracer_variables(ds) == ["tr17_1", "tr17_2", "tr17_10"]

    def test_negative_concentrations_are_clipped_at_the_read(self, ds):
        ds["tr17_1"][:] = -1.0
        assert (wt.tracer_stack(ds) >= 0).all()


class TestShares:
    def test_shares_sum_to_one_where_there_is_tagged_air(self, ds):
        shares, total = wt.tracer_shares(wt.tracer_stack(ds))
        tagged = np.isfinite(shares).all(axis=0)
        assert tagged.any()
        assert shares[:, tagged].sum(axis=0) == pytest.approx(1.0)

    def test_untagged_air_is_nan_not_a_fabricated_attribution(self, ds):
        shares, total = wt.tracer_shares(wt.tracer_stack(ds))
        assert np.isnan(shares[:, total < wt.DEFAULT_TOTAL_FLOOR]).all()

    def test_a_zero_floor_would_attribute_pure_noise(self, ds):
        """The discriminating case for why the floor exists at all."""
        stack = wt.tracer_stack(ds) * 0.0 + 1e-15
        with_floor, _ = wt.tracer_shares(stack)
        without, _ = wt.tracer_shares(stack, floor=0.0)
        assert np.isnan(with_floor).all()
        assert np.isfinite(without).all()


class TestDominantSource:
    def test_it_picks_the_largest_and_reports_its_share(self, ds):
        """The fixture gives tracer 1 half the mass, 2 a quarter, 3 an eighth,
        so the dominant share is 0.5/0.875 = 4/7."""
        index, purity, _total = wt.dominant_source(wt.tracer_stack(ds))
        tagged = index >= 0
        assert (index[tagged] == 0).all()
        assert purity[tagged] == pytest.approx(4.0 / 7.0)

    def test_untagged_cells_are_minus_one_and_nan(self, ds):
        index, purity, total = wt.dominant_source(wt.tracer_stack(ds))
        untagged = total < wt.DEFAULT_TOTAL_FLOOR
        assert untagged.any()
        assert (index[untagged] == -1).all()
        assert np.isnan(purity[untagged]).all()

    def test_it_does_not_warn_on_an_all_untagged_field(self, ds):
        """An untagged region is usually most of a domain, so a nanmax-style
        warning per column would bury a sweep's log."""
        stack = wt.tracer_stack(ds) * 0.0
        with np.errstate(all="raise"):
            index, purity, _ = wt.dominant_source(stack)
        assert (index == -1).all()


class TestProfiles:
    def test_column_spectrum_clips_to_the_requested_top(self, ds):
        stack = wt.tracer_stack(ds)[:, :, 0, 0]
        height = np.array([50.0, 150.0, 250.0, 350.0])
        shares, z = wt.column_spectrum(stack, height, top_m=200.0)
        assert z.tolist() == [50.0, 150.0]
        assert shares.shape == (3, 2)

    def test_layer_shares_are_concentration_weighted(self):
        """A level holding almost no tagged air must not get an equal vote with
        the level holding the plume -- averaging the SHARES would give it one."""
        # Level 0 holds a trace of tracer 2 and nothing else; level 1 holds the
        # plume, split evenly.  Concentration-weighted, tracer 1's share is
        # 1.0 / 2.001 = 0.4998; a MEAN OF PER-LEVEL SHARES would be
        # (0 + 0.5) / 2 = 0.25, letting the near-empty level halve the answer.
        stack = np.array([[0.0, 1.0], [1e-3, 1.0]])   # (2 tracers, 2 levels)
        height = np.array([50.0, 150.0])
        layer = wt.layer_shares(stack, height, [0.0, 200.0])
        assert layer[0, 0] == pytest.approx(1.0 / 2.001, rel=1e-6)
        assert layer[0, 0] != pytest.approx(0.25, abs=0.2)

    def test_a_layer_with_no_tagged_air_is_nan(self):
        stack = np.zeros((2, 2))
        layer = wt.layer_shares(stack, np.array([50.0, 150.0]), [0.0, 200.0])
        assert np.isnan(layer).all()

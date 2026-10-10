"""Unit tests for the pure scoring core — no database, no network."""

import pytest

from app.models import FloodSeverity, RiskBand
from app.services.risk import (
    ExposureHit,
    basin_depths,
    GaugeInfluence,
    approach_margin_score,
    band_for,
    flood_exposure_score,
    gauge_proximity_score,
    low_lying_score,
    score,
)


def hit(length_m: float, severity: FloodSeverity = FloodSeverity.SEVERE) -> ExposureHit:
    return ExposureHit(zone_id="z1", event="Flash Flood Warning", severity=severity, length_m=length_m)


# --------------------------------------------------------------------------- #
# Flood exposure
# --------------------------------------------------------------------------- #


def test_no_exposure_scores_zero():
    assert flood_exposure_score([]) == 0.0


def test_any_exposure_clears_the_floor():
    """Even 10 m of floodwater must score meaningfully — the road is impassable."""
    assert flood_exposure_score([hit(10)]) >= 20.0


def test_exposure_grows_with_length():
    assert flood_exposure_score([hit(200)]) < flood_exposure_score([hit(1500)])


def test_exposure_saturates_at_fifty():
    assert flood_exposure_score([hit(50_000)]) == pytest.approx(50.0)


def test_severity_is_weighted():
    severe = flood_exposure_score([hit(1500, FloodSeverity.SEVERE)])
    minor = flood_exposure_score([hit(1500, FloodSeverity.MINOR)])
    assert severe > minor


# --------------------------------------------------------------------------- #
# Terrain
# --------------------------------------------------------------------------- #


def test_flat_route_has_no_terrain_risk():
    assert low_lying_score([20.0] * 40) == 0.0


def test_gentle_slope_is_not_penalised():
    """A steady climb is not a flood risk, however much elevation it covers."""
    assert low_lying_score([10.0 + i * 0.5 for i in range(40)]) == 0.0


def test_deep_dip_is_penalised():
    elevations = [25.0] * 15 + [8.0] * 10 + [25.0] * 15
    assert low_lying_score(elevations) > 10.0


def test_deeper_dip_scores_worse():
    shallow = [25.0] * 15 + [20.0] * 10 + [25.0] * 15
    deep = [25.0] * 15 + [5.0] * 10 + [25.0] * 15
    assert low_lying_score(deep) > low_lying_score(shallow)


def test_terrain_score_is_capped():
    elevations = [50.0] * 5 + [0.0] * 60
    assert low_lying_score(elevations) <= 25.0


def test_missing_elevation_is_not_an_error():
    assert low_lying_score([]) == 0.0
    assert low_lying_score([12.0]) == 0.0


# --------------------------------------------------------------------------- #
# Gauges
# --------------------------------------------------------------------------- #


def test_normal_gauges_contribute_nothing():
    g = GaugeInfluence("1", "Normal creek", 500.0, at_flood_stage=False, at_action_stage=False)
    assert gauge_proximity_score([g]) == 0.0


def test_flooded_gauge_nearby_scores_high():
    g = GaugeInfluence("1", "Flooded bayou", 200.0, at_flood_stage=True, at_action_stage=True)
    assert gauge_proximity_score([g]) > 15.0


def test_distance_attenuates_gauge_influence():
    near = GaugeInfluence("1", "n", 500.0, True, True)
    far = GaugeInfluence("2", "f", 7_500.0, True, True)
    assert gauge_proximity_score([near]) > gauge_proximity_score([far])


def test_action_stage_counts_less_than_flood_stage():
    flood = GaugeInfluence("1", "a", 1000.0, at_flood_stage=True, at_action_stage=True)
    action = GaugeInfluence("2", "b", 1000.0, at_flood_stage=False, at_action_stage=True)
    assert gauge_proximity_score([flood]) > gauge_proximity_score([action])


def test_multiple_flooded_gauges_score_worse_than_one():
    one = [GaugeInfluence("1", "a", 1000.0, True, True)]
    three = one + [
        GaugeInfluence("2", "b", 2000.0, True, True),
        GaugeInfluence("3", "c", 3000.0, True, True),
    ]
    assert gauge_proximity_score(three) > gauge_proximity_score(one)


def test_gauge_score_is_capped():
    many = [GaugeInfluence(str(i), "g", 100.0, True, True) for i in range(20)]
    assert gauge_proximity_score(many) <= 20.0


# --------------------------------------------------------------------------- #
# Approach margin
# --------------------------------------------------------------------------- #


def test_no_zones_means_no_margin_penalty():
    assert approach_margin_score(None) == 0.0


def test_far_from_flooding_is_unpenalised():
    assert approach_margin_score(5_000.0) == 0.0


def test_skirting_the_edge_is_penalised():
    assert approach_margin_score(50.0) > approach_margin_score(900.0)
    assert approach_margin_score(50.0) <= 5.0


# --------------------------------------------------------------------------- #
# Bands and totals
# --------------------------------------------------------------------------- #


def test_exposure_always_forces_dangerous():
    """The headline guarantee: touching floodwater is never labelled safe."""
    assert band_for(1.0, has_exposure=True) is RiskBand.DANGEROUS


def test_bands_follow_thresholds():
    assert band_for(5.0, False) is RiskBand.SAFE
    assert band_for(30.0, False) is RiskBand.CAUTION
    assert band_for(70.0, False) is RiskBand.DANGEROUS


def test_clear_route_scores_safe():
    breakdown, band = score([], [20.0 + i * 0.3 for i in range(40)], [], nearest_zone_m=9_000.0)
    assert band is RiskBand.SAFE
    assert breakdown.total < 20.0


def test_flooded_route_scores_dangerous():
    elevations = [25.0] * 15 + [8.0] * 10 + [25.0] * 15
    gauges = [GaugeInfluence("1", "bayou", 400.0, True, True)]
    breakdown, band = score([hit(3_000)], elevations, gauges, nearest_zone_m=0.0)
    assert band is RiskBand.DANGEROUS
    assert breakdown.total > 70.0
    assert breakdown.flood_exposure == pytest.approx(50.0)


def test_total_never_exceeds_one_hundred():
    gauges = [GaugeInfluence(str(i), "g", 100.0, True, True) for i in range(10)]
    breakdown, _ = score([hit(99_000)], [60.0] * 5 + [0.0] * 60, gauges, 0.0)
    assert breakdown.total <= 100.0


def test_breakdown_sums_to_total():
    elevations = [25.0] * 15 + [10.0] * 10 + [25.0] * 15
    gauges = [GaugeInfluence("1", "g", 1_500.0, True, True)]
    b, _ = score([hit(800)], elevations, gauges, 300.0)
    parts = b.flood_exposure + b.low_lying + b.gauge_proximity + b.approach_margin
    assert parts == pytest.approx(b.total, abs=0.05)


def test_safest_route_ranks_below_flooded_route():
    """The core promise: a clear route must always score better than a flooded one."""
    clear, _ = score([], [22.0 + i * 0.2 for i in range(40)], [], 6_000.0)
    flooded, _ = score([hit(2_500)], [25.0] * 20 + [9.0] * 20, [], 0.0)
    assert clear.total < flooded.total


# --------------------------------------------------------------------------- #
# Basin detection (the terrain model underneath low_lying_score)
# --------------------------------------------------------------------------- #


def test_basin_needs_higher_ground_on_both_sides():
    """A descent to a plateau is not a basin — nothing dams the water in."""
    assert max(basin_depths([30.0] * 5 + [5.0] * 20)) == 0.0


def test_enclosed_dip_is_a_basin():
    depths = basin_depths([30.0] * 5 + [5.0] * 10 + [30.0] * 5)
    assert max(depths) == pytest.approx(25.0)


def test_basin_depth_uses_the_lower_of_the_two_rims():
    """Water can only rise to the lower rim before it spills over."""
    depths = basin_depths([40.0] * 3 + [10.0] * 4 + [22.0] * 3)
    assert max(depths) == pytest.approx(12.0)


def test_monotonic_routes_have_no_basins():
    assert max(basin_depths([float(i) for i in range(30)])) == 0.0
    assert max(basin_depths([float(30 - i) for i in range(30)])) == 0.0

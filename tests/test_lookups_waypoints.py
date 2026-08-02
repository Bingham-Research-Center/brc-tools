"""Integrity guards for the waypoint register in lookups.toml.

A typo in a ``[waypoint_groups]`` member does not fail at import; it fails later
inside an obs fetch or a figure job, usually on a compute node. These checks move
that to the test suite.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOOKUPS = ROOT / "brc_tools" / "nwp" / "lookups.toml"


@pytest.fixture(scope="module")
def lookups() -> dict:
    return tomllib.loads(LOOKUPS.read_text(encoding="utf-8"))


def test_every_group_member_is_a_known_waypoint(lookups):
    waypoints = lookups["waypoints"]
    dangling = {
        group: [name for name in members if name not in waypoints]
        for group, members in lookups["waypoint_groups"].items()
    }
    dangling = {g: m for g, m in dangling.items() if m}
    assert not dangling, f"waypoint_groups referencing undefined waypoints: {dangling}"


def test_waypoints_carry_coordinates_in_range(lookups):
    for name, wp in lookups["waypoints"].items():
        assert "lat" in wp and "lon" in wp, f"{name} is missing coordinates"
        assert 36.0 <= wp["lat"] <= 43.0, f"{name} latitude {wp['lat']} is outside Utah/Wyoming"
        assert -115.0 <= wp["lon"] <= -104.0, f"{name} longitude {wp['lon']} is out of region"


def test_groups_have_no_duplicate_members(lookups):
    dupes = {
        group: sorted({n for n in members if members.count(n) > 1})
        for group, members in lookups["waypoint_groups"].items()
    }
    dupes = {g: d for g, d in dupes.items() if d}
    assert not dupes, f"waypoint_groups with repeated members: {dupes}"


def test_ashley_outflow_group_covers_the_chk_outflow_stations(lookups):
    # CHK-OUTFLOW names exactly these six; the check cannot be reported against a
    # group that has quietly lost one.
    required = {"UTELP", "PC353", "UTASH", "UCC33", "KVEL", "PC266"}
    waypoints = lookups["waypoints"]
    stids = {
        waypoints[name].get("reference_stid")
        for name in lookups["waypoint_groups"]["ashley_outflow"]
    }
    assert required <= stids, f"ashley_outflow is missing {sorted(required - stids)}"


def test_ashley_outflow_is_ordered_west_to_east(lookups):
    # The outflow propagated W->E at ~22 m/s, so a timing panel built straight
    # from this group reads left to right only if the order holds.
    waypoints = lookups["waypoints"]
    lons = [waypoints[n]["lon"] for n in lookups["waypoint_groups"]["ashley_outflow"]]
    assert lons == sorted(lons), f"ashley_outflow is not west-to-east: {lons}"


def test_green_river_corridor_covers_the_chk_verify_stations(lookups):
    # CHK-VERIFY is scored against the corridor sites gate A0 confirmed reported
    # through 21-22 Nov 2025. A group that quietly loses one takes a verification
    # point with it, and nothing downstream would say so.
    required = {"UCC25", "CCRU1", "KPRU1", "SPMU1", "A3822", "JENU1"}
    waypoints = lookups["waypoints"]
    stids = {
        waypoints[name].get("reference_stid")
        for name in lookups["waypoint_groups"]["green_river_corridor"]
    }
    assert required <= stids, \
        f"green_river_corridor is missing {sorted(required - stids)}"


@pytest.mark.parametrize("group", ["green_river_corridor", "green_river_sources"])
def test_green_river_groups_are_pullable_not_just_labels(lookups, group):
    """Every member must carry a ``reference_stid``, and this already bit once.

    ``ObsSource._resolve_stids`` indexes ``["reference_stid"]`` with no default, so
    a single label-only member raises ``KeyError`` for the whole group -- not for
    that member. The first draft of both groups did exactly that, which is why
    ``flaming_gorge_dam`` and ``marsh_peak`` are excluded: they are orientation
    labels, and their nearest gauges returned no wind or temperature for the case
    window. Use them to annotate a section, never to pull observations.
    """
    waypoints = lookups["waypoints"]
    label_only = [n for n in lookups["waypoint_groups"][group]
                  if not waypoints[n].get("reference_stid")]
    assert not label_only, f"{group} carries label-only waypoints: {label_only}"


def test_reference_stids_are_unique_or_deliberate(lookups):
    """A stid pointing at two places means one of them pairs obs with the wrong site.

    ``A3822`` is a known offender, recorded in lookups.toml: ``dinosaur`` sits
    35 km from the station it names while carrying that station's elevation, and
    ``dinosaur_nm`` is the correct location. It is allow-listed here rather than
    silently repaired because four waypoint_groups reference ``dinosaur``.
    """
    known_conflicts = {"A3822"}
    seen: dict[str, list[str]] = {}
    for name, wp in lookups["waypoints"].items():
        stid = wp.get("reference_stid")
        if stid:
            seen.setdefault(stid, []).append(name)
    conflicts = {s: n for s, n in seen.items() if len(n) > 1 and s not in known_conflicts}
    assert not conflicts, f"reference_stid used by more than one waypoint: {conflicts}"

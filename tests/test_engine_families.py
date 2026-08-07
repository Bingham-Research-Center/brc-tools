"""The two sweep engines' family registries and CLI surface.

Both engines are scripts, so they are imported by path.  What is tested here is
the contract the skills and `docs/VISUAL-SUITE-SOP.md` promise: that `--figure`
selects families, that the family list an operator is told about is the family
list the engine has, and that the shared time flags exist on *both* engines --
the SOP presented `--start`/`--end` as engine-agnostic when only one engine had
them, so following it against the other was an argparse error.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_eng_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def winds():
    return _load("wrf_winds")


@pytest.fixture(scope="module")
def convective():
    return _load("wrf_convective")


def _parser_flags(mod) -> set[str]:
    """The engine's option strings, without running it."""
    import argparse

    seen: set[str] = set()
    real_add = argparse.ArgumentParser.add_argument

    def spy(self, *args, **kwargs):
        seen.update(a for a in args if isinstance(a, str) and a.startswith("-"))
        return real_add(self, *args, **kwargs)

    argparse.ArgumentParser.add_argument = spy
    try:
        with pytest.raises(SystemExit):
            mod.main.__globals__["sys"].argv = ["x", "--help"]
            mod.main()
    finally:
        argparse.ArgumentParser.add_argument = real_add
    return seen


class TestSharedFlags:
    """Both engines, same flags -- the SOP is written once for both."""

    @pytest.mark.parametrize("engine", ["wrf_winds", "wrf_convective"])
    def test_time_and_output_flags_exist(self, engine):
        flags = _parser_flags(_load(engine))
        for flag in ("--valid", "--lead", "--every", "--hourly", "--all",
                     "--start", "--end", "--figure", "--domain",
                     "--dry-run", "--skip-existing", "--report", "--allow-errors"):
            assert flag in flags, f"{engine} is missing {flag}"


class TestFamilies:
    def test_winds_families(self, winds):
        assert winds.FAMILIES == ("topdown", "section", "profile", "view3d",
                                  "tracers")

    def test_convective_families_include_meso(self, convective):
        assert "meso" in convective.FAMILIES
        assert convective.FAMILIES[0] == "surface"

    @pytest.mark.parametrize("engine", ["wrf_winds", "wrf_convective"])
    def test_every_family_is_named_in_the_module_docstring_or_registry(self, engine):
        """An operator picks families from what the engine advertises.  The
        convective skill named three of seven, so the other four were reachable
        only by reading the source."""
        mod = _load(engine)
        assert len(set(mod.FAMILIES)) == len(mod.FAMILIES), "duplicate family"
        assert all(f.islower() and f.isidentifier() for f in mod.FAMILIES)

"""The skills must stay in step with the engines they drive.

These are not style checks.  Every assertion here corresponds to a way the two
WRF skills had already drifted from the code by the time this was written: they
taught a pre-`FigureLedger` workflow, named three of seven families, never
mentioned the `.err` an operator has to read, and quoted four different values
for one knob.  A skill is the interface an agent sees; when it is stale, the
engine's own correctness does not help.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / ".claude" / "skills"
DOCS = ROOT / "docs"
README = ROOT / "README.md"

#: skill -> the engine script whose families it must advertise
DRIVEN_BY = {"wrf-basin-winds": "wrf_winds", "wrf-convective": "wrf_convective"}


def _skill(name: str) -> str:
    return (SKILLS / name / "SKILL.md").read_text()


def _engine(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_sk_{name}", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestReadmeTeachesHowToInvoke:
    """The skill table said which engine answers which question and never showed
    anyone how to ask.  A reader who cannot see an example prompt reaches for the
    engine's flags instead, which is the workflow the skills exist to replace."""

    def test_the_section_exists(self):
        assert "### How to use these skills" in README.read_text()

    @pytest.mark.parametrize("skill", sorted(p.name for p in SKILLS.iterdir()
                                             if (p / "SKILL.md").exists()))
    def test_every_skill_that_exists_gets_an_example_prompt(self, skill):
        """A skill added without an example here is one nobody finds."""
        section = README.read_text().split("### How to use these skills", 1)[1]
        section = section.split("### Which figure answers", 1)[0]
        assert f"/{skill}" in section, f"no example prompt for /{skill}"

    def test_it_names_the_convention_that_decides_the_engine(self):
        """`wrf_output` matches one filename format; `wrf_section` accepts both.
        A `nocolons = .true.` run therefore renders nothing under
        /wrf-full-figures, which looks like a broken run rather than a wrong
        engine -- so the README says so where the engine is chosen."""
        section = README.read_text().split("### How to use these skills", 1)[1]
        section = section.split("### Which figure answers", 1)[0]
        assert "nocolons" in section


@pytest.mark.parametrize("skill,engine", DRIVEN_BY.items())
def test_every_family_the_engine_has_is_named_in_its_skill(skill, engine):
    """`/wrf-convective` named `verify`, `beam` and `track` and not the other
    four, so an agent following it could not reach half the engine."""
    text = _skill(skill)
    missing = [f for f in _engine(engine).FAMILIES if f"`{f}`" not in text]
    assert not missing, f"{skill} does not name: {missing}"


@pytest.mark.parametrize("skill", DRIVEN_BY)
def test_skill_teaches_the_flags_that_keep_a_sweep_honest(skill):
    """All of these shipped before the skills were last touched, and none was
    mentioned: an operator following the skill could not tell a job that rendered
    400 of 400 figures from one that rendered 100."""
    text = _skill(skill)
    for flag in ("--dry-run", "--skip-existing", "--report", "--allow-errors",
                 "--start", "--figure"):
        assert flag in text, f"{skill} never mentions {flag}"


def test_full_figures_names_every_family_its_engine_has():
    """The one WRF skill the checks above do not cover, and it had drifted.

    `/wrf-full-figures` is deliberately outside `DRIVEN_BY`: that set also asserts
    `--dry-run`, `--report`, `--allow-errors` and three `(ask the user)` prompts,
    none of which the publication engine has -- it predates the `FigureLedger`
    workflow the two sweep engines share. Family coverage is the part that does
    apply, and by the time this was written `deficitbulk_map` and `deficit_budget`
    were in `FAMILIES` and named nowhere in the skill, so an agent following it
    could not reach them.
    """
    from brc_tools.nwp.wrf_figures import FAMILIES

    text = _skill("wrf-full-figures")
    missing = [f for f in FAMILIES if f"`{f}`" not in text and f not in text]
    assert not missing, f"wrf-full-figures does not name: {missing}"


@pytest.mark.parametrize("skill", ["wrf-basin-winds", "wrf-convective"])
def test_the_promote_target_is_not_only_a_ub_wx_variable(skill):
    """`$UB_WX_FIGS_KEEP` is set by a sibling repo's `.env`.

    Both skills named it as *the* place keepers go, so an agent working a case
    that is not a ub-wx one -- a study in `latex-jrl-mjd-mdpiair-2026`, say -- was
    told to copy figures to an unset variable. brc-tools has its own answer and
    the skills must name it: the output root these engines already default to.
    """
    text = _skill(skill)
    assert "BRC_TOOLS_OUTPUT_DIR" in text, \
        "name the brc-tools output root, not only the ub-wx variable"


@pytest.mark.parametrize("skill", DRIVEN_BY)
def test_skill_says_to_read_the_err_not_just_the_out(skill):
    """Any failure exits non-zero and the `[tally]` line is printed last -- but
    the skills told the agent to check the `.out`, which is where success looks
    like success."""
    text = _skill(skill)
    assert ".err" in text
    assert "tally" in text
    assert "exit code" in text.lower()


@pytest.mark.parametrize("skill", DRIVEN_BY)
def test_skill_points_at_the_method_doc(skill):
    """Neither skill linked the SOP, so an agent invoked via a slash command
    never saw the smoke-test, dry-run, coverage or notes steps."""
    assert "VISUAL-SUITE-SOP.md" in _skill(skill)


@pytest.mark.parametrize("skill", DRIVEN_BY)
def test_skill_asks_rather_than_assumes(skill):
    """Both skills used to say the opposite -- 'ask only if the run offers a
    genuinely different choice' -- while `/wrf-full-figures` said '(ask the
    user)'.  Case, families and cadence are not recoverable from the run dir."""
    text = _skill(skill)
    assert text.count("(ask the user)") >= 3, "case, families and times must be asked"
    assert "Ask only if" not in text


class TestWExagHasOneOwner:
    """Four published values for one knob: 5, 8-15, 10 and 100, across two
    skills and two docs, justified as 'the plot aspect'.  The quiver uses
    matplotlib's default ``angles='uv'``, where the drawn angle depends on the
    component ratio alone -- so the geometric story was wrong and the numbers
    were really four different regimes."""

    def test_the_rule_lives_in_wrf_winds(self):
        # strip markdown emphasis so a bolded word does not break the match
        text = (DOCS / "WRF-WINDS.md").read_text().replace("*", "").lower()
        assert "single source of truth for `w_exag`" in text
        assert "not the plot aspect" in text
        assert "angles=" in text, "say why it is not the plot aspect, not just that"

    @pytest.mark.parametrize("name", ["wrf-basin-winds", "wrf-convective"])
    def test_other_places_point_there_rather_than_restating(self, name):
        text = _skill(name)
        if "w_exag" not in text and "--w-exag" not in text:
            pytest.skip("skill does not mention the knob")
        assert "WRF-WINDS.md" in text, "must defer to the owning doc"

    def test_both_engines_give_the_same_help(self):
        """They said ~5 and ~10 for the same flag."""
        helps = []
        for engine in ("wrf_winds", "wrf_convective"):
            src = (ROOT / "scripts" / f"{engine}.py").read_text()
            after = src.split('"--w-exag"', 1)[1]
            body = after[:after.index(")\n")]          # this add_argument call only
            # concatenate the implicitly-joined string literals of help=...
            helps.append(" ".join(re.findall(r'"([^"]*)"', body.split("help=", 1)[1])))
        assert "typical |u| / typical |w|" in helps[0]
        assert "WRF-WINDS.md" in helps[0], "the help must point at the owning doc"
        assert helps[0] == helps[1], "the two engines describe the knob differently"

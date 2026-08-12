"""Tests for D-FT-21 research_md validator."""

from __future__ import annotations

import pytest

from app.ft_strategy.research_md_validator import (
    REQUIRED_SECTIONS,
    SUGGESTED_TEMPLATE,
    ResearchMdValidation,
    _extract_titles,
    _normalize,
    validate_research_md,
)
from app.loop.tuning_promotion_v3 import RESEARCH_MD_MIN_LENGTH


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def _full_brief() -> str:
    """A research brief that meets all required sections + 200-char minimum."""
    body = []
    body.append(SUGGESTED_TEMPLATE)
    body.append("\n\n## Elaboration\nThis brief is intentionally long to clear the")
    body.append(" 200 character minimum and demonstrate every required section is")
    body.append(" present. The body discusses BTC/USDT 5m futures, drawdown budget of")
    body.append(" 12%, decision size of ~$1000 per trade, and a clear open Q on")
    body.append(" whether 4h regime context will help. Failure modes include oracle-")
    body.append(" gaming via ROI clipping (Auto-Quant v0.1.0 lesson).")
    return "".join(body)


class TestHappyPath:
    def test_full_brief_passes(self):
        result = validate_research_md(_full_brief())
        assert result.ok
        assert result.missing_sections == ()
        assert len(result.present_sections) == len(REQUIRED_SECTIONS)
        assert result.errors == ()

    def test_length_just_below_minimum_fails(self):
        # cut down to < 200
        brief = "## Decision\nx"  # ~15 chars
        result = validate_research_md(brief)
        assert not result.ok
        assert any(">=" in e for e in result.errors)

    def test_length_at_minimum_passes(self):
        # Build a brief that has all 7 sections and is >= 200 chars
        # Use the exact template + padding
        padding = " " + ("x" * 250)
        brief = SUGGESTED_TEMPLATE + padding
        result = validate_research_md(brief)
        assert result.ok, result.errors
        assert result.length == len(brief)


# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------


class TestSectionDetection:
    def test_detects_all_7_required_sections(self):
        result = validate_research_md(_full_brief())
        assert set(result.present_sections) == set(REQUIRED_SECTIONS)

    def test_missing_section_causes_failure(self):
        # Drop "Open Qs"
        body = _full_brief().replace("## Open Qs\n", "")
        result = validate_research_md(body)
        assert not result.ok
        assert "open qs" in result.missing_sections
        assert any("open qs" in e for e in result.errors)

    def test_unknown_extra_sections_ignored(self):
        # Extra sections don't break the validator
        result = validate_research_md(_full_brief() + "\n\n## Notes\nMore text...")
        assert result.ok

    def test_section_case_insensitive(self):
        # Lowercase headings should still match
        brief = _full_brief().replace("## Decision\n", "## decision\n")
        result = validate_research_md(brief)
        assert result.ok

    def test_section_substring_match(self):
        # "Decision criteria" matches the "decision" required section
        brief = _full_brief().replace(
            "## Decision\n(What business decision does this strategy support?)",
            "## Decision criteria\nHow to score this strategy",
        )
        result = validate_research_md(brief)
        assert "decision" in result.present_sections

    def test_third_level_headings_detected(self):
        brief = _full_brief().replace("## Decision\n", "### Decision\n")
        result = validate_research_md(brief)
        assert "decision" in result.present_sections

    def test_plain_text_sections_not_detected(self):
        # Without `## ` prefix, a section titled "Decision" in body text
        # should not be picked up (would be too lenient).
        brief = (
            "Decision: x. " * 50 +
            "Question: y. " * 30 +
            "Motivation: z. " * 20 +
            "Universe: BTC/USDT. " * 10 +
            "Constraints: leverage=1. " * 10 +
            "Failure modes: dd. " * 10 +
            "Open Qs: 4h context helpful? " * 5
        )
        result = validate_research_md(brief)
        # Length is fine but sections are body text → not detected
        assert all(sec not in result.present_sections for sec in REQUIRED_SECTIONS)


# ---------------------------------------------------------------------------
# Defensive type-check
# ---------------------------------------------------------------------------


class TestTypeCheck:
    def test_none_input_returns_failed_result(self):
        result = validate_research_md(None)
        assert not result.ok
        assert any("must be str" in e for e in result.errors)

    def test_dict_input_returns_failed_result(self):
        result = validate_research_md({"not": "a string"})
        assert not result.ok
        assert any("must be str" in e for e in result.errors)

    def test_int_input_returns_failed_result(self):
        result = validate_research_md(42)  # type: ignore[arg-type]
        assert not result.ok
        assert any("must be str" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Custom min_length override
# ---------------------------------------------------------------------------


class TestCustomMinLength:
    def test_custom_min_length_lower_passes_short_brief(self):
        brief = "## Decision\nshort"
        # Default min (200) would fail; custom min (5) passes
        result = validate_research_md(brief, min_length=5)
        assert result.ok is False  # still missing 6 sections
        # But length check passes:
        assert not any(">=" in e for e in result.errors)
        # Length-specific error doesn't appear:
        assert all("characters" not in e for e in result.errors)

    def test_custom_min_length_higher_fails(self):
        # Brief with all sections but length below custom min
        brief = ("\n".join([
            "## Decision",
            "d",
            "## Question",
            "q",
            "## Motivation",
            "m",
            "## Universe",
            "u",
            "## Constraints",
            "c",
            "## Failure modes",
            "f",
            "## Open Qs",
            "o",
        ]))  # ~50 chars, well below 500
        result = validate_research_md(brief, min_length=500)
        assert not result.ok
        assert any(">= 500" in e for e in result.errors)

    def test_zero_min_length(self):
        result = validate_research_md("", min_length=0)
        # Length passes, but missing 7 sections -> fail
        assert not result.ok
        assert result.length == 0


# ---------------------------------------------------------------------------
# Suggestion template
# ---------------------------------------------------------------------------


class TestSuggestionTemplate:
    def test_template_provided_on_failure(self):
        result = validate_research_md("too short", min_length=100)
        assert not result.ok
        assert result.suggested_template == SUGGESTED_TEMPLATE
        assert "## Decision" in result.suggested_template

    def test_template_empty_on_success(self):
        result = validate_research_md(_full_brief())
        assert result.ok
        assert result.suggested_template == ""


# ---------------------------------------------------------------------------
# to_dict serialization (for JSON API responses / durable-facts logging)
# ---------------------------------------------------------------------------


class TestToDict:
    def test_failure_shape(self):
        result = validate_research_md("")
        d = result.to_dict()
        assert d["ok"] is False
        assert d["length"] == 0
        assert d["min_length"] == RESEARCH_MD_MIN_LENGTH
        assert set(d["missing_sections"]) == set(REQUIRED_SECTIONS)
        assert len(d["errors"]) > 0
        assert d["suggested_template"]

    def test_success_shape(self):
        result = validate_research_md(_full_brief())
        d = result.to_dict()
        assert d["ok"] is True
        assert d["missing_sections"] == []
        assert d["present_sections"]  # non-empty
        assert d["suggested_template"] == ""


# ---------------------------------------------------------------------------
# Immutable result
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_frozen_dataclass(self):
        result = validate_research_md(_full_brief())
        with pytest.raises(Exception):
            result.ok = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Helper internals
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_normalize_lowercase_and_strip(self):
        assert _normalize("  Decision Criteria  ") == "decision criteria"
        assert _normalize("Open Qs?") == "open qs"
        assert _normalize("Failure Modes!!") == "failure modes"

    def test_extract_titles(self):
        md = "# Top\n## Decision\n### Notes\nBody"
        assert _extract_titles(md) == ["Top", "Decision", "Notes"]

    def test_extract_titles_no_headings(self):
        assert _extract_titles("just body text\nmore body") == []

    def test_required_sections_count(self):
        # Sanity check on the contract: 7 sections per D-FT-21
        assert len(REQUIRED_SECTIONS) == 7

    def test_template_contains_all_required_sections(self):
        # The proposed template must be itself a valid input
        # (every required section is present).
        result = validate_research_md(SUGGESTED_TEMPLATE + ("x" * 200))
        assert result.ok, result.errors

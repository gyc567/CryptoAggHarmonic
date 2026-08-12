"""research_md validator — clarify-first gate (D-FT-21).

ADR-0012 D6: ``POST /api/ft-strategies`` body must contain ``research_md`` ≥
200 characters with all 7 required sections. Empty / too-short / missing
sections ⇒ 422 + template link.

Sourced from Auto-Quant V2 §Operator Guide "Clarify before quantifying" and
the plan §2.3 + §4.7. Lives next to other ft_strategy code; pure function
sibling to ``app.loop.tuning_promotion_v3``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.loop.tuning_promotion_v3 import RESEARCH_MD_MIN_LENGTH

# Required section headers (case-insensitive, "## " prefix optional).
# Match the plan §2.3 template headings; tolerate alternate phrasings
# like "## Question" vs "## Research Question".
REQUIRED_SECTIONS: tuple[str, ...] = (
    "decision",
    "question",
    "motivation",
    "universe",
    "constraints",
    "failure modes",
    "open qs",
)

# Heading must look like `^#{1,6}\s*(?P<title>.*)$` per CommonMark.
_HEADING_RE = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class ResearchMdValidation:
    ok: bool
    length: int
    min_length: int
    missing_sections: tuple[str, ...] = ()
    present_sections: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    suggested_template: str = field(default="")

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "length": self.length,
            "min_length": self.min_length,
            "missing_sections": list(self.missing_sections),
            "present_sections": list(self.present_sections),
            "errors": list(self.errors),
            "suggested_template": self.suggested_template,
        }


SUGGESTED_TEMPLATE = """## Decision
(What business decision does this strategy support?)

## Question
(One-sentence research question — what is being tested?)

## Motivation
(Why this question matters; what makes it interesting?)

## Universe
(Pair list, timeframes, market regime scope — be specific.)

## Constraints
(Leverage, drawdown tolerance, position sizing, time budget, etc.)

## Failure modes
(How will we know this is *not* working? Sharpe diving, regime mismatch,
oracle-gaming artifacts, etc.)

## Open Qs
(What do we still need to ask the user / clarify before generating code?)
"""


def _normalize(title: str) -> str:
    """Normalize a heading title for comparison: lowercase + collapse whitespace
    + strip trailing punctuation."""
    t = title.strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = t.rstrip("?:.!;,()[]{}")
    return t


def _extract_titles(md: str) -> list[str]:
    return [m.group("title") for m in _HEADING_RE.finditer(md)]


def validate_research_md(
    md: object,
    min_length: int = RESEARCH_MD_MIN_LENGTH,
) -> ResearchMdValidation:
    """Validate research_md for clarify-first gate (D-FT-21).

    Pure function. Defensive: non-string input yields a failed result rather
    than raising — matches D-FT-23's no-raises-for-business-false approach.
    """
    if not isinstance(md, str):
        return ResearchMdValidation(
            ok=False,
            length=0,
            min_length=min_length,
            errors=(f"research_md must be str, got {type(md).__name__}",),
            missing_sections=REQUIRED_SECTIONS,
            suggested_template=SUGGESTED_TEMPLATE,
        )

    length = len(md)
    errors: list[str] = []
    if length < min_length:
        errors.append(
            f"research_md must be >= {min_length} characters (got {length})"
        )

    titles = _extract_titles(md)
    present: list[str] = []
    missing: list[str] = []
    for sec in REQUIRED_SECTIONS:
        # Accept the section name as a substring/prefix within the title
        # (so "Decision" matches "## Decision" and "### Decision criteria").
        matched = any(sec in _normalize(t) for t in titles)
        if matched:
            present.append(sec)
        else:
            missing.append(sec)

    if missing:
        errors.append(
            f"research_md is missing required sections: {', '.join(missing)}"
        )

    return ResearchMdValidation(
        ok=not errors,
        length=length,
        min_length=min_length,
        missing_sections=tuple(missing),
        present_sections=tuple(present),
        errors=tuple(errors),
        suggested_template=SUGGESTED_TEMPLATE if errors else "",
    )

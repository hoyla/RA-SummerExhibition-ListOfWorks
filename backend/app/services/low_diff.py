"""Comparison + 2-way diff for the LOW → LPG reconciliation feature.

Two layers:

1. ``work_display_fields`` reduces a resolved database work to the same per-field
   *display strings* the renderer would emit, so the DB side and the parsed
   corrected-LOW side are directly comparable (see ``low_tag_parser``).

2. ``diff_low`` performs the 2-way diff (corrected LOW vs current DB): matches
   entries by catalogue number, aligns rooms by membership overlap, and emits
   significance-tiered findings tagged with the natural fix channel.

Comparison is at the display-string level — "did the printed value change" —
which is what the LPG depends on, and avoids inverting the renderer's £ / edition
formatting. Significance tiering and fix-channel routing live in ``LowDiffConfig``
(data, not hardcoded) so they can be tuned and later persisted as a Ruleset.

MVP scope is *detection only*: this module finds and classifies disparities; it
does not apply them. Resolution happens via existing channels (overrides for text
changes; spreadsheet re-import for structural ones — see fix_channel).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from backend.app.services.export_renderer import (
    DEFAULT_CONFIG,
    ExportConfig,
    _fmt_price,
)
from backend.app.services.low_tag_parser import ParsedEntry, recoverable_fields

# ---------------------------------------------------------------------------
# DB side: render a resolved work to display strings
# ---------------------------------------------------------------------------


def _edition_display(w: dict, config: ExportConfig) -> str:
    """Mirror the renderer's edition_display computation."""
    total = w.get("edition_total")
    price = w.get("edition_price_numeric")
    if total and price:
        inner = f"{config.edition_prefix} {total} at {_fmt_price(price, config)}"
    elif total:
        inner = f"{config.edition_prefix} {total}"
    else:
        return ""
    return f"({inner})" if config.edition_brackets else inner


def _price_display(w: dict, config: ExportConfig) -> str:
    """Mirror the renderer's price computation."""
    if w.get("price_numeric"):
        return _fmt_price(w["price_numeric"], config)
    if w.get("price_text"):
        return w["price_text"]
    return ""


def work_display_fields(w: dict, config: ExportConfig = DEFAULT_CONFIG) -> dict[str, str]:
    """Per-field display strings the renderer would emit for a resolved work
    dict (as produced by ``export_renderer._collect_export_data``).

    Only fields that are *recoverable* from the tags are included (enabled
    components with a non-empty character style), so the result is directly
    comparable to ``low_tag_parser.parse_low_tags`` output.
    """
    recoverable = set(recoverable_fields(config))
    candidates = {
        "work_number": str(w["number"]) if w.get("number") else "",
        "artist": w.get("artist") or "",
        "honorifics": (
            (w["honorifics"].lower() if config.honorifics_lowercase else w["honorifics"])
            if w.get("honorifics")
            else ""
        ),
        "title": w.get("title") or "",
        "edition": _edition_display(w, config),
        "price": _price_display(w, config),
        "medium": w.get("medium") or "",
        "artwork": str(w["artwork"]) if w.get("artwork") else "",
    }
    return {f: v for f, v in candidates.items() if f in recoverable and v != ""}


# ---------------------------------------------------------------------------
# 2-way diff configuration (data-driven significance tiering + fix routing)
# ---------------------------------------------------------------------------

# Typographic folds applied during cosmetic-noise suppression (InDesign smart
# quotes vs the straight quotes typically stored in the spreadsheet).
_TYPO_FOLD = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "′": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "″": '"',
}
_WS_RE = re.compile(r"\s+")


@dataclass
class LowDiffConfig:
    """Tunable diff policy. Plain dicts so it can be persisted as JSON / a
    Ruleset later and edited live, rather than baked into code."""

    # Severity per finding kind. field_change can be tuned per field.
    severity: dict = field(
        default_factory=lambda: {
            "entry_added": "high",
            "entry_removed": "high",
            "room_move": "high",
            "section_rename": "info",
            "field_change_default": "medium",
            "field_change": {},  # per-field override, e.g. {"price": "high"}
        }
    )
    # Where each kind of disparity is naturally resolved.
    fix_channel: dict = field(
        default_factory=lambda: {
            "field_change": "override",  # text correction → an override (later)
            "entry_added": "spreadsheet",  # structural → fix master + re-import
            "entry_removed": "spreadsheet",
            "room_move": "spreadsheet",
            "section_rename": "spreadsheet",
        }
    )
    suppress_cosmetic: bool = True  # drop diffs that vanish after normalisation
    fold_typographic: bool = True  # treat smart/straight quotes as equal

    @classmethod
    def from_dict(cls, d: dict | None) -> "LowDiffConfig":
        cfg = cls()
        if not d:
            return cfg
        for key in ("severity", "fix_channel"):
            if isinstance(d.get(key), dict):
                getattr(cfg, key).update(d[key])
        for key in ("suppress_cosmetic", "fold_typographic"):
            if key in d:
                setattr(cfg, key, bool(d[key]))
        return cfg


DEFAULT_DIFF_CONFIG = LowDiffConfig()


@dataclass
class Finding:
    """One detected disparity between the corrected LOW and the database."""

    kind: str  # field_change | entry_added | entry_removed | room_move | section_rename
    cat_no: str | None
    field: str | None
    db_value: str | None
    low_value: str | None
    section: str | None
    severity: str
    fix_channel: str
    message: str


@dataclass
class DiffResult:
    findings: list[Finding]
    section_alignment: dict[str, str]  # DB section name -> aligned LOW section name
    counts: dict
    # Field differences that vanish after normalisation (whitespace, quote style,
    # line breaks). Kept out of `findings` but retained for transparency/drill-in.
    cosmetic: list[Finding] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _norm(s: str | None, config: LowDiffConfig) -> str:
    """Normalise a display string for *comparison*: fold typography, NFC, and
    collapse all whitespace (incl. soft returns) to single spaces. This is what
    makes wrapping artefacts and smart-quote conversions non-significant."""
    s = s or ""
    if config.fold_typographic:
        s = "".join(_TYPO_FOLD.get(ch, ch) for ch in s)
    s = unicodedata.normalize("NFC", s)
    # Line breaks aren't editorially significant (the LPG re-lays-out), and the
    # parser deletes soft returns, so strip CR/LF on both sides — otherwise a
    # manual newline in a source field (e.g. a multi-line medium) reads as a
    # change because the DB keeps the newline and the parsed LOW does not.
    s = s.replace("\r", "").replace("\n", "")
    return _WS_RE.sub(" ", s).strip()


def _catsort(c: str):
    try:
        return (0, int(c))
    except (TypeError, ValueError):
        return (1, str(c))


def _severity(config: LowDiffConfig, kind: str, fld: str | None = None) -> str:
    sev = config.severity
    if kind == "field_change":
        return sev.get("field_change", {}).get(fld, sev.get("field_change_default", "medium"))
    return sev.get(kind, "medium")


def _channel(config: LowDiffConfig, kind: str) -> str:
    return config.fix_channel.get(kind, "review")


def _align_sections(
    matched: set[str], db_sec: dict[str, str], low_sec: dict[str, str]
) -> dict[str, str]:
    """Map each DB section to the LOW section it shares the most catalogue
    numbers with (so room renames/embellishments don't look like every work
    moving)."""
    overlap: dict[str, Counter] = defaultdict(Counter)
    for cat in matched:
        overlap[db_sec[cat]][low_sec[cat]] += 1
    return {db: cnt.most_common(1)[0][0] for db, cnt in overlap.items()}


def _count_by(findings: list[Finding], attr: str) -> dict:
    return dict(Counter(getattr(f, attr) for f in findings))


# ---------------------------------------------------------------------------
# 2-way diff
# ---------------------------------------------------------------------------


def diff_low(
    parsed: list[ParsedEntry],
    collected: list[dict],
    export_config: ExportConfig = DEFAULT_CONFIG,
    diff_config: LowDiffConfig = DEFAULT_DIFF_CONFIG,
) -> DiffResult:
    """Diff parsed corrected-LOW entries against the current resolved DB.

    ``collected`` is the output of ``export_renderer._collect_export_data``.
    Returns significance-tiered, fix-channel-tagged findings (detection only).
    """
    # DB side
    db_fields: dict[str, dict] = {}
    db_sec: dict[str, str] = {}
    for sec in collected:
        for w in sec["works"]:
            cat = str(w["number"]) if w.get("number") else None
            if not cat:
                continue
            db_fields[cat] = work_display_fields(w, export_config)
            db_sec[cat] = sec["section_name"]

    # LOW side
    low_fields: dict[str, dict] = {e.cat_no: e.fields for e in parsed}
    low_sec: dict[str, str] = {e.cat_no: e.section_name for e in parsed}

    db_cats, low_cats = set(db_fields), set(low_fields)
    matched = db_cats & low_cats
    db_only = db_cats - low_cats
    low_only = low_cats - db_cats
    aligned = _align_sections(matched, db_sec, low_sec)

    compare_fields = [f for f in recoverable_fields(export_config) if f != "work_number"]

    findings: list[Finding] = []
    cosmetic: list[Finding] = []

    for cat in sorted(matched, key=_catsort):
        # Field-level changes
        for fld in compare_fields:
            dv = db_fields[cat].get(fld, "")
            lv = low_fields[cat].get(fld, "")
            if dv == lv:
                continue  # identical
            if _norm(dv, diff_config) == _norm(lv, diff_config):
                # Differs only cosmetically (whitespace / quotes / line breaks).
                cf = Finding(
                    kind="field_change",
                    cat_no=cat,
                    field=fld,
                    db_value=dv,
                    low_value=lv,
                    section=db_sec[cat],
                    severity="cosmetic",
                    fix_channel=_channel(diff_config, "field_change"),
                    message=f"{fld}: {dv!r} → {lv!r} (cosmetic)",
                )
                (cosmetic if diff_config.suppress_cosmetic else findings).append(cf)
                continue
            findings.append(
                Finding(
                    kind="field_change",
                    cat_no=cat,
                    field=fld,
                    db_value=dv,
                    low_value=lv,
                    section=db_sec[cat],
                    severity=_severity(diff_config, "field_change", fld),
                    fix_channel=_channel(diff_config, "field_change"),
                    message=f"{fld}: {dv!r} → {lv!r}",
                )
            )
        # Room moves
        expected = aligned.get(db_sec[cat])
        if expected is not None and low_sec[cat] != expected:
            findings.append(
                Finding(
                    kind="room_move",
                    cat_no=cat,
                    field=None,
                    db_value=db_sec[cat],
                    low_value=low_sec[cat],
                    section=low_sec[cat],
                    severity=_severity(diff_config, "room_move"),
                    fix_channel=_channel(diff_config, "room_move"),
                    message=f"moved from {db_sec[cat]!r} to {low_sec[cat]!r}",
                )
            )

    for cat in sorted(low_only, key=_catsort):
        findings.append(
            Finding(
                kind="entry_added",
                cat_no=cat,
                field=None,
                db_value=None,
                low_value=low_fields[cat].get("title", ""),
                section=low_sec[cat],
                severity=_severity(diff_config, "entry_added"),
                fix_channel=_channel(diff_config, "entry_added"),
                message=f"cat {cat} present in LOW but not in data",
            )
        )

    for cat in sorted(db_only, key=_catsort):
        findings.append(
            Finding(
                kind="entry_removed",
                cat_no=cat,
                field=None,
                db_value=db_fields[cat].get("title", ""),
                low_value=None,
                section=db_sec[cat],
                severity=_severity(diff_config, "entry_removed"),
                fix_channel=_channel(diff_config, "entry_removed"),
                message=f"cat {cat} present in data but not in LOW",
            )
        )

    for db_s, low_s in aligned.items():
        if _norm(db_s, diff_config) != _norm(low_s, diff_config):
            findings.append(
                Finding(
                    kind="section_rename",
                    cat_no=None,
                    field=None,
                    db_value=db_s,
                    low_value=low_s,
                    section=low_s,
                    severity=_severity(diff_config, "section_rename"),
                    fix_channel=_channel(diff_config, "section_rename"),
                    message=f"section {db_s!r} appears as {low_s!r} in LOW",
                )
            )

    counts = {
        "matched": len(matched),
        "db_only": len(db_only),
        "low_only": len(low_only),
        "findings": len(findings),
        "suppressed_cosmetic": len(cosmetic),
        "by_severity": _count_by(findings, "severity"),
        "by_fix_channel": _count_by(findings, "fix_channel"),
    }
    return DiffResult(
        findings=findings,
        section_alignment=aligned,
        counts=counts,
        cosmetic=cosmetic,
    )

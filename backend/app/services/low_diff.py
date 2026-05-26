"""Comparison helpers for the LOW → LPG reconciliation feature.

This module reduces a resolved database work to the same per-field *display
strings* the renderer would emit, so they can be compared field-for-field
against parsed corrected-LOW tags (see ``low_tag_parser``).

Keeping the comparison at the display-string level (rather than structured
price/edition numbers) means the diff answers "did the printed value change",
which is exactly what the LPG depends on, and avoids inverting the renderer's
formatting. The 2-way diff itself (task #5) builds on top of this.
"""

from __future__ import annotations

from backend.app.services.export_renderer import (
    ExportConfig,
    DEFAULT_CONFIG,
    _fmt_price,
)
from backend.app.services.low_tag_parser import (
    recoverable_fields,
    _FIELD_STYLE_ATTRS,  # noqa: F401  (kept for symmetry / future use)
)


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
    return {
        f: v for f, v in candidates.items() if f in recoverable and v != ""
    }

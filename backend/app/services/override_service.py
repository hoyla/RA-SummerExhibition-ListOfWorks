"""
Override resolution service.

Provides `resolve_effective_work` which merges a Work's normalised fields with
any WorkOverride row to produce the values that should be used by the export
renderer and preview endpoints.

The resolved values are returned as a simple dataclass so callers never need to
re-query.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass
class EffectiveWork:
    """Resolved field values for a single catalogue work."""

    raw_cat_no: Optional[str]

    title: Optional[str]
    title_cased: Optional[str]
    artist_name: Optional[str]
    artist_honorifics: Optional[str]

    price_numeric: Optional[Decimal]
    price_text: Optional[str]

    edition_total: Optional[int]
    edition_price_numeric: Optional[Decimal]

    artwork: Optional[int]
    medium: Optional[str]

    include_in_export: bool


def resolve_effective_work(work, override) -> EffectiveWork:
    """
    Merge a Work ORM object with an optional WorkOverride ORM object.

    Rules:
      - If an override field is not None, it takes precedence.
      - For price: a non-empty price_text_override wins for display and
        suppresses the numeric, so a footnoted/non-numeric price (e.g.
        "£60,000*") can be carried for a work whose source price is numeric.
      - Raw fields (raw_cat_no) are never overridable – preserved as-is.
      - include_in_export lives on the Work directly (no override).

    Parameters
    ----------
    work:
        SQLAlchemy Work instance (or any object with matching attributes).
    override:
        SQLAlchemy WorkOverride instance, or None.

    Returns
    -------
    EffectiveWork
    """

    if override is None:
        return EffectiveWork(
            raw_cat_no=work.raw_cat_no,
            title=work.title,
            title_cased=getattr(work, "title_cased", None),
            artist_name=work.artist_name,
            artist_honorifics=work.artist_honorifics,
            price_numeric=work.price_numeric,
            price_text=work.price_text,
            edition_total=work.edition_total,
            edition_price_numeric=work.edition_price_numeric,
            artwork=work.artwork,
            medium=work.medium,
            include_in_export=bool(work.include_in_export),
        )

    # Price logic: if price_numeric_override is set, use it;
    # if price_text_override is set, use it; otherwise fall back to work values.
    effective_price_numeric = (
        override.price_numeric_override
        if override.price_numeric_override is not None
        else work.price_numeric
    )
    effective_price_text = (
        override.price_text_override
        if override.price_text_override is not None
        else work.price_text
    )
    # A non-empty price-text override means "display this exact price string"
    # (e.g. a footnoted "£60,000*"), so suppress the numeric — which otherwise
    # wins in the renderer. "" (clear text) does not suppress the numeric.
    if override.price_text_override:
        effective_price_numeric = None

    return EffectiveWork(
        raw_cat_no=work.raw_cat_no,
        title=(
            override.title_override
            if override.title_override is not None
            else work.title
        ),
        title_cased=(
            override.title_cased_override
            if getattr(override, "title_cased_override", None) is not None
            else getattr(work, "title_cased", None)
        ),
        artist_name=(
            override.artist_name_override
            if override.artist_name_override is not None
            else work.artist_name
        ),
        artist_honorifics=(
            override.artist_honorifics_override
            if override.artist_honorifics_override is not None
            else work.artist_honorifics
        ),
        price_numeric=effective_price_numeric,
        price_text=effective_price_text,
        edition_total=(
            override.edition_total_override
            if override.edition_total_override is not None
            else work.edition_total
        ),
        edition_price_numeric=(
            override.edition_price_numeric_override
            if override.edition_price_numeric_override is not None
            else work.edition_price_numeric
        ),
        artwork=(
            override.artwork_override
            if override.artwork_override is not None
            else work.artwork
        ),
        medium=(
            override.medium_override
            if override.medium_override is not None
            else work.medium
        ),
        include_in_export=bool(work.include_in_export),
    )

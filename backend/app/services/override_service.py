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
      - For price: if price_text_override is set, that wins for display;
        if price_numeric_override is also set, both are used.
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

    return EffectiveWork(
        raw_cat_no=work.raw_cat_no,
        title=(
            override.title_override
            if override.title_override is not None
            else work.title
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
        artwork=work.artwork,
        medium=(
            override.medium_override
            if override.medium_override is not None
            else work.medium
        ),
        include_in_export=bool(work.include_in_export),
    )

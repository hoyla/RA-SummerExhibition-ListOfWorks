"""
Pydantic request/response schemas shared across API route modules.
"""

from pydantic import BaseModel
from typing import List


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


class ImportOut(BaseModel):
    id: str
    filename: str
    uploaded_at: str
    notes: str | None
    sections: int
    works: int
    override_count: int
    last_override_at: str | None

    model_config = {"from_attributes": True}


class ReimportOut(BaseModel):
    import_id: str
    matched: int
    added: int
    removed: int
    overrides_preserved: int


# ---------------------------------------------------------------------------
# Work / Section listing
# ---------------------------------------------------------------------------


class WorkOverrideOut(BaseModel):
    """Embedded override snapshot attached to each WorkOut."""

    title_override: str | None = None
    artist_name_override: str | None = None
    artist_honorifics_override: str | None = None
    price_numeric_override: float | None = None
    price_text_override: str | None = None
    edition_total_override: int | None = None
    edition_price_numeric_override: float | None = None
    artwork_override: int | None = None
    medium_override: str | None = None

    model_config = {"from_attributes": True}


class WorkOut(BaseModel):
    id: str
    position_in_section: int
    raw_cat_no: str | None
    title: str | None
    artist_name: str | None
    artist_honorifics: str | None
    price_text: str | None
    price_numeric: float | None
    edition_total: int | None
    edition_price_numeric: float | None
    artwork: int | None
    medium: str | None
    include_in_export: bool
    override: WorkOverrideOut | None = None

    model_config = {"from_attributes": True}


class SectionOut(BaseModel):
    id: str
    name: str
    position: int
    works: List[WorkOut]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


class PreviewWorkOut(BaseModel):
    number: str | None
    title: str | None
    artist: str | None
    price_display: str | None
    edition_display: str | None

    model_config = {"from_attributes": True}


class PreviewSectionOut(BaseModel):
    name: str
    position: int
    works: List[PreviewWorkOut]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Validation warnings
# ---------------------------------------------------------------------------


class ValidationWarningOut(BaseModel):
    id: str
    work_id: str | None
    warning_type: str
    message: str
    artist_name: str | None = None
    title: str | None = None
    cat_no: str | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


class AuditLogOut(BaseModel):
    id: str
    import_id: str | None
    work_id: str | None
    template_id: str | None = None
    action: str
    field: str | None
    old_value: str | None
    new_value: str | None
    created_at: str
    # Denormalised work context (if the work still exists)
    cat_no: str | None = None
    artist_name: str | None = None
    title: str | None = None
    # Denormalised template context
    template_name: str | None = None


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


class OverrideIn(BaseModel):
    """Request body for setting work overrides. All fields are optional."""

    title_override: str | None = None
    artist_name_override: str | None = None
    artist_honorifics_override: str | None = None
    price_numeric_override: float | None = None
    price_text_override: str | None = None
    edition_total_override: int | None = None
    edition_price_numeric_override: float | None = None
    artwork_override: int | None = None
    medium_override: str | None = None


class OverrideOut(BaseModel):
    work_id: str
    title_override: str | None
    artist_name_override: str | None
    artist_honorifics_override: str | None
    price_numeric_override: float | None
    price_text_override: str | None
    edition_total_override: int | None
    edition_price_numeric_override: float | None
    artwork_override: int | None
    medium_override: str | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Normalisation config
# ---------------------------------------------------------------------------


class NormalisationIn(BaseModel):
    honorific_tokens: list[str] = [
        "RA",
        "PRA",
        "PPRA",
        "HON",
        "HONRA",
        "ELECT",
        "EX",
        "OFFICIO",
    ]


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


class ComponentConfigIn(BaseModel):
    field: str
    separator_after: str = "tab"
    omit_sep_when_empty: bool = True
    enabled: bool = True
    max_line_chars: int | None = None
    next_component_position: str = "end_of_text"
    balance_lines: bool = False


class TemplateBodyIn(BaseModel):
    name: str
    currency_symbol: str = "\u00a3"
    section_style: str = "SectionTitle"
    entry_style: str = "CatalogueEntry"
    edition_prefix: str = "edition of"
    edition_brackets: bool = True
    cat_no_style: str = "CatNo"
    artist_style: str = "ArtistName"
    honorifics_style: str = "Honorifics"
    honorifics_lowercase: bool = False
    title_style: str = "WorkTitle"
    price_style: str = "Price"
    medium_style: str = "Medium"
    artwork_style: str = "Artwork"
    thousands_separator: str = ","
    decimal_places: int = 0
    section_separator: str = "paragraph"
    leading_separator: str = "none"
    trailing_separator: str = "none"
    final_sep_from_last_component: bool = False
    components: list[ComponentConfigIn] = [
        ComponentConfigIn(field="work_number", separator_after="tab"),
        ComponentConfigIn(field="artist", separator_after="tab"),
        ComponentConfigIn(field="title", separator_after="tab"),
        ComponentConfigIn(field="edition", separator_after="tab"),
        ComponentConfigIn(field="artwork", separator_after="tab", enabled=False),
        ComponentConfigIn(field="price", separator_after="none"),
        ComponentConfigIn(field="medium", separator_after="none"),
    ]


class TemplateOut(BaseModel):
    id: str
    name: str
    created_at: str
    is_builtin: bool

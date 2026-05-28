"""
Pydantic request/response schemas shared across API route modules.
"""

from pydantic import BaseModel, field_validator
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


class GallerySummaryOut(BaseModel):
    """One gallery in the freshly-uploaded spreadsheet, for the UI picker."""

    name: str
    position: int
    work_count: int
    cat_no_min: int | None
    cat_no_max: int | None
    in_scope: bool


class UnmatchedOut(BaseModel):
    """A preserved override with no acceptable target in the new spreadsheet."""

    old_cat_no: str
    raw_title: str | None
    raw_artist: str | None
    had_override: bool
    reason: str


class AmbiguousOut(BaseModel):
    """A preserved override whose match is ambiguous and refused by the matcher."""

    old_cat_no: str
    raw_title: str | None
    raw_artist: str | None
    candidate_new_cat_nos: List[str]
    reason: str


class CrossGalleryMoveWarningOut(BaseModel):
    """A row in the selected gallery scope appears (by fingerprint) to be a
    work currently in a non-scope gallery — selective re-import would
    duplicate it."""

    new_cat_no: str
    raw_title: str | None
    raw_artist: str | None
    old_cat_no: str
    old_gallery: str
    new_gallery: str


class ReimportOut(BaseModel):
    import_id: str
    # Legacy fields preserved for backwards-compat with existing UI / tests.
    # ``matched`` is the sum of cat-no and fingerprint matches.
    matched: int
    added: int
    removed: int
    overrides_preserved: int
    # Plan details — new in the matcher-based re-import.
    dry_run: bool = False
    matched_by_cat_no: int = 0
    matched_by_fingerprint: int = 0
    overrides_at_risk: int = 0
    galleries: List[GallerySummaryOut] = []
    unmatched: List[UnmatchedOut] = []
    ambiguous: List[AmbiguousOut] = []
    cross_gallery_warnings: List[CrossGalleryMoveWarningOut] = []


# ---------------------------------------------------------------------------
# Work / Section listing
# ---------------------------------------------------------------------------


class WorkOverrideOut(BaseModel):
    """Embedded override snapshot attached to each WorkOut."""

    title_override: str | None = None
    title_cased_override: str | None = None
    artist_name_override: str | None = None
    artist_honorifics_override: str | None = None
    price_numeric_override: float | None = None
    price_text_override: str | None = None
    edition_total_override: int | None = None
    edition_price_numeric_override: float | None = None
    artwork_override: int | None = None
    medium_override: str | None = None
    notes: str | None = None

    model_config = {"from_attributes": True}


class WorkOut(BaseModel):
    id: str
    position_in_section: int
    raw_cat_no: str | None
    # Raw layer (verbatim from spreadsheet)
    raw_title: str | None = None
    raw_artist: str | None = None
    raw_price: str | None = None
    raw_edition: str | None = None
    raw_artwork: str | None = None
    raw_medium: str | None = None
    # Normalised layer
    title: str | None
    title_cased: str | None = None
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
    artist_id: str | None = None
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
    # Denormalised index artist context (if the artist still exists)
    index_artist_name: str | None = None
    # Denormalised template context
    template_name: str | None = None
    # User attribution
    user_email: str | None = None


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


class OverrideIn(BaseModel):
    """Request body for setting work overrides. All fields are optional."""

    title_override: str | None = None
    title_cased_override: str | None = None
    artist_name_override: str | None = None
    artist_honorifics_override: str | None = None
    price_numeric_override: float | None = None
    price_text_override: str | None = None
    edition_total_override: int | None = None
    edition_price_numeric_override: float | None = None
    artwork_override: int | None = None
    medium_override: str | None = None
    notes: str | None = None


class OverrideOut(BaseModel):
    work_id: str
    title_override: str | None
    title_cased_override: str | None
    artist_name_override: str | None
    artist_honorifics_override: str | None
    price_numeric_override: float | None
    price_text_override: str | None
    edition_total_override: int | None
    edition_price_numeric_override: float | None
    artwork_override: int | None
    medium_override: str | None
    notes: str | None

    @field_validator("work_id", mode="before")
    @classmethod
    def _stringify_work_id(cls, v):
        return str(v) if v is not None else v

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Normalisation config
# ---------------------------------------------------------------------------


_SUBSTITUTABLE_FIELDS = {"title", "medium", "artist"}


class TextSubstitutionIn(BaseModel):
    """A literal find→replace rule scoped to one or more derived fields.

    Spaces in find/replace are significant and preserved (so " - " only matches a
    spaced hyphen). find must be non-empty.

    When ``whole_word`` is true the find is wrapped in regex word boundaries
    so it only matches standalone occurrences — e.g. ``pla`` → ``PLA`` won't
    mangle ``plaster`` or ``display``. Default false to preserve the legacy
    plain-substring behaviour for existing rules (notably the ellipsis
    ``...`` → ``…`` rule, which can't use word boundaries because ``.`` isn't
    a word char on either side)."""

    find: str
    replace: str = ""
    fields: list[str] = ["title", "medium"]
    whole_word: bool = False

    @field_validator("find")
    @classmethod
    def _find_not_blank(cls, v: str) -> str:
        if not v:
            raise ValueError("substitution 'find' must not be empty")
        return v

    @field_validator("fields")
    @classmethod
    def _known_fields(cls, v: list[str]) -> list[str]:
        bad = [f for f in v if f not in _SUBSTITUTABLE_FIELDS]
        if bad:
            raise ValueError(
                f"unknown substitution field(s): {bad}; "
                f"allowed: {sorted(_SUBSTITUTABLE_FIELDS)}"
            )
        return v


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
    # Suppress editions whose total is <= this (0 = drop only "Edition of 0").
    edition_suppress_max: int = 0
    text_substitutions: list[TextSubstitutionIn] = [
        TextSubstitutionIn(find="...", replace="…", fields=["title", "medium"]),
    ]
    # Tokens whose casing is preserved when title-casing (acronyms, stylised names).
    title_case_exceptions: list[str] = [
        "RA", "PRA", "PPRA", "RWS", "RE", "NEAC", "OBE", "MBE", "CBE",
        "USA", "UK", "NYC", "LA", "BBC", "MoMA",
    ]

    @field_validator("edition_suppress_max")
    @classmethod
    def _sane_threshold(cls, v: int) -> int:
        if v < 0 or v > 10:
            raise ValueError("edition_suppress_max must be between 0 and 10")
        return v


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
    # When set, this component opens a new paragraph with this paragraph style
    # (LPG model). Empty/None keeps it inline (LOW model).
    paragraph_style: str | None = None


class TemplateBodyIn(BaseModel):
    name: str
    currency_symbol: str = "\u00a3"
    section_style: str = "SectionTitle"
    section_styles: list[str] = []
    entry_style: str = "CatalogueEntry"
    edition_prefix: str = "edition of"
    edition_brackets: bool = True
    cat_no_style: str = "CatNo"
    artist_style: str = "ArtistName"
    honorifics_style: str = "Honorifics"
    honorifics_lowercase: bool = False
    title_style: str = "WorkTitle"
    title_cased_style: str = "WorkTitle"
    price_style: str = "Price"
    medium_style: str = "Medium"
    artwork_style: str = "Artwork"
    edition_style: str = "Edition"
    thousands_separator: str = ","
    decimal_places: int = 0
    section_separator: str = "paragraph"
    section_separator_style: str = ""
    leading_separator: str = "none"
    trailing_separator: str = "none"
    final_sep_from_last_component: bool = False
    components: list[ComponentConfigIn] = [
        ComponentConfigIn(field="work_number", separator_after="tab"),
        ComponentConfigIn(field="artist", separator_after="tab"),
        ComponentConfigIn(field="title", separator_after="tab"),
        ComponentConfigIn(field="title_cased", separator_after="tab", enabled=False),
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


# ---------------------------------------------------------------------------
# Artists' Index Templates
# ---------------------------------------------------------------------------


class IndexTemplateBodyIn(BaseModel):
    name: str
    entry_style: str = "Index Text"
    ra_surname_style: str = "RA Member Cap Surname"
    ra_caps_style: str = "RA Caps"
    cat_no_style: str = "Index works numbers"
    honorifics_style: str = "Small caps"
    expert_numbers_style: str = "Expert numbers"
    quals_lowercase: bool = True
    expert_numbers_enabled: bool = False
    cat_no_separator: str = ","
    cat_no_separator_style: str = ""
    section_separator: str = "paragraph"
    section_separator_style: str = ""
    letter_heading_enabled: bool = False
    letter_heading_style: str = ""


# ---------------------------------------------------------------------------
# Artists' Index
# ---------------------------------------------------------------------------


class IndexCatNumberOut(BaseModel):
    id: str
    cat_no: int
    courtesy: str | None = None
    source_row: int | None = None

    model_config = {"from_attributes": True}


class AutoResolvedFields(BaseModel):
    """Auto-resolved values (normalisation + known artist, before user override)."""

    title: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    quals: str | None = None
    company: str | None = None
    address: str | None = None
    is_company: bool = False
    artist2_first_name: str | None = None
    artist2_last_name: str | None = None
    artist2_quals: str | None = None
    artist3_first_name: str | None = None
    artist3_last_name: str | None = None
    artist3_quals: str | None = None
    artist1_ra_styled: bool = False
    artist2_ra_styled: bool = False
    artist3_ra_styled: bool = False
    artist2_shared_surname: bool = False
    artist3_shared_surname: bool = False


class IndexArtistOut(BaseModel):
    id: str
    row_number: int | None = None
    raw_title: str | None = None
    raw_first_name: str | None = None
    raw_last_name: str | None = None
    raw_quals: str | None = None
    raw_company: str | None = None
    raw_address: str | None = None
    index_name: str
    title: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    quals: str | None = None
    company: str | None = None
    address: str | None = None
    artist2_first_name: str | None = None
    artist2_last_name: str | None = None
    artist2_quals: str | None = None
    artist3_first_name: str | None = None
    artist3_last_name: str | None = None
    artist3_quals: str | None = None
    artist1_ra_styled: bool = False
    artist2_ra_styled: bool = False
    artist3_ra_styled: bool = False
    artist2_shared_surname: bool = False
    artist3_shared_surname: bool = False
    is_ra_member: bool
    is_company: bool
    is_company_auto: bool = False
    has_known_artist: bool = False
    has_override: bool = False
    override: "IndexArtistOverrideOut | None" = None
    auto_resolved: AutoResolvedFields | None = None
    sort_key: str
    include_in_export: bool
    cat_numbers: List[IndexCatNumberOut]
    merged_from_rows: List[int] | None = None

    model_config = {"from_attributes": True}


class IndexArtistOverrideIn(BaseModel):
    """Request body for setting index artist overrides. All fields optional."""

    first_name_override: str | None = None
    last_name_override: str | None = None
    title_override: str | None = None
    quals_override: str | None = None
    artist2_first_name_override: str | None = None
    artist2_last_name_override: str | None = None
    artist2_quals_override: str | None = None
    artist3_first_name_override: str | None = None
    artist3_last_name_override: str | None = None
    artist3_quals_override: str | None = None
    artist1_ra_styled_override: bool | None = None
    artist2_ra_styled_override: bool | None = None
    artist3_ra_styled_override: bool | None = None
    artist2_shared_surname_override: bool | None = None
    artist3_shared_surname_override: bool | None = None
    is_company_override: bool | None = None
    company_override: str | None = None
    address_override: str | None = None
    notes: str | None = None


class IndexArtistOverrideOut(BaseModel):
    artist_id: str
    first_name_override: str | None = None
    last_name_override: str | None = None
    title_override: str | None = None
    quals_override: str | None = None
    artist2_first_name_override: str | None = None
    artist2_last_name_override: str | None = None
    artist2_quals_override: str | None = None
    artist3_first_name_override: str | None = None
    artist3_last_name_override: str | None = None
    artist3_quals_override: str | None = None
    artist1_ra_styled_override: bool | None = None
    artist2_ra_styled_override: bool | None = None
    artist3_ra_styled_override: bool | None = None
    artist2_shared_surname_override: bool | None = None
    artist3_shared_surname_override: bool | None = None
    is_company_override: bool | None = None
    company_override: str | None = None
    address_override: str | None = None
    notes: str | None = None

    model_config = {"from_attributes": True}


class IndexImportOut(BaseModel):
    id: str
    filename: str
    uploaded_at: str
    notes: str | None = None
    product_type: str
    artist_count: int
    override_count: int = 0

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Known Artists
# ---------------------------------------------------------------------------


class KnownArtistOut(BaseModel):
    id: str
    match_first_name: str | None = None
    match_last_name: str | None = None
    match_quals: str | None = None
    resolved_first_name: str | None = None
    resolved_last_name: str | None = None
    resolved_title: str | None = None
    resolved_quals: str | None = None
    resolved_is_company: bool | None = None
    resolved_company: str | None = None
    resolved_address: str | None = None
    resolved_artist2_first_name: str | None = None
    resolved_artist2_last_name: str | None = None
    resolved_artist2_quals: str | None = None
    resolved_artist3_first_name: str | None = None
    resolved_artist3_last_name: str | None = None
    resolved_artist3_quals: str | None = None
    resolved_artist1_ra_styled: bool | None = None
    resolved_artist2_ra_styled: bool | None = None
    resolved_artist3_ra_styled: bool | None = None
    resolved_artist2_shared_surname: bool | None = None
    resolved_artist3_shared_surname: bool | None = None
    notes: str | None = None
    is_seeded: bool = False

    model_config = {"from_attributes": True}


class KnownArtistCreate(BaseModel):
    match_first_name: str | None = None
    match_last_name: str | None = None
    match_quals: str | None = None
    resolved_first_name: str | None = None
    resolved_last_name: str | None = None
    resolved_title: str | None = None
    resolved_quals: str | None = None
    resolved_is_company: bool | None = None
    resolved_company: str | None = None
    resolved_address: str | None = None
    resolved_artist2_first_name: str | None = None
    resolved_artist2_last_name: str | None = None
    resolved_artist2_quals: str | None = None
    resolved_artist3_first_name: str | None = None
    resolved_artist3_last_name: str | None = None
    resolved_artist3_quals: str | None = None
    resolved_artist1_ra_styled: bool | None = None
    resolved_artist2_ra_styled: bool | None = None
    resolved_artist3_ra_styled: bool | None = None
    resolved_artist2_shared_surname: bool | None = None
    resolved_artist3_shared_surname: bool | None = None
    notes: str | None = None


class KnownArtistUpdate(BaseModel):
    match_first_name: str | None = None
    match_last_name: str | None = None
    match_quals: str | None = None
    resolved_first_name: str | None = None
    resolved_last_name: str | None = None
    resolved_title: str | None = None
    resolved_quals: str | None = None
    resolved_is_company: bool | None = None
    resolved_company: str | None = None
    resolved_address: str | None = None
    resolved_artist2_first_name: str | None = None
    resolved_artist2_last_name: str | None = None
    resolved_artist2_quals: str | None = None
    resolved_artist3_first_name: str | None = None
    resolved_artist3_last_name: str | None = None
    resolved_artist3_quals: str | None = None
    resolved_artist1_ra_styled: bool | None = None
    resolved_artist2_ra_styled: bool | None = None
    resolved_artist3_ra_styled: bool | None = None
    resolved_artist2_shared_surname: bool | None = None
    resolved_artist3_shared_surname: bool | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Cross-dataset comparison
# ---------------------------------------------------------------------------


class ComparisonEntryOut(BaseModel):
    cat_no: int

    # LoW side
    low_artist_name: str | None = None
    low_artist_honorifics: str | None = None
    low_work_id: str | None = None

    # Index side
    index_name: str | None = None
    index_first_name: str | None = None
    index_last_name: str | None = None
    index_title: str | None = None
    index_quals: str | None = None
    index_is_company: bool | None = None
    index_artist_id: str | None = None
    index_courtesy: str | None = None

    match_level: str  # "exact" | "equivalent" | "partial_title" | "partial_honorific" | "partial_ra" | "partial_name" | "none"
    differences: List[str] = []


class ComparisonSummaryOut(BaseModel):
    total_low: int
    total_index: int
    in_both: int
    only_in_low: int
    only_in_index: int
    match_exact: int
    match_equivalent: int
    match_partial_title: int
    match_partial_honorific: int
    match_partial_ra: int
    match_partial_name: int
    match_none: int


class ComparisonResultOut(BaseModel):
    low_import_id: str
    index_import_id: str
    summary: ComparisonSummaryOut
    entries: List[ComparisonEntryOut]

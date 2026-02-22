"""
Export routes: InDesign Tagged Text, JSON, XML, CSV.

Also contains _ruleset_to_export_config which converts a Ruleset DB row
into an ExportConfig dataclass.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from uuid import UUID

from backend.app.api.deps import get_db
from backend.app.services.export_renderer import (
    render_import_as_tagged_text,
    render_import_as_json,
    render_import_as_xml,
    render_import_as_csv,
    ExportConfig,
    DEFAULT_CONFIG,
    DEFAULT_COMPONENTS,
    ComponentConfig,
    resolve_export_config,
    escape_for_mac_roman,
)
from backend.app.services.export_diff_service import (
    save_export_snapshot,
    compute_diff,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper: convert a Ruleset row (or None) to an ExportConfig
# ---------------------------------------------------------------------------


def _ruleset_to_export_config(ruleset) -> ExportConfig:
    """Convert a Ruleset DB row (or None) to an ExportConfig, falling back to defaults."""
    if not ruleset:
        return DEFAULT_CONFIG
    cfg = ruleset.config
    raw_components = cfg.get(
        "components",
        [
            {
                "field": c.field,
                "separator_after": c.separator_after,
                "omit_sep_when_empty": c.omit_sep_when_empty,
                "enabled": c.enabled,
                "max_line_chars": c.max_line_chars,
                "next_component_position": c.next_component_position,
                "balance_lines": c.balance_lines,
            }
            for c in DEFAULT_COMPONENTS
        ],
    )
    components = [
        ComponentConfig(
            field=c["field"] if isinstance(c, dict) else c.field,
            separator_after=(
                c.get("separator_after", "tab")
                if isinstance(c, dict)
                else c.separator_after
            ),
            omit_sep_when_empty=(
                c.get("omit_sep_when_empty", True)
                if isinstance(c, dict)
                else c.omit_sep_when_empty
            ),
            enabled=c.get("enabled", True) if isinstance(c, dict) else c.enabled,
            max_line_chars=(
                c.get("max_line_chars") if isinstance(c, dict) else c.max_line_chars
            ),
            next_component_position=(
                c.get("next_component_position", "end_of_text")
                if isinstance(c, dict)
                else c.next_component_position
            ),
            balance_lines=(
                c.get("balance_lines", False)
                if isinstance(c, dict)
                else c.balance_lines
            ),
        )
        for c in raw_components
    ]
    return ExportConfig(
        currency_symbol=cfg.get("currency_symbol", DEFAULT_CONFIG.currency_symbol),
        section_style=cfg.get("section_style", DEFAULT_CONFIG.section_style),
        entry_style=cfg.get("entry_style", DEFAULT_CONFIG.entry_style),
        edition_prefix=cfg.get("edition_prefix", DEFAULT_CONFIG.edition_prefix),
        edition_brackets=cfg.get("edition_brackets", DEFAULT_CONFIG.edition_brackets),
        cat_no_style=cfg.get("cat_no_style", DEFAULT_CONFIG.cat_no_style),
        artist_style=cfg.get("artist_style", DEFAULT_CONFIG.artist_style),
        honorifics_style=cfg.get("honorifics_style", DEFAULT_CONFIG.honorifics_style),
        honorifics_lowercase=cfg.get(
            "honorifics_lowercase", DEFAULT_CONFIG.honorifics_lowercase
        ),
        title_style=cfg.get("title_style", DEFAULT_CONFIG.title_style),
        price_style=cfg.get("price_style", DEFAULT_CONFIG.price_style),
        medium_style=cfg.get("medium_style", DEFAULT_CONFIG.medium_style),
        artwork_style=cfg.get("artwork_style", DEFAULT_CONFIG.artwork_style),
        thousands_separator=cfg.get(
            "thousands_separator", DEFAULT_CONFIG.thousands_separator
        ),
        decimal_places=cfg.get("decimal_places", DEFAULT_CONFIG.decimal_places),
        leading_separator=cfg.get(
            "leading_separator", DEFAULT_CONFIG.leading_separator
        ),
        trailing_separator=cfg.get(
            "trailing_separator", DEFAULT_CONFIG.trailing_separator
        ),
        final_sep_from_last_component=cfg.get(
            "final_sep_from_last_component",
            DEFAULT_CONFIG.final_sep_from_last_component,
        ),
        components=components,
    )


# ---------------------------------------------------------------------------
# Export endpoints
# ---------------------------------------------------------------------------


@router.get("/imports/{import_id}/export-tags")
def export_indesign_tags(
    import_id: UUID,
    template_id: UUID | None = Query(None),
    db: Session = Depends(get_db),
):
    config = _ruleset_to_export_config(resolve_export_config(db, template_id))
    output = render_import_as_tagged_text(import_id, db, config)
    save_export_snapshot(import_id, template_id, db)
    return Response(
        content=escape_for_mac_roman(output).encode("mac_roman"),
        media_type="text/plain",
    )


@router.get("/imports/{import_id}/sections/{section_id}/export-tags")
def export_section_indesign_tags(
    import_id: UUID,
    section_id: UUID,
    template_id: UUID | None = Query(None),
    db: Session = Depends(get_db),
):
    """Export InDesign Tagged Text for a single section only."""
    config = _ruleset_to_export_config(resolve_export_config(db, template_id))
    output = render_import_as_tagged_text(import_id, db, config, section_id=section_id)
    # Section-level exports don't snapshot (full-import only)
    return Response(
        content=escape_for_mac_roman(output).encode("mac_roman"),
        media_type="text/plain",
    )


@router.get("/imports/{import_id}/export-json")
def export_json(import_id: UUID, db: Session = Depends(get_db)):
    output = render_import_as_json(import_id, db)
    save_export_snapshot(import_id, None, db)
    return Response(content=output, media_type="application/json")


@router.get("/imports/{import_id}/export-xml")
def export_xml(import_id: UUID, db: Session = Depends(get_db)):
    output = render_import_as_xml(import_id, db)
    save_export_snapshot(import_id, None, db)
    return Response(content=output, media_type="application/xml")


@router.get("/imports/{import_id}/export-csv")
def export_csv(import_id: UUID, db: Session = Depends(get_db)):
    output = render_import_as_csv(import_id, db)
    save_export_snapshot(import_id, None, db)
    return Response(content=output, media_type="text/csv")


# ---------------------------------------------------------------------------
# Export diff
# ---------------------------------------------------------------------------


@router.get("/imports/{import_id}/export-diff")
def get_export_diff(
    import_id: UUID,
    template_id: UUID | None = Query(None),
    db: Session = Depends(get_db),
):
    """Compare current export data against the last exported snapshot."""
    return compute_diff(import_id, template_id, db)

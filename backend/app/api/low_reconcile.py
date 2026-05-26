"""LOW → LPG reconciliation routes.

Diff a corrected InDesign List of Works export against the current database
(the source of truth) to surface data changes made downstream in InDesign, so
they can be carried into the Large Print Guide.

MVP / detection only: this endpoint parses an uploaded corrected-LOW Tagged Text
file and returns classified disparities. It does **not** persist anything or
apply changes. See ``docs/low-tag-reimport-diff-roadmap.md``.
"""

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.api.auth import require_role
from backend.app.api.low_exports import _ruleset_to_export_config
from backend.app.models.import_model import Import
from backend.app.services.export_renderer import (
    _collect_export_data,
    resolve_export_config,
)
from backend.app.services.low_tag_parser import parse_low_tags
from backend.app.services.low_diff import diff_low

router = APIRouter(tags=["reconcile"])


@router.post(
    "/imports/{import_id}/low-tag-diff",
    dependencies=[Depends(require_role("editor"))],
)
def low_tag_diff(
    import_id: UUID,
    file: UploadFile = File(...),
    template_id: UUID | None = Query(
        None, description="The export template that produced the LOW file."
    ),
    encoding: str = Query(
        "mac_roman", description="File encoding (mac_roman for our exports)."
    ),
    db: Session = Depends(get_db),
):
    """Parse an uploaded corrected LOW Tagged Text file and diff it against the
    import's current resolved data. Returns classified, significance-tiered
    findings (detection only — nothing is persisted or applied).

    ``template_id`` should be the export template that produced the LOW file: it
    supplies the character-style allowlist and component order the parser needs.
    Omit it to use the default config.
    """
    import_record = db.query(Import).filter(Import.id == import_id).first()
    if not import_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Import not found"
        )

    raw = file.file.read()
    try:
        text = raw.decode(encoding)
    except (UnicodeDecodeError, LookupError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not decode the uploaded file as {encoding!r}: {exc}",
        )

    config = _ruleset_to_export_config(resolve_export_config(db, template_id))
    parsed = parse_low_tags(text, config)
    collected = _collect_export_data(import_id, db)
    result = diff_low(parsed, collected, config)

    # Diagnostic guard: if far fewer entries parsed than the import contains, the
    # template/tag dialect probably doesn't match the file. Surface it loudly
    # rather than silently reporting a diff full of false "removed" findings.
    db_entries = sum(len(s["works"]) for s in collected)
    warnings: list[str] = []
    if parsed and db_entries and len(parsed) < db_entries * 0.5:
        warnings.append(
            f"Only {len(parsed)} of {db_entries} entries parsed — the chosen "
            f"template's paragraph/character styles may not match this file."
        )
    if not parsed:
        warnings.append(
            "No entries parsed. Check that template_id matches the export "
            "template that produced this file, and that the file is InDesign "
            "Tagged Text (<pstyle:>/<cstyle:> or <ParaStyle:>/<CharStyle:>)."
        )

    return {
        "import_id": str(import_id),
        "template_id": str(template_id) if template_id else None,
        "filename": file.filename,
        "parsed_entries": len(parsed),
        "db_entries": db_entries,
        "warnings": warnings,
        "section_alignment": result.section_alignment,
        "counts": result.counts,
        "findings": [asdict(f) for f in result.findings],
    }

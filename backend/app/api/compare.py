"""
Cross-dataset comparison routes.

Provides a single endpoint to compare a List of Works import against an
Artists' Index import by catalogue number.  The comparison is purely
read-only and uses resolved (post-override) values.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from backend.app.api.deps import get_db
from backend.app.api.schemas import (
    ComparisonEntryOut,
    ComparisonResultOut,
    ComparisonSummaryOut,
)
from backend.app.models.import_model import Import
from backend.app.services.comparison_service import compare_datasets

router = APIRouter(tags=["compare"])


@router.post(
    "/compare",
    response_model=ComparisonResultOut,
    summary="Compare LoW and Index datasets by catalogue number",
)
def compare_imports(
    low_import_id: UUID,
    index_import_id: UUID,
    db: Session = Depends(get_db),
):
    """Compare a List of Works import against an Artists' Index import.

    Keyed by catalogue number, returns a structured report showing:
    - catalogue numbers present in one dataset but not the other
    - name matches / mismatches for shared catalogue numbers
    - match level classification (exact, equivalent, partial, none)

    Uses resolved values (after overrides) from both datasets.
    """
    # Validate LoW import exists and is correct type
    low_import = db.query(Import).filter(Import.id == low_import_id).first()
    if not low_import:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"List of Works import {low_import_id} not found",
        )
    if low_import.product_type != "list_of_works":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Import {low_import_id} is not a list_of_works (got {low_import.product_type})",
        )

    # Validate Index import exists and is correct type
    idx_import = db.query(Import).filter(Import.id == index_import_id).first()
    if not idx_import:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artists' Index import {index_import_id} not found",
        )
    if idx_import.product_type != "artists_index":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Import {index_import_id} is not an artists_index (got {idx_import.product_type})",
        )

    result = compare_datasets(db, low_import_id, index_import_id)

    return ComparisonResultOut(
        low_import_id=result.low_import_id,
        index_import_id=result.index_import_id,
        summary=ComparisonSummaryOut(
            total_low=result.summary.total_low,
            total_index=result.summary.total_index,
            in_both=result.summary.in_both,
            only_in_low=result.summary.only_in_low,
            only_in_index=result.summary.only_in_index,
            match_exact=result.summary.match_exact,
            match_equivalent=result.summary.match_equivalent,
            match_partial_title=result.summary.match_partial_title,
            match_partial_honorific=result.summary.match_partial_honorific,
            match_partial_ra=result.summary.match_partial_ra,
            match_partial_name=result.summary.match_partial_name,
            match_none=result.summary.match_none,
        ),
        entries=[
            ComparisonEntryOut(
                cat_no=e.cat_no,
                low_artist_name=e.low_artist_name,
                low_artist_honorifics=e.low_artist_honorifics,
                low_work_id=e.low_work_id,
                index_name=e.index_name,
                index_first_name=e.index_first_name,
                index_last_name=e.index_last_name,
                index_title=e.index_title,
                index_quals=e.index_quals,
                index_is_company=e.index_is_company,
                index_artist_id=e.index_artist_id,
                index_courtesy=e.index_courtesy,
                match_level=e.match_level.value,
                differences=e.differences,
            )
            for e in result.entries
        ],
    )

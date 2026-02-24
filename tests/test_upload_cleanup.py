"""
Tests for upload file management: disk_filename tracking, file cleanup on
delete, and the orphan cleanup endpoint.
"""

import os
import uuid as _uuid

import pytest
from sqlalchemy.orm import Session

from backend.app.services.storage import storage
from backend.app.models.import_model import Import


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_import(
    db: Session,
    *,
    filename: str = "test.xlsx",
    disk_filename: str | None = None,
) -> Import:
    rec = Import(filename=filename, disk_filename=disk_filename)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def _create_upload_file(name: str, content: bytes = b"fake xlsx") -> str:
    """Write a fake file into storage and return the key."""
    storage.save(name, content)
    return name


# ---------------------------------------------------------------------------
# Delete removes file from disk
# ---------------------------------------------------------------------------


class TestDeleteCleansUpFile:
    def test_delete_removes_disk_file(self, client, db_session):
        disk_name = f"{_uuid.uuid4().hex}_sample.xlsx"
        _create_upload_file(disk_name)
        imp = _seed_import(db_session, disk_filename=disk_name)

        assert storage.exists(disk_name)

        r = client.delete(f"/imports/{imp.id}")
        assert r.status_code == 204
        assert not storage.exists(disk_name), "File should have been removed"

    def test_delete_works_when_file_already_gone(self, client, db_session):
        """Should not error if file was manually removed."""
        disk_name = f"{_uuid.uuid4().hex}_ghost.xlsx"
        imp = _seed_import(db_session, disk_filename=disk_name)

        r = client.delete(f"/imports/{imp.id}")
        assert r.status_code == 204

    def test_delete_works_when_disk_filename_is_null(self, client, db_session):
        """Legacy imports without disk_filename should delete cleanly."""
        imp = _seed_import(db_session, disk_filename=None)
        r = client.delete(f"/imports/{imp.id}")
        assert r.status_code == 204


# ---------------------------------------------------------------------------
# Orphan cleanup endpoint
# ---------------------------------------------------------------------------


class TestCleanupUploads:
    def test_cleanup_removes_orphans(self, client, db_session):
        # Create a referenced file
        ref_name = f"{_uuid.uuid4().hex}_ref.xlsx"
        _create_upload_file(ref_name)
        _seed_import(db_session, disk_filename=ref_name)

        # Create an orphan file (no DB record)
        orphan_name = f"{_uuid.uuid4().hex}_orphan.xlsx"
        _create_upload_file(orphan_name)

        r = client.post("/admin/cleanup-uploads")
        assert r.status_code == 200
        data = r.json()

        assert orphan_name in data["files_removed"]
        assert not storage.exists(orphan_name)
        # Referenced file should still exist
        assert storage.exists(ref_name)

        # Tidy up
        storage.delete(ref_name)

    def test_cleanup_empty_dir(self, client, db_session):
        """Endpoint responds even if nothing is ours to clean."""
        r = client.post("/admin/cleanup-uploads")
        assert r.status_code == 200
        data = r.json()
        # Just verify the shape — other tests may have left files
        assert "removed" in data
        assert "kept" in data

    def test_cleanup_preserves_gitkeep(self, client, db_session):
        # Ensure .gitkeep exists (only relevant for local backend)
        if hasattr(storage, "base_dir"):
            import os

            gitkeep = os.path.join(str(storage.base_dir), ".gitkeep")
            os.makedirs(str(storage.base_dir), exist_ok=True)
            if not os.path.isfile(gitkeep):
                open(gitkeep, "w").close()

        # Create an orphan
        orphan = f"{_uuid.uuid4().hex}_junk.xlsx"
        _create_upload_file(orphan)

        r = client.post("/admin/cleanup-uploads")
        data = r.json()

        if hasattr(storage, "base_dir"):
            assert os.path.isfile(gitkeep), ".gitkeep should be preserved"
        assert data["removed"] >= 1

        # Tidy up
        storage.delete(orphan)

    def test_cleanup_multiple_orphans(self, client, db_session):
        names = [f"{_uuid.uuid4().hex}_o{i}.xlsx" for i in range(5)]
        for n in names:
            _create_upload_file(n)

        r = client.post("/admin/cleanup-uploads")
        data = r.json()
        assert data["removed"] == 5
        assert data["kept"] == 0

        for n in names:
            assert not storage.exists(n)

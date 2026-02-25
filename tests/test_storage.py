"""Unit tests for the pluggable storage backend."""

import os
import tempfile

import pytest

from backend.app.services.storage import LocalStorage


@pytest.fixture
def local_store(tmp_path):
    """Return a LocalStorage backed by a pytest tmp directory."""
    return LocalStorage(base_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# LocalStorage basics
# ---------------------------------------------------------------------------


class TestLocalStorageSaveLoad:
    def test_save_bytes_and_load(self, local_store):
        local_store.save("test.xlsx", b"hello world")
        assert local_store.load("test.xlsx") == b"hello world"

    def test_save_file_like_and_load(self, local_store):
        import io

        buf = io.BytesIO(b"stream content")
        local_store.save("stream.xlsx", buf)
        assert local_store.load("stream.xlsx") == b"stream content"

    def test_save_creates_directory(self):
        target = tempfile.mkdtemp()
        nested = os.path.join(target, "sub", "dir")
        store = LocalStorage(base_dir=nested)
        store.save("f.bin", b"data")
        assert store.exists("f.bin")

    def test_save_returns_key(self, local_store):
        key = local_store.save("my_file.xlsx", b"data")
        assert key == "my_file.xlsx"


class TestLocalStorageDelete:
    def test_delete_existing(self, local_store):
        local_store.save("gone.xlsx", b"bye")
        assert local_store.delete("gone.xlsx") is True
        assert not local_store.exists("gone.xlsx")

    def test_delete_missing(self, local_store):
        assert local_store.delete("no_such_file.xlsx") is False


class TestLocalStorageExists:
    def test_exists_true(self, local_store):
        local_store.save("present.xlsx", b"data")
        assert local_store.exists("present.xlsx") is True

    def test_exists_false(self, local_store):
        assert local_store.exists("absent.xlsx") is False


class TestLocalStorageListKeys:
    def test_empty_directory(self, local_store):
        assert local_store.list_keys() == []

    def test_lists_saved_files(self, local_store):
        local_store.save("a.xlsx", b"1")
        local_store.save("b.xlsx", b"2")
        keys = sorted(local_store.list_keys())
        assert keys == ["a.xlsx", "b.xlsx"]

    def test_excludes_gitkeep(self, local_store):
        local_store.save(".gitkeep", b"")
        local_store.save("real.xlsx", b"data")
        assert local_store.list_keys() == ["real.xlsx"]

    def test_nonexistent_directory(self):
        store = LocalStorage(base_dir="/tmp/definitely_does_not_exist_xyz")
        assert store.list_keys() == []


class TestLocalStorageSize:
    def test_size(self, local_store):
        local_store.save("sized.xlsx", b"12345")
        assert local_store.size("sized.xlsx") == 5


class TestLocalStorageStats:
    def test_stats_empty(self, local_store):
        s = local_store.stats()
        assert s["uploads_count"] == 0
        assert s["uploads_size_mb"] == 0.0

    def test_stats_with_files(self, local_store):
        local_store.save("a.bin", b"x" * 1000)
        local_store.save("b.bin", b"y" * 2000)
        s = local_store.stats()
        assert s["uploads_count"] == 2
        assert s["uploads_size_mb"] == round(3000 / (1024**2), 2)


class TestLocalStorageOpenPath:
    def test_open_path_yields_valid_file(self, local_store):
        local_store.save("test.xlsx", b"data")
        with local_store.open_path("test.xlsx") as fp:
            assert os.path.isfile(fp)
            assert fp.endswith("test.xlsx")
        # File still exists after context exit (LocalStorage doesn't clean up)
        assert os.path.isfile(fp)

    def test_open_path_content_readable(self, local_store):
        local_store.save("test.xlsx", b"hello world")
        with local_store.open_path("test.xlsx") as fp:
            with open(fp, "rb") as f:
                assert f.read() == b"hello world"


class TestLocalStoragePathTraversal:
    def test_traversal_is_stripped(self, local_store):
        """Keys with path components should be sanitised to basename only."""
        local_store.save("../../etc/passwd", b"evil")
        # Both the save and the lookup strip to basename, so
        # the file ends up as "passwd" in the base directory.
        assert local_store.exists("passwd")
        # Crucially, nothing was written outside the base dir.
        with local_store.open_path("../../etc/passwd") as fp1:
            with local_store.open_path("passwd") as fp2:
                assert fp1 == fp2

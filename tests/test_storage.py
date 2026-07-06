import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import storage
from services.materials import MaterialService


class RecordingLock:
    def __init__(self):
        self.events = []

    def __enter__(self):
        self.events.append("enter")

    def __exit__(self, exc_type, exc, tb):
        self.events.append("exit")


class StorageTests(unittest.TestCase):
    def test_save_json_serializes_writes_with_shared_lock(self):
        lock = RecordingLock()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.json"

            with patch.object(storage, "_json_write_lock", lock):
                self.assertTrue(storage.save_json(str(path), {"ok": True}))

            self.assertEqual(lock.events, ["enter", "exit"])

    def test_material_index_uses_shared_json_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            service = MaterialService(
                root_dir=tmp_path,
                upload_dir=tmp_path / "uploads",
                local_pdf_dir=tmp_path / "pdf",
                index_path=tmp_path / "materials_index.json",
                cache_dir=tmp_path / "material_cache",
            )

            with patch("services.materials.save_json", return_value=True) as mocked_save:
                service._save_index({"client-1": []})

            mocked_save.assert_called_once_with(service.index_path, {"client-1": []})


if __name__ == "__main__":
    unittest.main()

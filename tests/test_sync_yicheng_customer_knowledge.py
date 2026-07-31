import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync_yicheng_customer_knowledge.py"


class SyncYichengCustomerKnowledgeTests(unittest.TestCase):
    def test_apply_copies_hefei_customer_knowledge_to_other_yicheng_clients(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            (data_dir / "knowledge_base" / "source").mkdir(parents=True)
            (data_dir / "knowledge_base" / "target").mkdir(parents=True)
            (data_dir / "clients.json").write_text(json.dumps([
                {"id": "source", "name": "合肥翼程教育"},
                {"id": "target", "name": "芜湖翼程教育"},
                {"id": "other", "name": "其他客户"},
            ], ensure_ascii=False), encoding="utf-8")
            (data_dir / "knowledge_base" / "source" / "customer_master.md").write_text("# 合肥资料", encoding="utf-8")
            (data_dir / "knowledge_base" / "source" / "customer_state.json").write_text('{"edited_at":"now"}', encoding="utf-8")
            (data_dir / "knowledge_base" / "target" / "customer_master.md").write_text("# 旧资料", encoding="utf-8")
            (data_dir / "knowledge_base" / "target" / "customer_state.json").write_text('{"old":true}', encoding="utf-8")

            result = subprocess.run(
                [sys.executable, "-X", "utf8", str(SCRIPT), "--data-dir", str(data_dir), "--apply", "--yes"],
                cwd=ROOT, text=True, capture_output=True, check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("# 合肥资料", (data_dir / "knowledge_base" / "target" / "customer_master.md").read_text(encoding="utf-8"))
            self.assertEqual('{"edited_at":"now"}', (data_dir / "knowledge_base" / "target" / "customer_state.json").read_text(encoding="utf-8"))
            self.assertIn("同步完成", result.stdout)
            self.assertTrue(list((data_dir / "knowledge_base").glob("_manual_backup_yicheng_*")))


if __name__ == "__main__":
    unittest.main()

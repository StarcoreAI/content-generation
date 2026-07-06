import unittest
import json
import tempfile
from unittest.mock import patch
from pathlib import Path
from subprocess import CompletedProcess

from services.node_crawler_bridge import (
    default_node_crawler_root,
    normalize_node_payload,
    parse_node_markdown,
    prepare_storage_state_for_node,
    run_node_crawler,
)


class NodeCrawlerBridgeTests(unittest.TestCase):
    def test_default_node_crawler_root_points_to_real_sibling_project(self):
        root = default_node_crawler_root(Path(__file__).resolve().parents[1])
        self.assertEqual(root.name, "ai-search-crawler（进阶API处理）")
        self.assertTrue((root / "src" / "index.js").exists())

    def test_parse_node_markdown_result_with_current_chinese_headings(self):
        markdown = """# Crawl Result - qwen

- Platform: `qwen`
- Total Queries: `1`
- Workers: `1`

## 1. 上海面部提升医生怎么选？

- Crawled At: `2026-07-01T12:00:00.000Z`

### 主问题回答

回答正文第一段。
回答正文第二段。

### 追问回答

(empty)

### 参考来源

1. 上海面部提升医生选择指南
   https://www.sohu.com/a/123
"""
        result = parse_node_markdown(markdown, citations_limit=10)
        self.assertTrue(result["ok"])
        self.assertEqual(result["platform"], "qwen")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["results"][0]["question"], "上海面部提升医生怎么选？")
        self.assertIn("回答正文第二段", result["results"][0]["answer"])
        self.assertEqual(result["results"][0]["refs"][0]["platform"], "搜狐")

    def test_parse_node_markdown_result(self):
        markdown = """# Crawl Result - doubao

- Platform: `doubao`
- Total Queries: `2`
- Workers: `1`

## 1. 上海面部提升医生怎么选？

- Crawled At: `2026-07-01T12:00:00.000Z`

### 主问题回答

回答正文第一段。

回答正文第二段。

### 追问回答

(empty)

### 参考来源

1. 上海面部提升医生选择指南
   https://www.toutiao.com/article/123
2. 医美医生面诊注意事项
   https://www.sohu.com/a/456

## 2. 没有引用的问题

- Crawled At: `2026-07-01T12:01:00.000Z`

### 主问题回答

第二个回答。

### 追问回答

(empty)

### 参考来源

(empty)
"""
        result = parse_node_markdown(markdown, citations_limit=10)
        self.assertTrue(result["ok"])
        self.assertEqual(result["platform"], "doubao")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["success"], 2)
        self.assertEqual(result["results"][0]["question"], "上海面部提升医生怎么选？")
        self.assertIn("回答正文第二段", result["results"][0]["answer"])
        self.assertEqual(len(result["results"][0]["refs"]), 2)
        self.assertEqual(result["results"][0]["refs"][0]["platform"], "今日头条")
        self.assertEqual(result["results"][1]["refs"], [])

    def test_normalize_future_json_payload(self):
        payload = {
            "platform": "qwen",
            "items": [
                {
                    "query": "问题A",
                    "answer": "回答A",
                    "citations": [
                        {"title": "搜狐文章", "url": "https://www.sohu.com/a/1"}
                    ],
                }
            ],
        }
        result = normalize_node_payload(payload)
        self.assertEqual(result["platform"], "qwen")
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["results"][0]["question"], "问题A")
        self.assertEqual(result["results"][0]["refs"][0]["platform"], "搜狐")

    def test_prepare_storage_state_wraps_legacy_cookies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir()
            cookie_path = data_dir / "doubao_cookies.json"
            cookie_path.write_text(
                json.dumps([
                    {"name": "session", "value": "abc", "domain": ".doubao.com", "path": "/"}
                ]),
                encoding="utf-8",
            )

            work_dir = root / "work"
            work_dir.mkdir()
            state_path = prepare_storage_state_for_node("doubao", work_dir, project_root=root)
            self.assertTrue(state_path)
            payload = json.loads(Path(state_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["cookies"][0]["name"], "session")
            self.assertEqual(payload["origins"], [])

    def test_run_node_crawler_preserves_output_dir_and_disables_followup_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crawler_root = root / "crawler"
            (crawler_root / "src").mkdir(parents=True)
            (crawler_root / "src" / "index.js").write_text("// test entry", encoding="utf-8")
            output_dir = root / "node-output"
            captured = {}

            def fake_subprocess_run(cmd, **kwargs):
                captured["cmd"] = cmd
                captured["env"] = kwargs["env"]
                out = Path(kwargs["env"]["OUTPUT_DIR"])
                out.mkdir(parents=True, exist_ok=True)
                (out / "qwen-test.md").write_text(
                    """# Crawl Result - qwen

- Platform: `qwen`

## 1. 测试问题

### 主问题回答

测试回答

### 参考来源

(empty)
""",
                    encoding="utf-8",
                )
                return CompletedProcess(cmd, 0, stdout="node stdout", stderr="node stderr")

            with patch("services.node_crawler_bridge.subprocess.run", side_effect=fake_subprocess_run):
                result = run_node_crawler(
                    "qwen",
                    ["测试问题"],
                    crawler_root=crawler_root,
                    output_dir=output_dir,
                )

            self.assertEqual(result["success"], 1)
            self.assertEqual(captured["env"]["OUTPUT_DIR"], str(output_dir))
            self.assertEqual(captured["env"]["GEO_NODE_BRIDGE"], "1")
            self.assertEqual(captured["env"]["FOLLOWUP_API_ENABLED"], "false")
            self.assertNotIn("GEO_NODE_NEW_PAGE_PER_QUERY", captured["env"])
            self.assertEqual(captured["env"]["GEO_NODE_NEW_CONVERSATION_EVERY"], "1")
            self.assertTrue((output_dir / "qwen-test.md").exists())
            self.assertEqual((output_dir / "node-stdout.log").read_text(encoding="utf-8"), "node stdout")
            self.assertEqual((output_dir / "node-stderr.log").read_text(encoding="utf-8"), "node stderr")

    def test_run_node_crawler_passes_all_questions_to_one_node_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crawler_root = root / "crawler"
            (crawler_root / "src").mkdir(parents=True)
            (crawler_root / "src" / "index.js").write_text("// test entry", encoding="utf-8")
            output_dir = root / "node-output"
            query_batches = []

            def fake_subprocess_run(cmd, **kwargs):
                query_file = Path(cmd[cmd.index("--query-file") + 1])
                queries = query_file.read_text(encoding="utf-8").splitlines()
                query_batches.append(queries)
                out = Path(kwargs["env"]["OUTPUT_DIR"])
                out.mkdir(parents=True, exist_ok=True)
                blocks = []
                for index, query in enumerate(queries, start=1):
                    blocks.append(
                        f"""## {index}. {query}

### 主问题回答

回答 {index}

### 参考来源

(empty)
"""
                    )
                (out / "qwen-test.md").write_text(
                    """# Crawl Result - qwen

- Platform: `qwen`

""" + "\n".join(blocks),
                    encoding="utf-8",
                )
                return CompletedProcess(cmd, 0, stdout=f"stdout {len(query_batches)}", stderr="")

            with patch("services.node_crawler_bridge.subprocess.run", side_effect=fake_subprocess_run):
                result = run_node_crawler(
                    "qwen",
                    ["问题A", "问题B"],
                    crawler_root=crawler_root,
                    output_dir=output_dir,
                )

            self.assertEqual(query_batches, [["问题A", "问题B"]])
            self.assertEqual(result["total"], 2)
            self.assertEqual(result["success"], 2)
            self.assertEqual([item["question"] for item in result["results"]], ["问题A", "问题B"])


if __name__ == "__main__":
    unittest.main()

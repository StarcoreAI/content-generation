import os
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import app as geo_app
from services.auth import create_user


@contextmanager
def isolated_app():
    original = {key: getattr(geo_app, key) for key in ["D", "F_CLIENTS", "F_GROUPS", "F_RAW_RECORDS", "F_USERS"]}
    original_auth = geo_app.app.config.get("AUTH_DISABLED")
    with tempfile.TemporaryDirectory() as tmp:
        geo_app.D = tmp
        geo_app.F_CLIENTS = os.path.join(tmp, "clients.json")
        geo_app.F_GROUPS = os.path.join(tmp, "probe_groups.json")
        geo_app.F_RAW_RECORDS = os.path.join(tmp, "raw_records.json")
        geo_app.F_USERS = os.path.join(tmp, "users.json")
        geo_app.app.config["AUTH_DISABLED"] = False
        try:
            yield
        finally:
            for key, value in original.items():
                setattr(geo_app, key, value)
            if original_auth is None:
                geo_app.app.config.pop("AUTH_DISABLED", None)
            else:
                geo_app.app.config["AUTH_DISABLED"] = original_auth


class SelectionEvidenceApiTests(unittest.TestCase):
    def test_refresh_and_read_are_client_isolated(self):
        with isolated_app():
            create_user(geo_app.F_USERS, "alice", "secret-pass", role="operator")
            create_user(geo_app.F_USERS, "bob", "secret-pass", role="operator")
            geo_app.save(geo_app.F_CLIENTS, [
                {"id": "alice-client", "owner_username": "alice"},
                {"id": "bob-client", "owner_username": "bob"},
            ])
            geo_app.save(geo_app.F_GROUPS, {
                "alice-client": [{"id": "group-1", "name": "问题组甲", "questions": ["评职称怎么提升学历？"]}],
            })
            geo_app.save(geo_app.F_RAW_RECORDS, [{
                "client_id": "alice-client", "group_id": "group-1", "question": "评职称怎么提升学历？",
                "today": "2026-07-26",
                "refs": [
                    {"title": "学历提升文章甲", "url": "https://example.com/a"},
                    {"title": "学历提升文章乙", "url": "https://example.com/b"},
                    {"title": "学历提升文章丙", "url": "https://example.com/c"},
                ],
            }])

            alice = geo_app.app.test_client()
            self.assertEqual(alice.post("/api/auth/login", json={"username": "alice", "password": "secret-pass"}).status_code, 200)
            with patch.object(geo_app, "fetch_article_text", return_value={
                "ok": True, "html": "<title>学历提升文章</title><meta name='description' content='评职称'><p>这是足够长的首段内容，用于提取具体场景词并测试接口返回。</p>",
            }), patch.object(geo_app, "ai_json", return_value={"items": [{
                "group_id": "group-1", "query": "评职称怎么提升学历？", "scene_terms": ["评职称"],
            }]}):
                refreshed = alice.post("/api/records/selection-evidence/alice-client/refresh")

            self.assertEqual(refreshed.status_code, 200)
            self.assertEqual(refreshed.get_json()["rows"][0]["scene_terms"], ["评职称"])
            self.assertEqual(refreshed.get_json()["source_date"], "2026-07-26")
            self.assertEqual(alice.get("/api/records/selection-evidence/alice-client").status_code, 200)

            bob = geo_app.app.test_client()
            self.assertEqual(bob.post("/api/auth/login", json={"username": "bob", "password": "secret-pass"}).status_code, 200)
            self.assertEqual(bob.get("/api/records/selection-evidence/alice-client").status_code, 404)
            self.assertEqual(bob.post("/api/records/selection-evidence/alice-client/refresh").status_code, 404)


if __name__ == "__main__":
    unittest.main()

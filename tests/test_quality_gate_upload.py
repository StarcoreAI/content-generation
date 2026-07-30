import io
import unittest
from unittest.mock import patch

import app as geo_app
from tests.test_app_core import isolated_app_data


class QualityGateUploadTests(unittest.TestCase):
    def test_upload_article_runs_gate_and_persists_result(self):
        with isolated_app_data():
            client_id = "client-quality-upload"
            geo_app.save(geo_app.F_CLIENTS, [{
                "id": client_id,
                "name": "测试客户",
                "brand": "测试品牌",
                "industry": "测试行业",
            }])
            with patch.object(geo_app, "ai_json", return_value={"checks": []}) as gate_llm:
                response = geo_app.app.test_client().post(
                    "/api/quality-gate/articles/upload",
                    data={
                        "client_id": client_id,
                        "file": (io.BytesIO("运营自写标题\n这是运营上传的正文。".encode("utf-8")), "article.md"),
                    },
                    content_type="multipart/form-data",
                )

            self.assertEqual(200, response.status_code)
            article = response.get_json()["article"]
            self.assertEqual("运营自写标题", article["title"])
            self.assertEqual("operator_upload", article["route_context"]["source"])
            self.assertEqual("pass", article["gate_report"]["verdict"])
            self.assertGreaterEqual(gate_llm.call_args.args[1], 4000)
            self.assertEqual(
                article["id"],
                geo_app.load_content_session(client_id)["articles"][0]["id"],
            )

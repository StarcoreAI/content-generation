import unittest
from unittest.mock import patch

from services.rwmeiti import RWMeitiClient, build_signature


class RWMeitiTests(unittest.TestCase):
    def test_signature_sorts_params_and_excludes_key_from_request(self):
        self.assertEqual(
            build_signature({"page": 1, "secret_id": "sid", "timestamp": 1700000000}, "secret"),
            "4CDC99B74D47CAB45834CEF536CEED1B",
        )

    @patch("services.rwmeiti.urlopen")
    def test_list_self_media_normalizes_provider_resource(self, mocked):
        mocked.return_value.__enter__.return_value.read.return_value = (
            '{"code":200,"data":[{"id":7,"wemedia_name":"账号A","price":"88","status":1}]}'.encode("utf-8")
        )
        client = RWMeitiClient("http://example.test", "sid", "secret")
        self.assertEqual(client.list_self_media(1, 200)[0]["resource_id"], "7")

    @patch("services.rwmeiti.urlopen")
    def test_create_and_query_self_media_orders(self, mocked):
        mocked.return_value.__enter__.return_value.read.side_effect = [
            b'{"code":200,"msg":"success","price":"88"}',
            b'{"code":200,"data":[{"status":2,"no3":"geo-1","url":"https://example.com/a"}]}',
        ]
        client = RWMeitiClient("http://example.test", "sid", "secret")
        self.assertEqual(client.create_self_media_order("标题", "内容", "7", "geo-1", 88)["price"], "88")
        self.assertEqual(client.query_self_media_orders(["geo-1"])[0]["url"], "https://example.com/a")


if __name__ == "__main__":
    unittest.main()

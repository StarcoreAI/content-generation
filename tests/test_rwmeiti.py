import unittest
from http.client import RemoteDisconnected
from unittest.mock import MagicMock, patch

from services.rwmeiti import RWMeitiClient, build_signature


class RWMeitiTests(unittest.TestCase):
    @patch("services.rwmeiti.urlopen")
    def test_user_info_returns_provider_data(self, mocked):
        mocked.return_value.__enter__.return_value.read.return_value = b'{"code":200,"data":{"money":100}}'
        client = RWMeitiClient("http://example.test", "sid", "secret")
        self.assertEqual(client.get_user_info()["money"], 100)

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
    def test_list_self_media_can_request_one_resource_id(self, mocked):
        mocked.return_value.__enter__.return_value.read.return_value = b'{"code":200,"data":[]}'
        client = RWMeitiClient("http://example.test", "sid", "secret")

        client.list_self_media(1, 5, resource_id="7")

        request_body = mocked.call_args.args[0].data.decode("utf-8")
        self.assertIn("id=7", request_body)

    @patch("services.rwmeiti.urlopen")
    def test_list_news_media_normalizes_provider_resource(self, mocked):
        mocked.return_value.__enter__.return_value.read.return_value = (
            '{"code":200,"data":[{"id":8,"media_name":"媒体A","price":"99","status":1}]}'.encode("utf-8")
        )
        client = RWMeitiClient("http://example.test", "sid", "secret")

        resource = client.list_news_media(1, 200, resource_id="8")[0]

        self.assertEqual(resource["resource_id"], "8")
        self.assertEqual(resource["name"], "媒体A")
        self.assertEqual(resource["resource_type"], "news_media")
        self.assertIn("id=8", mocked.call_args.args[0].data.decode("utf-8"))

    @patch("services.rwmeiti.urlopen")
    def test_create_news_media_order_uses_news_endpoint(self, mocked):
        mocked.return_value.__enter__.return_value.read.return_value = b'{"code":200}'
        client = RWMeitiClient("http://example.test", "sid", "secret")

        client.create_news_media_order("标题", "<p>正文</p>", "1364", "geo-1", 99)

        request = mocked.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/create_media_order"))
        self.assertIn("mid=1364", request.data.decode("utf-8"))

    @patch("services.rwmeiti.urlopen")
    def test_list_self_media_retries_a_transient_disconnect(self, mocked):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"code":200,"data":[]}'
        mocked.side_effect = [RemoteDisconnected("closed"), response]
        client = RWMeitiClient("http://example.test", "sid", "secret")
        self.assertEqual(client.list_self_media(1, 200), [])
        self.assertEqual(mocked.call_count, 2)

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

import hashlib
import json
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def build_signature(params, secret_key):
    pairs = [
        f"{key}={params[key]}" for key in sorted(params)
        if key != "signature" and params[key] not in ("", None)
    ]
    raw = "&".join(pairs) + f"&key={secret_key}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()


class RWMeitiClient:
    def __init__(self, base_url, secret_id, secret_key):
        self.base_url = str(base_url).rstrip("/")
        self.secret_id = str(secret_id)
        self.secret_key = str(secret_key)

    def list_self_media(self, page=1, limit=200):
        payload = self._post_form("wmedia_lst", {"page": page, "limit": limit})
        if payload.get("code") != 200:
            raise ValueError(str(payload.get("msg") or "rwmeiti_error"))
        return [
            {"resource_id": str(item.get("id") or ""), "name": str(item.get("wemedia_name") or ""),
             "price": float(item.get("price") or 0), "status": str(item.get("status") or ""), "raw": item}
            for item in (payload.get("data") or []) if item.get("id") is not None
        ]

    def create_self_media_order(self, title, content, mid, no, saling_price, account_rule=3):
        return self._post_form("create_wmedia_order", {
            "title": title, "content": content, "mid": mid, "no": no,
            "saling_price": saling_price, "account_rule": account_rule,
        })

    def query_self_media_orders(self, order_numbers):
        payload = self._post_form("query_wmedia_order", {"nostr": ",".join(order_numbers)})
        if payload.get("code") != 200:
            raise ValueError(str(payload.get("msg") or "rwmeiti_error"))
        return payload.get("data") or []

    def _post_form(self, path, params):
        signed = {**params, "secret_id": self.secret_id, "timestamp": int(time.time())}
        signed["signature"] = build_signature(signed, self.secret_key)
        request = Request(self.base_url + "/" + path, data=urlencode(signed).encode("utf-8"),
                          headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

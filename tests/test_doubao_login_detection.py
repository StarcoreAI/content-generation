import asyncio
import unittest

from doubao_crawler import check_logged_in


class _FakeElement:
    def __init__(self, visible=True, enabled=True):
        self._visible = visible
        self._enabled = enabled

    async def is_visible(self):
        return self._visible

    async def is_enabled(self):
        return self._enabled


class _FakePage:
    def __init__(self, url="https://www.doubao.com/chat/?from_login=1", body="", elements=None):
        self.url = url
        self._body = body
        self._elements = elements or {}

    async def evaluate(self, _script):
        return self._body

    async def query_selector(self, selector):
        return self._elements.get(selector)


class DoubaoLoginDetectionTests(unittest.TestCase):
    def test_logged_in_chat_accepts_contenteditable_input(self):
        page = _FakePage(
            body="豆包 对话 选择使用 Dola",
            elements={
                '[contenteditable="true"]': _FakeElement(),
            },
        )

        self.assertTrue(asyncio.run(check_logged_in(page)))


if __name__ == "__main__":
    unittest.main()

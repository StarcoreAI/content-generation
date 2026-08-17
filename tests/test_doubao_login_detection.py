import asyncio
import unittest
from unittest import mock

from doubao_crawler import check_logged_in, crawl_worker, goto_new_chat


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


class _FakeNewChatPage:
    def __init__(self):
        self.url = "https://www.doubao.com/chat/old-conversation"
        self.evaluate_scripts = []
        self.goto_calls = []
        self.input = _FakeElement()

    async def evaluate(self, script):
        self.evaluate_scripts.append(script)
        return True

    async def wait_for_timeout(self, _timeout):
        return None

    async def query_selector(self, selector):
        if selector == 'textarea[placeholder*="发消息"]':
            return self.input
        return None

    async def wait_for_selector(self, *_args, **_kwargs):
        return self.input

    async def goto(self, url, **_kwargs):
        self.goto_calls.append(url)


class _FakeCrawlerPage:
    def __init__(self, events):
        self.events = events

    async def goto(self, *_args, **_kwargs):
        self.events.append("goto")

    async def wait_for_timeout(self, _timeout):
        self.events.append("wait")


class _FakeContext:
    def __init__(self, page):
        self.page = page

    async def new_page(self):
        return self.page


class _FakeBrowser:
    def __init__(self, context, events):
        self.context = context
        self.events = events

    async def new_context(self, **_kwargs):
        return self.context

    async def close(self):
        self.events.append("close")


class _FakeChromium:
    def __init__(self, browser):
        self.browser = browser

    async def launch(self, **_kwargs):
        return self.browser


class _FakePlaywright:
    def __init__(self, browser):
        self.chromium = _FakeChromium(browser)


class DoubaoLoginDetectionTests(unittest.TestCase):
    def test_logged_in_chat_accepts_contenteditable_input(self):
        page = _FakePage(
            body="豆包 对话 选择使用 Dola",
            elements={
                '[contenteditable="true"]': _FakeElement(),
            },
        )

        self.assertTrue(asyncio.run(check_logged_in(page)))

    def test_new_chat_supports_new_sidebar_layout_without_requiring_url_change(self):
        page = _FakeNewChatPage()

        asyncio.run(goto_new_chat(page))

        self.assertEqual(page.goto_calls, [])
        self.assertIn("nav-link-", page.evaluate_scripts[0])
        self.assertIn("cursor-pointer", page.evaluate_scripts[0])

    def test_crawl_worker_waits_for_manual_login_before_closing_browser(self):
        events = []
        page = _FakeCrawlerPage(events)
        context = _FakeContext(page)
        browser = _FakeBrowser(context, events)
        playwright = _FakePlaywright(browser)
        login_states = iter([False, False, True])

        async def fake_check_logged_in(_page):
            events.append("check_login")
            return next(login_states)

        async def fake_save_cookies(_context):
            events.append("save_cookies")

        async def fake_save_storage_state(_context, platform, mark_ok=False):
            self.assertEqual(platform, "doubao")
            self.assertTrue(mark_ok)
            events.append("save_storage_state")

        with mock.patch("doubao_crawler.check_logged_in", side_effect=fake_check_logged_in), \
             mock.patch("doubao_crawler.load_cookies", new=mock.AsyncMock(return_value=False)), \
             mock.patch("doubao_crawler.save_cookies", side_effect=fake_save_cookies), \
             mock.patch("doubao_crawler.save_storage_state", side_effect=fake_save_storage_state):
            asyncio.run(crawl_worker(1, [], playwright, {}, asyncio.Lock()))

        self.assertEqual(events.count("check_login"), 3)
        self.assertIn("save_storage_state", events)
        self.assertLess(events.index("save_storage_state"), events.index("close"))


if __name__ == "__main__":
    unittest.main()

"""
qwen_crawler.py — 通义千问爬虫
实际运行域名：qianwen.com（会从tongyi.aliyun.com跳转）
已登录特征：左侧有「新建对话」按钮
"""
import asyncio
import json
import os
import re
import pathlib as _pl
from playwright.async_api import async_playwright
from base_crawler import (
    save_cookies, load_cookies, has_cookies,
    extract_platform, wait_for_captcha_if_needed,
    wait_until_stable, launch_browser_with_state, DATA_DIR,
    verify_saved_login
)

PLATFORM = "qwen"
QW_URL = "https://qianwen.com/"   # 实际域名（tongyi.aliyun.com会跳转到这里）


# ── 登录检测（唯一可靠方法：左侧「新建对话」按钮） ────────
async def check_logged_in(page) -> bool:
    """
    千问已登录判断：
    - 左侧边栏有「新建对话」按钮 = 已登录
    - URL 含 login/passport = 未登录
    - 不用 qwen-root class（实际页面URL是qianwen.com，class可能不同）
    """
    try:
        cur_url = page.url
        # 明确的登录页URL
        if any(kw in cur_url for kw in ["aliyun.com/login", "passport.aliyun",
                                          "auth.aliyun", "/signin", "login.htm"]):
            return False

        login_btn = await page.query_selector(
            'button:has-text("登录"), a:has-text("登录"), '
            'button:has-text("立即登录"), a:has-text("立即登录")'
        )
        if login_btn and await login_btn.is_visible():
            return False

        # 最可靠：「新建对话」按钮存在且可见
        new_chat = await page.query_selector(
            'button:has-text("新建对话"), '
            'a:has-text("新建对话"), '
            'span:has-text("新建对话"), '
            '[class*="new-conversation"], '
            '[class*="newConversation"], '
            '[class*="create-conversation"]'
        )
        if new_chat and await new_chat.is_visible():
            return True

        # 备用：用户头像/昵称
        user_el = await page.query_selector(
            '[class*="user-avatar"], [class*="avatar"], '
            '[class*="user-info"], [class*="userInfo"]'
        )
        if user_el and await user_el.is_visible():
            return True

        return False
    except:
        return False


# ── 开启新对话 ─────────────────────────────────────────────
async def goto_new_chat(page):
    try:
        for sel in [
            'button:has-text("新建对话")',
            'a:has-text("新建对话")',
            '[class*="new-conversation"]',
            '[class*="newConversation"]',
        ]:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                await page.wait_for_timeout(1500)
                # 等输入框就绪
                for _ in range(10):
                    inp = await find_input_box(page)
                    if inp and await inp.is_visible() and await inp.is_enabled():
                        return
                    await page.wait_for_timeout(500)
                return
        # 备用：直接导航
        await page.goto(QW_URL, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)
    except:
        pass


async def find_input_box(page):
    for sel in [
        'textarea[placeholder*="千问"]',
        'textarea[placeholder*="提问"]',
        'textarea[placeholder*="发送"]',
        'textarea',
        '[contenteditable="true"]',
        'div[role="textbox"]',
        '[data-testid*="chat-input"]',
        '[class*="chat-input"] [contenteditable="true"]',
        '[class*="input"] [contenteditable="true"]',
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible() and await el.is_enabled():
                return el
        except:
            pass
    return None


async def input_text_length(input_box):
    try:
        return await input_box.evaluate("""el => {
            if ('value' in el) return (el.value || '').length;
            return (el.innerText || el.textContent || '').trim().length;
        }""")
    except:
        return 0


async def click_send_if_needed(page, input_box):
    """Enter 有时只换行；如果输入框里仍有内容，再点一次发送按钮。"""
    if await input_text_length(input_box) == 0:
        return
    try:
        clicked = await page.evaluate("""() => {
            const candidates = [...document.querySelectorAll('button, div[role="button"]')];
            for (const el of candidates) {
                const text = (el.innerText || el.textContent || '').trim();
                const label = el.getAttribute('aria-label') || el.getAttribute('title') || '';
                const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
                if (!disabled && (text === '发送' || label.includes('发送') || label.toLowerCase().includes('send'))) {
                    el.click();
                    return true;
                }
            }
            return false;
        }""")
        if clicked:
            await page.wait_for_timeout(800)
    except:
        pass


# ── 等待生成完毕 ───────────────────────────────────────────
async def wait_until_done(page, timeout_s=120):
    """等千问生成完毕：内容稳定 + 输入框可用"""
    await page.wait_for_timeout(2000)
    last_len = 0
    stable = 0
    for _ in range(timeout_s * 2):
        await page.wait_for_timeout(500)
        try:
            cur_len = await page.evaluate("""() => {
                const els = document.querySelectorAll(
                    '[class*="markdown"], [class*="message-content"], [class*="answer"]'
                );
                let max = 0;
                for (const el of els) {
                    const t = (el.innerText || '').length;
                    if (t > max) max = t;
                }
                return max;
            }""")
            inp = await page.query_selector('textarea')
            inp_ok = inp and await inp.is_visible() and await inp.is_enabled()
            if inp_ok and cur_len > 50 and cur_len == last_len:
                stable += 1
                if stable >= 4:
                    return True
            else:
                stable = 0
                last_len = cur_len
        except:
            stable = 0
    return False


# ── 提取正文 ───────────────────────────────────────────────
async def get_answer(page):
    return await page.evaluate("""() => {
        const noise = ['向千问提问', '新建对话', '任务助理', '内容由AI生成'];
        function isNoise(t) { return noise.some(n => t.includes(n)); }
        const sels = [
            '[class*="markdown"]',
            '[class*="message-content"]',
            '[class*="answer-content"]',
            '[class*="response"]',
        ];
        for (const sel of sels) {
            const els = [...document.querySelectorAll(sel)];
            for (const el of els.reverse()) {
                const t = (el.innerText || '').trim();
                if (t.length >= 50 && !isNoise(t)) return t;
            }
        }
        return '';
    }""")


# ── 提取引用源 ─────────────────────────────────────────────
async def get_refs(page):
    """千问「参考来源（N）」面板，有序号+标题+来源域名"""
    refs = []
    try:
        raw = await page.evaluate("""() => {
            const results = [];
            const seen = new Set();
            // 千问引用直接在右侧面板，找所有外部链接
            const links = document.querySelectorAll('a[href^="http"]');
            for (const a of links) {
                const href = a.href || '';
                if (href.includes('qianwen.com') ||
                    href.includes('aliyun.com') ||
                    href.includes('tongyi')) continue;
                const title = (a.innerText || a.textContent || '').trim();
                if (!title || title.length < 5 || seen.has(href)) continue;
                seen.add(href);
                results.push({ title: title.slice(0, 120), href });
                if (results.length >= 15) break;
            }
            return results;
        }""")
        for i, item in enumerate(raw):
            refs.append({
                "title": item["title"],
                "url": item.get("href", ""),
                "platform": extract_platform(item.get("href", "")),
                "rank": i + 1,
            })
        print(f"  [千问] 引用源: {len(refs)}个")
    except Exception as e:
        print(f"  [千问] 引用提取异常: {e}")
    return refs


# ── 登录 ───────────────────────────────────────────────────
async def login_qwen_async():
    """打开浏览器让用户手动登录千问，自动检测成功后保存状态。"""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--window-position=0,0", "--window-size=1100,800",
                  "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            viewport={"width": 1100, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        try:
            await page.goto("https://tongyi.aliyun.com/qianwen",
                           wait_until="domcontentloaded", timeout=20000)
        except:
            await page.goto("https://qianwen.com/",
                           wait_until="domcontentloaded", timeout=20000)

        print("\n[千问] 浏览器已打开，请在窗口中完成登录（阿里云账号/手机扫码均可）")
        print("[千问] 程序自动检测，保存后会用新会话复验（最长等待5分钟）...")

        for _ in range(150):
            await page.wait_for_timeout(2000)
            if await check_logged_in(page):
                await page.wait_for_timeout(2000)
                await save_cookies(context, PLATFORM)
                verified = await verify_saved_login(
                    browser,
                    PLATFORM,
                    QW_URL,
                    check_logged_in,
                    viewport={"width": 1100, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )
                if verified:
                    print("[千问] 登录成功，状态已保存并复验通过")
                    await browser.close()
                    return True
                print("[千问] 检测到疑似登录，但新会话复验失败，请在窗口中继续完成登录")

        print("[千问] 登录超时（5分钟），请重试")
        await browser.close()
        return False


async def crawl_worker(worker_id, questions, pw, results_dict, lock):
    browser, context = await launch_browser_with_state(pw, PLATFORM, worker_id)
    page = await context.new_page()

    try:
        await page.goto("https://tongyi.aliyun.com/qianwen",
                       wait_until="domcontentloaded", timeout=20000)
    except:
        await page.goto("https://qianwen.com/",
                       wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(3000)

    if not await check_logged_in(page):
        await browser.close()
        async with lock:
            for idx, q in questions:
                results_dict[idx] = {"ok": False, "error": "need_login", "question": q}
        return
    print(f"  [QW Worker {worker_id}] 已登录，开始爬取 {len(questions)} 题")

    for i, (idx, question) in enumerate(questions):
        print(f"  [QW Worker {worker_id}] [{i+1}/{len(questions)}] #{idx} {question[:35]}...")
        await goto_new_chat(page)

        try:
            input_box = None
            for _ in range(16):
                input_box = await find_input_box(page)
                if input_box:
                    break
                await page.wait_for_timeout(500)

            if not input_box:
                page_hint = ""
                try:
                    page_hint = await page.evaluate("() => document.body.innerText.slice(0, 200)")
                except:
                    pass
                async with lock:
                    results_dict[idx] = {
                        "ok": False,
                        "error": "找不到输入框",
                        "question": question,
                        "url": page.url,
                        "page_hint": page_hint,
                    }
                continue

            await input_box.click()
            await page.wait_for_timeout(200)
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Delete")
            await input_box.fill(question)
            await page.wait_for_timeout(400)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(800)
            await click_send_if_needed(page, input_box)

            try:
                await wait_for_captcha_if_needed(page, worker_id, PLATFORM)
            except TimeoutError:
                async with lock:
                    results_dict[idx] = {"ok": False, "error": "人机验证超时", "question": question}
                continue

            print(f"  → [千问] 等待回答生成...")
            await wait_until_done(page, timeout_s=120)

            answer = await get_answer(page)
            print(f"  → [千问] 回答长度: {len(answer)} 字")
            if len(answer) < 50:
                async with lock:
                    results_dict[idx] = {
                        "ok": False,
                        "error": "回答为空或过短，可能未成功提交问题",
                        "question": question,
                        "url": page.url,
                    }
                continue

            refs = await get_refs(page)
            async with lock:
                results_dict[idx] = {"ok": True, "answer": answer, "refs": refs, "question": question}
            try:
                await save_cookies(context, PLATFORM)
            except:
                pass

        except Exception as e:
            async with lock:
                results_dict[idx] = {"ok": False, "error": str(e), "question": question}

    await save_cookies(context, PLATFORM)
    await browser.close()
    print(f"  [QW Worker {worker_id}] 完成")


# ── 批量爬取 ───────────────────────────────────────────────
async def crawl_batch_async(questions, parallel=2):
    os.makedirs(DATA_DIR, exist_ok=True)
    parallel = max(1, min(parallel, 3))
    indexed = [(i, q) for i, q in enumerate(questions)]
    chunks = [[] for _ in range(parallel)]
    for i, item in enumerate(indexed):
        chunks[i % parallel].append(item)
    chunks = [c for c in chunks if c]

    results_dict = {}
    lock = asyncio.Lock()
    async with async_playwright() as pw:
        tasks = [crawl_worker(i+1, chunk, pw, results_dict, lock)
                 for i, chunk in enumerate(chunks)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                print(f"  [QW Worker {i+1}] 异常退出: {r}")

    all_results = [
        results_dict.get(i, {"ok": False, "error": "未执行", "question": q})
        for i, q in indexed
    ]
    success = [r for r in all_results if r.get("ok")]
    return {"ok": True, "total": len(questions), "success": len(success), "results": all_results}


def login_qwen():
    asyncio.run(login_qwen_async())

def crawl_batch(questions, parallel=2):
    return asyncio.run(crawl_batch_async(questions, parallel))

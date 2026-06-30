"""
yuanbao_crawler.py — 腾讯元宝爬虫
URL: https://yuanbao.tencent.com/chat
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
    wait_until_stable, launch_browser, launch_browser_with_state,
    verify_saved_login
)

PLATFORM = "yuanbao"
YB_URL = "https://yuanbao.tencent.com/chat"

async def check_logged_in(page) -> bool:
    try:
        cur_url = page.url.lower()
        if any(kw in cur_url for kw in ["login", "passport", "auth", "signin"]):
            return False

        login_btn = await page.query_selector(
            '.agent-dialogue__tool__login, [class*="tool__login"], '
            'button:has-text("登录"), a:has-text("登录"), span:has-text("登录")'
        )
        if login_btn and await login_btn.is_visible():
            return False

        chat_ready = await page.query_selector(
            'textarea[placeholder*="尽管问"], textarea[placeholder*="问"], '
            'div[contenteditable="true"], button:has-text("新对话"), span:has-text("新对话")'
        )
        return bool(chat_ready and await chat_ready.is_visible())
    except Exception:
        return False


async def scroll_to_answer_bottom(page):
    try:
        await page.evaluate("""() => {
            const scrollers = [
                document.scrollingElement,
                document.documentElement,
                document.body,
                ...document.querySelectorAll('[class*="scroll"], [class*="conversation"], [class*="chat"]')
            ].filter(Boolean);
            for (const el of scrollers) {
                try {
                    el.scrollTop = el.scrollHeight;
                } catch(e) {}
            }
            window.scrollTo(0, document.body.scrollHeight);
        }""")
    except Exception:
        pass


def answer_looks_incomplete(answer):
    text = (answer or "").strip()
    if len(text) < 120:
        return True

    tail = text[-80:].strip()
    if not tail:
        return True
    if tail.endswith(("：", ":", "，", ",", "、", "；", ";", "（", "(", "-", "—", "/")):
        return True

    section_markers = len(re.findall(
        r"(?:^|\n)\s*(?:[一二三四五六七八九十]+[、.．]|[1-9][0-9]*[、.．])",
        text,
    ))
    expected_sections = [
        (r"以下\s*三|三类|三个|3\s*类|3\s*个", 3),
        (r"以下\s*四|四类|四个|4\s*类|4\s*个", 4),
        (r"以下\s*五|五类|五个|5\s*类|5\s*个", 5),
    ]
    for pattern, expected in expected_sections:
        if re.search(pattern, text) and section_markers and section_markers < expected:
            return True

    if text.count("```") % 2 == 1:
        return True
    return False


# ── 新对话 ───────────────────────────────────────────────
async def wait_for_generation_complete_yuanbao(page, timeout_s=60):
    """等元宝回答生成完毕：停止按钮消失"""
    await page.wait_for_timeout(2000)
    STOP_SELS = ['[class*="stop"]', 'button[aria-label*="停止"]', '[class*="stopIcon"]']
    for _ in range(timeout_s * 2):
        await page.wait_for_timeout(500)
        stop_visible = False
        for sel in STOP_SELS:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    stop_visible = True; break
            except: pass
        if not stop_visible:
            await page.wait_for_timeout(800)
            return True
    return False
async def goto_new_chat(page):
    try:
        for sel in [
            '[class*="newChat"]',
            'button[class*="new"]',
            '[data-testid="new-chat"]',
            'span:has-text("新对话")',
            'button:has-text("新对话")',
        ]:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                await page.wait_for_timeout(1500)
                return
        # 备用：左上角第二个图标（截图显示位置）
        icons = await page.query_selector_all('header svg, nav svg, [class*="icon"]')
        if len(icons) >= 2:
            await icons[1].click()
            await page.wait_for_timeout(1500)
            return
        await page.goto(YB_URL, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(1500)
    except:
        pass

# ── 等待并提取回答 ───────────────────────────────────────
async def wait_and_get_answer(page, worker_id=0):
    print("  → [元宝] 等待回答生成...")
    await page.wait_for_timeout(3000)
    await wait_for_captcha_if_needed(page, worker_id, PLATFORM)
    await wait_for_generation_complete_yuanbao(page, timeout_s=60)
    last_len = -1
    stable_ticks = 0
    for tick in range(90):
        await page.wait_for_timeout(1000)
        if tick % 10 == 9:
            await wait_for_captcha_if_needed(page, worker_id, PLATFORM)
        await scroll_to_answer_bottom(page)
        try:
            cur_len = await page.evaluate("""() => {
                let maxLen = 0;
                const els = document.querySelectorAll(
                    '[class*="markdown"], [class*="message-content"], [class*="chat-content"], [class*="answer-content"], [class*="reply"], div, article'
                );
                for (const el of els) {
                    const t = (el.innerText || '').trim();
                    if (t.length > maxLen
                        && !t.includes('有问题，尽管问')
                        && !t.includes('下载元宝')) {
                        maxLen = t.length;
                    }
                }
                return maxLen;
            }""")
            if cur_len >= 80 and cur_len == last_len:
                stable_ticks += 1
                if stable_ticks >= 6:
                    break
            else:
                stable_ticks = 0
                last_len = cur_len
        except Exception:
            pass
    await page.wait_for_timeout(500)
    await scroll_to_answer_bottom(page)

    answer = await page.evaluate("""() => {
        const noiseWords = [
            '有问题，尽管问', 'shift+enter换行', '深度思考', '工具',
            '下载元宝电脑版', '体验高效AI', '创建分组', '前往下载中心',
            '全部收藏', '智能联网'
        ];
        function hasNoise(t) {
            return noiseWords.filter(n => t.includes(n)).length >= 2;
        }
        const selectors = [
            '[class*="markdown"]',
            '[class*="message-content"]',
            '[class*="chat-content"]',
            '[class*="answer-content"]',
            '[class*="reply"]',
        ];
        for (const sel of selectors) {
            const els = document.querySelectorAll(sel);
            for (const el of [...els].reverse()) {
                const t = (el.innerText || '').trim();
                // 过滤视频卡片（通常很短）
                if (t.length >= 80 && !hasNoise(t)) return t;
            }
        }
        // 兜底
        const divs = [...document.querySelectorAll('div, article')];
        let best = '';
        for (const el of divs.reverse()) {
            const children = el.querySelectorAll('div').length;
            if (children > 80 || children < 1) continue;
            const t = (el.innerText || '').trim();
            if (t.length > best.length && t.length >= 80
                && !hasNoise(t)
                && !t.includes('有问题，尽管问')) {
                best = t;
            }
        }
        return best;
    }""")

    if len(answer) < 50:
        await page.wait_for_timeout(3000)
        await wait_for_captcha_if_needed(page, worker_id, PLATFORM)
        answer = await page.evaluate("""() => {
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_TEXT, null, false
            );
            const segs = [];
            let node;
            while (node = walker.nextNode()) {
                const t = (node.textContent || '').trim();
                if (t.length > 30
                    && !t.includes('有问题，尽管问')
                    && !t.includes('下载元宝')) segs.push(t);
            }
            return segs.sort((a,b)=>b.length-a.length).slice(0,5).join('\\n');
        }""")

    print(f"  → [元宝] 回答长度: {len(answer)} 字")
    if answer_looks_incomplete(answer):
        print("  → [元宝] 警告：回答可能不完整，已返回当前可提取内容")
    return answer

# ── 提取引用源 ────────────────────────────────────────────
async def get_refs(page):
    """
    提取元宝引用来源。
    点击「源」按钮展开「引用来源（N）」面板后，
    引用卡片 class: hyc-common-markdown__ref_card
    URL 存在 data-url 属性，标题在 h4.hyc-common-markdown__ref_card-title > span
    """
    refs = []
    try:
        # 点击「源」按钮展开引用面板
        clicked = False
        for sel in [
            '[class*="ToolbarSearchGuid_source"]',
            'span:has-text("源")',
            'button:has-text("源")',
        ]:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click()
                    await page.wait_for_timeout(1000)
                    clicked = True
                    break
            except:
                continue

        if not clicked:
            try:
                await page.evaluate("""() => {
                    const els = [...document.querySelectorAll('span,button')];
                    const btn = els.find(e => (e.innerText||'').trim() === '源');
                    if (btn) btn.click();
                }""")
                await page.wait_for_timeout(1000)
            except:
                pass

        # 用真实 class 提取引用卡片
        raw = await page.evaluate("""() => {
            const results = [];
            // 直接找 hyc-common-markdown__ref_card，data-url 就是链接
            const cards = document.querySelectorAll('[class*="hyc-common-markdown__ref_card"]');
            for (const card of cards) {
                // 跳过子元素（只要最外层容器）
                if (card.closest('[class*="hyc-common-markdown__ref_card"]') !== card) continue;

                const url = card.getAttribute('data-url') || '';
                // 标题：h4 > span
                const titleEl = card.querySelector(
                    'h4[class*="ref_card-title"] span, [class*="ref_card-title"] span, h4 span'
                );
                const title = (titleEl ? titleEl.innerText : card.querySelector('h4')?.innerText || '').trim();

                if (!title || title.length < 4) continue;
                results.push({ title: title.slice(0, 120), href: url });
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

        print(f"  [元宝] 引用源: {len(refs)}个")

        # 关闭引用面板
        try:
            await page.evaluate("""() => {
                const close = document.querySelector(
                    '[class*="close"], button[aria-label*="关闭"], .yb-icon-close'
                );
                if (close) close.click();
            }""")
            await page.wait_for_timeout(300)
        except:
            pass

    except Exception as e:
        print(f"  [元宝] 引用提取异常: {e}")
    return refs

# ── 登录 ─────────────────────────────────────────────────
async def login_yuanbao_async():
    """打开浏览器让用户手动登录元宝，自动检测成功后保存状态。"""
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
        await page.goto(YB_URL, wait_until="domcontentloaded", timeout=30000)

        print("\n[元宝] 浏览器已打开，请在窗口中完成登录（微信/QQ/手机号均可）")
        print("[元宝] 程序自动检测，保存后会用新会话复验（最长等待5分钟）...")

        for _ in range(150):
            await page.wait_for_timeout(2000)
            try:
                if await check_logged_in(page):
                    await page.wait_for_timeout(2000)
                    await save_cookies(context, PLATFORM)
                    verified = await verify_saved_login(
                        browser,
                        PLATFORM,
                        YB_URL,
                        check_logged_in,
                        viewport={"width": 1100, "height": 800},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    )
                    if verified:
                        print("[元宝] 登录成功，状态已保存并复验通过")
                        await browser.close()
                        return True
                    print("[元宝] 检测到疑似登录，但新会话复验失败，请在窗口中继续完成登录")
            except Exception as e:
                print(f"[元宝] 登录检测中: {e}")

        print("[元宝] 登录超时（5分钟），请重试")
        await browser.close()
        return False


async def crawl_worker(worker_id, questions, pw, results_dict, lock):
    browser, context = await launch_browser_with_state(pw, PLATFORM, worker_id)
    page = await context.new_page()

    await page.goto(YB_URL, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(2000)

    if not await check_logged_in(page):
        await browser.close()
        async with lock:
            for idx, q in questions:
                results_dict[idx] = {"ok": False, "error": "need_login", "question": q}
        return

    print(f"  [YB Worker {worker_id}] 已登录，开始爬取 {len(questions)} 题")

    for i, (idx, question) in enumerate(questions):
        print(f"  [YB Worker {worker_id}] [{i+1}/{len(questions)}] #{idx} {question[:35]}...")
        if i > 0:
            await goto_new_chat(page)

        try:
            input_box = None
            for sel in [
                'textarea[placeholder*="尽管问"]',
                'textarea[placeholder*="问"]',
                'div[contenteditable="true"]',
                'textarea',
            ]:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    input_box = el
                    break

            if not input_box:
                async with lock:
                    results_dict[idx] = {"ok": False, "error": "找不到输入框", "question": question}
                continue

            await input_box.click()
            await page.wait_for_timeout(200)
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Delete")
            await input_box.fill(question)
            await page.wait_for_timeout(300)
            await page.keyboard.press("Enter")

            await page.wait_for_timeout(800)
            try:
                await wait_for_captcha_if_needed(page, worker_id, PLATFORM)
            except TimeoutError:
                async with lock:
                    results_dict[idx] = {"ok": False, "error": "人机验证超时", "question": question}
                continue

            answer = await wait_and_get_answer(page, worker_id)
            if answer_looks_incomplete(answer):
                async with lock:
                    results_dict[idx] = {
                        "ok": False,
                        "error": "回答疑似截断或过短",
                        "question": question,
                        "answer_length": len(answer or ""),
                        "answer_tail": (answer or "")[-120:],
                    }
                continue
            refs = await get_refs(page)
            async with lock:
                results_dict[idx] = {"ok": True, "answer": answer, "refs": refs, "question": question}

        except Exception as e:
            async with lock:
                results_dict[idx] = {"ok": False, "error": str(e), "question": question}

    await save_cookies(context, PLATFORM)
    await browser.close()
    print(f"  [YB Worker {worker_id}] 完成")

# ── 批量爬取入口 ─────────────────────────────────────────
async def crawl_batch_async(questions, parallel=2):
    os.makedirs("data", exist_ok=True)
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
        await asyncio.gather(*tasks)

    all_results = [
        results_dict.get(i, {"ok": False, "error": "未执行", "question": q})
        for i, q in indexed
    ]
    success = [r for r in all_results if r.get("ok")]
    return {"ok": True, "total": len(questions), "success": len(success), "results": all_results}

def login_yuanbao():
    asyncio.run(login_yuanbao_async())

def crawl_batch(questions, parallel=2):
    return asyncio.run(crawl_batch_async(questions, parallel))

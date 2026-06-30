"""
deepseek_crawler.py — DeepSeek 爬虫
URL: https://chat.deepseek.com
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

PLATFORM = "deepseek"
DS_URL = "https://chat.deepseek.com/"

# ── 新对话 ───────────────────────────────────────────────
async def wait_for_generation_complete(page, timeout_s=120):
    """
    等待 DeepSeek 回答生成完毕。
    判断依据（从截图 DOM 分析）：
    1. 发送按钮（➤ 蓝色箭头）重新变为可点击状态
    2. 页面出现「继续生成」按钮（说明生成完成但内容被截断）
    3. 页面不含「有消息正在生成」提示
    4. 输入框重新变为可用
    """
    await page.wait_for_timeout(2000)

    stable_done = 0
    for _ in range(timeout_s * 2):
        await page.wait_for_timeout(500)
        try:
            done = await page.evaluate("""() => {
                const body = document.body.innerText || '';

                // 有「有消息正在生成」= 还没完成
                if (body.includes('有消息正在生成')) return false;

                // 有「继续生成」按钮 = 生成完成（内容被截断）
                const btns = [...document.querySelectorAll('button, [class*="btn"]')];
                for (const b of btns) {
                    if ((b.innerText || '').includes('继续生成')) return true;
                }

                // 发送按钮（➤）可用 = 生成完成
                // DeepSeek 发送按钮生成中是 disabled 或变成■
                const sendBtn = document.querySelector(
                    'button[class*="send"]:not([disabled]), button[aria-label*="发送"]:not([disabled])'
                );
                if (sendBtn) return true;

                // 输入框可用 = 生成完成
                const input = document.querySelector('textarea');
                if (input && !input.disabled && input.placeholder.includes('DeepSeek')) {
                    // 额外确认：不在加载状态
                    const loadings = document.querySelectorAll('[class*="loading"], [class*="spinner"], [class*="generating"]');
                    if (loadings.length === 0) return true;
                }

                return false;
            }""")
            if done:
                stable_done += 1
                if stable_done >= 3:
                    await page.wait_for_timeout(500)
                    return True
            else:
                stable_done = 0
        except:
            pass

    return False


async def extract_answer_text(page):
    return await page.evaluate("""() => {
        // 策略1: 真实 DS 回答 class
        const mainSels = [
            '.ds-markdown.ds-assistant-message-main-content',
            '[class*="ds-markdown"][class*="assistant"]',
            '[class*="ds-assistant-message-main-content"]',
            '[class*="ds-markdown"]',
        ];
        for (const sel of mainSels) {
            const els = document.querySelectorAll(sel);
            for (let i = els.length - 1; i >= 0; i--) {
                const t = (els[i].innerText || '').trim();
                if (t.length >= 50) return t;
            }
        }
        // 策略2: 兜底取最长干净块
        const noise = ['给 DeepSeek 发送消息', '深度思考', '智能搜索', '内容由AI生成', '本回答由 AI 生成', '继续生成'];
        function hasNoise(t) { return noise.some(n => t.includes(n)); }
        const divs = [...document.querySelectorAll('div, article')];
        let best = '';
        for (const el of divs.reverse()) {
            const c = el.querySelectorAll('div').length;
            if (c > 60 || c < 1) continue;
            const t = (el.innerText || '').trim();
            if (t.length > best.length && t.length >= 80 && !hasNoise(t)) best = t;
        }
        return best;
    }""")


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


async def click_continue_if_present(page):
    try:
        return await page.evaluate("""() => {
            const btns = [...document.querySelectorAll('button, [class*="btn"], div[role="button"]')];
            for (const b of btns) {
                const text = (b.innerText || b.textContent || '').trim();
                if (text === '继续生成') {
                    b.click();
                    return true;
                }
            }
            return false;
        }""")
    except Exception:
        return False


async def goto_new_chat(page):
    """开启新对话，并等待输入框真正可用"""
    try:
        for sel in [
            'div[class*="new"][class*="chat"]',
            'button:has-text("开启新对话")',
            '[class*="newChat"]',
            'a:has-text("新对话")',
        ]:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                break
        else:
            await page.goto(DS_URL, wait_until="domcontentloaded", timeout=20000)

        # 等待输入框出现且可用（最多10秒）
        for _ in range(20):
            await page.wait_for_timeout(500)
            for inp_sel in [
                'textarea[placeholder*="发送消息"]',
                'textarea[placeholder*="DeepSeek"]',
                '#chat-input', 'textarea',
            ]:
                try:
                    el = await page.query_selector(inp_sel)
                    if el and await el.is_visible() and await el.is_enabled():
                        await page.wait_for_timeout(300)
                        return
                except:
                    pass
    except:
        pass
    await page.wait_for_timeout(2000)


async def wait_and_get_answer(page, worker_id=0):
    print("  → [DeepSeek] 等待回答生成...")
    await page.wait_for_timeout(2000)
    await wait_for_captcha_if_needed(page, worker_id, PLATFORM)

    # 等「深度思考」完成
    for _ in range(40):
        thinking = await page.query_selector('[class*="thinking"], [class*="reasoner"]')
        if not thinking:
            break
        await page.wait_for_timeout(1000)

    # 等生成完成，最多尝试3次（处理「继续生成」截断情况）
    best_answer = ""
    for attempt in range(3):
        last_len = -1
        stable_ticks = 0
        for tick in range(120):
            await page.wait_for_timeout(1000)
            try:
                await scroll_to_answer_bottom(page)
                if tick % 10 == 9:
                    await wait_for_captcha_if_needed(page, worker_id, PLATFORM)

                answer_now = await extract_answer_text(page)
                if len(answer_now) > len(best_answer):
                    best_answer = answer_now

                cur_len = len(answer_now)
                if cur_len >= 80 and cur_len == last_len:
                    stable_ticks += 1
                else:
                    stable_ticks = 0
                    last_len = cur_len

                if stable_ticks >= 6:
                    if answer_looks_incomplete(answer_now) and tick < 75:
                        print(f"  → [DeepSeek] 回答疑似未完整，继续等待滚动 ({cur_len}字)")
                        stable_ticks = 0
                        continue
                    break
            except Exception:
                pass

        # 检查是否有「继续生成」按钮，有就点击
        continued = await click_continue_if_present(page)
        if continued:
            print(f"  → [DeepSeek] 检测到「继续生成」，自动点击（第{attempt+1}次）...")
            await page.wait_for_timeout(2000)
            continue
        break  # 没有「继续生成」按钮，退出循环

    await page.wait_for_timeout(500)
    await scroll_to_answer_bottom(page)

    answer = await extract_answer_text(page)
    if len(best_answer) > len(answer):
        answer = best_answer

    print(f"  → [DeepSeek] 回答长度: {len(answer)} 字")
    if answer_looks_incomplete(answer):
        print("  → [DeepSeek] 警告：回答可能仍不完整，已返回当前可提取的最长内容")
    return answer


async def get_refs(page):
    """
    提取 DeepSeek 引用源。
    DeepSeek 的引用来源直接内嵌在回答正文的「浏览X个页面」区域，
    不需要点击展开，直接从 DOM 里抓取链接即可。
    """
    refs = []
    try:
        raw = await page.evaluate("""() => {
            const results = [];
            const seen = new Set();

            // 策略1: 找「浏览X个页面」区块下的链接列表
            // DeepSeek 把搜索到的页面以列表形式内嵌在回答区域
            const allLinks = document.querySelectorAll('a[href^="http"]');
            for (const a of allLinks) {
                const href = a.href || '';
                const title = (a.innerText || a.textContent || '').trim();
                // 过滤：标题要有意义，不是导航链接
                if (!title || title.length < 5 || seen.has(href)) continue;
                // 过滤掉 deepseek 自己的页面
                if (href.includes('deepseek.com')) continue;
                seen.add(href);
                results.push({ title: title.slice(0, 120), href });
                if (results.length >= 15) break;
            }

            // 策略2: 如果策略1没拿到，找包含文章标题的文本节点
            if (results.length === 0) {
                // 找「浏览X个页面」后面的列表项
                const items = document.querySelectorAll(
                    '[class*="search"] li, [class*="browse"] li, [class*="source"] li'
                );
                for (const li of items) {
                    const a = li.querySelector('a[href]');
                    const title = (li.innerText || '').trim();
                    const href = a ? a.href : '';
                    if (title && title.length >= 5 && href && !seen.has(title)) {
                        seen.add(title);
                        results.push({ title: title.slice(0, 120), href });
                    }
                }
            }

            return results;
        }""")

        for i, item in enumerate(raw):
            refs.append({
                "title": item["title"],
                "url": item["href"],
                "platform": extract_platform(item["href"]),
                "rank": i + 1,
            })

        print(f"  [DeepSeek] 引用源: {len(refs)}个")
    except Exception as e:
        print(f"  [DeepSeek] 引用提取异常: {e}")
    return refs

# ── 登录 ─────────────────────────────────────────────────
async def check_logged_in(page) -> bool:
    try:
        cur_url = page.url.lower()
        if any(kw in cur_url for kw in ["login", "passport", "sign_in", "signin"]):
            return False

        body = await page.evaluate("() => (document.body && document.body.innerText) || ''")
        login_words = ["登录", "验证码", "手机号登录", "扫码登录", "注册"]
        if sum(1 for word in login_words if word in body) >= 2:
            return False

        for sel in [
            'textarea[placeholder*="发送消息"]',
            'textarea[placeholder*="DeepSeek"]',
            '#chat-input',
            'textarea',
        ]:
            el = await page.query_selector(sel)
            if el and await el.is_visible() and await el.is_enabled():
                return True
        return False
    except Exception:
        return False

async def login_deepseek_async():
    """打开浏览器让用户手动登录 DeepSeek，用 storage_state 保存完整状态（含localStorage token）"""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--window-position=0,0", "--window-size=900,700"]
        )
        # 登录时用普通context（不预加载状态，让用户全新登录）
        context = await browser.new_context(
            viewport={"width": 900, "height": 700},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await page.goto("https://chat.deepseek.com/", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # 如果已在登录页，等待用户登录
        print("[DeepSeek] 请在浏览器窗口中完成登录（手机号验证码或微信扫码）")
        print("[DeepSeek] 程序自动检测，保存后会用新会话复验（最长等待5分钟）...")

        for _ in range(150):
            await page.wait_for_timeout(2000)
            try:
                if await check_logged_in(page):
                    await page.wait_for_timeout(3000)
                    await save_cookies(context, PLATFORM)
                    verified = await verify_saved_login(
                        browser,
                        PLATFORM,
                        DS_URL,
                        check_logged_in,
                        viewport={"width": 900, "height": 700},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    )
                    if verified:
                        print("[DeepSeek] 登录成功！完整状态已保存并复验通过")
                        await browser.close()
                        return True
                    print("[DeepSeek] 检测到疑似登录，但新会话复验失败，请在窗口中继续完成登录")
            except Exception as e:
                print(f"[DeepSeek] 登录检测中: {e}")

        print("[DeepSeek] 登录超时（5分钟），请重试")
        await browser.close()
        return False
async def crawl_worker(worker_id, questions, pw, results_dict, lock, send_lock=None):
    """questions: list of (index, question_str)
    send_lock: 账号级全局锁，防止多Worker同时发送触发「有消息正在生成」
    """
    browser, context = await launch_browser_with_state(pw, PLATFORM, worker_id)
    page = await context.new_page()

    await page.goto(DS_URL, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(2000)

    if not await check_logged_in(page):
        await browser.close()
        async with lock:
            for idx, q in questions:
                results_dict[idx] = {"ok": False, "error": "need_login", "question": q}
        return

    print(f"  [DS Worker {worker_id}] 已登录，开始爬取 {len(questions)} 题")

    for i, (idx, question) in enumerate(questions):
        print(f"  [DS Worker {worker_id}] [{i+1}/{len(questions)}] #{idx} {question[:35]}...")

        # 每题都开新对话（包括第一题，确保没有上下文干扰）
        await goto_new_chat(page)

        try:
            # 找输入框
            input_box = None
            for sel in [
                'textarea[placeholder*="发送消息"]',
                'textarea[placeholder*="DeepSeek"]',
                '#chat-input', 'textarea',
            ]:
                el = await page.query_selector(sel)
                if el and await el.is_visible() and await el.is_enabled():
                    input_box = el
                    break

            if not input_box:
                async with lock:
                    results_dict[idx] = {"ok": False, "error": "找不到输入框", "question": question}
                continue

            # 发送问题（带重试：检测「有消息正在生成」错误）
            # 中途检测登录状态（防止 Cookie 失效）
            if "sign_in" in page.url or "login" in page.url:
                print(f"  [DS Worker {worker_id}] Cookie 中途失效，跳过剩余题目")
                async with lock:
                    results_dict[idx] = {"ok": False, "error": "cookie_expired", "question": question}
                break

            # ── 流水线模式：抢锁→发送→等生成完→释放锁 ──────────
            # 锁只在「发送+等待生成」期间持有，释放后下一Worker立刻抢锁
            # 这样两个窗口交替运行，几乎无等待浪费
            _sl = send_lock if send_lock else asyncio.Lock()

            # 先在锁外填好问题（节省持锁时间）
            await input_box.click()
            await page.wait_for_timeout(200)
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Delete")
            await input_box.fill(question)
            await page.wait_for_timeout(300)
            print(f"  [DS Worker {worker_id}] 等待发送锁...")

            async with _sl:
                print(f"  [DS Worker {worker_id}] 获得发送锁，发送问题")
                # 发送
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(1500)

                # 检测是否被拒绝
                sent_ok = False
                for attempt in range(5):
                    try:
                        body = await page.evaluate("() => document.body.innerText || ''")
                        if "有消息正在生成" in body:
                            wait_s = 8 + attempt * 5
                            print(f"  [DS Worker {worker_id}] 有消息正在生成，等{wait_s}秒重试（{attempt+1}次）...")
                            await page.wait_for_timeout(wait_s * 1000)
                            await goto_new_chat(page)
                            # 重新填问题
                            input_box = None
                            for sel in ['textarea[placeholder*="发送消息"]','textarea[placeholder*="DeepSeek"]','#chat-input','textarea']:
                                el = await page.query_selector(sel)
                                if el and await el.is_visible() and await el.is_enabled():
                                    input_box = el; break
                            if not input_box: continue
                            await input_box.click()
                            await page.wait_for_timeout(200)
                            await page.keyboard.press("Control+A")
                            await page.keyboard.press("Delete")
                            await input_box.fill(question)
                            await page.wait_for_timeout(300)
                            await page.keyboard.press("Enter")
                            await page.wait_for_timeout(1500)
                        else:
                            sent_ok = True; break
                    except:
                        sent_ok = True; break

                if not sent_ok:
                    async with lock:
                        results_dict[idx] = {"ok": False, "error": "发送失败：消息生成冲突", "question": question}
                    continue

                # 验证码
                try:
                    await wait_for_captcha_if_needed(page, worker_id, PLATFORM)
                except TimeoutError:
                    async with lock:
                        results_dict[idx] = {"ok": False, "error": "人机验证超时", "question": question}
                    continue

                # 等生成完毕（持锁，其他Worker在锁外填问题等待）
                answer = await wait_and_get_answer(page, worker_id)
                print(f"  [DS Worker {worker_id}] 生成完毕，释放发送锁")
            # ─────────────────────────────────────────────────────

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

            # 锁释放后获取引用（不阻塞其他Worker发送）
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
    print(f"  [DS Worker {worker_id}] 完成")

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
    # DeepSeek 账号级并发限制：同一时刻只能有一个对话在生成
    # 用 send_lock 确保多个 Worker 不会同时发送消息
    send_lock = asyncio.Lock()
    async with async_playwright() as pw:
        tasks = [crawl_worker(i+1, chunk, pw, results_dict, lock, send_lock)
                 for i, chunk in enumerate(chunks)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                print(f"  [DS Worker {i+1}] 异常退出: {r}")

    all_results = [
        results_dict.get(i, {"ok": False, "error": "未执行", "question": q})
        for i, q in indexed
    ]
    success = [r for r in all_results if r.get("ok")]
    return {"ok": True, "total": len(questions), "success": len(success), "results": all_results}

def login_deepseek():
    asyncio.run(login_deepseek_async())

def crawl_batch(questions, parallel=2):
    return asyncio.run(crawl_batch_async(questions, parallel))

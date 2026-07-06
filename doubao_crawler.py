"""
豆包自动爬取模块 v4
- headless=False 避免反爬
- 更健壮的回答提取逻辑
"""
import asyncio
import json
import os
import re
from playwright.async_api import async_playwright
from base_crawler import mark_login_status, save_cookies as save_storage_state, verify_saved_login

import pathlib as _pl
PLATFORM = "doubao"
COOKIE_FILE = str(_pl.Path(__file__).resolve().parent / "data" / "doubao_cookies.json")
DOUBAO_URL = "https://www.doubao.com/chat/"

# ── Cookie 管理 ──────────────────────────────────────────
async def save_cookies(context):
    cookies = await context.cookies()
    os.makedirs(str(_pl.Path(COOKIE_FILE).parent), exist_ok=True)
    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    print(f"[doubao] Cookie已保存: {COOKIE_FILE} ({len(cookies)}个)")

async def load_cookies(context):
    if os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        await context.add_cookies(cookies)
        print(f"[doubao] Cookie已加载: {COOKIE_FILE} ({len(cookies)}个)")
        return True
    print(f"[doubao] 未找到Cookie文件: {COOKIE_FILE}")
    return False

async def check_logged_in(page) -> bool:
    try:
        cur_url = page.url.lower()
        cur_url_without_query = cur_url.split("?", 1)[0]
        if any(kw in cur_url_without_query for kw in ["login", "passport", "signin", "sign_in"]):
            return False

        body = await page.evaluate("() => (document.body && document.body.innerText) || ''")
        not_login_hints = [
            "请先登录",
            "登录后",
            "受区域限制",
            "手机号登录",
            "验证码登录",
        ]
        if any(hint in body for hint in not_login_hints):
            return False

        login_btn = await page.query_selector(
            'button:has-text("登录"), a:has-text("登录"), '
            'button:has-text("立即登录"), a:has-text("立即登录")'
        )
        if login_btn and await login_btn.is_visible():
            return False

        for sel in [
            'textarea[placeholder*="发消息"]',
            'textarea[placeholder*="消息"]',
            'textarea[placeholder*="输入"]',
            '[contenteditable="true"][role="textbox"]',
            '[contenteditable="true"]',
            'textarea',
        ]:
            el = await page.query_selector(sel)
            if el and await el.is_visible() and await el.is_enabled():
                return True
        return False
    except Exception:
        return False

# ── 平台识别 ─────────────────────────────────────────────
def extract_platform(url):
    rules = [
        ("土巴兔", ["to8to"]),
        ("新浪家居", ["jiaju.sina"]),
        ("网易家居", ["house.163", "jiaju.163"]),
        ("今日头条", ["toutiao"]),
        ("搜狐", ["sohu"]),
        ("百度百科", ["baike.baidu"]),
        ("知乎", ["zhihu"]),
        ("小红书", ["xiaohongshu", "xhslink"]),
        ("抖音", ["douyin"]),
        ("微信公众号", ["mp.weixin"]),
        ("百家号", ["baijiahao"]),
        ("凤凰网", ["ifeng"]),
        ("腾讯新闻", ["news.qq"]),
        ("网易新闻", ["news.163"]),
        ("新浪新闻", ["news.sina"]),
        ("大众点评", ["dianping"]),
        ("58同城", ["58.com"]),
        ("安居客", ["anjuke"]),
        ("链家", ["lianjia"]),
    ]
    url_lower = url.lower()
    for name, keywords in rules:
        if any(kw in url_lower for kw in keywords):
            return name
    m = re.search(r'https?://(?:www\.)?([^/]+)', url)
    if m:
        parts = m.group(1).split(".")
        return parts[-2] if len(parts) >= 2 else m.group(1)
    return "未知"


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


# ── 等待并提取回答 ───────────────────────────────────────
async def wait_and_get_answer(page, worker_id=0):
    """等待豆包回答完成并提取正文文本（含空爬检测 + 人机验证检测）"""
    print("  → 等待回答生成...")
    await page.wait_for_timeout(3000)

    # 先检测是否弹出人机验证
    await wait_for_captcha_if_needed(page, worker_id)

    # ── 新增：等待豆包"生成中"状态消失（停止符/加载圈消失表示完成）──
    async def is_generating():
        """检测豆包是否仍在生成中"""
        try:
            result = await page.evaluate("""() => {
                // 豆包"停止生成"按钮存在 = 还在生成
                const stopSelectors = [
                    '[class*="stop"]', '[title*="停止"]', '[aria-label*="停止"]',
                    '[class*="generating"]', '[class*="loading"]',
                    'button[class*="send"] svg[class*="animate"]',
                ];
                for (const sel of stopSelectors) {
                    try {
                        const el = document.querySelector(sel);
                        if (el && el.offsetParent !== null) return true;
                    } catch(e) {}
                }
                // 检查是否有加载动画（旋转的圆圈等）
                const animEls = document.querySelectorAll(
                    '[class*="spin"], [class*="pulse"], [class*="blink"], [class*="dot-loading"]'
                );
                for (const el of animEls) {
                    if (el.offsetParent !== null) return true;
                }
                return false;
            }""")
            return result
        except:
            return False

    # 先等"生成中"状态消失（最多等45秒）
    for _ in range(45):
        await page.wait_for_timeout(1000)
        await scroll_to_answer_bottom(page)
        if not await is_generating():
            break
    # 生成完成后额外等0.8秒让DOM渲染稳定
    await page.wait_for_timeout(800)

    # 智能检测：内容稳定就停止等待（最多 60×0.5s = 30s）
    last_len = 0
    stable = 0
    for tick in range(60):
        await page.wait_for_timeout(500)

        # 每 10 tick 检查一次验证码（防止验证码在等待中途弹出）
        if tick % 10 == 9:
            try:
                await wait_for_captcha_if_needed(page, worker_id)
            except TimeoutError:
                print(f"  [Worker {worker_id}] 等待过程中人机验证超时，返回已有内容")
                break

        await scroll_to_answer_bottom(page)
        cur_len = await page.evaluate("""() => {
            let maxLen = 0;
            const divs = document.querySelectorAll('div, p, article');
            for (const el of divs) {
                const t = (el.innerText || '').trim();
                if (t.length > maxLen
                    && !t.includes('Ctrl K')
                    && !t.includes('新对话')
                    && !t.includes('历史对话')) {
                    maxLen = t.length;
                }
            }
            return maxLen;
        }""")

        if cur_len > 100 and cur_len == last_len:
            stable += 1
            if stable >= 6:
                print(f"  → 回答已稳定 ({cur_len}字)")
                break
        else:
            stable = 0
            last_len = cur_len

    await page.wait_for_timeout(500)
    await scroll_to_answer_bottom(page)

    # ── 提取回答正文（多策略，优先豆包语义容器）──────────────
    answer = await page.evaluate("""() => {
        const noiseWords = [
            'Ctrl K', 'Ctrl+K', '新对话', '历史对话',
            'AI 创作', '下载客户端', '你好，我是豆包',
            '图像生成', '编程', '翻译', '更多',
            '在此处拖放文件', '文件类型', '最多 50 个'
        ];
        function noiseCount(t) {
            return noiseWords.filter(n => t.includes(n)).length;
        }

        // ── 策略 1：豆包回答专属 data 属性 ─────────────────
        const dataSelectors = [
            '[data-testid="chat-message-content"]',
            '[data-testid="message-content"]',
            '[class*="chat-message"]',
            '[class*="message-content"]',
            '[class*="bot-message"]',
            '[class*="assistant-message"]',
            '[class*="answer-content"]',
            '[class*="reply-content"]',
        ];
        for (const sel of dataSelectors) {
            const els = document.querySelectorAll(sel);
            for (const el of els) {
                const t = (el.innerText || '').trim();
                if (t.length >= 80 && noiseCount(t) === 0) {
                    return t;
                }
            }
        }

        // ── 策略 2：找最后一个 AI 回答容器（深度适中）───────
        // 豆包回答通常是页面下方、子节点数适中的 div
        const allDivs = Array.from(document.querySelectorAll('div, article, section'));
        // 倒序遍历，越靠下越可能是最新回答
        let bestEl = null;
        let bestScore = 0;
        for (let i = allDivs.length - 1; i >= 0; i--) {
            const el = allDivs[i];
            const children = el.querySelectorAll('div').length;
            if (children > 60 || children < 1) continue;

            const t = (el.innerText || '').trim();
            if (t.length < 80 || t.length > 8000) continue;
            if (noiseCount(t) >= 1) continue;

            // 打分：文字量、结构特征
            let score = t.length;
            if (/[0-9]/.test(t)) score += 400;
            if (t.includes('推荐') || t.includes('公司') || t.includes('品牌')) score += 300;
            if (t.includes('1.') || t.includes('一、') || t.includes('首先') || t.includes('综合')) score += 250;
            if (t.includes('：') || t.includes('，') || t.includes('。')) score += 150;
            // 减分：含噪音或文件上传提示
            if (t.includes('拖放') || t.includes('上传')) score -= 1000;

            if (score > bestScore) {
                bestScore = score;
                bestEl = t;
            }
        }

        // ── 策略 3：兜底——取 <main> 或 body 中最长干净段落 ──
        if (!bestEl) {
            const container = document.querySelector('main') || document.body;
            const paras = container.querySelectorAll('p, li');
            const texts = [];
            for (const p of paras) {
                const t = (p.innerText || '').trim();
                if (t.length > 20 && noiseCount(t) === 0) texts.push(t);
            }
            if (texts.length > 0) bestEl = texts.join('\\n');
        }

        return bestEl || '';
    }""")

    # 空爬检测：如果提取结果疑似噪音或过短，等3秒后重试一次主提取逻辑
    if len(answer) < 50:
        print(f"  ⚠️  回答疑似空爬（{len(answer)}字），等待 3s 后重试...")
        await page.wait_for_timeout(3000)
        await wait_for_captcha_if_needed(page, worker_id)
        # 重试时复用主提取逻辑（策略1+2），不用"最长文本"兜底，防止把历史对话全文抓进来
        answer = await page.evaluate("""() => {
            const noiseWords = [
                'Ctrl K', 'Ctrl+K', '新对话', '历史对话',
                'AI 创作', '下载客户端', '你好，我是豆包',
                '图像生成', '编程', '翻译', '更多',
                '在此处拖放文件', '文件类型', '最多 50 个'
            ];
            function noiseCount(t) { return noiseWords.filter(n => t.includes(n)).length; }

            // 策略1：语义选择器，取最后一个匹配的（最新回答）
            const dataSelectors = [
                '[data-testid="chat-message-content"]',
                '[data-testid="message-content"]',
                '[class*="chat-message"]',
                '[class*="message-content"]',
                '[class*="bot-message"]',
                '[class*="assistant-message"]',
                '[class*="answer-content"]',
                '[class*="reply-content"]',
            ];
            for (const sel of dataSelectors) {
                const els = Array.from(document.querySelectorAll(sel));
                // 取最后一个（最新一条AI回答）
                for (let i = els.length - 1; i >= 0; i--) {
                    const t = (els[i].innerText || '').trim();
                    if (t.length >= 50 && t.length <= 6000 && noiseCount(t) === 0) return t;
                }
            }

            // 策略2：倒序扫描div，严格限制字数上限3000防止抓全页
            const allDivs = Array.from(document.querySelectorAll('div, article'));
            for (let i = allDivs.length - 1; i >= 0; i--) {
                const el = allDivs[i];
                const children = el.querySelectorAll('div').length;
                if (children > 60 || children < 1) continue;
                const t = (el.innerText || '').trim();
                if (t.length < 50 || t.length > 3000) continue;
                if (noiseCount(t) >= 1) continue;
                if (t.includes('拖放') || t.includes('上传')) continue;
                if (t.includes('。') || t.includes('，') || t.includes('：')) return t;
            }
            return '';
        }""")
        print(f"  → 重试后回答长度: {len(answer)} 字")
    else:
        print(f"  → 回答长度: {len(answer)} 字")

    if answer_looks_incomplete(answer):
        print("  → [豆包] 警告：回答可能不完整，已返回当前可提取内容")

    return answer

# ── 提取引用源 ───────────────────────────────────────────
async def get_refs(page):
    refs = []
    try:
        # 前置等待：确保引用区域已渲染（最多等5秒）
        await page.wait_for_timeout(1000)
        for _ in range(5):
            has_ref_hint = await page.evaluate("""() => {
                const t = (document.body && document.body.innerText) || '';
                return t.includes('篇资料') || t.includes('参考了') || t.includes('个搜索');
            }""")
            if has_ref_hint:
                break
            await page.wait_for_timeout(1000)

        # 第一步：尝试点击展开「参考了N篇资料」
        # 用JS找到包含"篇资料"的可点击元素
        expanded = await page.evaluate("""() => {
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_TEXT, null, false
            );
            let node;
            while (node = walker.nextNode()) {
                const t = node.textContent || '';
                if (t.includes('篇资料') || t.includes('参考了') || t.includes('个搜索')) {
                    const el = node.parentElement;
                    if (el) {
                        el.click();
                        return true;
                    }
                }
            }
            return false;
        }""")
        if expanded:
            await page.wait_for_timeout(1500)

        # 第二步：抓取引用链接（多选择器策略）
        # 策略1：豆包真实属性选择器
        links = await page.query_selector_all('a[data-tool-call-item-id]')

        # 策略2：class特征选择器
        if not links:
            links = await page.query_selector_all('a[class*="text-dbx-text-highlight"]')

        # 策略3：豆包引用列表容器内的链接（新版DOM适配）
        if not links:
            links = await page.query_selector_all(
                '[class*="reference"] a[href], [class*="cite"] a[href], '
                '[class*="source"] a[href], [class*="ref-item"] a[href], '
                '[class*="search-result"] a[href]'
            )

        # 策略4：JS直接提取所有外链
        if not links:
            raw_refs = await page.evaluate(r"""() => {
                const results = [];
                const seen = new Set();
                document.querySelectorAll('a[href]').forEach(a => {
                    const href = a.href || '';
                    const title = (a.innerText || '').trim().replace(/[\s]+/g, ' ');
                    if (href && !href.includes('doubao.com')
                        && !href.startsWith('javascript')
                        && title.length > 5 && title.length < 150
                        && !seen.has(href)) {
                        seen.add(href);
                        results.push({title, url: href});
                    }
                });
                return results.slice(0, 20);
            }""")
            for r in raw_refs:
                refs.append({
                    "title": r['title'][:120],
                    "url": r['url'],
                    "platform": extract_platform(r['url'])
                })
        else:
            for link in links:
                try:
                    href = (await link.get_attribute('href')) or ''
                    if not href or 'doubao.com' in href:
                        continue
                    title_el = await link.query_selector('[class*="truncate"]')
                    if title_el:
                        title = (await title_el.inner_text()).strip()
                    else:
                        title = (await link.inner_text()).strip()
                    title = ' '.join(title.split())
                    if title and len(title) > 4:
                        refs.append({
                            "title": title[:120],
                            "url": href,
                            "platform": extract_platform(href)
                        })
                except:
                    continue

        # 去重
        seen, unique = set(), []
        for r in refs:
            k = r.get('url', '')
            if k and k not in seen and 'doubao.com' not in k:
                seen.add(k)
                unique.append(r)
        refs = unique[:18]

    except Exception as e:
        print(f"  → 引用源提取出错: {e}")

    print(f"  → 引用源: {len(refs)} 条")
    return refs

# ── 人机验证检测与等待 ────────────────────────────────────
async def wait_for_captcha_if_needed(page, worker_id=0):
    """
    检测豆包是否弹出人机验证（拼图/滑块）窗口。
    若检测到，则持续等待，直到用户完成验证后自动继续。
    """
    CAPTCHA_KEYWORDS = [
        "拼图", "滑块", "验证", "拖动", "人机", "安全验证",
        "drag", "slider", "captcha", "puzzle", "verify"
    ]
    CAPTCHA_SELECTORS = [
        # 豆包常见拼图/滑块容器特征
        '[class*="captcha"]',
        '[class*="verify"]',
        '[class*="slider"]',
        '[class*="puzzle"]',
        '[class*="drag"]',
        '[id*="captcha"]',
        '[id*="verify"]',
        'canvas[width]',  # 拼图画布
    ]

    async def is_captcha_visible():
        # 1. 关键词扫描
        try:
            body_text = await page.evaluate(
                "() => (document.body && document.body.innerText) || ''"
            )
            kw_hit = sum(1 for kw in CAPTCHA_KEYWORDS if kw in body_text)
            if kw_hit >= 2:
                return True
        except:
            pass
        # 2. 选择器匹配
        for sel in CAPTCHA_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    # canvas 单独判断：只有同时存在验证关键词才算
                    if sel == 'canvas[width]':
                        try:
                            bt = await page.evaluate(
                                "() => (document.body && document.body.innerText) || ''"
                            )
                            if any(kw in bt for kw in ["验证", "拼图", "拖动", "滑块"]):
                                return True
                        except:
                            pass
                    else:
                        return True
            except:
                continue
        return False

    # 第一次检测
    if not await is_captcha_visible():
        return  # 没有验证码，直接返回

    print(f"\n  ⚠️  [Worker {worker_id}] 检测到人机验证窗口！")
    print(f"  ➡️  请在浏览器窗口中完成拼图/滑块验证，程序将自动继续...\n")

    # 持续轮询，直到验证码消失（最长等待 5 分钟）
    waited = 0
    MAX_WAIT = 300  # 秒
    CHECK_INTERVAL = 1500  # ms

    while waited < MAX_WAIT * 1000:
        await page.wait_for_timeout(CHECK_INTERVAL)
        waited += CHECK_INTERVAL
        still_visible = await is_captcha_visible()
        if not still_visible:
            print(f"  ✅  [Worker {worker_id}] 人机验证已通过，继续爬取...\n")
            await page.wait_for_timeout(1500)  # 验证通过后稍等页面恢复
            return

    # 超时仍未通过
    print(f"  ❌  [Worker {worker_id}] 等待人机验证超时（{MAX_WAIT}s），跳过本题")
    raise TimeoutError("人机验证等待超时")


# ── 新对话 ───────────────────────────────────────────────
async def goto_new_chat(page):
    """
    确保真正开启新对话：验证 URL 已变为新的 chat 页面才算成功。
    策略1：点击"新对话"按钮 + 等待URL变化确认
    策略2：直接 goto 首页（首页每次都是全新对话入口）
    """
    old_url = page.url

    # ── 策略1：点击"新对话"按钮 ─────────────────────────
    await page.evaluate("""() => {
        const keywords = ['新对话', '新建对话', 'New Chat', '新聊天'];
        const candidates = Array.from(document.querySelectorAll(
            'button, a, [role="button"], [class*="new-chat"], [class*="newchat"], ' +
            '[class*="sidebar"] button, [class*="nav"] button'
        ));
        for (const el of candidates) {
            const t = (el.innerText || el.title || el.getAttribute('aria-label') || '').trim();
            if (keywords.some(k => t.includes(k))) {
                el.click();
                return true;
            }
        }
        return false;
    }""")

    # 等待 URL 变化（最多5秒），URL变了说明真正进入了新对话页
    new_url_detected = False
    for _ in range(10):
        await page.wait_for_timeout(500)
        cur_url = page.url
        # 豆包新对话URL格式: /chat/ 或 /chat/<新id>，且与旧URL不同
        if cur_url != old_url and 'doubao.com' in cur_url:
            new_url_detected = True
            break

    if new_url_detected:
        try:
            await page.wait_for_selector('textarea', timeout=5000)
            await page.wait_for_timeout(500)
            print(f"  → 点击新对话成功 (URL变化已确认)")
            return
        except:
            pass  # URL变了但textarea没出现，继续降级

    # ── 策略2：直接 goto 豆包首页（首页每次都是全新对话）──
    print("  → 点击新对话未检测到URL变化，降级goto首页...")
    try:
        await page.goto(DOUBAO_URL, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_selector('textarea', timeout=8000)
        await page.wait_for_timeout(800)
        print(f"  → goto新对话成功")
    except Exception as e:
        print(f"  → goto新对话出错: {e}")
        # 最终兜底：再等4秒看textarea是否可用
        try:
            await page.wait_for_selector('textarea', timeout=4000)
        except:
            pass

# ── 登录 ─────────────────────────────────────────────────
async def login_doubao_async():
    """打开浏览器让用户手动登录豆包，自动检测并复验后保存状态。"""
    os.makedirs(str(_pl.Path(COOKIE_FILE).parent), exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()
        await page.goto(DOUBAO_URL, wait_until="domcontentloaded", timeout=20000)

        print("\n[豆包] 浏览器已打开，请在窗口中完成登录")
        print("[豆包] 程序自动检测，保存后会用新会话复验（最长等待5分钟）...\n")

        for _ in range(150):
            await page.wait_for_timeout(2000)
            if await check_logged_in(page):
                await page.wait_for_timeout(2000)
                cookies = await context.cookies()
                with open(COOKIE_FILE, "w", encoding="utf-8") as f:
                    json.dump(cookies, f, ensure_ascii=False, indent=2)
                await save_storage_state(context, PLATFORM, mark_ok=False)
                print(f"[豆包] 登录状态已保存（共{len(cookies)}个Cookie），开始复验")

                verified = await verify_saved_login(
                    browser,
                    PLATFORM,
                    DOUBAO_URL,
                    check_logged_in,
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )
                if verified:
                    print("[豆包] 登录成功，状态已保存并复验通过")
                    await browser.close()
                    return {"ok": True, "message": "登录成功，状态已保存并复验通过"}

                print("[豆包] 检测到疑似登录，但新会话复验失败，请在窗口中继续完成登录")

        mark_login_status(PLATFORM, "expired", "登录状态验证失败，请重新登录")
        await browser.close()
        return {"ok": False, "message": "登录超时或复验失败，请重试"}

async def crawl_worker(worker_id, questions, pw, results_dict, lock):
    """
    questions: list of (index, question_str) tuples
    results_dict: keyed by index (int)，避免同问题多轮爬取互相覆盖
    """
    # headless=False 避免豆包反爬导致DOM结构异常
    browser = await pw.chromium.launch(
        headless=False,
        args=["--no-sandbox", "--disable-dev-shm-usage",
              f"--window-position={worker_id * 420},0",
              "--window-size=420,700"]
    )
    context = await browser.new_context(
        viewport={"width": 420, "height": 700},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    await load_cookies(context)
    page = await context.new_page()

    # 打开豆包首页
    await page.goto(DOUBAO_URL, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(2000)

    # 检查登录状态
    if not await check_logged_in(page):
        await browser.close()
        async with lock:
            for idx, q in questions:
                results_dict[idx] = {"ok": False, "error": "need_login", "question": q}
        return
    print(f"  [Worker {worker_id}] 已登录，开始爬取 {len(questions)} 题")

    for i, (idx, question) in enumerate(questions):
        print(f"  [Worker {worker_id}] [{i+1}/{len(questions)}] #{idx} {question[:35]}...")

        # ── 强制新对话 + 发送前三重验证（最多重试3次）──────────
        input_box = None
        new_chat_ok = False
        for attempt in range(3):
            await goto_new_chat(page)

            # 验证1：URL 必须是豆包域名（未被导走）
            cur_url = page.url
            if 'doubao.com' not in cur_url:
                print(f"  [Worker {worker_id}] 尝试{attempt+1}：URL异常({cur_url[:40]})，重试...")
                await page.wait_for_timeout(1500)
                continue

            # 验证2：输入框必须存在且可见且为空
            try:
                box = None
                for sel in [
                    'textarea[placeholder*="发消息"]',
                    'textarea[placeholder*="消息"]',
                    'textarea[placeholder*="输入"]',
                    'textarea',
                ]:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        box = el
                        break

                if not box:
                    print(f"  [Worker {worker_id}] 尝试{attempt+1}：找不到输入框，重试...")
                    await page.wait_for_timeout(1500)
                    continue

                # 验证3：检测是否有用户发送的消息气泡（新对话为空，旧对话有用户消息）
                # 只检测用户侧的消息气泡，不检测豆包首页的推荐问题卡片
                has_history = await page.evaluate("""() => {
                    // 豆包用户消息的特征：包含实际对话内容的容器
                    // 首页推荐卡片不包含在对话容器内
                    const userMsgSelectors = [
                        '[class*="user-message"]',
                        '[class*="human-message"]',
                        '[class*="chat-message"][class*="user"]',
                        '[data-role="user"]',
                        '[data-sender="user"]',
                    ];
                    for (const sel of userMsgSelectors) {
                        if (document.querySelector(sel)) return true;
                    }
                    return false;
                }""")
                if has_history:
                    print(f"  [Worker {worker_id}] 尝试{attempt+1}：检测到用户历史消息，非新对话，重试...")
                    await page.wait_for_timeout(1500)
                    continue

                # 三项全过：确认是全新对话
                input_box = box
                new_chat_ok = True
                if attempt > 0:
                    print(f"  [Worker {worker_id}] 第{attempt+1}次尝试成功开启新对话 ✅")
                break

            except Exception as e:
                print(f"  [Worker {worker_id}] 尝试{attempt+1}：验证异常({e})，重试...")
                await page.wait_for_timeout(1500)
                continue

        if not new_chat_ok:
            print(f"  [Worker {worker_id}] ❌ 三次尝试均未能开启新对话，跳过本题")
            async with lock:
                results_dict[idx] = {"ok": False, "error": "无法开启新对话", "question": question}
            continue

        # 中途检测 Cookie 是否仍有效（防止同事操作导致 Session 失效）
        if not await check_logged_in(page):
            print(f"  [Worker {worker_id}] ⚠️ Cookie 中途失效，尝试重新加载 Cookie...")
            # 尝试重新加载 Cookie 并刷新页面（最多重试1次）
            await load_cookies(context)
            await page.goto(DOUBAO_URL, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
            if not await check_logged_in(page):
                # Cookie 确实已失效，无法恢复，退出
                print(f"  [Worker {worker_id}] ❌ Cookie 已彻底失效，请重新登录")
                async with lock:
                    results_dict[idx] = {"ok": False, "error": "cookie_expired", "question": question}
                break
            else:
                print(f"  [Worker {worker_id}] ✅ Cookie 重载成功，继续爬取")

        # 清空并输入问题
        await input_box.click()
        await page.wait_for_timeout(200)
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Delete")
        await input_box.fill(question)
        await page.wait_for_timeout(300)

        # 发送（用Enter，不点发送按钮避免误触）
        await page.keyboard.press("Enter")

        # 发送后检测是否立即弹出验证码
        await page.wait_for_timeout(800)
        try:
            await wait_for_captcha_if_needed(page, worker_id)
        except TimeoutError:
            # 验证码超时：跳过本题，继续下一题，不中断整个任务
            print(f"  [Worker {worker_id}] 人机验证超时，跳过本题继续")
            async with lock:
                results_dict[idx] = {"ok": False, "error": "人机验证超时", "question": question}
            continue

        # 等待并提取回答
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

        # 提取引用源（引用为0时等待后重试一次）
        refs = await get_refs(page)
        if len(refs) == 0:
            print(f"  ⚠️  [Worker {worker_id}] 引用源为空，等5秒重试...")
            await page.wait_for_timeout(5000)
            refs = await get_refs(page)
            if len(refs) == 0:
                print(f"  ⚠️  [Worker {worker_id}] 重试后仍为空，记录继续保存")

        result = {"ok": True, "answer": answer, "refs": refs, "question": question}
        async with lock:
            results_dict[idx] = result
        # 每题完成后立即保存Cookie，防止中途崩溃或Session失效丢失登录态
        try:
            await save_cookies(context)
        except:
            pass

        # ── 防频繁访问：每题完成后停留5秒 ──────────────────────
        print(f"  [Worker {worker_id}] 题目完成，停留5秒防频繁访问...")
        await page.wait_for_timeout(5000)

    await save_cookies(context)
    await browser.close()
    print(f"  [Worker {worker_id}] 完成")


# ── 批量爬取 ─────────────────────────────────────────────
async def crawl_batch_async(questions, progress_callback=None, parallel=2):
    os.makedirs("data", exist_ok=True)
    parallel = max(1, min(parallel, 3))

    # 用 (index, question) 元组，确保同一问题多次爬取时不互相覆盖
    indexed = [(i, q) for i, q in enumerate(questions)]

    chunks = [[] for _ in range(parallel)]
    for i, item in enumerate(indexed):
        chunks[i % parallel].append(item)
    chunks = [c for c in chunks if c]
    print(f"并行爬取：{len(questions)} 题 → {len(chunks)} 个窗口")

    results_dict = {}   # key = index (int)
    lock = asyncio.Lock()

    async with async_playwright() as pw:
        tasks = [crawl_worker(i+1, chunk, pw, results_dict, lock)
                 for i, chunk in enumerate(chunks)]
        # return_exceptions=True 确保单个 worker 崩溃不影响其他 worker
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                print(f"  [Worker {i+1}] 异常退出: {r}")

    # 按原始顺序还原结果，key 是 index
    all_results = [
        results_dict.get(i, {"ok": False, "error": "未执行", "question": q})
        for i, q in indexed
    ]
    success = [r for r in all_results if r.get("ok")]
    return {"ok": True, "total": len(questions), "success": len(success), "results": all_results}


def login_doubao():
    return asyncio.run(login_doubao_async())

def crawl_batch(questions, progress_callback=None):
    return asyncio.run(crawl_batch_async(questions, progress_callback))

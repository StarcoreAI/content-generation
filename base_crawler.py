"""
base_crawler.py — 各平台爬虫共用基础逻辑
关键修复：使用 storage_state 保存完整浏览器状态（含Cookie + localStorage + sessionStorage）
"""
import asyncio
import json
import os
import re
import pathlib as _pl
from datetime import datetime

_BASE_DIR = _pl.Path(__file__).resolve().parent
DATA_DIR = str(_BASE_DIR / "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ── storage_state 管理（同时保存Cookie + localStorage）──
def _state_path(platform: str) -> str:
    return os.path.join(DATA_DIR, f"{platform}_state.json")

def _cookie_path(platform: str) -> str:
    """兼容旧版doubao_cookies.json"""
    return os.path.join(DATA_DIR, f"{platform}_cookies.json")

def _login_status_path() -> str:
    return os.path.join(DATA_DIR, "platform_login_status.json")

def _load_login_statuses() -> dict:
    path = _login_status_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _save_login_statuses(data: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_login_status_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def mark_login_status(platform: str, status: str, message: str = ""):
    statuses = _load_login_statuses()
    statuses[platform] = {
        "status": status,
        "message": message,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save_login_statuses(statuses)

def get_saved_state_info(platform: str) -> dict:
    state_path = _state_path(platform)
    cookie_path = _cookie_path(platform)
    info = {
        "platform": platform,
        "state_file_exists": os.path.exists(state_path),
        "cookie_file_exists": os.path.exists(cookie_path),
        "has_saved_state": False,
        "cookie_count": 0,
        "origin_count": 0,
        "legacy_cookie_count": 0,
        "state_error": "",
    }

    if info["state_file_exists"]:
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            info["cookie_count"] = len(state.get("cookies", []))
            info["origin_count"] = len(state.get("origins", []))
        except Exception as e:
            info["state_error"] = str(e)

    if info["cookie_file_exists"]:
        try:
            with open(cookie_path, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            info["legacy_cookie_count"] = len(cookies) if isinstance(cookies, list) else 0
        except Exception as e:
            if not info["state_error"]:
                info["state_error"] = str(e)

    info["has_saved_state"] = (
        info["cookie_count"] > 0
        or info["origin_count"] > 0
        or info["legacy_cookie_count"] > 0
    )
    return info

def get_platform_login_status(platform: str) -> dict:
    state = get_saved_state_info(platform)
    statuses = _load_login_statuses()
    meta = statuses.get(platform, {})
    meta_status = meta.get("status", "")

    if not state["has_saved_state"]:
        status = "missing"
        logged_in = False
        message = "未保存登录状态"
    elif meta_status == "ok":
        status = "ok"
        logged_in = True
        message = meta.get("message") or "登录状态已保存"
    elif meta_status == "expired":
        status = "expired"
        logged_in = False
        message = meta.get("message") or "登录状态已过期，请重新登录"
    else:
        status = "unknown"
        logged_in = False
        message = "检测到登录状态文件，但尚未验证，请重新登录后继续"

    return {
        **state,
        "status": status,
        "logged_in": logged_in,
        "message": message,
        "checked_at": meta.get("updated_at", ""),
    }

async def save_cookies(context, platform: str, mark_ok: bool = False):
    """
    保存完整浏览器状态（Cookie + localStorage + sessionStorage）。
    对于使用localStorage存token的平台（DeepSeek/元宝/千问）是必须的。
    """
    path = _state_path(platform)
    try:
        state = await context.storage_state()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        cookie_count = len(state.get("cookies", []))
        origin_count = len(state.get("origins", []))
        if mark_ok:
            mark_login_status(platform, "ok", "登录状态已保存")
        print(f"[{platform}] 状态已保存: {path} (Cookie:{cookie_count}个 LocalStorage:{origin_count}个域)")
    except Exception as e:
        print(f"[{platform}] 状态保存失败: {e}")

async def verify_saved_login(browser, platform: str, url: str, check_logged_in, **context_kwargs) -> bool:
    """
    Save-time verification: open a fresh context from the persisted state and
    confirm the platform still looks logged in. This prevents false positives
    from public chat inputs or landing pages.
    """
    context = None
    try:
        context = await new_context_with_state(browser, platform, **context_kwargs)
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        ok = bool(await check_logged_in(page))
        if ok:
            mark_login_status(platform, "ok", "登录状态已保存并验证")
        else:
            mark_login_status(platform, "expired", "登录状态验证失败，请重新登录")
        return ok
    except Exception as e:
        mark_login_status(platform, "expired", f"登录状态验证失败: {e}")
        return False
    finally:
        if context:
            try:
                await context.close()
            except Exception:
                pass

async def load_cookies(context, platform: str) -> bool:
    """
    优先加载 storage_state，兼容旧版 cookies.json。
    """
    state_path = _state_path(platform)
    cookie_path = _cookie_path(platform)

    # 优先用新版 storage_state
    if os.path.exists(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            cookies = state.get("cookies", [])
            if cookies:
                await context.add_cookies(cookies)
            print(f"[{platform}] 状态已加载: {state_path} (Cookie:{len(cookies)}个)")
            return True
        except Exception as e:
            print(f"[{platform}] 状态加载失败: {e}")

    # 兼容旧版 cookies.json（豆包）
    if os.path.exists(cookie_path):
        try:
            with open(cookie_path, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            if cookies:
                await context.add_cookies(cookies)
                print(f"[{platform}] Cookie已加载(旧版): {cookie_path} ({len(cookies)}个)")
                return True
        except Exception as e:
            print(f"[{platform}] Cookie加载失败: {e}")

    print(f"[{platform}] 未找到登录状态文件")
    return False

def has_cookies(platform: str) -> bool:
    """检查是否有已保存的浏览器状态，不代表真实会话仍有效。"""
    return get_saved_state_info(platform)["has_saved_state"]

async def new_context_with_state(pw_browser, platform: str, **kwargs):
    """
    创建已加载登录状态的新 context。
    对 storage_state 用 new_context(storage_state=...) 是最可靠的方式。
    """
    state_path = _state_path(platform)
    cookie_path = _cookie_path(platform)

    # 优先用 storage_state 参数创建（最可靠，能还原localStorage）
    if os.path.exists(state_path):
        try:
            context = await pw_browser.new_context(
                storage_state=state_path,
                **kwargs
            )
            print(f"[{platform}] 使用storage_state创建context: {state_path}")
            return context
        except Exception as e:
            print(f"[{platform}] storage_state创建失败，降级: {e}")

    # 降级：普通context + add_cookies
    context = await pw_browser.new_context(**kwargs)
    if os.path.exists(cookie_path):
        try:
            with open(cookie_path) as f:
                cookies = json.load(f)
            if cookies:
                await context.add_cookies(cookies)
                print(f"[{platform}] 旧版Cookie已加载: {len(cookies)}个")
        except Exception as e:
            print(f"[{platform}] 旧版Cookie加载失败: {e}")
    return context

# ── 平台识别 ─────────────────────────────────────────────
def extract_platform(url: str) -> str:
    rules = [
        ("土巴兔",      ["to8to"]),
        ("新浪家居",    ["jiaju.sina"]),
        ("网易家居",    ["house.163", "jiaju.163"]),
        ("今日头条",    ["toutiao"]),
        ("搜狐",        ["sohu"]),
        ("百度百科",    ["baike.baidu"]),
        ("知乎",        ["zhihu"]),
        ("小红书",      ["xiaohongshu", "xhslink"]),
        ("抖音",        ["douyin"]),
        ("微信公众号",  ["mp.weixin"]),
        ("百家号",      ["baijiahao"]),
        ("凤凰网",      ["ifeng"]),
        ("腾讯新闻",    ["news.qq", "new.qq"]),
        ("网易新闻",    ["news.163"]),
        ("新浪新闻",    ["news.sina"]),
        ("大众点评",    ["dianping"]),
        ("58同城",      ["58.com"]),
        ("安居客",      ["anjuke"]),
        ("链家",        ["lianjia"]),
        ("IT之家",      ["ithome"]),
        ("36氪",        ["36kr"]),
        ("虎嗅",        ["huxiu"]),
        ("QQ新闻",      ["qq.com/news", "new.qq.com"]),
        ("新京报",      ["bjnews"]),
        ("中华网",      ["china.com"]),
        ("163",         ["163.com"]),
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

# ── 人机验证检测 ─────────────────────────────────────────
async def wait_for_captcha_if_needed(page, worker_id=0, platform=""):
    CAPTCHA_KEYWORDS = [
        "拼图", "滑块", "验证", "拖动", "人机", "安全验证",
        "drag", "slider", "captcha", "puzzle", "verify"
    ]
    CAPTCHA_SELECTORS = [
        '[class*="captcha"]', '[class*="verify"]', '[class*="slider"]',
        '[class*="puzzle"]', '[class*="drag"]',
        '[id*="captcha"]', '[id*="verify"]', 'canvas[width]',
    ]

    async def is_captcha_visible():
        try:
            body_text = await page.evaluate(
                "() => (document.body && document.body.innerText) || ''"
            )
            if sum(1 for kw in CAPTCHA_KEYWORDS if kw in body_text) >= 2:
                return True
        except:
            pass
        for sel in CAPTCHA_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
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

    if not await is_captcha_visible():
        return

    tag = f"[{platform or 'Worker'} {worker_id}]"
    print(f"\n  ⚠️  {tag} 检测到人机验证！请在浏览器完成验证，程序自动继续...\n")
    waited = 0
    MAX_WAIT = 300_000
    CHECK_INTERVAL = 1500
    while waited < MAX_WAIT:
        await page.wait_for_timeout(CHECK_INTERVAL)
        waited += CHECK_INTERVAL
        if not await is_captcha_visible():
            print(f"  ✅  {tag} 验证已通过，继续爬取...\n")
            await page.wait_for_timeout(1500)
            return
    raise TimeoutError("人机验证等待超时")

# ── 通用：等待内容稳定 ───────────────────────────────────
async def wait_until_stable(page, worker_id=0, platform="", max_ticks=60):
    last_len = 0
    stable = 0
    for tick in range(max_ticks):
        await page.wait_for_timeout(500)
        if tick % 10 == 9:
            await wait_for_captcha_if_needed(page, worker_id, platform)
        try:
            cur_len = await page.evaluate("""() => {
                let maxLen = 0;
                const divs = document.querySelectorAll('div, p, article');
                for (const el of divs) {
                    const t = (el.innerText || '').trim();
                    if (t.length > maxLen) maxLen = t.length;
                }
                return maxLen;
            }""")
        except:
            cur_len = last_len
        if cur_len > 100 and cur_len == last_len:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
            last_len = cur_len

# ── 通用：启动浏览器 ─────────────────────────────────────
async def launch_browser(pw, worker_id=1, headless=False):
    browser = await pw.chromium.launch(
        headless=headless,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            f"--window-position={worker_id * 440},0",
            "--window-size=440,720",
        ]
    )
    context = await browser.new_context(
        viewport={"width": 440, "height": 720},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    )
    return browser, context

async def launch_browser_with_state(pw, platform: str, worker_id=1, headless=False):
    """
    启动浏览器并用 storage_state 创建已登录的 context。
    这是最可靠的方式，能完整还原 localStorage 中的 token。
    """
    browser = await pw.chromium.launch(
        headless=headless,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            f"--window-position={worker_id * 440},0",
            "--window-size=440,720",
        ]
    )
    context = await new_context_with_state(
        browser, platform,
        viewport={"width": 440, "height": 720},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    )
    return browser, context

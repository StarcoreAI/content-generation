import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

function argValue(name, fallback = "") {
  const index = process.argv.indexOf(name);
  if (index < 0 || index + 1 >= process.argv.length) return fallback;
  return process.argv[index + 1];
}

function boolValue(value, fallback = false) {
  if (value === undefined || value === null || value === "") return fallback;
  return /^(1|true|yes|on)$/i.test(String(value));
}

function splitPlatforms(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
}

function positiveIntValue(value, fallback = 0) {
  const parsed = Number.parseInt(String(value || ""), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return parsed;
}

function authModeValue(value) {
  const mode = String(value || "strict").trim().toLowerCase();
  return ["strict", "soft", "manual"].includes(mode) ? mode : "strict";
}

function packagedBrowserRoot(crawlerRoot) {
  const browserRoot = path.join(crawlerRoot, "ms-playwright");
  if (!fs.existsSync(browserRoot)) return "";
  for (const entry of fs.readdirSync(browserRoot, { withFileTypes: true })) {
    if (!entry.isDirectory() || !entry.name.startsWith("chromium-")) continue;
    const chromiumRoot = path.join(browserRoot, entry.name);
    if (fs.existsSync(path.join(chromiumRoot, "chrome-win64", "chrome.exe"))) return browserRoot;
    if (fs.existsSync(path.join(chromiumRoot, "chrome-win", "chrome.exe"))) return browserRoot;
    if (hasMacChromiumExecutable(chromiumRoot)) return browserRoot;
  }
  return "";
}

function hasMacChromiumExecutable(chromiumRoot) {
  for (const entry of fs.readdirSync(chromiumRoot, { withFileTypes: true })) {
    if (!entry.isDirectory() || !entry.name.startsWith("chrome-mac")) continue;
    const macRoot = path.join(chromiumRoot, entry.name);
    for (const app of fs.readdirSync(macRoot, { withFileTypes: true })) {
      if (!app.isDirectory() || !app.name.endsWith(".app")) continue;
      const executableRoot = path.join(macRoot, app.name, "Contents", "MacOS");
      if (!fs.existsSync(executableRoot)) continue;
      if (fs.readdirSync(executableRoot, { withFileTypes: true }).some((item) => item.isFile())) return true;
    }
  }
  return false;
}

const STRICT_LOGIN_PLATFORMS = new Set(["qwen"]);

const PLATFORM_AUTH_COOKIES = {
  deepseek: [],
  doubao: [{
    hosts: ["doubao.com", "bytedance.com"],
    names: [
      "sessionid",
      "sessionid_ss",
      "sid_tt",
      "sid_guard",
      "sid_ucp_v1",
      "ssid_ucp_v1",
      "uid_tt",
      "uid_tt_ss"
    ]
  }],
  kimi: [{ hosts: ["kimi.com", "moonshot.cn"], names: ["kimi-auth"] }],
  qwen: [{ hosts: ["qianwen.com"], names: ["tongyi_sso_ticket", "tongyi_sso_ticket_hash"] }],
  yuanbao: [{ hosts: ["tencent.com", "yuanbao.tencent.com"], names: ["hy_token", "hy_user"] }],
  wenxin: [{
    hosts: ["baidu.com", "yiyan.baidu.com"],
    names: ["BDUSS", "BDUSS_BFESS", "STOKEN", "STOKEN_BFESS"]
  }]
};

function cookieIsUsable(cookie) {
  const expires = Number(cookie?.expires || 0);
  return Boolean(cookie?.value) && (expires <= 0 || expires > Date.now() / 1000);
}

function cookieMatchesPlatform(cookie, platform) {
  if (!cookieIsUsable(cookie)) return false;
  const domain = String(cookie.domain || "").toLowerCase();
  const name = String(cookie.name || "");
  return (PLATFORM_AUTH_COOKIES[platform] || []).some(
    (rule) => rule.names.includes(name) && rule.hosts.some((host) => {
      const normalizedDomain = domain.replace(/^\./, "");
      return normalizedDomain === host || normalizedDomain.endsWith(`.${host}`);
    })
  );
}

async function platformHasAuthCookie(page, platform) {
  const cookies = await page.context().cookies().catch(() => []);
  return cookies.some((cookie) => cookieMatchesPlatform(cookie, platform));
}

function storageValueHasAuth(rawValue) {
  const raw = String(rawValue ?? "").trim();
  if (!raw || raw === "null" || raw === "undefined") return false;
  try {
    const parsed = JSON.parse(raw);
    const value = parsed && typeof parsed === "object" && "value" in parsed
      ? parsed.value
      : parsed;
    return typeof value === "string" ? value.trim().length > 0 : Boolean(value);
  } catch {
    return true;
  }
}

function stateHasBrowserStorageAuth(state, platform) {
  const origins = Array.isArray(state?.origins) ? state.origins : [];
  for (const origin of origins) {
    const storage = Array.isArray(origin?.localStorage) ? origin.localStorage : [];
    const values = new Map(storage.map((item) => [String(item?.name || ""), item?.value]));
    if (
      platform === "deepseek" &&
      String(origin?.origin || "").includes("chat.deepseek.com") &&
      storageValueHasAuth(values.get("userToken"))
    ) {
      return true;
    }
    if (
      platform === "kimi" &&
      String(origin?.origin || "").includes("kimi.com") &&
      (storageValueHasAuth(values.get("access_token")) || storageValueHasAuth(values.get("refresh_token")))
    ) {
      return true;
    }
  }
  return false;
}

function stateHasVerifiedAuth(state, platform) {
  const cookies = Array.isArray(state?.cookies) ? state.cookies : [];
  return (
    cookies.some((cookie) => cookieMatchesPlatform(cookie, platform)) ||
    stateHasBrowserStorageAuth(state, platform)
  );
}

async function platformHasBrowserStorageAuth(page, platform) {
  if (!new Set(["deepseek", "kimi"]).has(platform)) return false;
  return page.evaluate((currentPlatform) => {
    const hasAuthValue = (rawValue) => {
      const raw = String(rawValue ?? "").trim();
      if (!raw || raw === "null" || raw === "undefined") return false;
      try {
        const parsed = JSON.parse(raw);
        const value = parsed && typeof parsed === "object" && "value" in parsed
          ? parsed.value
          : parsed;
        return typeof value === "string" ? value.trim().length > 0 : Boolean(value);
      } catch {
        return true;
      }
    };
    if (currentPlatform === "deepseek") {
      return hasAuthValue(window.localStorage.getItem("userToken"));
    }
    return (
      hasAuthValue(window.localStorage.getItem("access_token")) ||
      hasAuthValue(window.localStorage.getItem("refresh_token"))
    );
  }, platform).catch(() => false);
}

async function platformHasAuthEvidence(page, platform) {
  return (
    await platformHasAuthCookie(page, platform) ||
    await platformHasBrowserStorageAuth(page, platform)
  );
}

function validateSavedState(storageState, platform) {
  const raw = fs.readFileSync(storageState, "utf8");
  const state = JSON.parse(raw);
  const cookies = Array.isArray(state.cookies) ? state.cookies : [];
  const hasAuthCookie = cookies.some((cookie) => cookieMatchesPlatform(cookie, platform));
  const hasBrowserStorageAuth = stateHasBrowserStorageAuth(state, platform);
  if (!stateHasVerifiedAuth(state, platform)) {
    throw new Error(`saved state has no verified ${platform} login credential`);
  }
  return { hasAuthCookie, hasBrowserStorageAuth };
}

async function saveStorageState(context, adapter, storageState) {
  const adapterOptions =
    typeof adapter.getStorageStateOptions === "function"
      ? adapter.getStorageStateOptions()
      : {};
  try {
    await context.storageState({
      path: storageState,
      indexedDB: true,
      ...adapterOptions
    });
  } catch (error) {
    console.log(`[GEO] storage-state extended save failed; retrying compatible mode: ${error.message}`);
    await context.storageState({ path: storageState, indexedDB: true });
  }
}

async function saveVerifiedStorageState(context, adapter, page, platform, storageState) {
  const tempState = `${storageState}.tmp-${process.pid}-${Date.now()}`;
  try {
    if (page.isClosed()) {
      throw new Error("browser page was closed before login state could be saved");
    }
    await saveStorageState(context, adapter, tempState);
    const evidence = validateSavedState(tempState, platform);
    fs.copyFileSync(tempState, storageState);
    console.log(
      `[GEO] ${platform}: login state saved (${evidence.hasAuthCookie ? "auth cookie" : "browser token"}) -> ${storageState}`
    );
  } finally {
    fs.rmSync(tempState, { force: true });
  }
}

async function genericInputReady(page, timeoutMs = 1500) {
  const selectors = [
    "textarea:visible:not([aria-hidden='true'])",
    "[contenteditable='true'][role='textbox']:visible",
    "[contenteditable='true']:visible",
    "input[type='text']:visible"
  ];
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const selector of selectors) {
      const input = page.locator(selector).first();
      const visible = await input.isVisible({ timeout: 300 }).catch(() => false);
      if (visible) return true;
    }
    await page.waitForTimeout(250);
  }
  return false;
}

async function pageHasLoginBlocker(page) {
  return Promise.race([
    page.evaluate(() => {
      const visible = (element) => {
        if (!element || element.nodeType !== Node.ELEMENT_NODE) return false;
        const style = window.getComputedStyle(element);
        return (
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          style.opacity !== "0" &&
          element.getClientRects().length > 0
        );
      };
      const compact = (value) => String(value || "").replace(/\s+/g, " ").trim();
      const url = String(window.location.href || "");
      if (/login|passport|oauth|signin|sign-in/i.test(url)) return true;

      const loginPattern =
        /\u767b\u5f55|\u767b\u5165|\u6ce8\u518c|\u626b\u7801\u767b\u5f55|\u624b\u673a\u53f7\u767b\u5f55|\u9a8c\u8bc1\u7801\u767b\u5f55|Log in|Sign in|Sign up/i;
      const roots = Array.from(
        document.querySelectorAll(
          "[role='dialog'], [aria-modal='true'], [class*='modal'], [class*='dialog'], [class*='login'], [class*='passport']"
        )
      ).filter(visible);
      if (roots.some((root) => loginPattern.test(compact(root.innerText || root.textContent || "")))) {
        return true;
      }

      return Array.from(document.querySelectorAll("button, a, [role='button']"))
        .filter(visible)
        .some((node) =>
          /^(\u767b\u5f55|\u767b\u5165|\u6ce8\u518c|\u767b\u5f55\s*\/\s*\u6ce8\u518c|\u7acb\u5373\u767b\u5f55|\u626b\u7801\u767b\u5f55|Log in|Sign in|Sign up)$/i.test(
            compact(node.textContent || node.getAttribute("aria-label") || node.getAttribute("title") || "")
          )
        );
    }),
    new Promise((resolve) => setTimeout(() => resolve(false), 1000))
  ]).catch(() => false);
}

async function qwenHasVisibleLoginAction(page) {
  const loginText = "\u767b\u5f55";
  const directSelectors = [
    `button:has-text("${loginText}")`,
    `a:has-text("${loginText}")`,
    `[role='button']:has-text("${loginText}")`,
    `[aria-label*="${loginText}"]`,
    `[title*="${loginText}"]`
  ];
  for (const selector of directSelectors) {
    const visible = await page.locator(selector).first().isVisible({ timeout: 300 }).catch(() => false);
    if (visible) return true;
  }

  return Promise.race([
    page.evaluate(() => {
      const visible = (element) => {
        if (!element || element.nodeType !== Node.ELEMENT_NODE) return false;
        const style = window.getComputedStyle(element);
        return (
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          style.opacity !== "0" &&
          element.getClientRects().length > 0
        );
      };
      const compact = (value) => String(value || "").replace(/\s+/g, " ").trim();
      const nodeText = (node) =>
        compact(
          [
            node.textContent,
            node.getAttribute?.("aria-label"),
            node.getAttribute?.("title"),
            node.getAttribute?.("data-testid"),
            node.getAttribute?.("class")
          ]
            .filter(Boolean)
            .join(" ")
        );
      const url = String(window.location.href || "");
      if (/login|passport|oauth|signin|sign-in/i.test(url)) return true;

      const loginPattern =
        /\u767b\u5f55|\u767b\u5165|\u6ce8\u518c|\u7acb\u5373\u767b\u5f55|\u53bb\u767b\u5f55|\u624b\u673a\u53f7\u767b\u5f55|\u626b\u7801\u767b\u5f55|\u9a8c\u8bc1\u7801\u767b\u5f55|Log in|Sign in|Sign up/i;
      return Array.from(
        document.querySelectorAll("button, a, [role='button'], [aria-label], [title], span, div")
      )
        .filter(visible)
        .map(nodeText)
        .filter((text) => text && text.length <= 80)
        .some((text) => loginPattern.test(text));
    }),
    new Promise((resolve) => setTimeout(() => resolve(false), 1000))
  ]).catch(() => false);
}

async function qwenHasSessionCookie(page) {
  const cookies = await page.context().cookies().catch(() => []);
  return cookies.some((cookie) => {
    const domain = String(cookie.domain || "").toLowerCase();
    const name = String(cookie.name || "");
    const expires = Number(cookie.expires || 0);
    const notExpired = expires <= 0 || expires > Date.now() / 1000;
    return (
      domain.includes("qianwen.com") &&
      ["tongyi_sso_ticket", "tongyi_sso_ticket_hash"].includes(name) &&
      Boolean(cookie.value) &&
      notExpired
    );
  });
}

async function qwenHasAccountSignal(page) {
  return Promise.race([
    page.evaluate(() => {
      const visible = (element) => {
        if (!element || element.nodeType !== Node.ELEMENT_NODE) return false;
        const style = window.getComputedStyle(element);
        return (
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          style.opacity !== "0" &&
          element.getClientRects().length > 0
        );
      };
      const compact = (value) => String(value || "").replace(/\s+/g, " ").trim();
      const nodeText = (node) =>
        compact(
          [
            node.textContent,
            node.getAttribute?.("aria-label"),
            node.getAttribute?.("title"),
            node.getAttribute?.("data-testid"),
            node.getAttribute?.("class")
          ]
            .filter(Boolean)
            .join(" ")
        );
      const url = String(window.location.href || "");
      if (/login|passport|oauth|signin|sign-in/i.test(url)) return false;

      const loginPattern =
        /\u767b\u5f55|\u767b\u5165|\u6ce8\u518c|\u7acb\u5373\u767b\u5f55|\u53bb\u767b\u5f55|\u624b\u673a\u53f7\u767b\u5f55|\u626b\u7801\u767b\u5f55|\u9a8c\u8bc1\u7801\u767b\u5f55|Log in|Sign in|Sign up/i;
      const actionTexts = Array.from(
        document.querySelectorAll("button, a, [role='button'], [aria-label], [title]")
      )
        .filter(visible)
        .map(nodeText)
        .filter((text) => text && text.length <= 80);
      if (actionTexts.some((text) => loginPattern.test(text))) return false;

      const accountPattern =
        /\u5934\u50cf|\u4e2a\u4eba\u4e2d\u5fc3|\u4e2a\u4eba\u8d44\u6599|\u8d26\u53f7|\u8d26\u6237|\u9000\u51fa\u767b\u5f55|\u6211\u7684\u8d26\u6237|Profile|Account|Logout|Sign out/i;
      const accountTexts = Array.from(
        document.querySelectorAll(
          "button, a, [role='button'], [aria-label], [title], [class*='avatar'], [class*='profile'], [class*='account']"
        )
      )
        .filter(visible)
        .map(nodeText)
        .filter((text) => text && text.length <= 160);

      return accountTexts.some((text) => accountPattern.test(text));
    }),
    new Promise((resolve) => setTimeout(() => resolve(false), 1000))
  ]).catch(() => false);
}

async function qwenLoginState(page) {
  const state = {
    loginAction: await qwenHasVisibleLoginAction(page),
    sessionCookie: false,
    accountSignal: false,
    loggedIn: false
  };
  state.sessionCookie = await qwenHasSessionCookie(page);
  if (!state.loginAction) {
    state.accountSignal = await qwenHasAccountSignal(page);
  }
  // b-user-id exists for guests. The SSO ticket is the actual login signal;
  // account/avatar markup is only diagnostic because the current UI may hide it.
  state.loggedIn = !state.loginAction && state.sessionCookie;
  return state;
}

async function qwenIsLoggedIn(page) {
  return (await qwenLoginState(page)).loggedIn;
}

async function waitForPlatformReady(adapter, page, timeoutMs, platformOverride = "") {
  const deadline = Date.now() + timeoutMs;
  const platform = platformOverride || adapter?.name || "";
  let lastQwenStateMessage = "";
  while (Date.now() < deadline) {
    if (page.isClosed()) {
      console.log(`[GEO] ${platform}: browser was closed before login state was saved.`);
      return false;
    }
    let loggedIn = false;
    if (platform === "qwen" && STRICT_LOGIN_PLATFORMS.has(platform)) {
      const state = await qwenLoginState(page).catch(() => ({
        loginAction: false,
        sessionCookie: false,
        accountSignal: false,
        loggedIn: false
      }));
      loggedIn = state.loggedIn;
      const stateMessage =
        `loginAction=${state.loginAction} sessionCookie=${state.sessionCookie} accountSignal=${state.accountSignal} loggedIn=${state.loggedIn}`;
      if (stateMessage !== lastQwenStateMessage) {
        console.log(`[GEO] qwen login state: ${stateMessage}`);
        lastQwenStateMessage = stateMessage;
      }
    } else {
      const adapterLoggedIn =
        typeof adapter.isLoggedIn === "function"
          ? await adapter.isLoggedIn(page).catch(() => false)
          : !(await pageHasLoginBlocker(page));
      const authEvidence = await platformHasAuthEvidence(page, platform);
      const visibleLoginBlocker = authEvidence
        ? await pageHasLoginBlocker(page).catch(() => false)
        : true;
      // Guest pages can expose a working-looking composer. Every supported
      // platform must have a verified login cookie/token before it can pass.
      loggedIn = authEvidence && (adapterLoggedIn || !visibleLoginBlocker);
    }
    let ready = false;
    if (loggedIn && typeof adapter.waitUntilInputReady === "function") {
      ready = await adapter.waitUntilInputReady(page, 1500).catch(() => false);
    } else if (loggedIn && typeof adapter.resolveInput === "function") {
      ready = Boolean(await adapter.resolveInput(page, 1500).catch(() => null));
    } else if (loggedIn) {
      ready = await genericInputReady(page, 1500);
    }
    if (loggedIn && ready) {
      await page.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(500);
      return true;
    }
    await page.waitForTimeout(1000);
  }
  return false;
}

async function openHome(adapter, page) {
  await adapter.gotoHome(page, { nonInteractive: true, workerId: 1 }).catch(async () => {
    if (adapter.baseUrl) {
      await page.goto(adapter.baseUrl, { waitUntil: "domcontentloaded" });
    } else {
      throw new Error("adapter.gotoHome failed and adapter.baseUrl is unavailable");
    }
  });
  await page.waitForLoadState("domcontentloaded", { timeout: 5000 }).catch(() => {});
}

async function holdQwenPageForDebugging(platform, page) {
  if (platform !== "qwen") return;
  const holdMs = positiveIntValue(process.env.GEO_QWEN_AUTH_DEBUG_HOLD_MS, 0);
  if (!holdMs) return;

  console.log(`[GEO] qwen: debug hold ${Math.round(holdMs / 1000)}s before login decision.`);
  await page.waitForTimeout(holdMs);
}

async function platformHasVisibleLoginBlocker(adapter, page, platform) {
  if (platform === "qwen") {
    const state = await qwenLoginState(page).catch(() => ({ loginAction: false }));
    return Boolean(state.loginAction);
  }
  return pageHasLoginBlocker(page);
}

async function runPlatform(platform, adapter, browser, storageState, timeoutMs, authMode = "strict") {
  const contextOptions = {
    viewport: boolValue(process.env.GEO_LOGIN_CHECK_HEADLESS ?? process.env.HEADLESS, false)
      ? { width: 1365, height: 900 }
      : null
  };
  if (fs.existsSync(storageState)) {
    contextOptions.storageState = storageState;
  }

  const context = await browser.newContext(contextOptions);
  const page = await context.newPage();
  page.setDefaultTimeout(Math.min(timeoutMs, 30_000));
  try {
    console.log(`[GEO] checking ${platform} login (${authMode})...`);
    await openHome(adapter, page);
    await holdQwenPageForDebugging(platform, page);
    let ready = await waitForPlatformReady(adapter, page, 10_000, platform);
    const needsLogin = !ready && await platformHasVisibleLoginBlocker(adapter, page, platform);
    if (!ready && authMode === "soft" && !needsLogin) {
      console.log(`[GEO] ${platform}: soft login check did not confirm readiness; continuing.`);
      return true;
    }
    if (!ready) {
      const action = authMode === "manual" ? "finish login" : "confirm login";
      console.log(`[GEO] ${platform}: please ${action} in the browser. Keep the browser open; it will close automatically after the login state is safely saved.`);
      ready = await waitForPlatformReady(adapter, page, timeoutMs, platform);
    }
    if (!ready) {
      console.log(`[GEO] ${platform}: login was not completed or the browser was closed before saving.`);
      return false;
    }
    await saveVerifiedStorageState(context, adapter, page, platform, storageState);
    console.log(`[GEO] ${platform}: login ready.`);
    return true;
  } finally {
    await context.close().catch(() => {});
  }
}

async function main() {
  process.env.GEO_NODE_BRIDGE = "1";

  const platforms = splitPlatforms(argValue("--platforms"));
  const crawlerRoot = path.resolve(argValue("--crawler-root", process.cwd()));
  if (process.env.PLAYWRIGHT_BROWSERS_PATH && !fs.existsSync(process.env.PLAYWRIGHT_BROWSERS_PATH)) {
    delete process.env.PLAYWRIGHT_BROWSERS_PATH;
  }
  if (!process.env.PLAYWRIGHT_BROWSERS_PATH) {
    const browserRoot = packagedBrowserRoot(crawlerRoot);
    if (browserRoot) process.env.PLAYWRIGHT_BROWSERS_PATH = browserRoot;
  }
  const storageState = path.resolve(argValue("--storage-state"));
  const timeoutMs = Math.max(30_000, Number(argValue("--timeout-ms", "1800000")) || 1_800_000);
  const authMode = authModeValue(argValue("--mode", "strict"));
  if (!platforms.length) {
    console.error("[GEO] no platforms provided.");
    process.exitCode = 2;
    return;
  }

  fs.mkdirSync(path.dirname(storageState), { recursive: true });

  const requireFromCrawler = createRequire(path.join(crawlerRoot, "package.json"));
  const { chromium } = requireFromCrawler("playwright");
  const adaptersModule = await import(pathToFileURL(path.join(crawlerRoot, "src", "adapters", "index.js")).href);
  const headless = boolValue(process.env.GEO_LOGIN_CHECK_HEADLESS ?? process.env.HEADLESS, false);
  const browser = await chromium.launch({
    headless,
    slowMo: 0,
    args: headless ? [] : ["--start-maximized"]
  });

  try {
    for (const platform of platforms) {
      const adapter = adaptersModule.getAdapter(platform);
      const ok = await runPlatform(platform, adapter, browser, storageState, timeoutMs, authMode);
      if (!ok) {
        process.exitCode = 1;
        return;
      }
    }
  } finally {
    await browser.close().catch(() => {});
  }

  console.log("[GEO] all platform logins are ready.");
}

const isDirectRun = Boolean(process.argv[1]) &&
  import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;

if (isDirectRun) {
  main().catch((error) => {
    console.error(`[GEO] auth preflight failed: ${error?.message || String(error)}`);
    process.exitCode = 1;
  });
}

export { qwenLoginState, stateHasVerifiedAuth };

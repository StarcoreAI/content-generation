import { pathToFileURL } from "node:url";
import path from "node:path";

const crawlerRoot = String(process.env.GEO_NODE_CRAWLER_ROOT || "").trim();
if (!crawlerRoot) {
  throw new Error("GEO_NODE_CRAWLER_ROOT is required by the Wenxin adapter override");
}

const baseAdapterUrl = pathToFileURL(
  path.join(crawlerRoot, "src", "adapters", "baseAdapter.js")
).href;
const externalAdapterUrl = pathToFileURL(
  path.join(crawlerRoot, "src", "adapters", "wenxinAdapter.js")
).href;
const [{ BaseAdapter }, { WenxinAdapter: ExternalWenxinAdapter }] = await Promise.all([
  import(baseAdapterUrl),
  import(externalAdapterUrl)
]);

if (!ExternalWenxinAdapter?.prototype) {
  throw new Error("External crawler does not export a compatible WenxinAdapter");
}

function randomInt(min, max) {
  const lower = Math.ceil(min);
  const upper = Math.floor(max);
  return Math.floor(Math.random() * (upper - lower + 1)) + lower;
}

class ManagedWenxinAdapter extends BaseAdapter {
  constructor() {
    super("wenxin", "https://wenxin.baidu.com/");
    this.answerCountBeforeSubmitByPage = new WeakMap();
    this.submittedPromptByPage = new WeakMap();
  }

  getFollowUpPlan() {
    return {
      followUp1: false,
      followUp2: true
    };
  }

  getStorageStateOptions() {
    return {
      indexedDB: true
    };
  }

  async beforeFollowUps(page) {
    await this.openLatestSourceSidebar(page, "before follow-up");
  }

  async openLatestSourceSidebar(page, reason = "extract citations") {
    try {
      if (/wenxin\.baidu\.com/i.test(page.url())) {
        const referenceLists = page.locator("ol[class*='_reference-list_']").filter({
          has: page.locator("li[data-long-press-ext-info], li[class*='_reference-item_']")
        });
        const listCount = await referenceLists.count();
        if (listCount) {
          const sourceItems = referenceLists.last().locator(
            "li[data-long-press-ext-info], li[class*='_reference-item_']"
          );
          console.log(
            `[Wenxin] reference dropdown DOM detected (${reason}), items=${await sourceItems.count()}`
          );
          return true;
        }

        const summaries = page
          .locator(".thinking-steps-title-extra, [class*='thinking-steps-title-extra']")
          .filter({ hasText: /(?:共参考|查看)\s*\d+\s*篇(?:参考)?资料/ });
        const summaryCount = await summaries.count();
        if (!summaryCount) {
          console.log(`[Wenxin] no reference dropdown found on latest answer (${reason})`);
          return false;
        }

        const summary = summaries.last();
        const container = summary.locator(
          "xpath=ancestor::div[contains(@class, '_collapse-container_')][1]"
        );
        const sourceItems = container.locator(
          "ol[class*='_reference-list_'] li[data-long-press-ext-info], ol[class*='_reference-list_'] li[class*='_reference-item_']"
        );
        const itemCount = await sourceItems.count();
        if (itemCount > 0 && (await sourceItems.first().isVisible().catch(() => false))) {
          console.log(`[Wenxin] reference dropdown already expanded (${reason}), items=${itemCount}`);
          return true;
        }

        const toggle = summary.locator(
          "xpath=ancestor::*[contains(@class, '_could-expand_')][1]"
        );
        await toggle.click({ timeout: 5_000, delay: randomInt(40, 120) });
        await sourceItems.first().waitFor({ state: "visible", timeout: 8_000 });
        console.log(
          `[Wenxin] expanded latest reference dropdown (${reason}), items=${await sourceItems.count()}`
        );
        return true;
      }

      const clicked = await Promise.race([
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
          const thinkingPattern =
            /深度思考|思考中|思考过程|已深度思考|展开思考|收起思考|推理中|推理过程|reasoning|thinking/i;
          const isThinkingOnly = (element) => {
            const text = compact(element?.innerText || element?.textContent || "");
            if (!text) return false;
            const hasAnswerRoot = Boolean(element?.querySelector?.("#answer_text_id"));
            return thinkingPattern.test(text) && !hasAnswerRoot;
          };

          const answerRoots = Array.from(document.querySelectorAll("#answer_text_id"))
            .filter(visible)
            .sort((a, b) => {
              const rectA = a.getBoundingClientRect();
              const rectB = b.getBoundingClientRect();
              return rectA.top - rectB.top || rectA.bottom - rectB.bottom;
            });
          const answerRoot = [...answerRoots]
            .reverse()
            .find((root) => !isThinkingOnly(root.closest(".flexBox__btVTGt0X") || root));
          if (!answerRoot) {
            return { clicked: false, reason: "no answer root" };
          }

          const answerRect = answerRoot.getBoundingClientRect();
          const triggerSelectors = [
            ".titleText__NtUo8QGH",
            "[class*='titleText']",
            "[class*='source']",
            "[class*='reference']",
            "[class*='citation']"
          ];
          const triggers = Array.from(document.querySelectorAll(triggerSelectors.join(",")))
            .filter(visible)
            .map((node) => {
              const rect = node.getBoundingClientRect();
              const text = compact(node.innerText || node.textContent || node.getAttribute("title") || "");
              const container = answerRoot.closest(".flexBox__btVTGt0X") || answerRoot.parentElement || answerRoot;
              const sameContainer = container.contains(node);
              const aboveAnswer = rect.bottom <= answerRect.top + 12;
              const verticalDistance = aboveAnswer
                ? Math.abs(answerRect.top - rect.bottom)
                : Math.abs(rect.top - answerRect.bottom) + 800;
              const likelyText = /引用|参考|来源|资料|篇|搜索|title/i.test(text) || node.matches(".titleText__NtUo8QGH");
              const score =
                (sameContainer ? 0 : 1000) +
                (aboveAnswer ? 0 : 3000) +
                (likelyText ? 0 : 1500) +
                verticalDistance;
              return { node, text, rect, score, aboveAnswer };
            })
            .filter((item) => item.aboveAnswer || item.score < 2500)
            .sort((a, b) => a.score - b.score);

          const target = triggers[0]?.node;
          if (!target) {
            return {
              clicked: false,
              reason: "no nearby source trigger",
              answerTop: Math.round(answerRect.top),
              answerBottom: Math.round(answerRect.bottom),
              triggerCount: triggers.length
            };
          }

          target.scrollIntoView({ block: "center", inline: "nearest" });
          target.click();
          return {
            clicked: true,
            text: compact(target.innerText || target.textContent || target.getAttribute("title") || "").slice(0, 80),
            answerTop: Math.round(answerRect.top),
            answerBottom: Math.round(answerRect.bottom)
          };
        }),
        new Promise((resolve) => setTimeout(() => resolve({ clicked: false, reason: "click timeout" }), 4_000))
      ]);

      if (!clicked?.clicked) {
        throw new Error(clicked?.reason || "latest source trigger not clicked");
      }
      console.log(
        `[Wenxin] clicked source trigger above latest answer (${reason}), text="${clicked.text || ""}"`
      );
      await page.waitForTimeout(800);

      const sourceItem = page.locator(".item__IBNbaily").first();
      await sourceItem.waitFor({ state: "visible", timeout: 8_000 });
      console.log("[Wenxin] source sidebar list detected, continue workflow");
      return true;
    } catch (err) {
      console.log(`[Wenxin] source sidebar not ready in time, continue anyway: ${err.message}`);
      return false;
    }
  }

  normalizeText(text) {
    if (!text) return "";
    try {
      const normalized = String(text)
        .split("")
        .map((char) => {
          const code = char.charCodeAt(0);
          if (code >= 128 && code <= 255) {
            try {
              return decodeURIComponent(
                "%" + code.toString(16).padStart(2, "0")
              );
            } catch {
              return char;
            }
          }
          return char;
        })
        .join("");
      return normalized;
    } catch {
      return String(text);
    }
  }

  async resolveInput(page, timeoutMs = 30_000) {
    const selectors = [
      "#chat-textarea:visible",
      "textarea:visible:not([aria-hidden='true'])",
      "[contenteditable='true'][role='textbox']:visible",
      "[contenteditable='true']:visible",
      "input[type='text']:visible"
    ];
    const start = Date.now();

    while (Date.now() - start < timeoutMs) {
      for (const selector of selectors) {
        const input = page.locator(selector).first();
        try {
          await input.waitFor({ state: "visible", timeout: 1_000 });
          return input;
        } catch {
          // Try next selector.
        }
      }
    }

    throw new Error("No visible input box found on wenxin page");
  }

  async detectLoginBlocker(page) {
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
        if (/login|passport|oauth/i.test(url)) {
          return { blocked: true, message: "login url detected" };
        }

        const loginPattern =
          /登录|登入|百度账号|扫码登录|手机号登录|验证码登录|账号密码登录|立即登录|请先登录|login|sign in/i;
        const explicitLoggedOutMarker = Array.from(
          document.querySelectorAll(".chat-aside-user-mask.unlogin, [class*='user-mask'][class*='unlogin']")
        ).find(visible);
        if (explicitLoggedOutMarker) {
          return { blocked: true, message: "wenxin logged-out marker detected" };
        }

        const editable = Array.from(
          document.querySelectorAll(
            "textarea, [contenteditable='true'][role='textbox'], [contenteditable='true'], input[type='text']"
          )
        ).find((node) => visible(node) && !node.disabled && !node.readOnly);

        const roots = Array.from(
          document.querySelectorAll(
            "[role='dialog'], [aria-modal='true'], [class*='modal'], [class*='dialog'], [class*='login'], [class*='passport']"
          )
        ).filter(visible);

        for (const root of roots) {
          const text = compact(root.innerText || root.textContent || "");
          if (loginPattern.test(text)) {
            return { blocked: true, message: text.slice(0, 100) };
          }
        }

        const loginAction = Array.from(document.querySelectorAll("button, a, [role='button']"))
          .filter(visible)
          .map((node) => compact(node.textContent || node.getAttribute("aria-label") || node.getAttribute("title") || ""))
          .find((text) =>
            /^(登录|登入|立即登录|扫码登录|手机号登录|百度账号登录|Log in|Sign in)$/i.test(text)
          );
        if (loginAction && !editable) {
          return { blocked: true, message: `login action detected: ${loginAction}` };
        }

        if (!editable) {
          const bodyText = compact(document.body?.innerText || "");
          if (bodyText.length < 2000 && loginPattern.test(bodyText)) {
            return { blocked: true, message: bodyText.slice(0, 100) };
          }
        }

        return { blocked: false, message: "" };
      }),
      new Promise((resolve) => setTimeout(() => resolve({ blocked: false, message: "" }), 1_000))
    ]).catch(() => ({ blocked: false, message: "" }));
  }

  async isLoggedIn(page) {
    const blocker = await this.detectLoginBlocker(page);
    if (blocker.blocked) return false;

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
        const editable = Array.from(
          document.querySelectorAll(
            "textarea, [contenteditable='true'][role='textbox'], [contenteditable='true'], input[type='text']"
          )
        ).find((node) => visible(node) && !node.disabled && !node.readOnly);
        if (!editable) return false;

        const explicitLoggedOutMarker = Array.from(
          document.querySelectorAll(".chat-aside-user-mask.unlogin, [class*='user-mask'][class*='unlogin']")
        ).find(visible);
        if (explicitLoggedOutMarker) return false;

        const bodyText = String(document.body?.innerText || "");
        if (
          !editable &&
          bodyText.length < 2000 &&
          /请先登录|扫码登录|百度账号|手机号登录|验证码登录|立即登录/.test(bodyText)
        ) {
          return false;
        }

        return true;
      }),
      new Promise((resolve) => setTimeout(() => resolve(false), 3_000))
    ]).catch(() => false);
  }

  async waitForLoginReady(page, timeoutMs = 120_000) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (await this.isLoggedIn(page)) {
        await page.waitForTimeout(1_000);
        return true;
      }
      await page.waitForTimeout(1_000);
    }
    return false;
  }

  async gotoHome(page) {
    await page.goto(this.baseUrl, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
  }

  async startNewConversation(page) {
    // Wenxin may show the "task mode" onboarding modal above the home page.
    // Escape closes it without accepting or changing any user preference.
    await page.keyboard.press("Escape").catch(() => {});
    await page.waitForTimeout(300);

    const selectors = [
      "button:has-text('开启新对话'):visible",
      "[role='button']:has-text('开启新对话'):visible",
      ":text-is('开启新对话'):visible",
      ".new-dialog-container:visible",
      ".new-dialog-container-button:visible",
      ".sidebarNewSession__DmglL_Yc:visible",
      ".sidebarNewSession__DmglL_Yc"
    ];

    for (const selector of selectors) {
      const trigger = page.locator(selector).first();
      try {
        await trigger.waitFor({ state: "visible", timeout: 3_000 });
        await trigger.click({ delay: randomInt(40, 120) });
        await page.waitForTimeout(randomInt(600, 1_400));
        console.log(`[Wenxin] created new conversation by selector: ${selector}`);
        return;
      } catch {
        // Try next selector.
      }
    }

    throw new Error("Failed to find Wenxin new-conversation trigger");
  }

  async beforeMainQuery(page) {
    console.log("[Wenxin] creating a fresh conversation requested by scheduler");
    await this.startNewConversation(page);
    await this.resolveInput(page, 30_000);
  }

  async readInputText(input) {
    return input
      .evaluate((node) => {
        const tag = String(node.tagName || "").toLowerCase();
        if (tag === "textarea" || tag === "input") return node.value || "";
        return node.innerText || node.textContent || "";
      })
      .catch(() => "");
  }

  async ensureInputContains(page, input, message) {
    const expected = String(message || "").trim();
    const normalize = (value) => String(value || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();

    for (let attempt = 0; attempt < 4; attempt += 1) {
      const current = normalize(await this.readInputText(input));
      if (current === normalize(expected) || current.includes(normalize(expected))) {
        return true;
      }

      await input.fill(expected).catch(async () => {
        await input.press("ControlOrMeta+A").catch(() => {});
        await input.press("Backspace").catch(() => {});
        await input.type(expected, { delay: 8 }).catch(() => {});
      });
      await page.waitForTimeout(400);
    }

    const finalText = normalize(await this.readInputText(input));
    return finalText === normalize(expected) || finalText.includes(normalize(expected));
  }

  async submitQuery(page, query) {
    const message = String(query || "").trim();
    if (!message) {
      throw new Error("Query is empty");
    }

    const answerCountBeforeSubmit = await page
      .evaluate(() => {
        const legacyAnswers = document.querySelectorAll("#answer_text_id");
        return legacyAnswers.length || document.querySelectorAll(".answer-box").length;
      })
      .catch(() => 0);
    this.answerCountBeforeSubmitByPage.set(page, answerCountBeforeSubmit);
    this.submittedPromptByPage.set(page, message);

    const input = await this.resolveInput(page, 30_000);
    await input.click({ delay: randomInt(40, 120) }).catch(() => {});
    await page.waitForTimeout(randomInt(100, 250));

    // Prefer keyboard clear to mimic real input behavior.
    await input.press("ControlOrMeta+A").catch(() => {});
    await input.press("Backspace").catch(() => {});
    await page.waitForTimeout(randomInt(80, 200));

    try {
      await input.fill(message);
    } catch {
      const typeDelay = message.length > 120 ? randomInt(8, 18) : randomInt(18, 35);
      const lines = message.split(/\r?\n/);
      for (let i = 0; i < lines.length; i += 1) {
        const line = lines[i] ?? "";
        if (line) {
          await input.type(line, { delay: typeDelay });
        }
        if (i < lines.length - 1) {
          await input.press("Shift+Enter");
          await page.waitForTimeout(randomInt(40, 100));
        }
      }
    }

    const inputReady = await this.ensureInputContains(page, input, message);
    if (!inputReady) {
      throw new Error("Wenxin input did not contain the full message before submit");
    }

    await page.waitForTimeout(randomInt(500, 900));
    await input.press("Enter");

    const userMessage = page.locator(`text=${message}`).first();
    try {
      await userMessage.waitFor({ state: "visible", timeout: 3_000 });
    } catch {
      const sendBtn = page
        .locator(
          "#ci-submit-button-ai, .ci-submit-button, button:has-text('发送'), button[aria-label*='发送'], button[data-testid*='send']"
        )
        .first();
      await sendBtn.click({ timeout: 3_000 }).catch(() => {});
      await userMessage.waitFor({ state: "visible", timeout: 8_000 });
    }
  }

  async resolvePanelCitationUrlsByClick(page, citations, clickLimit = 8) {
    if (!Array.isArray(citations) || citations.length === 0) return citations;

    const refs = citations.map((item) => ({ ...item }));
    const listItems = page.locator(".item__IBNbaily");
    const itemCount = await listItems.count().catch(() => 0);
    if (!itemCount) return refs;

    const context = page.context();
    const mainPage = page;
    const ensureMainTabReady = async () => {
      if (mainPage.isClosed()) return;

      const pages = context.pages();
      for (const p of pages) {
        if (p === mainPage) continue;
        await p.close().catch(() => {});
      }

      await mainPage.bringToFront().catch(() => {});
      const mainUrl = String(mainPage.url() || "").trim();
      if (mainUrl && !/(?:yiyan|wenxin)\.baidu\.com/i.test(mainUrl)) {
        await mainPage
          .goto(this.baseUrl, { waitUntil: "domcontentloaded", timeout: 8_000 })
          .catch(() => {});
        await mainPage.waitForTimeout(300);
      }
    };

    let attempts = 0;
    for (let i = 0; i < refs.length && i < itemCount; i += 1) {
      if (attempts >= clickLimit) break;

      const existingUrl = String(refs[i]?.url || "").trim();
      if (existingUrl) continue;

      attempts += 1;
      const item = listItems.nth(i);
      let capturedUrl = "";

      try {
        await item.scrollIntoViewIfNeeded({ timeout: 2_000 }).catch(() => {});
        await page.waitForTimeout(120);

        const pagesBefore = context.pages();
        const popupPromise = context
          .waitForEvent("page", { timeout: 3_500 })
          .catch(() => null);

        const navRequests = [];
        const onRequest = (request) => {
          if (!request.isNavigationRequest()) return;
          const url = String(request.url() || "").trim();
          if (!/^https?:\/\//i.test(url)) return;
          if (/(?:yiyan|wenxin)\.baidu\.com/i.test(url)) return;
          navRequests.push(url);
        };
        page.on("request", onRequest);

        await item.click({
          timeout: 2_500,
          delay: randomInt(40, 120),
          noWaitAfter: true
        });
        await page.waitForTimeout(250);

        const popup = await popupPromise;
        const pagesAfter = context.pages();
        const extraPages = pagesAfter.filter((p) => !pagesBefore.includes(p));
        const pagesToHandle = popup ? [popup, ...extraPages] : extraPages;

        for (const openedPage of pagesToHandle) {
          if (!openedPage || openedPage.isClosed() || openedPage === mainPage) continue;
          await openedPage
            .waitForLoadState("domcontentloaded", { timeout: 4_000 })
            .catch(() => {});
          const openedUrl = String(openedPage.url() || "").trim();
          if (!capturedUrl && /^https?:\/\//i.test(openedUrl) && !/(?:yiyan|wenxin)\.baidu\.com/i.test(openedUrl)) {
            capturedUrl = openedUrl;
          }
          await openedPage.close().catch(() => {});
        }

        if (!capturedUrl && navRequests.length > 0) {
          capturedUrl = navRequests[0];
        }

        if (!capturedUrl) {
          const currentUrl = String(page.url() || "").trim();
          if (currentUrl && !/(?:yiyan|wenxin)\.baidu\.com/i.test(currentUrl)) {
            capturedUrl = currentUrl;
            await page.goBack({ waitUntil: "commit", timeout: 2_000 }).catch(() => {});
            await page.waitForTimeout(300);
          }
        }

        page.off("request", onRequest);
        await ensureMainTabReady();
      } catch (err) {
        console.log(`[Wenxin] resolve url by click failed for item ${i + 1}: ${err.message}`);
        await ensureMainTabReady();
      }

      if (/^https?:\/\//i.test(capturedUrl)) {
        refs[i].url = capturedUrl;
        refs[i].text = refs[i].text || refs[i].title || capturedUrl;
      }
    }

    return refs;
  }

  async getLatestAnswerText(page, options = {}) {
    const answerCountBeforeSubmit = Number(this.answerCountBeforeSubmitByPage.get(page) || 0);
    const minAnswerIndex = options.ignoreAnswerCountGate ? 0 : answerCountBeforeSubmit;
    const onlyNewAnswer = Boolean(options.onlyNewAnswer);
    const submittedPrompt = options.ignorePromptAnchor ? "" : String(this.submittedPromptByPage.get(page) || "");
    return Promise.race([
      page
        .evaluate(({ minAnswerIndex, onlyNewAnswer, submittedPrompt }) => {
          function tableToMarkdown(table) {
            const rows = Array.from(table.querySelectorAll("tr"));
            if (!rows.length) return "";

            const markdownRows = [];
            rows.forEach((row, rowIndex) => {
              const cells = Array.from(row.querySelectorAll("th, td"));
              const cellTexts = cells.map((cell) =>
                (cell.textContent || "").trim().replace(/\|/g, "\\|")
              );
              markdownRows.push(`| ${cellTexts.join(" | ")} |`);

              if (rowIndex === 0) {
                const isHeader = row.querySelector("th") !== null;
                if (isHeader) {
                  const separator = cells.map(() => "---").join(" | ");
                  markdownRows.push(`| ${separator} |`);
                }
              }
            });

            if (!rows[0].querySelector("th") && markdownRows.length > 1) {
              const cells = Array.from(rows[0].querySelectorAll("td"));
              const separator = cells.map(() => "---").join(" | ");
              markdownRows.splice(1, 0, `| ${separator} |`);
            }

            return markdownRows.join("\n");
          }

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
          const thinkingPattern =
            /深度思考|思考中|思考过程|已深度思考|展开思考|收起思考|推理中|推理过程|reasoning|thinking/i;
          const answerRootSelector = "#answer_text_id, .answer-box";
          const isThinkingOnly = (element) => {
            const text = compact(element?.innerText || element?.textContent || "");
            if (!text) return false;
            const hasAnswerRoot = Boolean(element?.matches?.(answerRootSelector) || element?.querySelector?.(answerRootSelector));
            return thinkingPattern.test(text) && !hasAnswerRoot;
          };
          const follows = (previous, next) =>
            Boolean(previous && next && (previous.compareDocumentPosition(next) & Node.DOCUMENT_POSITION_FOLLOWING));
          const findPromptAnchor = () => {
            const promptText = compact(submittedPrompt);
            if (!promptText) return null;

            const nodes = Array.from(
              document.querySelectorAll(
                "[class], [data-testid], [role], div, p, span, section, article"
              )
            ).filter(visible);
            const matches = nodes.filter((node) => {
              const text = compact(node.innerText || node.textContent || "");
              if (!text || !text.includes(promptText)) return false;
              if (node.matches?.(answerRootSelector) || node.querySelector?.(answerRootSelector)) return false;
              return text.length <= promptText.length + 300;
            });
            return matches[matches.length - 1] || null;
          };

          let answerRoot = null;
          const legacyAnswerRoots = Array.from(document.querySelectorAll("#answer_text_id"));
          const answerRoots = Array.from(
            document.querySelectorAll(legacyAnswerRoots.length ? "#answer_text_id" : ".answer-box")
          )
            .filter(visible)
            .sort((a, b) => {
              const rectA = a.getBoundingClientRect();
              const rectB = b.getBoundingClientRect();
              return rectA.top - rectB.top || rectA.bottom - rectB.bottom;
            });
          const promptAnchor = findPromptAnchor();
          const promptCandidateRoots = promptAnchor
            ? answerRoots.filter((root) => follows(promptAnchor, root))
            : [];
          const candidateRoots = promptAnchor
            ? promptCandidateRoots
            : answerRoots.slice(Math.max(0, minAnswerIndex));
          const rootsToScan = candidateRoots.length > 0 ? candidateRoots : onlyNewAnswer ? [] : answerRoots;
          for (let i = rootsToScan.length - 1; i >= 0; i -= 1) {
            const root = rootsToScan[i];
            const container = root.closest(".flexBox__btVTGt0X") || root;
            if (!isThinkingOnly(container)) {
              answerRoot = root;
              break;
            }
          }

          if (!answerRoot && !onlyNewAnswer) {
            for (let i = answerRoots.length - 1; i >= 0; i -= 1) {
              const root = answerRoots[i];
              const container = root.closest(".flexBox__btVTGt0X") || root;
              if (!isThinkingOnly(container)) {
                answerRoot = root;
                break;
              }
            }
          }

          if (!answerRoot) {
            return "";
          }

          const answerParts = [];
          const contentRoots = answerRoot.matches("#answer_text_id")
            ? [answerRoot]
            : Array.from(
                answerRoot.querySelectorAll(
                  ".chat-search-answer-generate-item .cosd-markdown, .cs-answer-container .cosd-markdown"
                )
              ).filter(visible);
          const rootsToExtract = contentRoots.length > 0 ? contentRoots : [answerRoot];

          rootsToExtract.forEach((contentRoot) => {
            const tables = Array.from(contentRoot.querySelectorAll("table"));
            const tableMap = new Map();
            tables.forEach((table) => {
              const markdown = tableToMarkdown(table);
              if (markdown.length > 0) {
                tableMap.set(table, markdown);
              }
            });

            const childNodes = Array.from(contentRoot.childNodes);
            childNodes.forEach((node) => {
              if (node.nodeType === Node.TEXT_NODE) {
                const text = (node.textContent || "").trim();
                if (text) answerParts.push(text);
                return;
              }

              if (node.nodeType === Node.ELEMENT_NODE) {
                const tagName = node.tagName.toLowerCase();
                if (tagName === "table" && tableMap.has(node)) {
                  answerParts.push(tableMap.get(node));
                  return;
                }

                const text = (node.innerText || node.textContent || "").trim();
                if (text) answerParts.push(text);
              }
            });
          });

          const rawAnswer = answerParts.length
            ? answerParts.join("\n\n")
            : (answerRoot.textContent || "");

          return rawAnswer
            .replace(/[\u200B-\u200D\uFEFF]/g, "")
            .split(/\n+/)
            .map((line) => line.trim())
            .filter((line) => line && !thinkingPattern.test(line))
            .join("\n\n")
            .trim();
        }, { minAnswerIndex, onlyNewAnswer, submittedPrompt }),
      new Promise((resolve) => setTimeout(() => resolve(""), 3_000))
    ]).catch(() => "");
  }

  normalizeAnswerForStable(text) {
    return String(text || "")
      .replace(/\r\n/g, "\n")
      .replace(/\r/g, "\n")
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => {
        if (!line) return false;
        if (/深度思考|思考中|思考过程|已深度思考|展开思考|收起思考|推理中|推理过程/i.test(line)) {
          return false;
        }
        if (/^(复制|分享|点赞|点踩|重新生成|换一换|继续追问|你可能还想问|推荐问题|相关问题)$/i.test(line)) {
          return false;
        }
        if (/^\d+\s*(秒|s)$/.test(line)) return false;
        return true;
      })
      .join("\n")
      .replace(/\s+/g, " ")
      .trim();
  }

  getAnswerBodyLines(text) {
    return String(text || "")
      .replace(/\r\n/g, "\n")
      .replace(/\r/g, "\n")
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => {
        if (!line) return false;
        if (/深度思考|思考中|思考过程|已深度思考|展开思考|收起思考|推理中|推理过程/i.test(line)) {
          return false;
        }
        if (/^(复制|分享|点赞|点踩|重新生成|换一换|继续追问|你可能还想问|推荐问题|相关问题)$/i.test(line)) {
          return false;
        }
        if (/^\d+\s*(秒|s)$/.test(line)) return false;
        return true;
      });
  }

  async isThinkingOrGenerating(page) {
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
        const latestAnswerBox = Array.from(document.querySelectorAll(".answer-box")).pop();
        if (latestAnswerBox?.querySelector(".cs-answer-container[data-status='GENERATING']")) {
          return true;
        }
        if (latestAnswerBox?.querySelector(".chat-answer-typing-loading")) {
          return true;
        }

        const controlPattern = /停止生成|停止回答/i;
        const statusPattern = /^(正在)?(思考中|思考|推理中|推理|生成中|生成|正在生成|正在思考|正在推理)[.。…\s]*$/i;
        const nodes = Array.from(
          document.querySelectorAll("button, [role='button'], [aria-label], [title], span, div")
        ).filter(visible);

        return nodes.some((node) => {
          if (node.querySelector?.("#answer_text_id, .answer-box")) return false;
          const text = compact(
            node.textContent ||
              node.getAttribute("aria-label") ||
              node.getAttribute("title") ||
              ""
          );
          if (!text || text.length > 80) return false;
          const isControl =
            node.matches?.("button, [role='button'], [aria-label], [title]") || false;
          if (isControl && controlPattern.test(text)) return true;
          return node.childElementCount <= 3 && statusPattern.test(text);
        });
      }),
      new Promise((resolve) => setTimeout(() => resolve(false), 1_000))
    ]).catch(() => false);
  }

  async waitResponseStable(page, timeoutMs, options = {}) {
    const minimumWaitMs = 8_000;
    const checkIntervalMs = 2_000;
    const requiredStableCount = 3;
    const stageLabel = options?.stageLabel || "回答";

    const start = Date.now();
    let lastLineCount = -1;
    let lastTextLength = -1;
    let stableCount = 0;
    let answerStarted = false;

    while (Date.now() - start < timeoutMs) {
      const elapsed = Date.now() - start;

      if (await this.isThinkingOrGenerating(page)) {
        console.log(`[Wenxin/${stageLabel}] thinking/generating detected, pause ${checkIntervalMs / 1000}s...`);
        stableCount = 0;
        await page.waitForTimeout(checkIntervalMs);
        continue;
      }

      const currentText = await this.getLatestAnswerText(page, {
        ignoreAnswerCountGate: true,
        ignorePromptAnchor: true
      });
      if (!currentText || currentText.length <= 1) {
        console.log(`[Wenxin/${stageLabel}] waiting official answer body, pause ${checkIntervalMs / 1000}s...`);
        await page.waitForTimeout(checkIntervalMs);
        continue;
      }

      const stableText = this.normalizeAnswerForStable(currentText);
      if (!stableText || stableText.length <= 1) {
        console.log(`[Wenxin/${stageLabel}] waiting normalized answer content, pause ${checkIntervalMs / 1000}s...`);
        await page.waitForTimeout(checkIntervalMs);
        continue;
      }

      const bodyLines = this.getAnswerBodyLines(currentText);
      const lineCount = bodyLines.length;
      const textLength = stableText.length;

      if (!answerStarted) {
        answerStarted = true;
        console.log(`[Wenxin/${stageLabel}] official answer body started, lines=${lineCount}, len=${textLength}`);
      }

      if (lineCount === lastLineCount && textLength === lastTextLength) {
        stableCount += 1;
        console.log(`[Wenxin/${stageLabel}] answer body stable (${stableCount}/${requiredStableCount}), lines=${lineCount}, len=${textLength}`);
      } else {
        stableCount = 0;
        lastLineCount = lineCount;
        lastTextLength = textLength;
        console.log(`[Wenxin/${stageLabel}] answer body changed, lines=${lineCount}, len=${textLength}, reset stable counter`);
      }

      if (stableCount >= requiredStableCount) {
        if (elapsed < minimumWaitMs) {
          const remaining = minimumWaitMs - elapsed;
          console.log(
            `[Wenxin/${stageLabel}] answer already stable, waiting minimum ${Math.floor(elapsed / 1000)}s/${minimumWaitMs / 1000}s`
          );
          await page.waitForTimeout(Math.min(remaining, checkIntervalMs));
          continue;
        }
        console.log(`[Wenxin/${stageLabel}] answer body stable, response complete`);
        return;
      }

      await page.waitForTimeout(checkIntervalMs);
    }

    throw new Error("Wenxin response did not become available/stable before timeout");
  }
async extractLatestAnswer(page, options = {}) {
    console.log("[Wenxin] extracting latest answer...");
    let domAnswer = "";
    for (let attempt = 0; attempt < 16; attempt += 1) {
      domAnswer = await this.getLatestAnswerText(page, {
        ignoreAnswerCountGate: true,
        ignorePromptAnchor: true
      });
      if (domAnswer && domAnswer.length > 1) {
        break;
      }
      await page.waitForTimeout(500);
    }
    console.log(`[Wenxin] DOM answer length: ${domAnswer?.length || 0}`);

    await this.openLatestSourceSidebar(page, "extract current answer citations");

    const domCitations = await Promise.race([
      page.evaluate(() => {
        const compact = (value) => String(value || "").replace(/\s+/g, " ").trim();
        const refs = [];
        const pushRef = (title, text, url) => {
          const normalizedUrl = String(url || "").trim();
          const normalizedTitle = compact(title) || compact(text) || normalizedUrl;
          const normalizedText = compact(text) || normalizedTitle;
          if (!normalizedTitle && !normalizedUrl) return;
          refs.push({ title: normalizedTitle, text: normalizedText, url: normalizedUrl });
        };

        // The new Wenxin site stores each top-dropdown source in JSON on the <li>,
        // rather than rendering a normal <a href>. Always take the last dropdown so
        // citations stay paired with the latest answer in multi-turn conversations.
        const referenceLists = Array.from(
          document.querySelectorAll("ol[class*='_reference-list_']")
        ).filter((list) =>
          list.querySelector("li[data-long-press-ext-info], li[class*='_reference-item_']")
        );
        const latestReferenceList = referenceLists[referenceLists.length - 1];
        const referenceContainer = latestReferenceList?.closest(
          "div[class*='_collapse-container_']"
        );
        const referenceItems = latestReferenceList
          ? Array.from(
              latestReferenceList.querySelectorAll(
                "li[data-long-press-ext-info], li[class*='_reference-item_']"
              )
            )
          : [];

        for (const item of referenceItems) {
          const rawInfo = item.getAttribute("data-long-press-ext-info") || "";
          let info = {};
          try {
            info = rawInfo ? JSON.parse(rawInfo) : {};
          } catch {
            info = {};
          }

          const url = info.link || item.getAttribute("data-url") || item.getAttribute("data-href") || "";
          const titleNode = item.querySelector("[class*='_text_']");
          const title = info.linkTitle || compact(titleNode?.textContent) || compact(item.textContent);
          pushRef(title, title, url);
        }

        const legacyRoots = Array.from(document.querySelectorAll("#answer_text_id"));
        const answerRoots = legacyRoots.length
          ? legacyRoots
          : Array.from(document.querySelectorAll(".answer-box"));
        const answerRoot = answerRoots[answerRoots.length - 1];
        const selectors = [
          "a[href^='http']",
          ".cosd-citation-link[href]",
          ".cosd-citation-title[href]",
          ".cosd-citation-list a[href]"
        ];
        const linkScopes = [referenceContainer, answerRoot].filter(Boolean);
        for (const scope of linkScopes) {
          for (const node of scope.querySelectorAll(selectors.join(","))) {
            const url = node.getAttribute("href") || "";
            const titleNode = node.querySelector(
              ".cosd-citation-title-text, .cosd-citation-list-content-title"
            );
            const text = compact(titleNode?.textContent || node.textContent || "");
            if (/^https?:\/\//i.test(url)) pushRef(text || url, text, url);
          }
        }

        const uniqueRefs = new Map();
        for (const ref of refs) {
          const key = ref.url || `${ref.title}||${ref.text}`;
          if (!uniqueRefs.has(key)) uniqueRefs.set(key, ref);
        }
        return Array.from(uniqueRefs.values());
      }),
      new Promise((resolve) => setTimeout(() => resolve([]), 3_000))
    ]).catch(() => []);

    const panelCitations = await Promise.race([
      page.evaluate(() => {
        const refs = [];
        const items = Array.from(document.querySelectorAll(".item__IBNbaily"));

        const pickHttpUrl = (values) =>
          values
            .map((v) => String(v || "").trim())
            .find((v) => /^https?:\/\//i.test(v)) || "";

        for (const item of items) {
          const title = (item.querySelector(".titleInfo__rxRVcuFq")?.textContent || "").trim();
          const siteName = (item.querySelector(".siteText__Km0xjWwt")?.textContent || "").trim();
          const publishDate = (item.querySelector(".date__Uclpu4ly")?.textContent || "").trim();

          const attrCandidates = [];
          const iconLinkNode = item.querySelector(".site_icon_box__KTj5kYq3");
          if (iconLinkNode) {
            attrCandidates.push(iconLinkNode.getAttribute("href"));
            attrCandidates.push(iconLinkNode.getAttribute("data-url"));
            attrCandidates.push(iconLinkNode.getAttribute("data-href"));

            const nestedIconAnchor = iconLinkNode.querySelector("a[href]");
            if (nestedIconAnchor) {
              attrCandidates.push(nestedIconAnchor.getAttribute("href"));
              attrCandidates.push(nestedIconAnchor.getAttribute("data-url"));
              attrCandidates.push(nestedIconAnchor.getAttribute("data-href"));
            }
          }

          const directLink =
            item.querySelector(".site_icon_box__KTj5kYq3[href]") ||
            item.querySelector(".site_icon_box__KTj5kYq3 a[href]") ||
            item.querySelector("a.site-item[href]");
          if (directLink) {
            attrCandidates.push(directLink.getAttribute("href"));
            attrCandidates.push(directLink.getAttribute("data-url"));
            attrCandidates.push(directLink.getAttribute("data-href"));
          }

          const candidateNodes = Array.from(item.querySelectorAll("a[href], [data-url], [data-href]"));
          for (const node of candidateNodes) {
            attrCandidates.push(node.getAttribute("href"));
            attrCandidates.push(node.getAttribute("data-url"));
            attrCandidates.push(node.getAttribute("data-href"));
          }

          let url = pickHttpUrl(attrCandidates);
          if (!url) {
            const textBlob = item.textContent || "";
            const match = textBlob.match(/https?:\/\/[^\s"'<>]+/i);
            if (match) url = match[0];
          }

          const fallbackText = (
            directLink?.querySelector(".site-title")?.textContent ||
            directLink?.textContent ||
            title ||
            url
          ).trim();
          const metaParts = [siteName, publishDate].filter(Boolean);
          const metaText = metaParts.length ? ` [${metaParts.join(" | ")}]` : "";
          const finalTitle = title || fallbackText || siteName || "来源条目";
          const finalText = (title || fallbackText || "").trim() + metaText;

          refs.push({
            title: finalTitle,
            text: finalText || finalTitle,
            url: String(url || "").trim()
          });
        }

        return refs;
      }),
      new Promise((resolve) => setTimeout(() => resolve([]), 3_000))
    ]).catch(() => []);

    const normalizedDomCitations = domCitations.map((item) => ({
      title: this.normalizeText(item.title),
      text: this.normalizeText(item.text),
      url: item.url
    }));
    const normalizedPanelCitations = panelCitations.map((item) => ({
      title: this.normalizeText(item.title),
      text: this.normalizeText(item.text),
      url: item.url
    }));
    const resolvedPanelCitations = await this.resolvePanelCitationUrlsByClick(
      page,
      normalizedPanelCitations
    );
    const effectiveDomCitations = resolvedPanelCitations.length > 0 ? [] : normalizedDomCitations;

    const mergedByKey = new Map();
    for (const item of [...effectiveDomCitations, ...resolvedPanelCitations]) {
      const url = String(item?.url || "").trim();
      const title = String(item?.title || "").trim();
      const text = String(item?.text || "").trim();
      const dedupeKey = url || `${title}||${text}`;
      if (!dedupeKey.trim()) continue;

      if (!mergedByKey.has(dedupeKey)) {
        mergedByKey.set(dedupeKey, {
          title: title || text || url,
          text: text || title,
          url
        });
        continue;
      }
      const prev = mergedByKey.get(dedupeKey);
      mergedByKey.set(dedupeKey, {
        title: prev.title || title || text || url,
        text: prev.text || text || title,
        url: prev.url || url
      });
    }

    const citations = Array.from(mergedByKey.values());
    const noUrlCount = citations.filter((x) => !String(x?.url || "").trim()).length;
    const recoveredByClickCount = resolvedPanelCitations.filter((x) =>
      /^https?:\/\//i.test(String(x?.url || "").trim())
    ).length;
    console.log(
      `[Wenxin] found ${citations.length} citations (DOM:${effectiveDomCitations.length}/${normalizedDomCitations.length} + sidebar:${resolvedPanelCitations.length})`
    );
    console.log(`[Wenxin] sidebar click URL recovery count: ${recoveredByClickCount}`);
    if (noUrlCount > 0) {
      console.log(`[Wenxin] ${noUrlCount} citation entries have no URL, kept by title/site text`);
    }

    return { answer: domAnswer, citations };
  }
}






const managedGotoHome = ManagedWenxinAdapter.prototype.gotoHome;
for (const methodName of Object.getOwnPropertyNames(ManagedWenxinAdapter.prototype)) {
  if (methodName === "constructor") continue;
  const descriptor = Object.getOwnPropertyDescriptor(
    ManagedWenxinAdapter.prototype,
    methodName
  );
  Object.defineProperty(ExternalWenxinAdapter.prototype, methodName, descriptor);
}

ExternalWenxinAdapter.prototype.gotoHome = async function gotoManagedWenxinHome(page) {
  this.baseUrl = "https://wenxin.baidu.com/";
  return managedGotoHome.call(this, page);
};

console.log("[wenxin] Managed adapter override loaded");

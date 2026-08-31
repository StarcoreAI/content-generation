import { pathToFileURL } from "node:url";
import path from "node:path";

function randomInt(min, max) {
  const lower = Math.ceil(min);
  const upper = Math.floor(max);
  return Math.floor(Math.random() * (upper - lower + 1)) + lower;
}

const crawlerRoot = String(process.env.GEO_NODE_CRAWLER_ROOT || "").trim();
if (!crawlerRoot) {
  throw new Error("GEO_NODE_CRAWLER_ROOT is required by the Yuanbao adapter override");
}

const adapterUrl = pathToFileURL(
  path.join(crawlerRoot, "src", "adapters", "yuanbaoAdapter.js")
).href;
const { YuanbaoAdapter } = await import(adapterUrl);

if (!YuanbaoAdapter?.prototype) {
  throw new Error("External crawler does not export a compatible YuanbaoAdapter");
}

YuanbaoAdapter.prototype.startNewConversation = async function startNewConversation(page) {
  const selectors = [
    "[data-desc='new-chat']:visible",
    "[aria-label='新建对话']:visible",
    "[aria-label='新对话']:visible",
    "button:has-text('新对话'):visible",
    "[role='button']:has-text('新对话'):visible",
    "a:has-text('新对话'):visible",
    ":text-is('新对话'):visible",
    ":text-is('新建对话'):visible",
    ":text-is('New chat'):visible",
    ".yb-tencent-yuanbao-list__recent:visible"
  ];

  const trigger = page.locator(selectors.join(", ")).first();
  try {
    await trigger.waitFor({ state: "visible", timeout: 5_000 });
    await trigger.click({ delay: randomInt(40, 120) });
    await page.waitForTimeout(randomInt(600, 1_400));
    console.log("[yuanbao] Created new conversation by managed selector");
    return;
  } catch {
    // Fall back to Playwright's text engine for unexpected markup.
  }

  for (const text of ["新对话", "新建对话", "New chat"]) {
    const textTrigger = page.getByText(text, { exact: true }).first();
    try {
      await textTrigger.waitFor({ state: "visible", timeout: 1_500 });
      await textTrigger.click({ delay: randomInt(40, 120) });
      await page.waitForTimeout(randomInt(600, 1_400));
      console.log(`[yuanbao] Created new conversation by managed text: ${text}`);
      return;
    } catch {
      // Try the next visible text.
    }
  }

  throw new Error("Failed to find Yuanbao new-conversation trigger");
};

YuanbaoAdapter.prototype.openReferenceSidebar = async function openReferenceSidebar(page) {
  const toggles = [
    "[class*='ToolbarSearchGuid_searchGuidTool__'][class*='Toolbar_icon__']",
    "[class*='ToolbarSearchGuid_searchGuidTool__']",
    "[class*='ToolbarSearchGuid_source']",
    "button:has-text('源'):visible",
    "[role='button']:has-text('源'):visible",
    "span:has-text('源'):visible"
  ];

  // The host engine caps extraction at 10 seconds. Keep the sidebar attempt well
  // inside that budget so a slow/missing references panel never discards the answer.
  const deadline = Date.now() + 2_500;
  let clicked = false;
  while (Date.now() < deadline && !clicked) {
    for (const selector of toggles) {
      try {
        const candidates = page.locator(selector);
        for (let index = (await candidates.count()) - 1; index >= 0; index -= 1) {
          const candidate = candidates.nth(index);
          if (!(await candidate.isVisible().catch(() => false))) continue;
          await candidate.scrollIntoViewIfNeeded().catch(() => {});
          await candidate.click({ timeout: 800, delay: randomInt(30, 100) });
          await page.waitForTimeout(randomInt(150, 350));
          clicked = true;
          break;
        }
      } catch {
        // Try the next selector while Yuanbao finishes rendering its toolbar.
      }
      if (clicked) break;
    }
    if (!clicked) await page.waitForTimeout(300);
  }

  await page
    .locator(
      "#search-guide-tool .agent-dialogue-references__item, " +
      ".agent-dialogue-references__item, " +
      ".hyc-common-markdown__ref_card[data-url]"
    )
    .first()
    .waitFor({ state: "visible", timeout: 1_200 })
    .then(() => console.log("[yuanbao] Reference sidebar detected"))
    .catch((error) => {
      console.log(`[yuanbao] Reference sidebar not ready in time: ${error.message}`);
    });
};

YuanbaoAdapter.prototype.extractLatestAnswer = async function extractLatestAnswer(page) {
  const answer = await this.getLatestAnswerText(page);
  await this.openReferenceSidebar(page);

  const rawCitations = await Promise.race([
    page.evaluate(() => {
      const compact = (value) => String(value || "").replace(/\s+/g, " ").trim();
      const citations = [];
      const add = (url, title, text) => {
        const cleanUrl = compact(url);
        if (!/^https?:\/\//i.test(cleanUrl)) return;
        const cleanTitle = compact(title) || cleanUrl;
        citations.push({
          title: cleanTitle,
          text: compact(text) || cleanTitle,
          url: cleanUrl
        });
      };

      const items = Array.from(
        document.querySelectorAll(
          "#search-guide-tool .agent-dialogue-references__item, " +
          ".agent-dialogue-references__item"
        )
      );
      for (const item of items) {
        const title =
          compact(item.querySelector("h4 span")?.textContent) ||
          compact(item.querySelector("h4")?.textContent) ||
          compact(item.querySelector("[class*='title']")?.textContent);
        const dataUrl = compact(
          item.querySelector(".hyc-common-markdown__ref_card[data-url], [data-url]")
            ?.getAttribute("data-url")
        );
        const anchor = item.querySelector("a[href^='http']");
        add(dataUrl || anchor?.getAttribute("href"), title, title);
      }

      const cards = Array.from(
        document.querySelectorAll(
          "#search-guide-tool .hyc-common-markdown__ref_card[data-url], " +
          ".hyc-common-markdown__ref_card[data-url]"
        )
      );
      for (const card of cards) {
        const url = compact(card.getAttribute("data-url"));
        const title =
          compact(card.querySelector("h4 span")?.textContent) ||
          compact(card.querySelector("h4")?.textContent) ||
          compact(card.querySelector("[class*='ref_card-title']")?.textContent) ||
          url;
        const source =
          compact(card.querySelector("[class*='ref_card-foot__source_txt']")?.textContent) ||
          title;
        add(url, title, source);
      }

      const latestAnswer = Array.from(
        document.querySelectorAll(
          ".agent-chat__speech-text--box.agent-chat__speech-text--box-left"
        )
      ).at(-1);
      for (const anchor of latestAnswer?.querySelectorAll("a[href^='http']") || []) {
        const title = compact(anchor.getAttribute("title") || anchor.textContent);
        add(anchor.getAttribute("href"), title, title);
      }
      return citations;
    }),
    new Promise((resolve) => setTimeout(() => resolve([]), 1_500))
  ]).catch(() => []);

  const chooseCleaner = (left, right, fallback) => {
    const a = String(left || "").replace(/\s+/g, " ").trim();
    const b = String(right || "").replace(/\s+/g, " ").trim();
    if (!a) return b || fallback;
    if (!b) return a;
    if (a.length > 120 && b.length <= 120) return b;
    if (b.length > 120 && a.length <= 120) return a;
    return b.length < a.length ? b : a;
  };

  const byUrl = new Map();
  for (const raw of rawCitations) {
    const url = String(raw?.url || "").trim();
    if (!/^https?:\/\//i.test(url)) continue;
    const title = this.normalizeText(
      String(raw?.title || url).replace(/\s+/g, " ").trim()
    );
    const text = this.normalizeText(
      String(raw?.text || title).replace(/\s+/g, " ").trim()
    );
    const previous = byUrl.get(url);
    byUrl.set(url, previous ? {
      title: chooseCleaner(previous.title, title, url),
      text: chooseCleaner(previous.text, text, title),
      url
    } : { title, text, url });
  }

  const citations = Array.from(byUrl.values());
  console.log(`[yuanbao] Managed adapter found ${citations.length} citations`);
  return { answer, citations };
};

console.log("[yuanbao] Managed adapter override loaded");

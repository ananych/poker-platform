import { expect, test, type Page } from "@playwright/test";

const PASSWORD = "e2e-secret";
const shots = process.env.E2E_SHOTS ?? "e2e-artifacts";

async function noHorizontalScroll(page: Page) {
  const [sw, iw] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(sw).toBeLessThanOrEqual(iw + 1);
}

async function tapTargetsOk(page: Page) {
  for (const b of await page.locator("button:visible").all()) {
    const box = await b.boundingBox();
    if (box && (await b.isEnabled())) expect.soft(box.height, await b.innerText()).toBeGreaterThanOrEqual(40);
  }
}

test("phone host + desktop guest play a hand", async ({ browser }) => {
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true,
                                           hasTouch: true, deviceScaleFactor: 2 });
  const desk = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const host = await phone.newPage();
  const guest = await desk.newPage();

  // host: guest session + create room
  await host.goto("/");
  await host.getByPlaceholder("例如：Andrew").fill("Andrew");
  await host.getByRole("button", { name: "進入" }).click();
  await expect(host.getByText("建立私人房間")).toBeVisible();
  await host.getByPlaceholder("房間名稱（選填）").fill("週五牌局");
  await host.getByPlaceholder("房間密碼（至少 4 字）").fill(PASSWORD);
  await host.getByRole("button", { name: "建立並取得邀請連結" }).click();
  await host.waitForURL(/\/rooms\//);
  await expect(host.getByText("邀請連結").first()).toBeVisible();
  await host.screenshot({ path: `${shots}/01-phone-created.png` });
  const invite = await host.evaluate(() => {
    const k = Object.keys(localStorage).find((x) => x.startsWith("invite:"))!;
    return localStorage.getItem(k)!;
  });
  await host.getByRole("button", { name: "關閉面板" }).click();

  // host sits at seat 1
  await host.getByRole("button", { name: "坐到 1 號位" }).click();
  await host.getByRole("button", { name: "坐下", exact: true }).click();
  await expect(host.locator("[data-me]")).toContainText("Andrew");

  // guest joins via invite + password, sits at seat 4
  await guest.goto(invite);
  await guest.getByLabel("暱稱").fill("Bob");
  await guest.getByLabel("房間密碼").fill("wrong-pass");
  await guest.getByRole("button", { name: "加入" }).click();
  await expect(guest.getByText("房間密碼錯誤")).toBeVisible();
  await guest.getByLabel("房間密碼").fill(PASSWORD);
  await guest.getByRole("button", { name: "加入" }).click();
  await guest.waitForURL(/\/rooms\/[^/]+$/);
  await guest.getByRole("button", { name: "坐到 4 號位" }).click();
  await guest.getByRole("button", { name: "坐下", exact: true }).click();
  await expect(guest.locator("[data-me]")).toContainText("Bob");
  await expect(host.getByText("Bob", { exact: true })).toBeVisible();

  // host starts the hand from the phone
  await host.getByRole("button", { name: "開始下一手" }).click();
  await expect(host.getByLabel("你的手牌")).toBeVisible();
  await expect(guest.getByLabel("你的手牌")).toBeVisible();
  // privacy: the guest page never shows host's cards
  const hostCards = await host.getByLabel("你的手牌").locator("[aria-label]").evaluateAll(
    (els) => els.map((e) => e.getAttribute("aria-label")));
  const guestCardLabels = await guest.locator("[aria-label]").evaluateAll(
    (els) => els.map((e) => e.getAttribute("aria-label")));
  const guestOwn = await guest.getByLabel("你的手牌").locator("[aria-label]").evaluateAll(
    (els) => els.map((e) => e.getAttribute("aria-label")));
  for (const c of hostCards) {
    if (!guestOwn.includes(c)) expect(guestCardLabels).not.toContain(c);
  }

  await expect(host.getByText("輪到你了")).toBeVisible(); // heads-up: button/SB acts first
  await host.screenshot({ path: `${shots}/02-phone-my-turn.png` });
  await guest.screenshot({ path: `${shots}/03-desktop-waiting.png` });
  await noHorizontalScroll(host);
  await tapTargetsOk(host);

  // host raises with the pot preset, guest calls, then both check down
  await host.getByRole("button", { name: "1 池", exact: true }).click();
  await host.getByRole("button", { name: /加注到/ }).click();
  await expect(guest.getByText("輪到你了")).toBeVisible();
  await guest.getByRole("button", { name: /^跟注/ }).click();
  for (let i = 0; i < 40; i++) {
    if (await host.getByText(/贏得/).isVisible()) break;
    for (const p of [guest, host]) {
      const check = p.getByRole("button", { name: "過牌", exact: true });
      if (await check.isVisible()) { await check.click(); await p.waitForTimeout(250); }
    }
    await host.waitForTimeout(200);
  }
  await expect(host.getByText(/贏得/)).toBeVisible({ timeout: 15_000 });
  // winner is marked on the seat, and each player still sees their own cards after the hand
  await expect(host.getByText(/🏆 \+/)).toBeVisible();
  for (const c of hostCards) await expect(host.getByLabel(c!, { exact: true }).first()).toBeVisible();
  for (const c of guestOwn) await expect(guest.getByLabel(c!, { exact: true }).first()).toBeVisible();
  // running profit/loss on every seat
  await expect(host.getByText(/^總 [+−0]/).first()).toBeVisible();
  await host.screenshot({ path: `${shots}/04-phone-result.png` });
  await guest.screenshot({ path: `${shots}/05-desktop-result.png` });

  // chat: bubble over the sender's seat + toast for the other player
  await guest.getByLabel("聊天訊息").fill("nice hand <b>!</b>");
  await guest.getByRole("button", { name: "送出" }).click();
  await expect(guest.getByText("nice hand <b>!</b>").first()).toBeVisible();
  await expect(host.getByText(/💬 Bob: nice hand/)).toBeVisible();
  await expect(host.locator(".seat-bubble")).toHaveText("nice hand <b>!</b>");
  await host.screenshot({ path: `${shots}/06-phone-chat-bubble.png` });

  // auto-deal: hand #2 starts by itself ~5 s later, nobody clicks
  await expect(host.getByText(/下一手 \d+ 秒後開始/)).toBeVisible();
  await expect(host.getByText(/#2 · 翻牌前/)).toBeVisible({ timeout: 12_000 });

  // pre-action: the waiting player queues "跟任何注", the actor raises, the call fires by itself
  const [actor, waiter] = (await host.getByText("輪到你了").isVisible()) ? [host, guest] : [guest, host];
  await waiter.getByRole("button", { name: /跟任何注/ }).click();
  await expect(waiter.getByRole("button", { name: /跟任何注/ })).toHaveAttribute("aria-pressed", "true");
  await actor.getByRole("button", { name: "1 池", exact: true }).click();
  await actor.getByRole("button", { name: /加注到/ }).click();
  await expect(host.getByText(/#2 · 翻牌$/)).toBeVisible({ timeout: 10_000 });
  await waiter.screenshot({ path: `${shots}/07-preaction-fired.png` });

  // English UI
  await guest.getByRole("button", { name: "設定" }).click();
  await guest.getByRole("button", { name: "English" }).click();
  await expect(guest.getByRole("tab", { name: "Chat" })).toBeVisible();
  await expect(guest.getByText(/#2 · Flop/)).toBeVisible();
  await guest.screenshot({ path: `${shots}/08-desktop-english.png` });
  await guest.getByRole("button", { name: "中文" }).click();
  await guest.keyboard.press("Escape");

  // standings + history (desktop side panel)
  await guest.getByRole("tab", { name: "戰績" }).click();
  await expect(guest.getByText("水上水下")).toBeVisible();
  await guest.getByRole("tab", { name: "歷史" }).click();
  await guest.getByText("#1 ·").click();
  await guest.waitForURL(/\/hands\//);
  await guest.getByRole("button", { name: "播放" }).click();
  await guest.waitForTimeout(1500);
  await guest.screenshot({ path: `${shots}/09-desktop-replay.png` });
  await host.goto(guest.url());
  await expect(host.getByText(/回放 #1/)).toBeVisible();
  await host.screenshot({ path: `${shots}/10-phone-replay.png` });
  await noHorizontalScroll(host);
});

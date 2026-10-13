import { expect, test } from "@playwright/test";
const SUIT: Record<string, string> = { s: "♠", h: "♥", d: "♦", c: "♣" };
const cardLabel = (c: string) => `${c[0] === "T" ? "10" : c[0]}${SUIT[c[1]]}`;

import {
  act, autoplay, blankPlayer, btn, cjkLeftovers, cleanup, createRoom, DEVICES, join, newPlayer,
  noHorizontalScroll, openRoom, PASSWORD, shot, sit, startHand, table, turnText, view, waitResult,
  whoseTurn, type Player,
} from "./helpers";

test.afterEach(async () => { await cleanup(); });

// ---------------------------------------------------------------------------
test("lobby: nickname, room validation, invite + password, buy-in limits", async ({ browser }) => {
  const a = await blankPlayer(browser, "Alice", DEVICES.phone);
  await a.page.goto("/");
  const enter = btn(a, "進入");
  await expect(enter).toBeDisabled();
  await a.page.getByPlaceholder("例如：Andrew").fill("   ");
  await expect(enter).toBeDisabled();
  await a.page.getByPlaceholder("例如：Andrew").fill("Alice");
  await enter.click();
  await expect(a.page.getByText("建立私人房間")).toBeVisible();
  await expect(a.page.getByText("目前暱稱：")).toBeVisible();

  const create = btn(a, "建立並取得邀請連結");
  // password too short: blocked by the browser, stays in the lobby
  await a.page.getByPlaceholder("房間密碼（至少 4 字）").fill("abc");
  await create.click();
  await expect(a.page).toHaveURL(/\/$/);
  // invalid blinds / buy-ins: specific messages
  await a.page.getByPlaceholder("房間密碼（至少 4 字）").fill(PASSWORD);
  await a.page.getByLabel("小盲").fill("20");
  await create.click();
  const alert = a.page.locator("p[role=alert]");
  await expect(alert).toHaveText("小盲必須小於大盲");
  await a.page.getByLabel("小盲").fill("5");
  await a.page.getByLabel("最低買入").fill("5000");
  await create.click();
  await expect(alert).toHaveText("最低買入不能大於最高買入");
  await a.page.getByLabel("最低買入").fill("5");
  await create.click();
  await expect(alert).toHaveText("最低買入至少要 1 個大盲");
  await a.page.getByLabel("最低買入").fill("200");
  await a.page.getByPlaceholder("房間名稱（選填）").fill("週五牌局");
  await create.click();
  await a.page.waitForURL(/\/rooms\//);
  await expect(a.page.getByText("邀請連結").first()).toBeVisible();
  const invite = await a.page.evaluate(() => {
    const k = Object.keys(localStorage).find((x) => x.startsWith("invite:"))!;
    return localStorage.getItem(k)!;
  });
  const roomId = a.page.url().split("/rooms/")[1].split("?")[0];
  await shot(a.page, "f01-phone-room-created");

  // lobby lists the room as mine (host crown)
  await a.page.goto("/");
  await expect(a.page.getByRole("link", { name: /週五牌局 ♛/ })).toBeVisible();

  // join: missing invite code, wrong password, then success
  const b = await blankPlayer(browser, "Bob", DEVICES.desktop);
  await b.page.goto(`/join/${roomId}`);
  await expect(b.page.getByText("連結缺少邀請碼")).toBeVisible();
  await expect(btn(b, "加入")).toBeDisabled();
  await b.page.goto(invite);
  await b.page.getByLabel("暱稱").fill("Bob");
  await b.page.getByLabel("房間密碼").fill("nope-nope");
  await btn(b, "加入").click();
  await expect(b.page.getByText("房間密碼錯誤")).toBeVisible();
  await b.page.getByLabel("房間密碼").fill(PASSWORD);
  await btn(b, "加入").click();
  await b.page.waitForURL(/\/rooms\/[^/]+$/);
  await expect(b.page.getByText("觀戰中 · 點空位坐下")).toBeVisible();

  // buy-in dialog enforces min/max
  await b.page.getByRole("button", { name: "坐到 3 號位" }).click();
  const amount = b.page.getByLabel("金額", { exact: true });
  const sitBtn = btn(b, "坐下");
  await amount.fill("50");
  await expect(sitBtn).toBeDisabled();
  await amount.fill("3000");
  await expect(sitBtn).toBeDisabled();
  await amount.fill("500");
  await sitBtn.click();
  await expect(b.page.locator("[data-me]")).toContainText("Bob");
  await expect(b.page.getByText("觀戰中 · 點空位坐下")).toBeHidden();
  await noHorizontalScroll(a.page);
});

// ---------------------------------------------------------------------------
test("three-way all-in: main + side pot, showdown cards, conservation", async ({ browser }) => {
  const { players, room } = await table(browser, ["Ann", "Ben", "Cat"], { buyins: [100, 300, 500] });
  await startHand(players[0], room);
  for (let i = 0; i < 12; i++) {
    if ((await view(players[0], room)).hand === null) break;
    await act(await whoseTurn(players), "allin");
  }
  await waitResult(players[0]);
  const v0 = await view(players[0], room);
  expect(v0.seats.reduce((n: number, x: { stack: number }) => n + x.stack, 0)).toBe(900);
  expect(v0.seats.reduce((n: number, x: { net: number }) => n + x.net, 0)).toBe(0);
  expect(v0.standings.reduce((n: number, x: { net: number }) => n + x.net, 0)).toBe(0);
  const last = v0.last_hand;
  expect(last.completed.pots.length).toBeGreaterThanOrEqual(2);
  await expect(players[1].page.getByText("主池")).toBeVisible();
  await expect(players[1].page.getByText("邊池 1")).toBeVisible();
  // everyone sees every live hand at showdown (A-02) + their own cards
  for (const p of players) {
    for (const s of last.showdown.shown) {
      for (const c of s.hole_cards) await expect(p.page.getByLabel(cardLabel(c), { exact: true }).first()).toBeVisible();
    }
  }
  await shot(players[1].page, "f03-side-pot");
  // busted players can't be dealt in; with < 2 funded players the table waits
  const v = await view(players[0], room);
  const funded = v.seats.filter((s: { stack: number }) => s.stack > 0).length;
  if (funded < 2) await expect(players[0].page.getByText("等待至少 2 位玩家")).toBeVisible({ timeout: 10_000 });
});

// ---------------------------------------------------------------------------
test("pre-actions: invalidation, call-any, check/fold, pre-raise", async ({ browser }) => {
  const { players, room } = await table(browser, ["Ann", "Ben", "Cat"]);
  await startHand(players[0], room);
  const v = await view(players[0], room);
  const bySeat = (n: number) => players.find((_, i) => i + 1 === n)!;
  const BTN = bySeat(v.hand.button_seat), SB = bySeat(v.hand.sb_seat), BB = bySeat(v.hand.bb_seat);
  const pre = (p: Player, label: string) =>
    p.page.getByRole("button", { name: `預選：${label}`, exact: true });

  expect(await whoseTurn(players)).toBe(BTN); // 3-handed: button acts first preflop
  await pre(SB, "跟注 5").click();
  await expect(pre(SB, "跟注 5")).toHaveAttribute("aria-pressed", "true");
  await pre(BB, "過牌").click();
  await expect(pre(BB, "過牌")).toHaveAttribute("aria-pressed", "true");

  await act(BTN, "potRaise"); // raise to 35 -> both queued choices are now stale
  await expect(turnText(SB)).toBeVisible();
  await SB.page.waitForTimeout(1200);
  await expect(turnText(SB)).toBeVisible(); // "call 5" was cancelled, nothing auto-fired
  await expect(pre(BB, "跟注 25")).toHaveAttribute("aria-pressed", "false"); // "check" cancelled
  await pre(BB, "跟任何注").click();
  await act(SB, "call");
  // BB's call-any fires by itself -> flop
  await expect(players[0].page.getByText(/^#1 · 翻牌$/)).toBeVisible({ timeout: 10_000 });

  // flop: SB acts first. BB queues check/fold, BTN queues a ½-pot pre-raise.
  expect(await whoseTurn(players)).toBe(SB);
  await pre(BB, "過牌/棄牌").click();
  await pre(BTN, "½ 池").click();
  await shot(BTN.page, "f04-preaction-queued");
  await act(SB, "halfPot"); // SB bets -> BB's check/fold folds, BTN's pre-raise raises
  await expect(BB.page.getByText("棄牌", { exact: true }).first()).toBeVisible({ timeout: 10_000 });
  await expect(turnText(SB)).toBeVisible({ timeout: 10_000 }); // back to SB facing BTN's raise
  const v2 = await view(SB, room);
  const btnSeat = v2.hand.seats.find((s: { seat_no: number }) => s.seat_no === v.hand.button_seat);
  const sbSeat = v2.hand.seats.find((s: { seat_no: number }) => s.seat_no === v.hand.sb_seat);
  expect(btnSeat.street_contribution).toBeGreaterThan(sbSeat.street_contribution);
  expect(v2.hand.seats.find((s: { seat_no: number }) => s.seat_no === v.hand.bb_seat).folded).toBe(true);
  await act(SB, "fold");
  await waitResult(BTN);
  await expect(BTN.page.getByText(/🏆 \+/).first()).toBeVisible();
});

// ---------------------------------------------------------------------------
test("timeout: auto-fold, sit out, dealt out, then back in", async ({ browser }) => {
  test.setTimeout(120_000);
  const { players, room } = await table(browser, ["Ann", "Ben", "Cat"]);
  await startHand(players[0], room);
  const sleeper = await whoseTurn(players);
  const others = players.filter((p) => p !== sleeper);
  // nobody touches the sleeper's page; server must fold them (12 s test timeout)
  await expect(sleeper.page.getByText("你逾時已自動棄牌並暫離")).toBeVisible({ timeout: 25_000 });
  await shot(sleeper.page, "f05-timeout-toast");
  await autoplay(others, async () => (await view(others[0], room)).hand === null, 30_000, "fold");
  await expect(btn(sleeper, "回到牌局")).toBeVisible();
  await expect(others[0].page.locator("span", { hasText: /^暫離$/ })).toBeVisible();
  // next hand is dealt automatically without the sleeper
  await expect(others[0].page.getByText(/^#2 · 翻牌前$/)).toBeVisible({ timeout: 12_000 });
  await expect(sleeper.page.getByLabel("你的手牌")).toBeHidden();
  // back in -> dealt into the following hand
  await btn(sleeper, "回到牌局").click();
  await expect(btn(sleeper, "暫離")).toBeVisible();
  await autoplay(others, async () => (await view(others[0], room)).hand === null, 30_000, "fold");
  await expect(sleeper.page.getByLabel("你的手牌")).toBeVisible({ timeout: 12_000 });
});

// ---------------------------------------------------------------------------
test("auto-deal countdown, deal now, host pause/resume", async ({ browser }) => {
  test.setTimeout(120_000);
  const { players, room } = await table(browser, ["Hal", "Ivy"]);
  const [host, ivy] = players;
  await btn(host, "開始下一手").click();
  await act(await whoseTurn(players), "fold");
  await expect(host.page.getByText(/^下一手 \d 秒後開始$/)).toBeVisible();
  await expect(btn(host, "立即發下一手")).toBeVisible();
  await expect(btn(ivy, "立即發下一手")).toBeHidden(); // host-only control
  await shot(host.page, "f06-countdown");
  // deal now skips the countdown
  await btn(host, "立即發下一手").click();
  await expect(host.page.getByText(/^#2 · 翻牌前$/)).toBeVisible({ timeout: 3_000 });
  await act(await whoseTurn(players), "fold");

  // pause auto-deal from the host panel
  await host.page.getByRole("tab", { name: "房主" }).click();
  await expect(host.page.getByText("已開啟", { exact: true })).toBeVisible();
  await btn(host, "暫停自動發牌").click();
  await expect(host.page.getByText("已暫停", { exact: true })).toBeVisible();
  await expect(ivy.page.getByText("自動發牌已暫停")).toBeVisible();
  await host.page.waitForTimeout(7_000);
  expect((await view(host, room)).hand).toBeNull();
  // manual start still works while paused
  await btn(host, "開始下一手").first().click();
  await expect(host.page.getByText(/^#3 · 翻牌前$/)).toBeVisible();
  await act(await whoseTurn(players), "fold");
  await expect(ivy.page.getByText("自動發牌已暫停")).toBeVisible();
  // resume -> next hand without any click
  await btn(host, "恢復自動發牌").click();
  await expect(ivy.page.getByText(/^#4 · 翻牌前$/)).toBeVisible({ timeout: 10_000 });
});

// ---------------------------------------------------------------------------
test("host leaves: hand finishes, new host elected, dealing continues, idle player stood up", async ({ browser }) => {
  test.setTimeout(200_000);
  const { players, room } = await table(browser, ["Host", "Ben", "Cat"]);
  const [host, ben, cat] = players;
  await startHand(host, room);
  await host.ctx.close(); // the host just closes the browser
  const rest = [ben, cat];
  // the remaining two keep playing; the host's turns time out
  await autoplay(rest, async () => {
    const v = await view(ben, room);
    return v.hand !== null && v.hand.ordinal >= 2;
  }, 60_000);
  // Ben joined first among the connected members -> new host
  await expect(ben.page.getByRole("tab", { name: "房主" })).toBeVisible({ timeout: 15_000 });
  await shot(ben.page, "f07-new-host");
  const v = await view(ben, room);
  const hostSeat = v.seats.find((s: { nickname: string }) => s.nickname === "Host");
  expect(hostSeat.participation_state).toBe("SITTING_OUT");
  expect(v.hand.seats.map((s: { seat_no: number }) => s.seat_no)).not.toContain(hostSeat.seat_no);
  // sitting out longer than the limit (1 min in this test stack) -> stood up + cashed out
  await autoplay(rest, async () =>
    !(await view(ben, room)).seats.some((s: { nickname: string }) => s.nickname === "Host"), 110_000);
  const v2 = await view(ben, room);
  const row = v2.standings.find((r: { nickname: string }) => r.nickname === "Host");
  expect(row.seated).toBe(false);
  expect(row.cashed_out).toBeGreaterThan(0);
});

// ---------------------------------------------------------------------------
test("chat: toast, seat bubble, unread badges, escaping, rate limit", async ({ browser }) => {
  const { players } = await table(browser, ["Ann", "Bob"], { devices: [DEVICES.phone, DEVICES.desktop] });
  const [ann, bob] = players;
  const msg = "嗨 <img src=x onerror=alert(1)> 🎉";
  await bob.page.getByLabel("聊天訊息").fill(msg);
  await btn(bob, "送出").click();
  await expect(ann.page.getByText(`💬 Bob: ${msg}`)).toBeVisible();
  await expect(ann.page.locator(".seat-bubble")).toHaveText(msg);
  await expect(ann.page.getByRole("button", { name: "開啟面板" })).toContainText("1");
  await shot(ann.page, "f08-chat-toast-bubble");
  await ann.page.getByRole("button", { name: "開啟面板" }).click();
  await expect(ann.page.getByRole("tab", { name: "聊天" })).toHaveAttribute("aria-selected", "true");
  await expect(ann.page.getByText(msg).first()).toBeVisible();
  await ann.page.getByRole("button", { name: "關閉面板" }).click();
  await expect(ann.page.getByRole("button", { name: "開啟面板" })).not.toContainText("1");
  // reply reaches the desktop panel directly (no toast needed there)
  await ann.page.getByRole("button", { name: "開啟面板" }).click();
  await ann.page.getByLabel("聊天訊息").fill("gg");
  await btn(ann, "送出").click();
  await expect(bob.page.locator("aside").getByText("gg", { exact: true })).toBeVisible();
  // 500 chars max
  await expect(bob.page.getByLabel("聊天訊息")).toHaveAttribute("maxlength", "500");
  // spamming is rate limited with a localized message
  for (let i = 0; i < 14; i++) {
    await bob.page.getByLabel("聊天訊息").fill(`spam ${i}`);
    await bob.page.getByLabel("聊天訊息").press("Enter");
  }
  await expect(bob.page.getByText("操作太頻繁，請稍候")).toBeVisible();
});

// ---------------------------------------------------------------------------
test("top-ups: request, approve, reject, limit", async ({ browser }) => {
  const { players, room } = await table(browser, ["Hal", "Bob"], { buyins: [1000, 500] });
  const [hal, bob] = players;
  await btn(bob, "補碼").click();
  await bob.page.getByLabel("金額", { exact: true }).fill("1600");
  await expect(btn(bob, "送出申請")).toBeDisabled(); // 500 + 1600 > 2000
  await bob.page.getByLabel("金額", { exact: true }).fill("1000");
  await btn(bob, "送出申請").click();
  await expect(bob.page.getByText("補碼 1,000：待核准")).toBeVisible();
  await expect(hal.page.getByRole("tab", { name: /房主/ })).toContainText("1");
  await hal.page.getByRole("tab", { name: /房主/ }).click();
  await expect(hal.page.getByText("Bob 申請 1,000")).toBeVisible();
  await btn(hal, "核准").click();
  await expect(bob.page.getByText("1,500").first()).toBeVisible(); // applied now (no hand running)
  await expect(bob.page.getByText("補碼 1,000：待核准")).toBeHidden();
  // reject
  await btn(bob, "補碼").click();
  await bob.page.getByLabel("金額", { exact: true }).fill("200");
  await btn(bob, "送出申請").click();
  await btn(hal, "拒絕").click();
  await expect(bob.page.getByText("補碼 200：待核准")).toBeHidden();
  const v = await view(bob, room);
  const me = v.standings.find((r: { nickname: string }) => r.nickname === "Bob");
  expect(me.invested).toBe(1500);
  expect(me.net).toBe(0);
});

// ---------------------------------------------------------------------------
test("host settings mid-hand apply next hand; members: kick, ban, unban, transfer", async ({ browser }) => {
  test.setTimeout(120_000);
  const { players, room } = await table(browser, ["Hal", "Bob", "Cat"]);
  const [hal, bob, cat] = players;
  await startHand(hal, room);
  await hal.page.getByRole("tab", { name: "房主" }).click();
  await expect(hal.page.getByText("盲注與買入（下一手生效）")).toBeVisible();
  await hal.page.getByLabel("小盲").fill("10");
  await hal.page.getByLabel("大盲").fill("20");
  await btn(hal, "儲存設定").click();
  await expect(bob.page.getByText(/下一手改設定/)).toBeVisible();
  await autoplay(players, async () => (await view(hal, room)).hand === null, 30_000, "fold");
  await expect(bob.page.getByText(/盲注 10\/20/)).toBeVisible({ timeout: 10_000 });

  // pause dealing so membership changes happen between hands
  await btn(hal, "暫停自動發牌").click();
  await autoplay(players, async () => (await view(hal, room)).hand === null, 30_000, "fold");
  await hal.page.getByRole("tab", { name: "成員" }).click();
  const row = (name: string) => hal.page.locator("aside div.rounded-lg").filter({ hasText: name });
  await row("Bob").getByRole("button", { name: "請離桌" }).click();
  await expect(bob.page.getByText("觀戰中 · 點空位坐下")).toBeVisible();
  await row("Cat").getByRole("button", { name: "封鎖" }).click();
  await expect(cat.page.getByText("你已被此房間封鎖")).toBeVisible({ timeout: 10_000 });
  await shot(cat.page, "f09-banned");
  await row("Cat").getByRole("button", { name: "解除封鎖" }).click();
  await join(cat, room); // can come back with the invite + password after unban
  await openRoom(cat, room);
  await row("Bob").getByRole("button", { name: "轉讓房主" }).click();
  await expect(bob.page.getByRole("tab", { name: "房主" })).toBeVisible();
  await expect(hal.page.getByRole("tab", { name: "房主" })).toBeHidden();
  const v = await view(hal, room);
  expect(v.standings.find((r: { nickname: string }) => r.nickname === "Bob").seated).toBe(false);
});

// ---------------------------------------------------------------------------
test("standings pop every 5 hands, history, replay, ledger", async ({ browser }) => {
  test.setTimeout(120_000);
  const { players, room } = await table(browser, ["Hal", "Ivy"]);
  const [hal, ivy] = players;
  for (let n = 1; n <= 5; n++) {
    if (n === 1) await btn(hal, "開始下一手").click();
    else await btn(hal, "立即發下一手").click();
    await expect(hal.page.getByText(new RegExp(`^#${n} · 翻牌前$`))).toBeVisible();
    await act(await whoseTurn(players), "fold");
    await waitResult(hal);
  }
  const pop = ivy.page.getByRole("dialog", { name: "水上水下" });
  await expect(pop).toBeVisible();
  await expect(pop.getByText("第 5 手後")).toBeVisible();
  await shot(ivy.page, "f10-standings-pop");
  await pop.getByRole("button", { name: "關閉" }).click();
  await expect(pop).toBeHidden();
  await btn(ivy, "水上水下").click(); // header 🏆
  await expect(pop).toBeVisible();
  await btn(ivy, "水上水下").click();

  await hal.page.getByRole("tab", { name: "房主" }).click();
  await btn(hal, "暫停自動發牌").click();
  await ivy.page.getByRole("tab", { name: "戰績" }).click();
  const v = await view(ivy, room);
  expect(v.standings.reduce((s: number, r: { net: number }) => s + r.net, 0)).toBe(0);
  await ivy.page.getByRole("tab", { name: "籌碼" }).click();
  await expect(ivy.page.getByRole("cell", { name: "淨值" })).toBeVisible();
  await ivy.page.getByRole("tab", { name: "歷史" }).click();
  for (let n = 1; n <= 5; n++) await expect(ivy.page.getByText(`#${n} · 5/10`)).toBeVisible();
  await ivy.page.getByText("#1 · 5/10").click();
  await ivy.page.waitForURL(/\/hands\//);
  await expect(ivy.page.getByText(/回放 #1/)).toBeVisible();
  await btn(ivy, "下一步").click();
  await btn(ivy, "下一步").click();
  await btn(ivy, "上一步").click();
  await btn(ivy, "播放").click();
  await expect(ivy.page.getByText("結算完成")).toBeVisible({ timeout: 15_000 });
  await ivy.page.getByRole("link", { name: "‹ 回牌桌" }).click();
  await expect(ivy.page.getByLabel(/連線狀態/)).toBeVisible();
});

// ---------------------------------------------------------------------------
test("English: browser default, toggle, persistence, no untranslated UI", async ({ browser }) => {
  const en = await blankPlayer(browser, "Eve", DEVICES.desktop, "en-US");
  await en.page.goto("/");
  await expect(btn(en, "Enter")).toBeVisible();
  await en.page.getByPlaceholder("e.g. Andrew").fill("Eve");
  await btn(en, "Enter").click();
  await expect(en.page.getByText("Create a private room")).toBeVisible();
  expect(await cjkLeftovers(en.page, ["中"])).toEqual([]);
  await btn(en, "切換成中文").click();
  await expect(en.page.getByText("建立私人房間")).toBeVisible();
  await en.page.reload();
  await expect(en.page.getByText("建立私人房間")).toBeVisible(); // remembered
  await btn(en, "Switch to English").click();

  // full room in English
  const room = await createRoom(en, { name: "Friday" });
  const zed = await newPlayer(browser, "Zed", DEVICES.phone, "en-US");
  await join(zed, room);
  await sit(en, room, 1);
  await sit(zed, room, 2);
  await openRoom(en, room);
  await openRoom(zed, room);
  await btn(en, "Deal next hand").click();
  const players = [en, zed];
  const actor = await whoseTurn(players);
  await expect(actor.page.getByRole("button", { name: /^(Call|Check)/ }).first()).toBeVisible();
  expect(await cjkLeftovers(en.page, ["中文"])).toEqual([]);
  expect(await cjkLeftovers(zed.page, [])).toEqual([]);
  await shot(zed.page, "f11-english-phone");
  await autoplay(players, async () => (await view(en, room)).hand === null, 30_000, "fold");
  await expect(en.page.getByText(/wins/).first()).toBeVisible();
  for (const tab of ["Standings", "Players", "History", "Chips", "Host"]) {
    await en.page.getByRole("tab", { name: tab }).click();
    expect(await cjkLeftovers(en.page, ["中文"]), `tab ${tab}`).toEqual([]);
  }
  await shot(en.page, "f12-english-desktop-host");
});

// ---------------------------------------------------------------------------
test("settings: music, sound, notifications; no audio errors", async ({ browser }) => {
  const { players } = await table(browser, ["Ann", "Bob"]);
  const [ann] = players;
  // headless Chromium reports "denied" even when granted; emulate a real granted browser
  await ann.page.addInitScript(() => {
    Object.defineProperty(Notification, "permission", { get: () => "granted" });
  });
  await ann.page.reload();
  await btn(ann, "設定").click();
  for (const name of ["背景音樂", "音效", "背景通知"]) {
    const sw = ann.page.getByRole("switch", { name });
    const before = await sw.getAttribute("aria-checked");
    await sw.click();
    await expect(sw).not.toHaveAttribute("aria-checked", before!);
  }
  await ann.page.waitForTimeout(2500); // music scheduler runs
  const prefs = await ann.page.evaluate(() => JSON.parse(localStorage.getItem("sound-prefs") ?? "{}"));
  expect(prefs).toEqual({ music: true, sfx: false, notify: true });
  await ann.page.keyboard.press("Escape");
  await expect(ann.page.getByRole("switch", { name: "背景音樂" })).toBeHidden();
  await ann.page.reload();
  await btn(ann, "設定").click();
  await expect(ann.page.getByRole("switch", { name: "背景音樂" })).toHaveAttribute("aria-checked", "true");
});

// ---------------------------------------------------------------------------
test("leave seat mid-hand folds, cashes out after the hand", async ({ browser }) => {
  const { players, room } = await table(browser, ["Hal", "Bob", "Cat"]);
  const [hal, bob, cat] = players;
  await startHand(hal, room);
  await bob.page.getByRole("button", { name: "座位選項" }).click(); // seat tools live in the action bar mid-hand
  await bob.page.getByRole("menuitem", { name: "離桌" }).click(); // confirm() accepted by the helper
  await expect(hal.page.getByText("離桌中")).toBeVisible();
  await autoplay([hal, cat], async () => (await view(hal, room)).hand === null, 40_000, "fold");
  await expect(bob.page.getByText("觀戰中 · 點空位坐下")).toBeVisible();
  const row = (await view(hal, room)).standings.find((r: { nickname: string }) => r.nickname === "Bob");
  expect(row.seated).toBe(false);
  expect(row.cashed_out).toBeGreaterThan(0);
});

// ---------------------------------------------------------------------------
test("spectator never sees hidden hole cards", async ({ browser }) => {
  const { players, room } = await table(browser, ["Ann", "Bob"]);
  const spec = await newPlayer(browser, "Spy");
  await join(spec, room);
  await openRoom(spec, room);
  await startHand(players[0], room);
  await expect(players[0].page.getByLabel("你的手牌")).toBeVisible();
  const own = async (p: Player) => p.page.getByLabel("你的手牌").locator("[aria-label]")
    .evaluateAll((els) => els.map((e) => e.getAttribute("aria-label")));
  const hidden = [...(await own(players[0])), ...(await own(players[1]))];
  const seen = await spec.page.locator("[aria-label]").evaluateAll((els) => els.map((e) => e.getAttribute("aria-label")));
  for (const c of hidden) expect(seen).not.toContain(c);
  await expect(spec.page.getByText("觀戰中 · 點空位坐下")).toBeVisible();
  const v = await view(spec, room);
  expect(v.hand.your_cards).toBeUndefined();
});

// ---------------------------------------------------------------------------
test("invite rotation, nickname change, re-sitting after leaving", async ({ browser }) => {
  const { players, room } = await table(browser, ["Hal", "Bob"]);
  const [hal, bob] = players;
  // host rotates the invite: the old link stops working
  await hal.page.getByRole("tab", { name: "房主" }).click();
  await btn(hal, "產生新連結（舊的失效）").click();
  await expect(hal.page.getByText(/\/join\//)).toBeVisible();
  const late = await blankPlayer(browser, "Late");
  await late.page.goto(room.invite_path);
  await late.page.getByLabel("暱稱").fill("Late");
  await late.page.getByLabel("房間密碼").fill(PASSWORD);
  await btn(late, "加入").click();
  await expect(late.page.locator("p[role=alert]")).toHaveText("邀請連結已失效，請向房主索取新的連結");
  await expect(late.page).toHaveURL(/\/join\//);
  // the new link works
  const fresh = (await hal.page.getByText(/\/join\//).innerText()).trim();
  await late.page.goto(fresh);
  await late.page.getByLabel("房間密碼").fill(PASSWORD);
  await btn(late, "加入").click();
  await late.page.waitForURL(/\/rooms\/[^/]+$/);

  // nickname change from the lobby shows up at the table
  await bob.page.goto("/");
  await bob.page.getByPlaceholder("改暱稱").fill("Bobby");
  await btn(bob, "更新").click();
  await expect(bob.page.getByText("目前暱稱：")).toContainText("Bobby");
  await openRoom(bob, room);
  await expect(hal.page.locator("[data-seat='2']")).toContainText("Bobby");

  // leave the seat, then sit down again with a new buy-in
  await btn(bob, "離桌").click();
  await expect(bob.page.getByText("觀戰中 · 點空位坐下")).toBeVisible();
  await bob.page.getByRole("button", { name: "坐到 5 號位" }).click();
  await bob.page.getByLabel("金額", { exact: true }).fill("300");
  await btn(bob, "坐下").click();
  await expect(bob.page.locator("[data-me]")).toContainText("300");
  const v = await view(hal, room);
  const row = v.standings.find((r: { nickname: string }) => r.nickname === "Bobby");
  expect(row.invested).toBe(1300);
  expect(row.net).toBe(0);
});

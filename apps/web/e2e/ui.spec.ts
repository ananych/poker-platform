import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import {
  api, BASE, blankPlayer, cleanup, createRoom, DEVICES, finishHandViaApi, join, newPlayer, noHorizontalScroll,
  openRoom, SHOTS, sit, startHand, type Player,
} from "./helpers";

/**
 * Layout sweep: a full 9-handed table with long/mixed nicknames, viewed from many
 * devices. Checks no horizontal scroll, no clipped seats, little seat overlap, and
 * saves screenshots for visual review.
 */
test.afterEach(cleanup);

const NAMES = ["Andrew", "超級無敵長的暱稱測試玩家一號", "Bob", "VeryLongEnglishNicknameForTest",
  "小明", "Émilie 🎲", "李四", "Charlie", "王小美"];

const VIEWS = {
  "320-phone": DEVICES.smallPhone,
  "390-phone": DEVICES.phone,
  "412-android": DEVICES.android,
  "844-landscape": DEVICES.landscape,
  "768-tablet": DEVICES.tablet,
  "1024-tablet-land": { viewport: { width: 1024, height: 768 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
  "1366-laptop": { viewport: { width: 1366, height: 768 } },
  "1280-desktop": DEVICES.desktop,
  "1920-wide": DEVICES.wide,
};

interface Box { x: number; y: number; w: number; h: number }
async function layout(page: Page) {
  return page.evaluate(() => {
    const box = (r: DOMRect) => ({ x: r.left, y: r.top, w: r.width, h: r.height });
    const area = document.querySelector("[data-testid=table-area]")!.getBoundingClientRect();
    const seats = [...document.querySelectorAll("[data-seat]")].map((e) => {
      const card = e.querySelector(":scope > .rounded-xl") as HTMLElement | null;
      return { n: Number(e.getAttribute("data-seat")), occupied: !!card,
               box: box((card ?? (e as HTMLElement)).getBoundingClientRect()) };
    });
    const bets = [...document.querySelectorAll("[data-bet]")].map((e) => ({
      n: Number(e.getAttribute("data-bet")), box: box(e.getBoundingClientRect()) }));
    const center = ["board", "pot"].map((id) => document.querySelector(`[data-testid=${id}]`))
      .filter(Boolean).map((e) => box(e!.getBoundingClientRect()));
    return { area: box(area), seats, bets, center, vw: innerWidth, sw: document.documentElement.scrollWidth };
  });
}
const inter = (a: Box, b: Box) =>
  Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)) *
  Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));

function check(name: string, l: Awaited<ReturnType<typeof layout>>) {
  const problems: string[] = [];
  if (l.sw > l.vw + 1) problems.push(`horizontal scroll ${l.sw}>${l.vw}`);
  const occ = l.seats.filter((s) => s.occupied);
  for (const s of l.seats) {
    const b = s.box, a = l.area;
    if (b.x < a.x - 1 || b.y < a.y - 1 || b.x + b.w > a.x + a.w + 1 || b.y + b.h > a.y + a.h + 1) {
      problems.push(`seat ${s.n} clipped`);
    }
  }
  for (const b of l.bets) {
    for (const c of l.center) {
      if (inter(b.box, c) / (b.box.w * b.box.h) > 0.3) problems.push(`bet ${b.n} overlaps pot/board`);
    }
    for (const s of occ) {
      if (inter(b.box, s.box) / (b.box.w * b.box.h) > 0.25) problems.push(`bet ${b.n} covers seat ${s.n}`);
    }
  }
  for (let i = 0; i < occ.length; i++) {
    for (let j = i + 1; j < occ.length; j++) {
      const r = inter(occ[i].box, occ[j].box) / Math.min(occ[i].box.w * occ[i].box.h, occ[j].box.w * occ[j].box.h);
      if (r > 0.12) problems.push(`seats ${occ[i].n}/${occ[j].n} overlap ${(r * 100).toFixed(0)}%`);
    }
  }
  return { name, problems };
}

test("9-handed table on every device", async ({ browser }) => {
  test.setTimeout(240_000);
  const players: Player[] = [];
  for (const n of NAMES) players.push(await newPlayer(browser, n));
  const room = await createRoom(players[0], { name: "週五夜場 Friday Night Poker Club" });
  for (const p of players.slice(1)) await join(p, room);
  for (const [i, p] of players.entries()) await sit(p, room, i + 1, 1000 + i * 111);
  await startHand(players[0], room);
  const viewer = players[1];
  const state = await viewer.ctx.storageState();

  const report = [];
  for (const [name, device] of Object.entries(VIEWS)) {
    const ctx = await browser.newContext({ ...device, locale: "zh-TW", baseURL: BASE, storageState: state });
    const page = await ctx.newPage();
    await page.goto(`/rooms/${room.room_id}`);
    await expect(page.getByLabel(/連線狀態 open/)).toBeVisible();
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${SHOTS}/u-${name}.png` });
    report.push(check(name, await layout(page)));
    await ctx.close();
  }
  // spectator + English on a phone
  const spy = await newPlayer(browser, "Spectator", DEVICES.phone, "en-US");
  await join(spy, room);
  await openRoom(spy, room);
  await spy.page.waitForTimeout(600);
  await spy.page.screenshot({ path: `${SHOTS}/u-390-spectator-en.png` });
  report.push(check("390-spectator-en", await layout(spy.page)));

  // after the hand: showdown cards, winner glow, per-seat +/- pills
  const after = ["320-phone", "390-phone", "844-landscape", "1280-desktop"] as const;
  const pages = [];
  for (const name of after) {
    const ctx = await browser.newContext({ ...VIEWS[name], locale: "zh-TW", baseURL: BASE, storageState: state });
    const page = await ctx.newPage();
    await page.goto(`/rooms/${room.room_id}`);
    await expect(page.getByLabel(/連線狀態 open/)).toBeVisible();
    pages.push({ name, ctx, page });
  }
  // keep the result on screen (no auto-deal) while we take the screenshots
  await api(players[0], "POST", `/rooms/${room.room_id}/auto-deal`, { enabled: false });
  await finishHandViaApi(players, room);
  for (const { name, ctx, page } of pages) {
    await expect(page.getByText(/贏得/).first()).toBeVisible();
    await page.waitForTimeout(700);
    await page.screenshot({ path: `${SHOTS}/u-${name}-result.png` });
    report.push(check(`${name}-result`, await layout(page)));
    await ctx.close();
  }

  fs.writeFileSync(`${SHOTS}/u-report.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report.filter((r) => r.problems.length), null, 2));
  expect(report.filter((r) => r.problems.some((p) => p.includes("horizontal") || p.includes("clipped"))),
         "no clipped seats / horizontal scroll").toEqual([]);
});

test("lobby and join pages on a 320px phone", async ({ browser }) => {
  const host = await newPlayer(browser, "Host");
  const room = await createRoom(host);
  const p = await blankPlayer(browser, "Tiny", DEVICES.smallPhone);
  await p.page.goto("/");
  await noHorizontalScroll(p.page);
  await p.page.screenshot({ path: `${SHOTS}/u-320-lobby.png`, fullPage: true });
  await p.page.goto(room.invite_path);
  await noHorizontalScroll(p.page);
  await p.page.screenshot({ path: `${SHOTS}/u-320-join.png` });
  for (const b of await p.page.locator("button:visible").all()) {
    const box = await b.boundingBox();
    if (box && await b.isEnabled()) expect.soft(box.height, await b.innerText()).toBeGreaterThanOrEqual(40);
  }
});

test("my-turn controls and seat menu on small screens", async ({ browser }) => {
  test.setTimeout(120_000);
  const views = { "320": DEVICES.smallPhone, "390": DEVICES.phone, "844-land": DEVICES.landscape } as const;
  for (const [name, device] of Object.entries(views)) {
    const a = await newPlayer(browser, "Andrew", device);
    const b = await newPlayer(browser, "Bob");
    const room = await createRoom(a);
    await join(b, room);
    await sit(a, room, 1);
    await sit(b, room, 2);
    await openRoom(a, room);
    await startHand(a, room);
    // heads-up: the button (seat 1 = Andrew) acts first preflop
    await expect(a.page.getByText("輪到你了")).toBeVisible();
    await noHorizontalScroll(a.page);
    await a.page.screenshot({ path: `${SHOTS}/u-${name}-myturn.png` });
    for (const el of await a.page.locator("[data-testid=action-bar] button:visible").all()) {
      const box = await el.boundingBox();
      if (box) expect.soft(box.height, `${name}: ${await el.innerText()}`).toBeGreaterThanOrEqual(40);
    }
    await a.page.getByRole("button", { name: "座位選項" }).click();
    await expect(a.page.getByRole("menuitem", { name: "補碼" })).toBeVisible();
    await a.page.screenshot({ path: `${SHOTS}/u-${name}-seatmenu.png` });
    await a.page.keyboard.press("Escape");
    await cleanup();
  }
});

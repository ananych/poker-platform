import { expect, type Browser, type BrowserContext, type Page } from "@playwright/test";

/** Shared helpers for multi-player E2E tests (each player = its own browser context). */

export const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3000";
export const PASSWORD = "e2e-secret";
export const SHOTS = process.env.E2E_SHOTS ?? "e2e-artifacts";

export const DEVICES = {
  phone: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
  smallPhone: { viewport: { width: 320, height: 568 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
  android: { viewport: { width: 412, height: 915 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2.6 },
  landscape: { viewport: { width: 844, height: 390 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
  tablet: { viewport: { width: 768, height: 1024 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
  desktop: { viewport: { width: 1280, height: 800 } },
  wide: { viewport: { width: 1920, height: 1080 } },
} as const;
type Device = (typeof DEVICES)[keyof typeof DEVICES];

export interface Player {
  name: string;
  ctx: BrowserContext;
  page: Page;
  /** uncaught page errors + unexpected alert() dialogs */
  errors: string[];
}

const live: Player[] = [];

/** Close every player created in this test and fail on any page error. */
export async function cleanup() {
  const all = live.splice(0);
  const errs = all.flatMap((p) => p.errors.map((e) => `${p.name}: ${e}`));
  await Promise.all(all.map((p) => p.ctx.close().catch(() => {})));
  expect(errs, "uncaught page errors").toEqual([]);
}

/** A browser profile without a guest session yet (for UI onboarding tests). */
export async function blankPlayer(browser: Browser, name: string, device: Device = DEVICES.desktop,
                                  locale = "zh-TW"): Promise<Player> {
  const ctx = await browser.newContext({ ...device, locale, baseURL: BASE });
  const page = await ctx.newPage();
  const p: Player = { name, ctx, page, errors: [] };
  page.on("pageerror", (e) => p.errors.push(String(e)));
  page.on("dialog", async (d) => {
    if (d.type() !== "confirm") p.errors.push(`unexpected ${d.type()}: ${d.message()}`);
    await d.accept();
  });
  live.push(p);
  return p;
}

/** A player that already has a guest session (fast setup through the API). */
export async function newPlayer(browser: Browser, name: string, device: Device = DEVICES.desktop,
                                locale = "zh-TW"): Promise<Player> {
  const p = await blankPlayer(browser, name, device, locale);
  await api(p, "POST", "/guests/session", { nickname: name });
  return p;
}

export async function api<T = any>(p: Player, method: string, path: string, body?: unknown): Promise<T> { // eslint-disable-line @typescript-eslint/no-explicit-any
  const r = await p.ctx.request.fetch(`${BASE}/api/v1${path}`, {
    method,
    data: body === undefined ? undefined : JSON.stringify(body),
    headers: { Origin: BASE, "X-Poker-CSRF": "1", "Content-Type": "application/json" },
  });
  if (!r.ok()) throw new Error(`${p.name}: ${method} ${path} -> ${r.status()} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export interface Room { room_id: string; invite_token: string; invite_path: string }

export async function createRoom(host: Player, cfg: Record<string, unknown> = {}): Promise<Room> {
  return api<Room>(host, "POST", "/rooms", {
    password: PASSWORD, name: "E2E", sb: 5, bb: 10, min_buyin: 100, max_buyin: 2000, ...cfg,
  });
}

export async function join(p: Player, room: Room) {
  await api(p, "POST", `/rooms/${room.room_id}/join`, { invite_token: room.invite_token, password: PASSWORD });
}

export async function sit(p: Player, room: Room, seat: number, buyin = 1000) {
  await api(p, "POST", `/rooms/${room.room_id}/seats/${seat}`, { buyin });
}

export async function view(p: Player, room: Room) {
  return api(p, "GET", `/rooms/${room.room_id}`);
}

export async function startHand(host: Player, room: Room) {
  const v = await view(host, room);
  return api(host, "POST", `/rooms/${room.room_id}/start-hand`, { expected_room_version: v.room_version });
}

/** Create a room with `host` + `others`, everyone joined and seated (seats 1..n), pages open. */
export async function table(browser: Browser, names: string[], opts: {
  devices?: Device[]; buyins?: number[]; cfg?: Record<string, unknown>; seats?: number[]; locale?: string;
} = {}) {
  const players: Player[] = [];
  for (const [i, n] of names.entries()) {
    players.push(await newPlayer(browser, n, opts.devices?.[i] ?? DEVICES.desktop, opts.locale));
  }
  const room = await createRoom(players[0], opts.cfg);
  for (const p of players.slice(1)) await join(p, room);
  for (const [i, p] of players.entries()) await sit(p, room, opts.seats?.[i] ?? i + 1, opts.buyins?.[i] ?? 1000);
  for (const p of players) await openRoom(p, room);
  return { players, room };
}

export async function openRoom(p: Player, room: Room) {
  await p.page.goto(`/rooms/${room.room_id}`);
  await expect(p.page.getByLabel(/連線狀態 open|Connection open/)).toBeVisible({ timeout: 15_000 });
}

export const turnText = (p: Player) => p.page.getByText(/^(輪到你了|Your turn)$/);

/** Whose turn is it (by the UI)? Polls all pages. */
export async function whoseTurn(players: Player[], timeout = 20_000): Promise<Player> {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    for (const p of players) {
      if (await turnText(p).isVisible().catch(() => false)) return p;
    }
    await players[0].page.waitForTimeout(150);
  }
  throw new Error("nobody has the turn");
}

export function btn(p: Player, name: string | RegExp) {
  return p.page.getByRole("button", { name, exact: typeof name === "string" });
}

/** Perform a poker action through the action bar, then wait for the turn to move on. */
export async function act(p: Player, a: "fold" | "check" | "call" | "checkOrCall" | "allin" | "potRaise" | "halfPot") {
  await actOnce(p, a);
  // don't let the next whoseTurn() pick this page again from a not-yet-updated view
  await turnText(p).waitFor({ state: "hidden", timeout: 1500 }).catch(() => {});
}

async function actOnce(p: Player, a: "fold" | "check" | "call" | "checkOrCall" | "allin" | "potRaise" | "halfPot") {
  const page = p.page;
  await expect(turnText(p)).toBeVisible();
  // labels in both UI languages
  const FOLD = /^(棄牌|Fold)$/, CHECK = /^(過牌|Check)$/, CALL = /^(跟注|Call) /;
  if (a === "fold") return btn(p, FOLD).click();
  if (a === "check") return btn(p, CHECK).click();
  if (a === "call") return btn(p, CALL).click();
  if (a === "checkOrCall") {
    if (await btn(p, CHECK).isVisible()) return btn(p, CHECK).click();
    return btn(p, CALL).click();
  }
  const preset = { allin: /^(全下|All-in)$/, potRaise: /^(1 池|Pot)$/, halfPot: /^(½ 池|½ pot)$/ }[a];
  const presetBtn = page.getByRole("button", { name: preset }).first();
  if (await presetBtn.isVisible()) {
    await presetBtn.click();
    // the confirm button is the last button in the action grid (bet/raise/all-in)
    const confirm = page.getByRole("button", { name: /^(下注|加注到|全下|Bet|Raise to|All-in)/ }).last();
    return confirm.click();
  }
  // cannot raise (e.g. facing a bigger all-in): call instead
  return btn(p, CALL).click();
}

/** Wait until the current hand is over (result banner) on the given page. */
export async function waitResult(p: Player, timeout = 20_000) {
  await expect(p.page.getByText(/贏得|wins/).first()).toBeVisible({ timeout });
}

/** Keep playing passively (check/call) for `players` until `done()` is true. */
export async function autoplay(players: Player[], done: () => Promise<boolean>, timeout = 60_000,
                               style: "passive" | "fold" = "passive") {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    if (await done()) return;
    for (const p of players) {
      if (p.page.isClosed()) continue;
      if (await turnText(p).isVisible().catch(() => false)) {
        try { await act(p, style === "fold" ? "fold" : "checkOrCall"); } catch { /* raced */ }
        await p.page.waitForTimeout(250);
      }
    }
    await players[0].page.waitForTimeout(200);
  }
  throw new Error("autoplay timed out");
}

/** Play the current hand to the end through the REST action endpoint (fast, no UI). */
export async function finishHandViaApi(players: Player[], room: Room, policy: "passive" | "fold" = "passive") {
  for (let i = 0; i < 200; i++) {
    let acted = false;
    for (const p of players) {
      const v = await view(p, room);
      if (!v.hand) return;
      const la = v.hand.legal_actions;
      if (!la) continue;
      const action = policy === "fold" && !la.can_check ? "FOLD" : la.can_check ? "CHECK" : "CALL";
      await api(p, "POST", `/rooms/${room.room_id}/actions`, {
        action_id: crypto.randomUUID(), hand_id: v.hand.hand_id, expected_room_version: v.room_version, action,
      }).catch(() => {});
      acted = true;
      break;
    }
    if (!acted) await players[0].page.waitForTimeout(100);
  }
  throw new Error("hand did not finish");
}

export async function noHorizontalScroll(page: Page) {
  const [sw, iw] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(sw, "horizontal scroll").toBeLessThanOrEqual(iw + 1);
}

/** Visible text containing CJK characters, excluding user-provided names/messages. */
export async function cjkLeftovers(page: Page, allow: string[]) {
  const text = await page.evaluate(() => document.body.innerText);
  let rest = text;
  for (const a of allow) rest = rest.split(a).join("");
  return [...new Set(rest.split("\n").filter((l) => /[㐀-鿿]/.test(l)).map((l) => l.trim()))];
}

export async function shot(page: Page, name: string) {
  await page.screenshot({ path: `${SHOTS}/${name}.png` });
}

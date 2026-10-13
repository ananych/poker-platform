import { expect, test } from "@playwright/test";
import { execSync } from "node:child_process";
import { act, btn, cleanup, shot, startHand, table, view, waitResult, whoseTurn } from "./helpers";

/**
 * Server restart (deploy) while people are playing. Needs the local test stack:
 * RESTART_API points at a script that restarts the API process.
 */
const RESTART = process.env.RESTART_API;
test.skip(!RESTART, "RESTART_API not set");
test.afterEach(cleanup);
test.describe.configure({ mode: "serial" });

test("restart mid-hand: clients reconnect, hand frozen, host resumes", async ({ browser }) => {
  test.setTimeout(120_000);
  const { players, room } = await table(browser, ["Hal", "Ivy"]);
  const [hal, ivy] = players;
  await startHand(hal, room);
  await whoseTurn(players);
  execSync(RESTART!, { stdio: "ignore" });
  for (const p of players) {
    await expect(p.page.getByText("伺服器重啟後牌局已凍結", { exact: false })).toBeVisible({ timeout: 30_000 });
    await expect(p.page.getByLabel(/連線狀態 open/)).toBeVisible({ timeout: 30_000 });
  }
  await expect(btn(ivy, "繼續牌局")).toBeHidden(); // host only
  await shot(hal.page, "r01-paused-after-restart");
  await btn(hal, "繼續牌局").click();
  await expect(hal.page.getByText("伺服器重啟後牌局已凍結", { exact: false })).toBeHidden();
  const actor = await whoseTurn(players);
  await act(actor, "fold");
  await waitResult(hal);
});

test("restart between hands: auto-deal continues by itself", async ({ browser }) => {
  test.setTimeout(120_000);
  const { players, room } = await table(browser, ["Hal", "Ivy"]);
  const [hal] = players;
  await startHand(hal, room);
  await act(await whoseTurn(players), "fold");
  await waitResult(hal);
  execSync(RESTART!, { stdio: "ignore" });
  await expect(hal.page.getByText(/^#2 · 翻牌前$/)).toBeVisible({ timeout: 40_000 });
  expect((await view(hal, room)).operational_status).toBe("ACTIVE");
  await whoseTurn(players); // someone can act in the new hand
});

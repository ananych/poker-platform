import type { MsgKey, TFn } from "./i18n";
import type { HandView, LegalActions } from "./types";

export const SUIT_SYMBOL: Record<string, string> = { s: "♠", h: "♥", d: "♦", c: "♣" };
export const RANK_LABEL: Record<string, string> = { T: "10" };

export function parseCard(card: string) {
  const rank = card[0];
  const suit = card[1];
  return { rank: RANK_LABEL[rank] ?? rank, suit, symbol: SUIT_SYMBOL[suit] ?? "?",
           red: suit === "h" || suit === "d" };
}

/** Chip formatting with grouping; integers only. */
export function chips(n: number | null | undefined): string {
  if (n === null || n === undefined) return "-";
  return Math.trunc(n).toLocaleString("en-US");
}

/**
 * A-09: ½-pot / pot presets rounded to a legal integer street total and clamped
 * to the server-provided [min_raise_to, max_raise_to]. The server always validates.
 */
export function presetRaiseTo(hand: HandView, la: LegalActions, myStreet: number,
                              fraction: number): number {
  const toCall = Math.max(0, hand.current_bet - myStreet);
  const potAfterCall = hand.pot + toCall;
  const raw = hand.current_bet + Math.floor(potAfterCall * fraction);
  return clamp(raw, la.min_raise_to, la.max_raise_to);
}

export function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, Math.round(v)));
}

/** Angle-based seat placement around an ellipse; `mySeat` is drawn at bottom center. */
export function seatPosition(seat: number, mySeat: number | null) {
  const anchor = mySeat ?? 1;
  const idx = (seat - anchor + 9) % 9;
  const angle = Math.PI / 2 + (idx * 2 * Math.PI) / 9;
  return { left: 50 + 44 * Math.cos(angle), top: 50 + 41 * Math.sin(angle) };
}

export function phaseKey(phase: string): MsgKey {
  return `phase.${phase}` as MsgKey;
}

const RANKS = new Set(["Royal Flush", "Straight Flush", "Four Of A Kind", "Full House", "Flush",
  "Straight", "Three Of A Kind", "Two Pair", "One Pair", "High Card"]);
export function rankText(t: TFn, rank: string | undefined | null): string {
  if (!rank) return "";
  return RANKS.has(rank) ? t(`rank.${rank}` as MsgKey) : rank;
}

/** Client-side mirror of the server's room-config rules (server still validates). */
export function configError(c: { sb: number; bb: number; min_buyin: number; max_buyin: number }):
  MsgKey | null {
  const vals = [c.sb, c.bb, c.min_buyin, c.max_buyin];
  if (vals.some((v) => !Number.isInteger(v) || v <= 0)) return "cfg.err_int";
  if (c.sb >= c.bb) return "cfg.err_blinds";
  if (c.min_buyin > c.max_buyin) return "cfg.err_range";
  if (c.min_buyin < c.bb) return "cfg.err_min_bb";
  return null;
}

/** Signed chip delta, e.g. +1,200 / −300 / 0. */
export function signed(n: number): string {
  if (n > 0) return `+${chips(n)}`;
  if (n < 0) return `−${chips(-n)}`;
  return "0";
}

const AVATAR_COLORS = ["#e11d48", "#d97706", "#65a30d", "#0891b2", "#4f46e5", "#c026d3",
  "#ea580c", "#059669", "#2563eb", "#9333ea"];
export function avatarColor(seed: string): string {
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}
export function initial(name: string | null | undefined): string {
  const s = (name ?? "?").trim();
  return s ? [...s][0].toUpperCase() : "?";
}

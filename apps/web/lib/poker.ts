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

export const PHASE_LABEL: Record<string, string> = {
  PREFLOP: "翻牌前", FLOP: "翻牌", TURN: "轉牌", RIVER: "河牌", SHOWDOWN: "攤牌",
  SETTLEMENT: "結算", HAND_COMPLETE: "結束",
};

export const RANK_NAME_ZH: Record<string, string> = {
  "Royal Flush": "皇家同花順", "Straight Flush": "同花順", "Four Of A Kind": "四條",
  "Full House": "葫蘆", "Flush": "同花", "Straight": "順子", "Three Of A Kind": "三條",
  "Two Pair": "兩對", "One Pair": "一對", "High Card": "高牌",
};

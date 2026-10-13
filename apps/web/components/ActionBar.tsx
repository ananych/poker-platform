"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Card } from "./Card";
import { errorCodeText } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { chips, clamp, presetRaiseTo } from "@/lib/poker";
import type { ActionResult, HandView, LegalActions, PokerAction, RoomView } from "@/lib/types";

/** Queued choice made while waiting; executed the moment it becomes our turn. */
type PreAction =
  | { kind: "check_fold" }
  | { kind: "check" }
  | { kind: "call"; amount: number }
  | { kind: "call_any" }
  | { kind: "raise"; frac: 0.5 | 0.75 | 1 | "allin" };

const sameKind = (a: PreAction | null, b: PreAction) =>
  !!a && a.kind === b.kind && (a.kind !== "raise" || (b.kind === "raise" && a.frac === b.frac));

function resolvePre(pre: PreAction, hand: HandView, la: LegalActions, myStreet: number):
  { action: PokerAction; raiseTo?: number } | null {
  switch (pre.kind) {
    case "check_fold": return { action: la.can_check ? "CHECK" : "FOLD" };
    case "check": return la.can_check ? { action: "CHECK" } : null;
    case "call":
      if (la.can_check && pre.amount === 0) return { action: "CHECK" };
      return la.call_amount === pre.amount ? { action: "CALL" } : null;
    case "call_any": return { action: la.can_check ? "CHECK" : "CALL" };
    case "raise": {
      if (la.can_bet || la.can_raise) {
        const v = pre.frac === "allin" ? la.max_raise_to : presetRaiseTo(hand, la, myStreet, pre.frac);
        if (v >= la.max_raise_to) return { action: "ALL_IN" };
        return { action: la.can_bet ? "BET" : "RAISE", raiseTo: v };
      }
      return { action: la.can_check ? "CHECK" : "CALL" };
    }
  }
}

/**
 * Sticky action row (SDD §11). Legal actions & min/max come only from the
 * server-side projection; the client never decides eligibility.
 */
export function ActionBar({ view, act, hideCards, compact = false, side = false, tools }: {
  view: RoomView;
  act: (a: PokerAction, raiseTo?: number) => Promise<ActionResult>;
  hideCards: boolean;
  /** short screens: smaller cards and controls */
  compact?: boolean;
  /** rendered in a side column (landscape phones) instead of stuck to the bottom */
  side?: boolean;
  /** my-seat tools (⋯ menu / I'm back), shown at the right of the top row */
  tools?: React.ReactNode;
}) {
  const { t } = useT();
  const hand = view.hand as HandView | null;
  const la = hand?.legal_actions;
  const me = hand?.seats.find((s) => s.seat_no === hand.your_seat);
  const myStreet = me?.street_contribution ?? 0;
  const [amount, setAmount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [preState, setPreState] = useState<{ p: PreAction; street: string } | null>(null);
  const street = hand ? `${hand.hand_id}:${hand.phase}` : "";
  // a queued choice only applies to the street it was made on
  const pre = preState && preState.street === street ? preState.p : null;
  const setPre = (p: PreAction | null) => setPreState(p ? { p, street } : null);
  const firedFor = useRef<string | null>(null);

  const canSize = !!la && (la.can_bet || la.can_raise);
  useEffect(() => {
    if (la && canSize) setAmount(la.min_raise_to);
    setErr(null);
  }, [la?.min_raise_to, la?.max_raise_to, hand?.hand_id, view.room_version]); // eslint-disable-line react-hooks/exhaustive-deps

  const toCall = hand && me ? Math.max(0, hand.current_bet - myStreet) : 0;
  const maxCall = me ? Math.min(toCall, me.stack) : 0;
  // invalidate when the price changes under a fixed-amount choice
  useEffect(() => {
    if (!pre) return;
    if ((pre.kind === "check" && toCall > 0) || (pre.kind === "call" && pre.amount !== maxCall)) {
      setPreState(null);
    }
  }, [pre, toCall, maxCall]);

  async function run(a: PokerAction, raiseTo?: number) {
    setBusy(true);
    setErr(null);
    const r = await act(a, raiseTo);
    setBusy(false);
    if (!r.accepted) setErr(errorCodeText(r.error?.code, r.error?.message));
  }

  // fire the queued pre-action exactly once when our turn arrives
  useEffect(() => {
    if (!la || !hand || !pre) return;
    const key = `${hand.hand_id}:${view.room_version}`;
    if (firedFor.current === key) return;
    firedFor.current = key;
    const choice = resolvePre(pre, hand, la, myStreet);
    setPreState(null);
    if (choice) void run(choice.action, choice.raiseTo);
  }, [la, hand, pre, view.room_version, myStreet]); // eslint-disable-line react-hooks/exhaustive-deps

  const presets = useMemo(() => {
    if (!hand || !la || !canSize) return [];
    return [
      { label: t("act.half_pot"), v: presetRaiseTo(hand, la, myStreet, 0.5) },
      { label: t("act.3q_pot"), v: presetRaiseTo(hand, la, myStreet, 0.75) },
      { label: t("act.pot"), v: presetRaiseTo(hand, la, myStreet, 1) },
      { label: t("act.all_in"), v: la.max_raise_to },
    ];
  }, [hand, la, canSize, myStreet, t]);

  const myCards = hand?.your_cards ?? [];
  const btnH = compact ? "h-11" : "h-12";
  const sizeVerb = la?.can_bet ? t("act.bet") : t("act.raise_to");
  const actorName = hand?.actor_seat
    ? view.seats.find((s) => s.seat_no === hand.actor_seat)?.nickname ?? `#${hand.actor_seat}` : null;
  const canPre = !la && !!hand && !!me && !me.folded && !me.all_in && me.stack > 0
    && ["PREFLOP", "FLOP", "TURN", "RIVER"].includes(hand.phase);

  const preBtn = (p: PreAction, label: string) => {
    const on = sameKind(pre, p);
    return (
      <button key={label} type="button" aria-pressed={on} aria-label={t("pre.aria", { a: label })}
              onClick={() => setPre(on ? null : p)}
              className={`flex ${compact ? "h-10" : "h-11"} min-w-0 flex-1 items-center justify-center gap-1.5 rounded-lg px-1 text-xs font-medium ring-1 transition ${
                on ? "bg-chip text-black ring-chip" : "bg-neutral-900 text-neutral-300 ring-neutral-700"}`}>
        {/* drawn checkbox (glyphs render inconsistently as emoji on some phones) */}
        <span aria-hidden className={`flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-[3px] border text-[10px] leading-none ${
          on ? "border-black bg-black text-chip" : "border-neutral-500"}`}>
          {on && <svg viewBox="0 0 12 12" className="h-2.5 w-2.5"><path d="M2 6.5 5 9l5-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>}
        </span>
        <span className="truncate">{label}</span>
      </button>
    );
  };

  return (
    <div data-testid="action-bar" className={side
      ? "border-t border-white/10 bg-neutral-950 px-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] pt-2"
      : `sticky bottom-0 z-20 border-t border-white/10 bg-neutral-950/95 px-3 backdrop-blur ${compact
        ? "pb-[max(0.5rem,env(safe-area-inset-bottom))] pt-1.5" : "pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2"}`}>
      <div className={`mx-auto flex max-w-3xl flex-col ${compact ? "gap-1.5" : "gap-2"}`}>
        <div className={`flex items-center ${compact ? "gap-2" : "gap-3"}`}>
          {myCards.length > 0 && (
            <div className={`flex gap-1 transition ${hideCards ? "blur-md" : ""}`} aria-label={t("table.your_cards")}>
              {myCards.map((c) => <Card key={c} card={c} size={compact ? "md" : "lg"} />)}
            </div>
          )}
          <div className="min-w-0 flex-1 text-xs text-neutral-400">
            {la ? <span className="your-turn text-sm font-semibold text-chip">{t("act.your_turn")}</span>
              : actorName ? <span className="line-clamp-2 break-all">{t("act.waiting_for", { name: actorName })}</span> : null}
            {err && <div role="alert" className="text-red-400">{err}</div>}
          </div>
          {tools}
        </div>

        {canPre && hand && (
          <div className="flex flex-col gap-1.5" aria-label={t("pre.title")}>
            <div className="flex gap-1.5">
              {preBtn({ kind: "check_fold" }, t("pre.check_fold"))}
              {toCall === 0
                ? preBtn({ kind: "check" }, t("pre.check"))
                : preBtn({ kind: "call", amount: maxCall }, t("pre.call", { n: chips(maxCall) }))}
              {preBtn({ kind: "call_any" }, t("pre.call_any"))}
            </div>
            <div className="flex items-center gap-1.5">
              <span className="shrink-0 text-[11px] text-neutral-500">{t("pre.raise")}</span>
              {preBtn({ kind: "raise", frac: 0.5 }, t("act.half_pot"))}
              {preBtn({ kind: "raise", frac: 0.75 }, t("act.3q_pot"))}
              {preBtn({ kind: "raise", frac: 1 }, t("act.pot"))}
              {preBtn({ kind: "raise", frac: "allin" }, t("act.all_in"))}
            </div>
          </div>
        )}

        {la && (
          <>
            {canSize && (
              <div className="flex flex-col gap-2">
                <div className="flex gap-1.5">
                  {presets.map((p) => (
                    <button key={p.label} type="button" onClick={() => setAmount(p.v)}
                            className={`${compact ? "h-10" : "h-11"} flex-1 rounded-lg bg-neutral-800 text-xs font-medium active:bg-neutral-700`}>
                      {p.label}
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <input type="range" min={la.min_raise_to} max={la.max_raise_to} step={1}
                         value={amount} onChange={(e) => setAmount(Number(e.target.value))}
                         className={`${compact ? "h-10" : "h-11"} min-w-0 flex-1 accent-amber-400`} aria-label={t("act.amount")} />
                  <input type="number" inputMode="numeric" min={la.min_raise_to} max={la.max_raise_to}
                         value={amount}
                         onChange={(e) => setAmount(Number(e.target.value))}
                         onBlur={() => setAmount((v) => clamp(v || 0, la.min_raise_to, la.max_raise_to))}
                         className={`${compact ? "h-10" : "h-11"} w-24 rounded-lg bg-neutral-900 px-2 text-right tabular-nums ring-1 ring-neutral-700`}
                         aria-label={t("common.amount")} />
                </div>
              </div>
            )}
            <div className="grid grid-cols-3 gap-2">
              <button disabled={busy} onClick={() => run("FOLD")}
                      className={`${btnH} rounded-xl bg-neutral-700 font-semibold disabled:opacity-50`}>{t("act.fold")}</button>
              {la.can_check ? (
                <button disabled={busy} onClick={() => run("CHECK")}
                        className={`${btnH} rounded-xl bg-sky-700 font-semibold disabled:opacity-50`}>{t("act.check")}</button>
              ) : (
                <button disabled={busy || la.call_amount <= 0} onClick={() => run("CALL")}
                        className={`${btnH} rounded-xl bg-sky-700 font-semibold disabled:opacity-50`}>
                  {t("act.call", { n: chips(la.call_amount) })}
                </button>
              )}
              {canSize ? (
                <button disabled={busy} onClick={() => {
                          const v = clamp(amount, la.min_raise_to, la.max_raise_to);
                          if (v === la.max_raise_to) run("ALL_IN");
                          else run(la.can_bet ? "BET" : "RAISE", v);
                        }}
                        className={`${btnH} rounded-xl bg-amber-500 font-semibold text-black disabled:opacity-50`}>
                  {amount >= la.max_raise_to ? t("act.all_in") : `${sizeVerb} ${chips(amount)}`}
                </button>
              ) : (
                <button disabled className={`${btnH} rounded-xl bg-neutral-800 text-sm text-neutral-500`}>
                  {t("act.no_raise")}
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

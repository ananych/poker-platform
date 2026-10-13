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
export function ActionBar({ view, act, hideCards }: {
  view: RoomView;
  act: (a: PokerAction, raiseTo?: number) => Promise<ActionResult>;
  hideCards: boolean;
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
  const sizeVerb = la?.can_bet ? t("act.bet") : t("act.raise_to");
  const actorName = hand?.actor_seat
    ? view.seats.find((s) => s.seat_no === hand.actor_seat)?.nickname ?? `#${hand.actor_seat}` : null;
  const canPre = !la && !!hand && !!me && !me.folded && !me.all_in && me.stack > 0
    && ["PREFLOP", "FLOP", "TURN", "RIVER"].includes(hand.phase);

  const preBtn = (p: PreAction, label: string) => {
    const on = sameKind(pre, p);
    return (
      <button key={label} type="button" aria-pressed={on}
              onClick={() => setPre(on ? null : p)}
              className={`h-11 flex-1 rounded-lg px-1 text-xs font-medium ring-1 transition ${
                on ? "bg-chip text-black ring-chip" : "bg-neutral-900 text-neutral-300 ring-neutral-700"}`}>
        <span className="mr-1">{on ? "☑" : "☐"}</span>{label}
      </button>
    );
  };

  return (
    <div className="sticky bottom-0 z-20 border-t border-white/10 bg-neutral-950/95 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2 backdrop-blur">
      <div className="mx-auto flex max-w-3xl flex-col gap-2">
        <div className="flex items-center gap-3">
          {myCards.length > 0 && (
            <div className={`flex gap-1 transition ${hideCards ? "blur-md" : ""}`} aria-label={t("table.your_cards")}>
              {myCards.map((c) => <Card key={c} card={c} size="lg" />)}
            </div>
          )}
          <div className="min-w-0 flex-1 text-xs text-neutral-400">
            {la ? <span className="your-turn text-sm font-semibold text-chip">{t("act.your_turn")}</span>
              : actorName ? t("act.waiting_for", { name: actorName }) : null}
            {err && <div role="alert" className="text-red-400">{err}</div>}
          </div>
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
                            className="h-11 flex-1 rounded-lg bg-neutral-800 text-xs font-medium active:bg-neutral-700">
                      {p.label}
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <input type="range" min={la.min_raise_to} max={la.max_raise_to} step={1}
                         value={amount} onChange={(e) => setAmount(Number(e.target.value))}
                         className="h-11 flex-1 accent-amber-400" aria-label={t("act.amount")} />
                  <input type="number" inputMode="numeric" min={la.min_raise_to} max={la.max_raise_to}
                         value={amount}
                         onChange={(e) => setAmount(Number(e.target.value))}
                         onBlur={() => setAmount((v) => clamp(v || 0, la.min_raise_to, la.max_raise_to))}
                         className="h-11 w-24 rounded-lg bg-neutral-900 px-2 text-right tabular-nums ring-1 ring-neutral-700"
                         aria-label={t("common.amount")} />
                </div>
              </div>
            )}
            <div className="grid grid-cols-3 gap-2">
              <button disabled={busy} onClick={() => run("FOLD")}
                      className="h-12 rounded-xl bg-neutral-700 font-semibold disabled:opacity-50">{t("act.fold")}</button>
              {la.can_check ? (
                <button disabled={busy} onClick={() => run("CHECK")}
                        className="h-12 rounded-xl bg-sky-700 font-semibold disabled:opacity-50">{t("act.check")}</button>
              ) : (
                <button disabled={busy || la.call_amount <= 0} onClick={() => run("CALL")}
                        className="h-12 rounded-xl bg-sky-700 font-semibold disabled:opacity-50">
                  {t("act.call", { n: chips(la.call_amount) })}
                </button>
              )}
              {canSize ? (
                <button disabled={busy} onClick={() => {
                          const v = clamp(amount, la.min_raise_to, la.max_raise_to);
                          if (v === la.max_raise_to) run("ALL_IN");
                          else run(la.can_bet ? "BET" : "RAISE", v);
                        }}
                        className="h-12 rounded-xl bg-amber-500 font-semibold text-black disabled:opacity-50">
                  {amount >= la.max_raise_to ? t("act.all_in") : `${sizeVerb} ${chips(amount)}`}
                </button>
              ) : (
                <button disabled className="h-12 rounded-xl bg-neutral-800 text-sm text-neutral-500">
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

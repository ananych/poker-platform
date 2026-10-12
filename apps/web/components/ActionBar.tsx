"use client";

import { useEffect, useMemo, useState } from "react";
import { Card } from "./Card";
import { chips, clamp, presetRaiseTo } from "@/lib/poker";
import type { ActionResult, HandView, PokerAction, RoomView } from "@/lib/types";
import { ERROR_TEXT } from "@/lib/api";

/**
 * Sticky action row (SDD §11). Legal actions & min/max come only from the
 * server-side projection; the client never decides eligibility.
 */
export function ActionBar({ view, act, hideCards }: {
  view: RoomView;
  act: (a: PokerAction, raiseTo?: number) => Promise<ActionResult>;
  hideCards: boolean;
}) {
  const hand = view.hand as HandView | null;
  const la = hand?.legal_actions;
  const me = hand?.seats.find((s) => s.seat_no === hand.your_seat);
  const myStreet = me?.street_contribution ?? 0;
  const [amount, setAmount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const canSize = !!la && (la.can_bet || la.can_raise);
  useEffect(() => {
    if (la && canSize) setAmount(la.min_raise_to);
    setErr(null);
  }, [la?.min_raise_to, la?.max_raise_to, hand?.hand_id, view.room_version]); // eslint-disable-line react-hooks/exhaustive-deps

  const presets = useMemo(() => {
    if (!hand || !la || !canSize) return [];
    return [
      { label: "½ 池", v: presetRaiseTo(hand, la, myStreet, 0.5) },
      { label: "¾ 池", v: presetRaiseTo(hand, la, myStreet, 0.75) },
      { label: "1 池", v: presetRaiseTo(hand, la, myStreet, 1) },
      { label: "全下", v: la.max_raise_to },
    ];
  }, [hand, la, canSize, myStreet]);

  async function run(a: PokerAction, raiseTo?: number) {
    setBusy(true);
    setErr(null);
    const r = await act(a, raiseTo);
    setBusy(false);
    if (!r.accepted) setErr(ERROR_TEXT[r.error?.code ?? ""] ?? r.error?.message ?? "動作失敗");
  }

  const myCards = hand?.your_cards ?? [];
  const sizeVerb = la?.can_bet ? "下注" : "加注到";

  return (
    <div className="sticky bottom-0 z-20 border-t border-white/10 bg-neutral-950/95 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2 backdrop-blur">
      <div className="mx-auto flex max-w-3xl flex-col gap-2">
        <div className="flex items-center gap-3">
          {myCards.length > 0 && (
            <div className={`flex gap-1 transition ${hideCards ? "blur-md" : ""}`} aria-label="你的手牌">
              {myCards.map((c) => <Card key={c} card={c} size="lg" />)}
            </div>
          )}
          <div className="min-w-0 flex-1 text-xs text-neutral-400">
            {la ? <span className="font-medium text-chip">輪到你了</span>
              : hand ? (hand.actor_seat ? `等待 #${hand.actor_seat} 行動` : "")
              : null}
            {err && <div role="alert" className="text-red-400">{err}</div>}
          </div>
        </div>

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
                         className="h-11 flex-1 accent-amber-400" aria-label="下注金額" />
                  <input type="number" inputMode="numeric" min={la.min_raise_to} max={la.max_raise_to}
                         value={amount}
                         onChange={(e) => setAmount(Number(e.target.value))}
                         onBlur={() => setAmount((v) => clamp(v || 0, la.min_raise_to, la.max_raise_to))}
                         className="h-11 w-24 rounded-lg bg-neutral-900 px-2 text-right tabular-nums ring-1 ring-neutral-700"
                         aria-label="金額" />
                </div>
              </div>
            )}
            <div className="grid grid-cols-3 gap-2">
              <button disabled={busy} onClick={() => run("FOLD")}
                      className="h-12 rounded-xl bg-neutral-700 font-semibold disabled:opacity-50">棄牌</button>
              {la.can_check ? (
                <button disabled={busy} onClick={() => run("CHECK")}
                        className="h-12 rounded-xl bg-sky-700 font-semibold disabled:opacity-50">過牌</button>
              ) : (
                <button disabled={busy || la.call_amount <= 0} onClick={() => run("CALL")}
                        className="h-12 rounded-xl bg-sky-700 font-semibold disabled:opacity-50">
                  跟注 {chips(la.call_amount)}
                </button>
              )}
              {canSize ? (
                <button disabled={busy} onClick={() => {
                          const v = clamp(amount, la.min_raise_to, la.max_raise_to);
                          if (v === la.max_raise_to) run("ALL_IN");
                          else run(la.can_bet ? "BET" : "RAISE", v);
                        }}
                        className="h-12 rounded-xl bg-amber-500 font-semibold text-black disabled:opacity-50">
                  {amount >= la.max_raise_to ? "全下" : `${sizeVerb} ${chips(amount)}`}
                </button>
              ) : (
                <button disabled className="h-12 rounded-xl bg-neutral-800 text-sm text-neutral-500">
                  不可加注
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

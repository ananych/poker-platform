"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Card, CardBack, EmptyCard } from "@/components/Card";
import { btnGhost } from "@/components/Modal";
import { api, errorText } from "@/lib/api";
import { chips, PHASE_LABEL, RANK_NAME_ZH } from "@/lib/poker";
import type { Replay, ReplayEvent } from "@/lib/types";

interface RSeat { seat_no: number; stack: number; street: number; folded: boolean; all_in: boolean;
                  cards?: string[]; won?: number; rank?: string }
interface RState { phase: string; board: string[]; pot: number; seats: Map<number, RSeat>;
                   last?: string; button: number; sb?: number; bb?: number }

/** Rebuild the publicly observable table at step `upto` from logged events only (SDD §10). */
function reduceTo(rep: Replay, upto: number): RState {
  const s: RState = { phase: "PREFLOP", board: [], pot: 0, seats: new Map(), button: rep.button_seat };
  const nick = new Map(rep.players.map((p) => [p.seat_no, p.nickname ?? `#${p.seat_no}`]));
  const put = (seat: number, amt: number) => {
    const p = s.seats.get(seat)!;
    p.stack -= amt; p.street += amt; s.pot += amt;
    if (p.stack === 0) p.all_in = true;
  };
  for (const e of rep.events.slice(0, upto + 1) as ReplayEvent[]) {
    const pl = e.payload as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    switch (e.type) {
      case "hand.started":
        for (const x of pl.seats) s.seats.set(x.seat_no, { seat_no: x.seat_no, stack: x.stack, street: 0, folded: false, all_in: false });
        s.sb = pl.sb_seat; s.bb = pl.bb_seat; s.last = "開始發牌";
        break;
      case "blind.posted":
        put(pl.seat_no, pl.amount); s.last = `${nick.get(pl.seat_no)} 下 ${pl.blind} ${chips(pl.amount)}`;
        break;
      case "hand.street_changed":
        s.phase = pl.phase; s.board = pl.board;
        for (const p of s.seats.values()) p.street = 0;
        s.last = PHASE_LABEL[pl.phase] ?? pl.phase;
        break;
      case "action.result": {
        const p = s.seats.get(pl.seat_no)!;
        const who = nick.get(pl.seat_no);
        if (pl.action === "FOLD") { p.folded = true; s.last = `${who} 棄牌${pl.timeout ? "（逾時）" : ""}${pl.forced ? "（離桌）" : ""}`; }
        else if (pl.action === "CHECK") s.last = `${who} 過牌${pl.timeout ? "（逾時）" : ""}`;
        else if (pl.action === "CALL") { put(pl.seat_no, pl.amount); s.last = `${who} 跟注 ${chips(pl.amount)}`; }
        else { put(pl.seat_no, pl.raise_to - p.street); s.last = `${who} ${pl.action === "BET" ? "下注" : "加注到"} ${chips(pl.raise_to)}${pl.all_in ? "（全下）" : ""}`; }
        break;
      }
      case "chips.uncalled_refund": {
        const p = s.seats.get(pl.seat_no)!;
        p.stack += pl.amount; s.pot -= pl.amount; s.last = `退回 ${nick.get(pl.seat_no)} 未被跟注的 ${chips(pl.amount)}`;
        break;
      }
      case "hand.showdown":
        s.phase = "SHOWDOWN";
        for (const x of pl.shown) { const p = s.seats.get(x.seat_no)!; p.cards = x.hole_cards; p.rank = x.rank; }
        s.last = "攤牌";
        break;
      case "hand.completed":
        s.phase = "HAND_COMPLETE";
        for (const [k, v] of Object.entries(pl.payouts as Record<string, number>)) {
          const p = s.seats.get(Number(k))!; p.won = (p.won ?? 0) + v;
        }
        for (const [k, v] of Object.entries(pl.stacks as Record<string, number>)) s.seats.get(Number(k))!.stack = v;
        s.pot = 0; s.board = pl.board;
        s.last = "結算完成";
        break;
    }
  }
  return s;
}

export default function ReplayPage() {
  const { roomId, handId } = useParams<{ roomId: string; handId: string }>();
  const [rep, setRep] = useState<Replay | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    api.replay(roomId, handId).then((r) => { setRep(r); setStep(0); }).catch((e) => setErr(errorText(e)));
  }, [roomId, handId]);
  const total = rep?.events.length ?? 0;
  useEffect(() => {
    if (!playing) return;
    if (step >= total - 1) { setPlaying(false); return; }
    const t = setTimeout(() => setStep((s) => s + 1), 900);
    return () => clearTimeout(t);
  }, [playing, step, total]);

  const st = useMemo(() => (rep ? reduceTo(rep, step) : null), [rep, step]);
  if (err) return <main className="p-6 text-sm text-red-400">{err}</main>;
  if (!rep || !st) return <main className="p-6 text-neutral-400">載入中…</main>;
  const nick = new Map(rep.players.map((p) => [p.seat_no, p.nickname]));

  return (
    <main className="mx-auto flex min-h-dvh max-w-2xl flex-col gap-4 px-4 py-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
      <header className="flex items-center gap-2">
        <Link href={`/rooms/${roomId}`} className="flex h-11 items-center text-neutral-400">‹ 回牌桌</Link>
        <h1 className="flex-1 text-center font-semibold">回放 #{rep.ordinal} · {rep.config.sb}/{rep.config.bb}</h1>
      </header>

      <section className="flex flex-col items-center gap-2 rounded-2xl bg-felt p-4">
        <div className="text-xs text-white/70">{PHASE_LABEL[st.phase] ?? st.phase} · 底池 {chips(st.pot)}</div>
        <div className="flex gap-1">
          {[0, 1, 2, 3, 4].map((i) => st.board[i] ? <Card key={st.board[i]} card={st.board[i]} /> : <EmptyCard key={i} />)}
        </div>
        <div className="min-h-5 text-sm text-chip">{st.last}</div>
      </section>

      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {[...st.seats.values()].map((p) => {
          const mine = p.seat_no === rep.my_seat;
          const cards = p.cards ?? (mine ? rep.my_cards ?? undefined : undefined);
          return (
            <li key={p.seat_no} className={`flex items-center gap-3 rounded-xl bg-neutral-900 p-2 ${p.folded ? "opacity-50" : ""}`}>
              <div className="flex gap-0.5">
                {cards ? cards.map((c) => <Card key={c} card={c} size="sm" />) : <><CardBack /><CardBack /></>}
              </div>
              <div className="min-w-0 flex-1 text-sm">
                <div className="truncate">
                  {nick.get(p.seat_no) ?? "?"} <span className="text-xs text-neutral-500">#{p.seat_no}</span>
                  {p.seat_no === st.button && <span className="ml-1 rounded bg-white px-1 text-[10px] text-black">D</span>}
                  {mine && <span className="ml-1 text-xs text-chip">（你）</span>}
                </div>
                <div className="text-xs tabular-nums text-neutral-400">
                  籌碼 {chips(p.stack)}{p.street > 0 && ` · 本輪 ${chips(p.street)}`}
                  {p.rank && ` · ${RANK_NAME_ZH[p.rank] ?? p.rank}`}
                </div>
              </div>
              {p.won ? <span className="text-sm text-emerald-400">+{chips(p.won)}</span> : null}
            </li>
          );
        })}
      </ul>

      <div className="sticky bottom-0 flex items-center gap-2 bg-neutral-950/90 py-2">
        <button className={btnGhost} onClick={() => { setPlaying(false); setStep(0); }} aria-label="第一步">⏮</button>
        <button className={btnGhost} disabled={step === 0} onClick={() => { setPlaying(false); setStep((s) => s - 1); }}>上一步</button>
        <button className="h-11 flex-1 rounded-lg bg-chip font-medium text-black" onClick={() => {
          if (step >= total - 1) setStep(0);
          setPlaying((p) => !p);
        }}>{playing ? "暫停" : "播放"}</button>
        <button className={btnGhost} disabled={step >= total - 1} onClick={() => { setPlaying(false); setStep((s) => s + 1); }}>下一步</button>
        <span className="w-14 text-right text-xs tabular-nums text-neutral-500">{step + 1}/{total}</span>
      </div>
      <p className="text-center text-[11px] text-neutral-500">
        回放只顯示當時公開的資訊；攤牌時所有人亮牌，棄牌者的手牌不會顯示。
      </p>
    </main>
  );
}

"use client";

import { Card, EmptyCard } from "./Card";
import { Seat } from "./Seat";
import { chips, PHASE_LABEL, RANK_NAME_ZH, seatPosition } from "@/lib/poker";
import type { RoomView } from "@/lib/types";

export function PokerTable({ view, remaining, onSit }: {
  view: RoomView;
  remaining: number | null;
  onSit: (seat: number) => void;
}) {
  const hand = view.hand;
  const mySeat = view.me?.seat_no ?? null;
  const seatsBy = new Map(view.seats.map((s) => [s.seat_no, s]));
  const handSeats = new Map((hand?.seats ?? []).map((s) => [s.seat_no, s]));
  const last = !hand ? view.last_hand : null;
  const shownBy = new Map((last?.showdown?.shown ?? []).map((s) => [s.seat_no, s]));
  const board = hand?.community_cards ?? last?.completed?.board ?? [];
  const winningCards = new Set((last?.showdown?.shown ?? [])
    .filter((s) => last?.completed?.pots.some((p) => p.winners.includes(s.seat_no)))
    .flatMap((s) => s.best_five));
  const hostSeat = view.seats.find((s) => s.member_id === view.host_member_id)?.seat_no;
  const canSit = view.me !== null && mySeat === null && view.status !== "CLOSED";

  return (
    <div className="relative mx-auto aspect-[3/4] w-full max-w-[min(100%,calc((100dvh-12rem)*0.75))] sm:aspect-[16/10] sm:max-w-[min(100%,calc((100dvh-10rem)*1.6))]">
      {/* felt */}
      <div className="absolute inset-[9%] rounded-[45%] border-[10px] border-rail bg-[radial-gradient(ellipse_at_center,var(--color-felt)_0%,var(--color-felt-dark)_75%)] shadow-[inset_0_0_40px_rgba(0,0,0,.6)]" />

      {/* center: board + pot */}
      <div className="absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-2">
        <div className="text-[11px] uppercase tracking-wider text-white/60">
          {hand ? `#${hand.ordinal} · ${PHASE_LABEL[hand.phase] ?? hand.phase}`
            : view.operational_status === "PAUSED_RECOVERY" ? "暫停中" : "等待房主開始"}
        </div>
        <div className="flex gap-1">
          {[0, 1, 2, 3, 4].map((i) => board[i]
            ? <Card key={board[i]} card={board[i]} size="md" highlight={winningCards.has(board[i])} />
            : <EmptyCard key={i} size="md" />)}
        </div>
        {hand && (
          <div className="rounded-full bg-black/50 px-3 py-0.5 text-sm tabular-nums">
            底池 <span className="font-semibold text-chip">{chips(hand.pot)}</span>
          </div>
        )}
        {last?.completed && (
          <div className="max-w-[16rem] rounded-lg bg-black/60 px-3 py-1 text-center text-xs">
            {last.completed.pots.map((p) => (
              <div key={p.index}>
                {p.index === 0 ? "主池" : `邊池 ${p.index}`} {chips(p.amount)} →{" "}
                {p.winners.map((w) => seatsBy.get(w)?.nickname ?? `#${w}`).join("、")}
                {(() => {
                  const r = p.winners.map((w) => shownBy.get(w)?.rank).find(Boolean);
                  return r ? `（${RANK_NAME_ZH[r] ?? r}）` : "";
                })()}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* street bets */}
      {hand?.seats.filter((s) => s.street_contribution > 0).map((s) => {
        const pos = seatPosition(s.seat_no, mySeat);
        const bx = 50 + (pos.left - 50) * 0.55;
        const by = 50 + (pos.top - 50) * 0.55;
        return (
          <div key={`bet-${s.seat_no}`} className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full bg-black/60 px-2 py-0.5 text-xs tabular-nums text-chip"
               style={{ left: `${bx}%`, top: `${by}%` }}>
            ● {chips(s.street_contribution)}
          </div>
        );
      })}

      {/* seats */}
      {Array.from({ length: 9 }, (_, i) => i + 1).map((n) => {
        const pos = seatPosition(n, mySeat);
        const seat = seatsBy.get(n);
        const hs = handSeats.get(n);
        return (
          <div key={n} className="absolute -translate-x-1/2 -translate-y-1/2"
               style={{ left: `${pos.left}%`, top: `${pos.top}%` }}>
            <Seat seatNo={n} seat={seat} handSeat={hs} isMe={n === mySeat}
                  isActor={!!hand && hand.actor_seat === n}
                  isButton={!!hand && hand.button_seat === n}
                  blind={hand ? (hand.sb_seat === n ? "SB" : hand.bb_seat === n ? "BB" : undefined) : undefined}
                  isHost={n === hostSeat}
                  shownCards={n !== mySeat ? shownBy.get(n)?.hole_cards : undefined}
                  won={last?.completed?.payouts[String(n)]}
                  remaining={remaining} canSit={canSit} onSit={() => onSit(n)} />
          </div>
        );
      })}
    </div>
  );
}

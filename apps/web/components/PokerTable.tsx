"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Card, EmptyCard } from "./Card";
import { Seat } from "./Seat";
import { useT } from "@/lib/i18n";
import { tableLayout } from "@/lib/layout";
import { chips, phaseKey, rankText } from "@/lib/poker";
import type { RoomView } from "@/lib/types";

/** Seconds until `iso` (server clock), ticking; null when no target. */
function useSecondsUntil(iso: string | null | undefined, clockOffset: number) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!iso) return;
    setNow(Date.now()); // don't show a stale value for the first tick
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [iso]);
  if (!iso) return null;
  return Math.max(0, Math.ceil((new Date(iso).getTime() - (now + clockOffset)) / 1000));
}

export function PokerTable({ view, remaining, clockOffset, bubbles, onSit }: {
  view: RoomView;
  remaining: number | null;
  clockOffset: number;
  bubbles: Record<string, string>;
  onSit: (seat: number) => void;
}) {
  const { t } = useT();
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const hand = view.hand;
  const mySeat = view.me?.seat_no ?? null;
  const seatsBy = new Map(view.seats.map((s) => [s.seat_no, s]));
  const handSeats = new Map((hand?.seats ?? []).map((s) => [s.seat_no, s]));
  const last = !hand ? view.last_hand : null;
  const shownBy = new Map((last?.showdown?.shown ?? []).map((s) => [s.seat_no, s]));
  const board = hand?.community_cards ?? last?.completed?.board ?? [];
  const winnerSeats = new Set((last?.completed?.pots ?? []).flatMap((p) => p.winners));
  const winningCards = new Set((last?.showdown?.shown ?? [])
    .filter((s) => winnerSeats.has(s.seat_no))
    .flatMap((s) => s.best_five));
  const hostSeat = view.seats.find((s) => s.member_id === view.host_member_id)?.seat_no;
  const canSit = view.me !== null && mySeat === null && view.status !== "CLOSED";
  const nextIn = useSecondsUntil(!hand ? view.next_hand_at : null, clockOffset);
  const seatedEligible = view.seats.filter((s) => s.stack > 0 && !s.pending_leave &&
    s.participation_state !== "SITTING_OUT" && !s.sit_out_next).length;

  // name for a seat in the finished hand (the player may have left since)
  const nameOf = (seat: number) => {
    const live = seatsBy.get(seat);
    const mid = last?.seat_members?.[String(seat)];
    if (live && (!mid || live.member_id === mid)) return live.nickname ?? `#${seat}`;
    return view.members.find((m) => m.member_id === mid)?.nickname ?? `#${seat}`;
  };

  let status: string;
  if (hand) status = `#${hand.ordinal} · ${t(phaseKey(hand.phase))}`;
  else if (view.operational_status === "PAUSED_RECOVERY") status = t("table.paused");
  else if (nextIn !== null && seatedEligible >= 2) status = t("table.next_in", { s: nextIn });
  else if (seatedEligible < 2) status = t("table.waiting_players");
  else if (!view.auto_deal) status = t("table.deal_paused");
  else status = t("table.waiting_host");

  const geo = size && size.w > 0 && size.h > 0 ? tableLayout(size.w, size.h, mySeat) : null;

  return (
    // fills the table area; geometry is computed from its real size (lib/layout.ts)
    <div ref={ref} data-testid="table" className="absolute inset-x-1 inset-y-2">
      {geo && (<>
        {/* felt */}
        <div className="absolute rounded-[50%] border-[8px] border-rail bg-[radial-gradient(ellipse_at_center,var(--color-felt)_0%,var(--color-felt-dark)_75%)] shadow-[inset_0_0_40px_rgba(0,0,0,.6)] sm:border-[10px]"
             style={{ left: geo.felt.cx - geo.felt.rx, top: geo.felt.cy - geo.felt.ry,
                      width: geo.felt.rx * 2, height: geo.felt.ry * 2 }} />

        {/* center: board + pot + result */}
        <div className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-1.5"
             style={{ left: geo.felt.cx, top: geo.felt.cy, maxWidth: geo.felt.rx * 1.8 }}>
          <div className="whitespace-nowrap text-xs tracking-wide text-white/70">
            <span data-testid="status" aria-live="polite">{status}</span>
            {/* small tables: the pot rides on the status line to keep the middle short */}
            {hand && geo.compact && (
              <span data-testid="pot" className="ml-1.5 rounded-full bg-black/50 px-2 py-0.5 tabular-nums text-white">
                {t("table.pot")} <span className="font-semibold text-chip">{chips(hand.pot)}</span>
              </span>
            )}
          </div>
          <div data-testid="board" className="flex gap-1">
            {[0, 1, 2, 3, 4].map((i) => board[i]
              ? <Card key={board[i]} card={board[i]} size={geo.boardCard} highlight={winningCards.has(board[i])} />
              : <EmptyCard key={i} size={geo.boardCard} />)}
          </div>
          {hand && !geo.compact && (
            <div data-testid="pot" className="rounded-full bg-black/50 px-3 py-0.5 text-sm tabular-nums">
              {t("table.pot")} <span className="font-semibold text-chip">{chips(hand.pot)}</span>
            </div>
          )}
          {last?.completed && (
            <div className="win-pop max-w-full rounded-xl border border-chip/60 bg-black/75 px-3 py-1.5 text-center shadow-xl" role="status">
              {last.completed.pots.map((p) => {
                const r = p.winners.map((w) => shownBy.get(w)?.rank).find(Boolean);
                const names = p.winners.map(nameOf);
                return (
                  <div key={p.index} className={geo.compact ? "text-xs" : "text-sm"}>
                    {last.completed!.pots.length > 1 && (
                      <span className="mr-1 text-[10px] text-white/60">
                        {p.index === 0 ? t("table.main_pot") : t("table.side_pot", { n: p.index })}
                      </span>
                    )}
                    <span className="font-semibold text-chip">
                      🏆{" "}
                      {names.map((nm, i) => (
                        <span key={i}>
                          {i > 0 && " / "}
                          <span className={`inline-block truncate align-bottom ${geo.compact ? "max-w-[6.5rem]" : "max-w-[10rem]"}`}>{nm}</span>
                        </span>
                      ))}{" "}
                      {t("table.wins_amt", { amt: chips(p.amount) })}
                    </span>
                    {p.winners.length > 1 && <span className="text-xs text-white/70"> · {t("table.split")}</span>}
                    {r && <span className="text-xs text-white/80">（{rankText(t, r)}）</span>}
                  </div>
                );
              })}
              {last.completed.uncontested && (
                <div className="text-[10px] text-white/60">{t("table.uncontested")}</div>
              )}
            </div>
          )}
        </div>

        {/* street bets, between each seat and the middle */}
        {hand?.seats.filter((s) => s.street_contribution > 0).map((s) => {
          const spot = geo.bets[s.seat_no];
          return (
            <div key={`bet-${s.seat_no}`} data-bet={s.seat_no} className="absolute z-20 -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded-full bg-black/70 px-2 py-0.5 text-xs tabular-nums text-chip"
                 style={{ left: spot.x, top: spot.y }}>
              ● {chips(s.street_contribution)}
            </div>
          );
        })}

        {/* seats */}
        {Array.from({ length: 9 }, (_, i) => i + 1).map((n) => {
          const spot = geo.seats[n];
          const seat = seatsBy.get(n);
          const hs = handSeats.get(n);
          const sameMember = !!seat && last?.seat_members?.[String(n)] === seat.member_id;
          const shown = sameMember ? shownBy.get(n) : undefined;
          // my own cards after the hand: always visible to me (even if I folded)
          const mine = n === mySeat && sameMember && last?.my_seat === n ? last?.my_cards : undefined;
          const delta = sameMember ? last?.deltas?.[String(n)] : undefined;
          return (
            <div key={n} className="absolute -translate-x-1/2 -translate-y-1/2"
                 style={{ left: spot.x, top: spot.y, zIndex: seat ? 10 : 1 }}>
              <Seat seatNo={n} seat={seat} handSeat={hs} isMe={n === mySeat}
                    compact={geo.compact} width={geo.seatW}
                    isActor={!!hand && hand.actor_seat === n}
                    isButton={!!hand && hand.button_seat === n}
                    blind={hand ? (hand.sb_seat === n ? "SB" : hand.bb_seat === n ? "BB" : undefined) : undefined}
                    isHost={n === hostSeat}
                    shownCards={shown?.hole_cards ?? mine ?? undefined}
                    winningCards={winningCards}
                    rank={shown ? rankText(t, shown.rank) : undefined}
                    delta={delta}
                    isWinner={sameMember && winnerSeats.has(n)}
                    bubble={seat ? bubbles[seat.member_id] : undefined}
                    bubbleAlign={spot.x < geo.w * 0.25 ? "left" : spot.x > geo.w * 0.75 ? "right" : "center"}
                    bubbleBelow={spot.y < geo.h * 0.3}
                    remaining={remaining} timeoutTotal={view.action_timeout ?? 30}
                    canSit={canSit} onSit={() => onSit(n)} />
            </div>
          );
        })}
      </>)}
    </div>
  );
}

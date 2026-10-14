import { Card, CardBack } from "./Card";
import { TimerBar } from "./Countdown";
import { useT } from "@/lib/i18n";
import { avatarColor, chips, initial, signed } from "@/lib/poker";
import type { HandSeat, SeatView } from "@/lib/types";

export interface SeatProps {
  seatNo: number;
  seat?: SeatView;
  handSeat?: HandSeat;
  isMe: boolean;
  /** small-screen variant: tighter text, cards tucked over the top edge */
  compact?: boolean;
  /** card width in px (from the table geometry) */
  width?: number;
  isActor: boolean;
  isButton: boolean;
  blind?: "SB" | "BB";
  isHost: boolean;
  /** cards to show face-up on this seat (showdown, or my own cards after the hand) */
  shownCards?: string[];
  /** cards that make up the winning five (highlighted) */
  winningCards?: Set<string>;
  rank?: string;
  /** net chips won/lost in the hand that just finished */
  delta?: number;
  isWinner?: boolean;
  bubble?: string | null;
  /** keep the chat bubble on-screen for seats at the table edge */
  bubbleAlign?: "left" | "center" | "right";
  /** top-row seats show the bubble under the seat instead of above it */
  bubbleBelow?: boolean;
  remaining: number | null;
  timeoutTotal?: number;
  canSit: boolean;
  onSit?: () => void;
}

export function Seat(p: SeatProps) {
  const { t } = useT();
  const c = !!p.compact;
  if (!p.seat) {
    return p.canSit ? (
      <button onClick={p.onSit} data-seat={p.seatNo}
              className={`flex flex-col items-center justify-center rounded-full border border-dashed border-white/30 text-xs text-white/70 hover:border-chip hover:text-chip ${
                c ? "h-11 w-14" : "h-14 w-20"}`}
              aria-label={t("table.sit_here", { n: p.seatNo })}>
        <span>{t("table.sit")}</span><span className="text-[10px] opacity-70">#{p.seatNo}</span>
      </button>
    ) : (
      <div data-seat={p.seatNo} className={`flex items-center justify-center rounded-full border border-white/10 text-[10px] text-white/30 ${c ? "h-8 w-8" : "h-10 w-10"}`}>
        {p.seatNo}
      </div>
    );
  }
  const h = p.handSeat;
  const folded = h?.folded ?? false;
  const stack = h ? h.stack : p.seat.stack;
  const state = p.seat.participation_state;
  const cards = p.shownCards ?? h?.shown_cards;
  const name = p.seat.nickname ?? "?";
  const away = state === "SITTING_OUT" || p.seat.sit_out_next;
  const delta = p.delta ?? 0;
  const showBacks = !cards && !p.isMe && !!h?.has_cards;

  const cardRow = cards ? cards.map((x) => <Card key={x} card={x} size={c ? "xs" : "sm"} highlight={p.winningCards?.has(x)} />)
    : showBacks ? (<><CardBack size={c ? "xs" : "sm"} /><CardBack size={c ? "xs" : "sm"} /></>) : null;

  return (
    <div data-seat={p.seatNo} data-me={p.isMe || undefined}
         style={{ width: p.width }}
         className={`relative flex flex-col items-center ${c ? "" : "gap-1"} ${p.width ? "" : "w-24 sm:w-32"} ${folded ? "opacity-50" : ""}`}>
      {/* chat bubble */}
      {p.bubble && (
        <div className={`seat-bubble seat-bubble-${p.bubbleAlign ?? "center"} ${p.bubbleBelow ? "seat-bubble-below top-full mt-2" : "-top-9"} absolute z-30 max-w-[10rem] truncate rounded-xl bg-white px-2 py-1 text-xs text-black shadow-lg ${
          p.bubbleAlign === "left" ? "left-0" : p.bubbleAlign === "right" ? "right-0" : "left-1/2 -translate-x-1/2"}`}>
          {p.bubble}
        </div>
      )}
      {/* cards: in compact mode they overlap the top edge so the seat stays short */}
      {cardRow && (c ? (
        <div className="absolute -top-6 left-1/2 z-10 flex -translate-x-1/2 gap-0.5">{cardRow}</div>
      ) : (
        <div className="flex h-10 gap-0.5">{cardRow}</div>
      ))}
      {!cardRow && !c && <div className="h-10" aria-hidden />}
      <div className={`relative w-full rounded-xl border text-center shadow-lg transition ${c ? "px-1 pt-1" : "px-2 pt-1"} ${
        delta ? (c ? "pb-3" : "pb-3.5") : "pb-1"} ${
        p.isWinner ? "winner-glow border-chip bg-amber-950/90"
          : p.isActor ? "border-chip bg-neutral-800 ring-2 ring-chip/60"
          : p.isMe ? "border-sky-500 bg-neutral-900/90"
          : "border-white/10 bg-neutral-900/90"}`}>
        <div className={`flex items-center justify-center ${c ? "gap-1" : "gap-1.5"}`}>
          {/* avatar */}
          <span className={`relative flex shrink-0 items-center justify-center rounded-full font-bold text-white ${
            c ? "h-5 w-5 text-[10px]" : "h-6 w-6 text-[11px] sm:h-7 sm:w-7"}`}
                style={{ background: avatarColor(p.seat.member_id) }} aria-hidden>
            {initial(name)}
            {p.isWinner && <span className="absolute -top-3 text-sm" aria-hidden>👑</span>}
            {!p.seat.connected && <span className="absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full bg-neutral-500 ring-1 ring-black" title={t("table.offline")} />}
          </span>
          <span className={`min-w-0 truncate font-medium ${c ? "text-[11px]" : "text-xs sm:text-sm"}`}>
            {p.isHost && <span title={t("table.host")} className="text-chip">♛</span>}
            {name}
          </span>

        </div>
        <div className={`font-semibold tabular-nums text-chip ${c ? "text-xs leading-4" : "text-sm"}`}>{chips(stack)}</div>
        <div className={`tabular-nums leading-tight ${c ? "text-[9px]" : "text-[10px]"} ${
          p.seat.net > 0 ? "text-emerald-400" : p.seat.net < 0 ? "text-red-400" : "text-neutral-500"}`}
             title={t("table.net")}>
          {t("table.net")} {signed(p.seat.net)}
        </div>
        <div className={`flex flex-wrap justify-center gap-1 leading-tight ${c ? "text-[9px]" : "text-[10px]"}`}>
          {h?.all_in && <span className="rounded bg-red-600 px-1">ALL-IN</span>}
          {folded && <span className="rounded bg-neutral-700 px-1">{t("table.fold")}</span>}
          {!h && away && <span className="rounded bg-neutral-700 px-1">{t("table.away")}</span>}
          {!h && state === "WAITING_FOR_BLIND" && !away && <span className="rounded bg-sky-800 px-1">{t("table.next_hand_join")}</span>}
          {p.seat.pending_leave && <span className="rounded bg-neutral-700 px-1">{t("table.leaving")}</span>}
          {p.rank && <span className="rounded bg-black/50 px-1 text-neutral-200">{p.rank}</span>}
        </div>
        {delta !== 0 && (
          <div className={`win-pop absolute -bottom-3 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full px-2 py-0.5 font-bold shadow-lg ${
            c ? "text-[11px]" : "text-xs"} ${delta > 0 ? "bg-emerald-500 text-black" : "bg-red-600/90 text-white"}`}>
            {p.isWinner && "🏆 "}{signed(delta)}
          </div>
        )}
        {p.isActor && <div className="mt-1"><TimerBar remaining={p.remaining} total={p.timeoutTotal} /></div>}
        {p.isButton && (
          <span className="absolute -right-2 -top-2 flex h-5 w-5 items-center justify-center rounded-full bg-white text-[10px] font-bold text-black" title="Dealer">D</span>
        )}
        {p.blind && (
          <span className="absolute -left-2 -top-2 rounded-full bg-sky-600 px-1 text-[9px] font-bold">{p.blind}</span>
        )}
        {/* "you" tag on the top edge, so the name line keeps its room */}
        {p.isMe && !cardRow && (
          <span className="absolute -top-2 left-1/2 -translate-x-1/2 rounded bg-sky-600 px-1 text-[9px] font-semibold leading-[14px] text-white">{t("table.me")}</span>
        )}
      </div>
    </div>
  );
}

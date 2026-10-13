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
  isActor: boolean;
  isButton: boolean;
  blind?: "SB" | "BB";
  isHost: boolean;
  /** cards to show face-up on this seat (showdown, or my own cards after the hand) */
  shownCards?: string[];
  /** cards that make up the winning five (highlighted) */
  winningCards?: Set<string>;
  rank?: string;
  won?: number;
  isWinner?: boolean;
  bubble?: string | null;
  /** keep the chat bubble on-screen for seats at the table edge */
  bubbleAlign?: "left" | "center" | "right";
  remaining: number | null;
  canSit: boolean;
  onSit?: () => void;
}

export function Seat(p: SeatProps) {
  const { t } = useT();
  if (!p.seat) {
    return p.canSit ? (
      <button onClick={p.onSit}
              className="flex h-12 w-16 flex-col items-center justify-center rounded-full border border-dashed border-white/30 text-xs text-white/70 hover:border-chip hover:text-chip sm:h-14 sm:w-20"
              aria-label={t("table.sit_here", { n: p.seatNo })}>
        <span>{t("table.sit")}</span><span className="text-[10px] opacity-70">#{p.seatNo}</span>
      </button>
    ) : (
      <div className="flex h-10 w-10 items-center justify-center rounded-full border border-white/10 text-[10px] text-white/30">
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

  return (
    <div className={`relative flex w-24 flex-col items-center gap-1 sm:w-32 ${folded ? "opacity-50" : ""}`}>
      {/* chat bubble */}
      {p.bubble && (
        <div className={`seat-bubble seat-bubble-${p.bubbleAlign ?? "center"} absolute -top-9 z-30 max-w-[10rem] truncate rounded-xl bg-white px-2 py-1 text-xs text-black shadow-lg ${
          p.bubbleAlign === "left" ? "left-0" : p.bubbleAlign === "right" ? "right-0" : "left-1/2 -translate-x-1/2"}`}>
          {p.bubble}
        </div>
      )}
      {/* cards: opponents' backs / anyone's shown cards; my live cards live in the action bar */}
      {(!p.isMe || cards) && (
        <div className="flex h-10 gap-0.5">
          {cards ? cards.map((c) => <Card key={c} card={c} size="sm" highlight={p.winningCards?.has(c)} />)
            : h?.has_cards ? (<><CardBack /><CardBack /></>) : null}
        </div>
      )}
      <div className={`relative w-full rounded-xl border px-2 pt-1 text-center shadow-lg transition ${p.isWinner && p.won ? "pb-3.5" : "pb-1"} ${
        p.isWinner ? "winner-glow border-chip bg-amber-950/90"
          : p.isActor ? "border-chip bg-neutral-800 ring-2 ring-chip/60"
          : "border-white/10 bg-neutral-900/90"}`}>
        <div className="flex items-center justify-center gap-1.5">
          {/* avatar */}
          <span className="relative flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white sm:h-7 sm:w-7"
                style={{ background: avatarColor(p.seat.member_id) }} aria-hidden>
            {initial(name)}
            {p.isWinner && <span className="absolute -top-3 text-sm" aria-hidden>👑</span>}
            {!p.seat.connected && <span className="absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full bg-neutral-500 ring-1 ring-black" title={t("table.offline")} />}
          </span>
          <span className="min-w-0 truncate text-xs font-medium sm:text-sm">
            {p.isHost && <span title={t("table.host")} className="text-chip">♛</span>}
            {name}{p.isMe ? t("common.you") : ""}
          </span>
        </div>
        <div className="text-sm font-semibold tabular-nums text-chip">{chips(stack)}</div>
        <div className={`text-[10px] tabular-nums leading-tight ${
          p.seat.net > 0 ? "text-emerald-400" : p.seat.net < 0 ? "text-red-400" : "text-neutral-500"}`}
             title={t("table.net")}>
          {t("table.net")} {signed(p.seat.net)}
        </div>
        <div className="flex flex-wrap justify-center gap-1 text-[10px] leading-tight">
          {h?.all_in && <span className="rounded bg-red-600 px-1">ALL-IN</span>}
          {folded && <span className="rounded bg-neutral-700 px-1">{t("table.fold")}</span>}
          {!h && away && <span className="rounded bg-neutral-700 px-1">{t("table.away")}</span>}
          {!h && state === "WAITING_FOR_BLIND" && !away && <span className="rounded bg-sky-800 px-1">{t("table.next_hand_join")}</span>}
          {p.seat.pending_leave && <span className="rounded bg-neutral-700 px-1">{t("table.leaving")}</span>}
          {p.rank && <span className="rounded bg-black/50 px-1 text-neutral-200">{p.rank}</span>}
        </div>
        {p.isWinner && p.won ? (
          <div className="win-pop absolute -bottom-3 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-emerald-500 px-2 py-0.5 text-xs font-bold text-black shadow-lg">
            🏆 +{chips(p.won)}
          </div>
        ) : null}
        {p.isActor && <div className="mt-1"><TimerBar remaining={p.remaining} /></div>}
        {p.isButton && (
          <span className="absolute -right-2 -top-2 flex h-5 w-5 items-center justify-center rounded-full bg-white text-[10px] font-bold text-black" title="Dealer">D</span>
        )}
        {p.blind && (
          <span className="absolute -left-2 -top-2 rounded-full bg-sky-600 px-1 text-[9px] font-bold">{p.blind}</span>
        )}
      </div>
    </div>
  );
}

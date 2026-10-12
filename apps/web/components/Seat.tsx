import { Card, CardBack } from "./Card";
import { TimerBar } from "./Countdown";
import { chips } from "@/lib/poker";
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
  shownCards?: string[];
  won?: number;
  remaining: number | null;
  canSit: boolean;
  onSit?: () => void;
}

export function Seat(p: SeatProps) {
  if (!p.seat) {
    return p.canSit ? (
      <button onClick={p.onSit}
              className="flex h-12 w-16 flex-col items-center justify-center rounded-full border border-dashed border-white/30 text-xs text-white/70 hover:border-chip hover:text-chip sm:h-14 sm:w-20"
              aria-label={`坐到 ${p.seatNo} 號位`}>
        <span>坐下</span><span className="text-[10px] opacity-70">#{p.seatNo}</span>
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

  return (
    <div className={`flex w-[5.5rem] flex-col items-center gap-1 sm:w-28 ${folded ? "opacity-50" : ""}`}>
      {/* cards (opponents only; my own cards are shown in the action area) */}
      {!p.isMe && (
        <div className="flex h-10 gap-0.5">
          {cards ? cards.map((c) => <Card key={c} card={c} size="sm" />)
            : h?.has_cards ? (<><CardBack /><CardBack /></>) : null}
        </div>
      )}
      <div className={`relative w-full rounded-xl border px-2 py-1 text-center shadow-lg ${
        p.isActor ? "border-chip bg-neutral-800 ring-2 ring-chip/60" : "border-white/10 bg-neutral-900/90"}`}>
        <div className="flex items-center justify-center gap-1 truncate text-xs font-medium sm:text-sm">
          {!p.seat.connected && <span title="離線" className="text-neutral-500">⦸</span>}
          {p.isHost && <span title="房主" className="text-chip">♛</span>}
          <span className="truncate">{p.seat.nickname ?? "?"}{p.isMe ? "（你）" : ""}</span>
        </div>
        <div className="text-sm font-semibold tabular-nums text-chip">{chips(stack)}</div>
        <div className="flex flex-wrap justify-center gap-1 text-[10px] leading-tight">
          {h?.all_in && <span className="rounded bg-red-600 px-1">ALL-IN</span>}
          {folded && <span className="rounded bg-neutral-700 px-1">棄牌</span>}
          {!h && state === "SITTING_OUT" && <span className="rounded bg-neutral-700 px-1">暫離</span>}
          {!h && state === "WAITING_FOR_BLIND" && <span className="rounded bg-sky-800 px-1">下一手加入</span>}
          {p.seat.pending_leave && <span className="rounded bg-neutral-700 px-1">離桌中</span>}
          {p.won ? <span className="rounded bg-emerald-600 px-1">+{chips(p.won)}</span> : null}
        </div>
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

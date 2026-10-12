"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Card } from "./Card";
import { api, errorText } from "@/lib/api";
import { chips } from "@/lib/poker";
import type { HandSummary } from "@/lib/types";

export function HistoryPanel({ roomId, refreshKey }: { roomId: string; refreshKey: unknown }) {
  const [items, setItems] = useState<HandSummary[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(async (c?: number | null) => {
    try {
      const r = await api.hands(roomId, c);
      setItems((prev) => (c ? [...prev, ...r.items] : r.items));
      setCursor(r.next_cursor);
    } catch (e) { setErr(errorText(e)); }
  }, [roomId]);
  useEffect(() => { load(); }, [load, refreshKey]);

  return (
    <div className="h-full space-y-2 overflow-y-auto p-3 text-sm">
      {err && <p className="text-red-400">{err}</p>}
      {items.length === 0 && !err && <p className="text-xs text-neutral-500">還沒有完成的牌局</p>}
      {items.map((h) => {
        const winners = h.players.filter((p) => p.won > 0);
        return (
          <Link key={h.hand_id} href={`/rooms/${roomId}/hands/${h.hand_id}`}
                className="block rounded-lg bg-neutral-900 p-2 hover:bg-neutral-800">
            <div className="flex items-center justify-between text-xs text-neutral-400">
              <span>#{h.ordinal} · {h.blinds[0]}/{h.blinds[1]}</span>
              {h.my_seat !== null && (
                <span className={h.my_result ? "text-emerald-400" : ""}>
                  {h.my_result ? `+${chips(h.my_result)}` : "參與"}
                </span>
              )}
            </div>
            <div className="mt-1 flex gap-0.5">
              {h.board.map((c) => <Card key={c} card={c} size="sm" />)}
            </div>
            <div className="mt-1 text-xs">
              贏家：{winners.map((w) => `${w.nickname ?? "#" + w.seat_no} +${chips(w.won)}`).join("、")}
              {h.uncontested ? "（無人跟）" : ""}
            </div>
          </Link>
        );
      })}
      {cursor && <button onClick={() => load(cursor)} className="h-11 w-full rounded-lg bg-neutral-800 text-xs">載入更多</button>}
    </div>
  );
}

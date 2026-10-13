"use client";

import { useT } from "@/lib/i18n";
import { avatarColor, chips, initial, signed } from "@/lib/poker";
import type { Standing } from "@/lib/types";

/** Running profit/loss per player (virtual chips). */
export function StandingsList({ rows, myMemberId, compact = false }: {
  rows: Standing[]; myMemberId?: string; compact?: boolean;
}) {
  const { t } = useT();
  if (rows.length === 0) return <p className="text-xs text-neutral-500">{t("stand.empty")}</p>;
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.net)));
  return (
    <ol className="space-y-1.5">
      {rows.map((r, i) => {
        const pct = (Math.abs(r.net) / max) * 50;
        return (
          <li key={r.member_id}
              className={`relative overflow-hidden rounded-lg px-2 py-1.5 ${r.member_id === myMemberId ? "bg-neutral-800 ring-1 ring-chip/50" : "bg-neutral-900"}`}>
            {/* centered bar: right = up, left = down */}
            <span aria-hidden className={`absolute inset-y-0 ${r.net >= 0 ? "left-1/2 bg-emerald-500/15" : "right-1/2 bg-red-500/15"}`}
                  style={{ width: `${pct}%` }} />
            <div className="relative flex items-center gap-2 text-sm">
              <span className="w-4 text-right text-xs tabular-nums text-neutral-500">{i + 1}</span>
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white"
                    style={{ background: avatarColor(r.member_id) }} aria-hidden>{initial(r.nickname)}</span>
              <span className="min-w-0 flex-1 truncate">
                {r.nickname ?? "?"}
                {!r.seated && <span className="ml-1 text-[10px] text-neutral-500">{t("stand.left")}</span>}
              </span>
              {!compact && (
                <span className="text-[11px] tabular-nums text-neutral-500">
                  {chips(r.stack + r.cashed_out)}/{chips(r.invested)}
                </span>
              )}
              <span className={`w-20 text-right font-semibold tabular-nums ${
                r.net > 0 ? "text-emerald-400" : r.net < 0 ? "text-red-400" : "text-neutral-400"}`}>
                {signed(r.net)}
              </span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function StandingsPanel({ rows, myMemberId }: { rows: Standing[]; myMemberId?: string }) {
  const { t } = useT();
  return (
    <div className="h-full space-y-3 overflow-y-auto p-3">
      <h3 className="text-xs font-medium text-neutral-400">{t("stand.title")}</h3>
      <StandingsList rows={rows} myMemberId={myMemberId} />
      <p className="text-[11px] leading-snug text-neutral-500">{t("ledger.note")}</p>
    </div>
  );
}

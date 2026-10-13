"use client";

import { useEffect, useState } from "react";
import { api, errorText } from "@/lib/api";
import { chips } from "@/lib/poker";
import type { LedgerSummary, MemberView } from "@/lib/types";
import { useT, type MsgKey } from "@/lib/i18n";

export function LedgerPanel({ roomId, members, refreshKey }:
  { roomId: string; members: MemberView[]; refreshKey: unknown }) {
  const { t } = useT();
  const [summary, setSummary] = useState<LedgerSummary[]>([]);
  const [entries, setEntries] = useState<{ id: string; member_id: string; type: string; amount: number }[]>([]);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.ledger(roomId).then((r) => { setSummary(r.summary); setEntries(r.entries); })
      .catch((e) => setErr(errorText(e)));
  }, [roomId, refreshKey]);
  const nick = new Map(members.map((m) => [m.member_id, m.nickname]));
  return (
    <div className="h-full space-y-3 overflow-y-auto p-3 text-sm">
      <p className="text-[11px] leading-snug text-neutral-500">
        {t("ledger.note")}
      </p>
      {err && <p className="text-red-400">{err}</p>}
      <table className="w-full text-xs tabular-nums">
        <thead className="text-neutral-400"><tr>
          <th className="text-left font-normal">{t("ledger.player")}</th><th className="text-right font-normal">{t("ledger.invested")}</th>
          <th className="text-right font-normal">{t("ledger.holding")}</th><th className="text-right font-normal">{t("ledger.net")}</th>
        </tr></thead>
        <tbody>
          {summary.map((s) => (
            <tr key={s.member_id} className="border-t border-white/5">
              <td className="py-1">{nick.get(s.member_id) ?? s.member_id.slice(0, 6)}</td>
              <td className="text-right">{chips(s.total_buyins + s.total_topups)}</td>
              <td className="text-right">{chips(s.current_stack + s.cash_out)}</td>
              <td className={`text-right ${s.net > 0 ? "text-emerald-400" : s.net < 0 ? "text-red-400" : ""}`}>
                {s.net > 0 ? "+" : ""}{chips(s.net)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <details className="text-xs">
        <summary className="cursor-pointer text-neutral-400">{t("ledger.all", { n: entries.length })}</summary>
        <ul className="mt-1 space-y-0.5">
          {entries.map((e) => (
            <li key={e.id} className="flex justify-between">
              <span>{nick.get(e.member_id) ?? "?"} · {t(`ledger.${e.type}` as MsgKey) ?? e.type}</span>
              <span className="tabular-nums">{chips(e.amount)}</span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

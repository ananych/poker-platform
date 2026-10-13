"use client";

import { useEffect, useState } from "react";
import { useT } from "@/lib/i18n";

/** Display-only countdown; the server alone decides timeouts (SDD §12). */
export function useRemaining(deadline: string | null | undefined, clockOffset: number) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!deadline) return;
    setNow(Date.now()); // don't show a stale value for the first tick
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [deadline]);
  if (!deadline) return null;
  const ms = new Date(deadline).getTime() - (now + clockOffset);
  return Math.max(0, ms / 1000);
}

export function TimerBar({ remaining, total = 30 }: { remaining: number | null; total?: number }) {
  const { t } = useT();
  if (remaining === null) return null;
  const pct = Math.max(0, Math.min(100, (remaining / total) * 100));
  const color = remaining <= 5 ? "bg-red-500" : remaining <= 10 ? "bg-amber-400" : "bg-emerald-400";
  return (
    <div className="h-1 w-full overflow-hidden rounded bg-black/40" role="timer"
         aria-label={t("table.remaining", { s: Math.ceil(remaining) })}>
      <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

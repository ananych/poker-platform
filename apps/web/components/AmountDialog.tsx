"use client";

import { useState } from "react";
import { Modal, btnPrimary, inputCls } from "./Modal";
import { chips } from "@/lib/poker";
import { useT } from "@/lib/i18n";

export function AmountDialog({ title, min, max, initial, confirm, onSubmit, onClose }: {
  title: string; min: number; max: number; initial: number; confirm: string;
  onSubmit: (amount: number) => Promise<string | null>; onClose: () => void;
}) {
  const { t } = useT();
  const [v, setV] = useState(String(initial));
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const n = Number(v);
  const valid = Number.isInteger(n) && n >= min && n <= max;
  return (
    <Modal title={title} onClose={onClose}>
      <form className="flex flex-col gap-3" onSubmit={async (e) => {
        e.preventDefault();
        if (!valid) return;
        setBusy(true);
        const r = await onSubmit(n);
        setBusy(false);
        if (r) setErr(r); else onClose();
      }}>
        <p className="text-xs text-neutral-400">{t("common.range", { min: chips(min), max: chips(max) })}</p>
        {max > min && (
          <input type="range" min={min} max={max} step={1} value={valid ? n : min}
                 onChange={(e) => setV(e.target.value)} className="h-11 accent-amber-400" />
        )}
        <input inputMode="numeric" value={v} onChange={(e) => setV(e.target.value.replace(/\D/g, ""))}
               className={inputCls} aria-label={t("common.amount")} />
        {err && <p role="alert" className="text-sm text-red-400">{err}</p>}
        <button disabled={!valid || busy} className={btnPrimary}>{confirm}</button>
      </form>
    </Modal>
  );
}

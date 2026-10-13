"use client";

import { useEffect, useRef, useState } from "react";
import { useT } from "@/lib/i18n";

/**
 * My-seat tools shown inside the action bar while I'm in a hand (keeps the
 * table tall on phones): a prominent "I'm back" when sitting out, and a ⋯ menu
 * with sit out / top up / leave seat.
 */
export function SeatMenu({ away, onSitOut, onBack, onTopup, onLeave, notes }: {
  away: boolean;
  onSitOut: () => void;
  onBack: () => void;
  onTopup: () => void;
  onLeave: () => void;
  notes?: string[];
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  const item = "flex h-11 w-full items-center rounded-lg px-3 text-left text-sm hover:bg-neutral-800";
  const pick = (fn: () => void) => () => { setOpen(false); fn(); };

  return (
    <div ref={ref} className="relative flex shrink-0 items-center gap-1.5">
      {away && (
        <button type="button" onClick={onBack}
                className="h-10 rounded-lg bg-emerald-600 px-3 text-sm font-semibold">{t("room.back_in")}</button>
      )}
      <button type="button" onClick={() => setOpen((o) => !o)} aria-label={t("room.seat_menu")} aria-expanded={open}
              className="relative flex h-10 w-10 items-center justify-center rounded-lg bg-neutral-800 text-lg leading-none">
        ⋯
        {!!notes?.length && <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-amber-400" />}
      </button>
      {open && (
        <div className="absolute bottom-12 right-0 z-40 w-52 space-y-0.5 rounded-xl border border-white/10 bg-neutral-900 p-1.5 shadow-2xl" role="menu">
          {!away && <button type="button" role="menuitem" className={item} onClick={pick(onSitOut)}>{t("room.sit_out")}</button>}
          <button type="button" role="menuitem" className={item} onClick={pick(onTopup)}>{t("room.topup")}</button>
          <button type="button" role="menuitem" className={item} onClick={pick(onLeave)}>{t("room.leave")}</button>
          {notes?.map((n) => <p key={n} className="px-3 py-1 text-xs text-neutral-400">{n}</p>)}
        </div>
      )}
    </div>
  );
}

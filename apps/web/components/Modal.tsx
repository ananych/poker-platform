"use client";

import { useEffect } from "react";

export function Modal({ title, onClose, children }:
  { title: string; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 sm:items-center"
         role="dialog" aria-modal="true" aria-label={title} onClick={onClose}>
      <div className="w-full max-w-sm rounded-t-2xl bg-neutral-900 p-4 pb-[max(1rem,env(safe-area-inset-bottom))] shadow-xl sm:rounded-2xl"
           onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold">{title}</h2>
          <button onClick={onClose} className="h-11 w-11 rounded-full text-xl text-neutral-400" aria-label="關閉">×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export const inputCls =
  "h-11 w-full rounded-lg bg-neutral-950 px-3 outline-none ring-1 ring-neutral-700 focus:ring-chip";
export const btnPrimary =
  "h-11 rounded-lg bg-chip px-4 font-medium text-black disabled:opacity-50";
export const btnGhost =
  "h-11 rounded-lg bg-neutral-800 px-3 text-sm disabled:opacity-50";

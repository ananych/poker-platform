"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useT } from "@/lib/i18n";
import { getPrefs, requestNotify, setPrefs, subscribePrefs, unlockAudio } from "@/lib/sound";
import { useVersions, versionLabel } from "@/lib/version";

const serverPrefs = { music: false, sfx: true, notify: false };

export function useSoundPrefs() {
  return useSyncExternalStore(subscribePrefs, getPrefs, () => serverPrefs);
}

function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label}
            onClick={() => onChange(!on)}
            className={`relative h-7 w-12 shrink-0 rounded-full transition ${on ? "bg-chip" : "bg-neutral-700"}`}>
      <span className={`absolute top-1 h-5 w-5 rounded-full bg-white transition-all ${on ? "left-6" : "left-1"}`} />
    </button>
  );
}

/** Header gear: language, music, sound effects, background notifications. */
export function SettingsMenu() {
  const { t, lang, setLang } = useT();
  const prefs = useSoundPrefs();
  const [open, setOpen] = useState(false);
  const [denied, setDenied] = useState(false);
  const versions = useVersions();
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

  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => { unlockAudio(); setOpen((o) => !o); }}
              className="flex h-11 w-11 items-center justify-center rounded-lg text-lg text-neutral-300"
              aria-label={t("set.title")} aria-expanded={open}>
        {prefs.music ? "♫" : "⚙"}
      </button>
      {open && (
        <div className="absolute right-0 top-12 z-50 w-64 space-y-3 rounded-xl border border-white/10 bg-neutral-900 p-3 text-sm shadow-2xl">
          <div className="flex items-center justify-between">
            <span>{t("set.language")}</span>
            <div className="flex overflow-hidden rounded-lg ring-1 ring-neutral-700">
              {(["zh", "en"] as const).map((l) => (
                <button key={l} type="button" onClick={() => setLang(l)}
                        className={`h-9 px-3 text-xs ${lang === l ? "bg-chip text-black" : "text-neutral-300"}`}>
                  {l === "zh" ? "中文" : "English"}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center justify-between">
            <span>♫ {t("set.music")}</span>
            <Toggle on={prefs.music} label={t("set.music")}
                    onChange={(v) => { unlockAudio(); setPrefs({ music: v }); }} />
          </div>
          <div className="flex items-center justify-between">
            <span>🔊 {t("set.sfx")}</span>
            <Toggle on={prefs.sfx} label={t("set.sfx")}
                    onChange={(v) => { unlockAudio(); setPrefs({ sfx: v }); }} />
          </div>
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span>🔔 {t("set.notify")}</span>
              <Toggle on={prefs.notify} label={t("set.notify")} onChange={async (v) => {
                if (!v) { setPrefs({ notify: false }); return; }
                const ok = await requestNotify();
                setDenied(!ok);
                setPrefs({ notify: ok });
              }} />
            </div>
            <p className="text-[11px] leading-snug text-neutral-500">
              {denied ? t("set.notify_denied") : t("set.notify_hint")}
            </p>
          </div>
          <div className="space-y-0.5 border-t border-white/10 pt-2 text-[11px] tabular-nums text-neutral-400" data-testid="versions">
            <div className="text-neutral-300">{t("ver.title")}</div>
            <div>{t("ver.web")} {versionLabel(versions.web)}</div>
            <div>{t("ver.api")} {versionLabel(versions.api)}</div>
            {versions.mismatch && <div className="text-amber-400">{t("ver.mismatch")}</div>}
          </div>
        </div>
      )}
    </div>
  );
}

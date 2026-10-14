"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { btnGhost, btnPrimary, inputCls } from "@/components/Modal";
import { inviteStorageKey } from "@/components/HostPanel";
import { api, errorText } from "@/lib/api";
import { configError } from "@/lib/poker";
import { useVersions, versionLabel } from "@/lib/version";
import { LangToggle, useT, type MsgKey } from "@/lib/i18n";
import type { Me } from "@/lib/types";

export default function Lobby() {
  const router = useRouter();
  const { t } = useT();
  const versions = useVersions();
  const [me, setMe] = useState<Me | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [nickname, setNickname] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({ name: "", password: "", sb: "5", bb: "10", min_buyin: "200", max_buyin: "2000" });

  const refresh = () => api.me().then(setMe).catch(() => setMe(null)).finally(() => setLoaded(true));
  useEffect(() => { refresh(); }, []);

  async function enter(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try { await api.createSession(nickname); await refresh(); setNickname(""); }
    catch (x) { setErr(errorText(x)); } finally { setBusy(false); }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    const cfg = { sb: Number(f.sb), bb: Number(f.bb), min_buyin: Number(f.min_buyin),
                  max_buyin: Number(f.max_buyin) };
    const bad = configError(cfg);
    if (bad) { setErr(t(bad)); return; }
    setBusy(true); setErr(null);
    try {
      const r = await api.createRoom({ name: f.name || undefined, password: f.password, ...cfg });
      try { localStorage.setItem(inviteStorageKey(r.room_id), r.invite_path); } catch {}
      router.push(`/rooms/${r.room_id}?created=1`);
    } catch (x) { setErr(errorText(x)); setBusy(false); }
  }

  const num = (k: keyof typeof f) => ({
    value: f[k], inputMode: "numeric" as const, className: inputCls, required: true,
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value.replace(/\D/g, "") }),
  });

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col gap-5 px-4 py-8">
      <header className="flex items-start gap-2">
        <div className="flex-1">
          <h1 className="text-2xl font-semibold">Private Hold&apos;em</h1>
          <p className="text-sm text-neutral-400">{t("app.tagline")}</p>
        </div>
        <LangToggle className="bg-neutral-800" />
      </header>

      {err && <p role="alert" className="rounded-lg bg-red-950 p-3 text-sm text-red-300">{err}</p>}

      <form onSubmit={enter} className="flex flex-col gap-3 rounded-xl bg-rail p-4">
        <label htmlFor="nick" className="text-sm text-neutral-300">
          {me ? <>{t("lobby.nick_current")}<b>{me.nickname}</b>{t("lobby.nick_display_only")}</> : t("lobby.nick_label")}
        </label>
        <div className="flex gap-2">
          <input id="nick" value={nickname} onChange={(e) => setNickname(e.target.value)}
                 maxLength={32} required className={inputCls} placeholder={me ? t("lobby.nick_change") : t("lobby.nick_placeholder")} />
          <button disabled={busy || !nickname.trim()} className={`${btnPrimary} shrink-0`}>
            {me ? t("lobby.update") : t("lobby.enter")}
          </button>
        </div>
      </form>

      {me && (
        <form onSubmit={create} className="flex flex-col gap-3 rounded-xl bg-rail p-4">
          <h2 className="font-medium">{t("lobby.create_title")}</h2>
          <input placeholder={t("lobby.room_name")} maxLength={64} className={inputCls}
                 value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          <input type="password" placeholder={t("lobby.room_password")} minLength={4} maxLength={128}
                 required className={inputCls} value={f.password} autoComplete="new-password"
                 onChange={(e) => setF({ ...f, password: e.target.value })} />
          <div className="grid grid-cols-2 gap-2 text-xs text-neutral-400">
            <label>{t("cfg.sb")}<input {...num("sb")} /></label>
            <label>{t("cfg.bb")}<input {...num("bb")} /></label>
            <label>{t("cfg.min_buyin")}<input {...num("min_buyin")} /></label>
            <label>{t("cfg.max_buyin")}<input {...num("max_buyin")} /></label>
          </div>
          <button disabled={busy} className={btnPrimary}>{t("lobby.create")}</button>
        </form>
      )}

      {me && me.rooms.length > 0 && (
        <section className="rounded-xl bg-rail p-4">
          <h2 className="mb-2 font-medium">{t("lobby.my_rooms")}</h2>
          <ul className="space-y-1">
            {me.rooms.map((r) => (
              <li key={r.room_id}>
                <Link href={`/rooms/${r.room_id}`} className={`${btnGhost} flex items-center justify-between`}>
                  <span className="truncate">{r.name ?? r.room_id.slice(0, 8)}{r.is_host && " ♛"}</span>
                  <span className="text-xs text-neutral-400">{r.banned ? t("lobby.banned") : t(`status.${r.status}` as MsgKey)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {loaded && !me && (
        <p className="text-xs text-neutral-500">{t("lobby.invite_hint")}</p>
      )}

      <footer className="mt-auto text-xs leading-relaxed text-neutral-500">
        {t("app.disclaimer")}
        <div className="mt-2 tabular-nums text-neutral-600" data-testid="versions">
          {t("ver.web")} {versionLabel(versions.web)} · {t("ver.api")} {versionLabel(versions.api)}
        </div>
      </footer>
    </main>
  );
}

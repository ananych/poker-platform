"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { btnPrimary, inputCls } from "@/components/Modal";
import { api, errorText } from "@/lib/api";
import { LangToggle, useT } from "@/lib/i18n";
import type { Me } from "@/lib/types";

function JoinForm() {
  const { roomId } = useParams<{ roomId: string }>();
  const invite = useSearchParams().get("invite") ?? "";
  const router = useRouter();
  const { t } = useT();
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [nickname, setNickname] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.me().then(setMe).catch(() => setMe(null)); }, []);
  useEffect(() => {
    if (me?.rooms.some((r) => r.room_id === roomId && !r.banned)) router.replace(`/rooms/${roomId}`);
  }, [me, roomId, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      if (!me) await api.createSession(nickname);
      await api.join(roomId, invite, password);
      router.push(`/rooms/${roomId}`);
    } catch (x) { setErr(errorText(x)); setBusy(false); }
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-4 px-4 py-8">
      <div className="flex items-center"><h1 className="flex-1 text-xl font-semibold">{t("join.title")}</h1><LangToggle className="bg-neutral-800" /></div>
      {!invite && <p className="text-sm text-red-400">{t("join.no_invite")}</p>}
      <form onSubmit={submit} className="flex flex-col gap-3 rounded-xl bg-rail p-4">
        {me === null && (
          <input value={nickname} onChange={(e) => setNickname(e.target.value)} required maxLength={32}
                 placeholder={t("join.nickname")} className={inputCls} aria-label={t("join.nickname_label")} />
        )}
        {me && <p className="text-sm text-neutral-300">{t("join.as", { name: me.nickname })}</p>}
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
               placeholder={t("join.password")} className={inputCls} aria-label={t("join.password")} autoComplete="off" />
        {err && <p role="alert" className="text-sm text-red-400">{err}</p>}
        <button disabled={busy || !invite || me === undefined} className={btnPrimary}>{t("join.submit")}</button>
      </form>
    </main>
  );
}

export default function JoinPage() {
  return <Suspense><JoinForm /></Suspense>;
}

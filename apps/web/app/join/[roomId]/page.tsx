"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { btnPrimary, inputCls } from "@/components/Modal";
import { api, errorText } from "@/lib/api";
import type { Me } from "@/lib/types";

function JoinForm() {
  const { roomId } = useParams<{ roomId: string }>();
  const invite = useSearchParams().get("invite") ?? "";
  const router = useRouter();
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
      <h1 className="text-xl font-semibold">加入私人房間</h1>
      {!invite && <p className="text-sm text-red-400">連結缺少邀請碼，請向房主索取完整連結。</p>}
      <form onSubmit={submit} className="flex flex-col gap-3 rounded-xl bg-rail p-4">
        {me === null && (
          <input value={nickname} onChange={(e) => setNickname(e.target.value)} required maxLength={32}
                 placeholder="你的暱稱" className={inputCls} aria-label="暱稱" />
        )}
        {me && <p className="text-sm text-neutral-300">以 <b>{me.nickname}</b> 加入</p>}
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
               placeholder="房間密碼" className={inputCls} aria-label="房間密碼" autoComplete="off" />
        {err && <p role="alert" className="text-sm text-red-400">{err}</p>}
        <button disabled={busy || !invite || me === undefined} className={btnPrimary}>加入</button>
      </form>
    </main>
  );
}

export default function JoinPage() {
  return <Suspense><JoinForm /></Suspense>;
}

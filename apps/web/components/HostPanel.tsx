"use client";

import { useState } from "react";
import { api, errorText } from "@/lib/api";
import { chips } from "@/lib/poker";
import type { RoomConfig, RoomView } from "@/lib/types";
import { btnGhost, btnPrimary, inputCls } from "./Modal";

export function inviteStorageKey(roomId: string) { return `invite:${roomId}`; }

export function readInvite(roomId: string): string | null {
  try { return localStorage.getItem(inviteStorageKey(roomId)); } catch { return null; }
}

export function InviteBox({ roomId, isHost }: { roomId: string; isHost: boolean }) {
  const [link, setLink] = useState<string | null>(() =>
    typeof window === "undefined" ? null : readInvite(roomId));
  const [copied, setCopied] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const full = link ? `${window.location.origin}${link}` : null;
  return (
    <div className="space-y-2 rounded-lg bg-neutral-900 p-3 text-xs">
      <div className="font-medium text-neutral-300">邀請連結</div>
      {full ? (
        <>
          <div className="break-all rounded bg-black/40 p-2 font-mono text-[11px]">{full}</div>
          <p className="text-neutral-500">對方還需要房間密碼才能加入。</p>
          <button className={btnGhost} onClick={async () => {
            try { await navigator.clipboard.writeText(full); setCopied(true); setTimeout(() => setCopied(false), 1500); }
            catch { setErr("無法複製，請手動選取"); }
          }}>{copied ? "已複製 ✓" : "複製連結"}</button>
        </>
      ) : <p className="text-neutral-500">此裝置沒有保存邀請連結。</p>}
      {isHost && (
        <button className={`${btnGhost} ml-2`} onClick={async () => {
          try {
            const r = await api.rotateInvite(roomId);
            localStorage.setItem(inviteStorageKey(roomId), r.invite_path);
            setLink(r.invite_path);
          } catch (e) { setErr(errorText(e)); }
        }}>產生新連結（舊的失效）</button>
      )}
      {err && <p className="text-red-400">{err}</p>}
    </div>
  );
}

export function HostPanel({ view }: { view: RoomView }) {
  const rid = view.room_id;
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const base = view.pending_config ?? view.config;
  const [cfg, setCfg] = useState<Record<keyof RoomConfig, string>>({
    sb: String(base.sb), bb: String(base.bb),
    min_buyin: String(base.min_buyin), max_buyin: String(base.max_buyin),
  });
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true); setErr(null);
    try { await fn(); } catch (e) { setErr(errorText(e)); } finally { setBusy(false); }
  };
  const eligible = view.seats.filter((s) => s.stack > 0 && !s.pending_leave &&
    s.participation_state !== "SITTING_OUT").length;

  return (
    <div className="h-full space-y-3 overflow-y-auto p-3 text-sm">
      {err && <p role="alert" className="text-red-400">{err}</p>}
      {view.operational_status === "PAUSED_RECOVERY" ? (
        <button disabled={busy} className={`${btnPrimary} w-full`}
                onClick={() => run(() => api.resume(rid))}>繼續牌局（Resume）</button>
      ) : !view.hand ? (
        <button disabled={busy || eligible < 2} className={`${btnPrimary} w-full`}
                onClick={() => run(() => api.startHand(rid, view.room_version))}>
          開始下一手 {eligible < 2 && "（需要 2 位可參與玩家）"}
        </button>
      ) : <p className="text-xs text-neutral-400">牌局進行中，結束後可開始下一手。</p>}

      {(view.pending_topups?.length ?? 0) > 0 && (
        <section className="space-y-1">
          <h3 className="text-xs font-medium text-neutral-400">補碼申請</h3>
          {view.pending_topups!.map((t) => (
            <div key={t.request_id} className="flex items-center gap-2 rounded-lg bg-neutral-900 p-2">
              <span className="flex-1">{t.nickname} 申請 <b className="text-chip">{chips(t.amount)}</b></span>
              <button className={btnGhost} disabled={busy}
                      onClick={() => run(() => api.decideTopup(rid, t.request_id, true))}>核准</button>
              <button className={btnGhost} disabled={busy}
                      onClick={() => run(() => api.decideTopup(rid, t.request_id, false))}>拒絕</button>
            </div>
          ))}
          <p className="text-[11px] text-neutral-500">核准後在兩手之間套用，不影響進行中的牌局。</p>
        </section>
      )}

      <section className="space-y-2">
        <h3 className="text-xs font-medium text-neutral-400">
          盲注與買入（{view.hand ? "下一手生效" : "立即生效"}）
        </h3>
        <div className="grid grid-cols-2 gap-2">
          {(["sb", "bb", "min_buyin", "max_buyin"] as const).map((k) => (
            <label key={k} className="text-[11px] text-neutral-400">
              {{ sb: "小盲", bb: "大盲", min_buyin: "最低買入", max_buyin: "最高買入" }[k]}
              <input inputMode="numeric" value={cfg[k]} className={inputCls}
                     onChange={(e) => setCfg({ ...cfg, [k]: e.target.value.replace(/\D/g, "") })} />
            </label>
          ))}
        </div>
        <button className={btnGhost} disabled={busy} onClick={() => run(() => api.config(rid, {
          sb: Number(cfg.sb), bb: Number(cfg.bb), min_buyin: Number(cfg.min_buyin),
          max_buyin: Number(cfg.max_buyin) }))}>儲存設定</button>
      </section>
      <InviteBox roomId={rid} isHost />
    </div>
  );
}

export function MembersPanel({ view }: { view: RoomView }) {
  const isHost = !!view.me?.is_host;
  const [err, setErr] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>, confirmText?: string) => {
    if (confirmText && !window.confirm(confirmText)) return;
    setErr(null);
    try { await fn(); } catch (e) { setErr(errorText(e)); }
  };
  const seatOf = new Map(view.seats.map((s) => [s.member_id, s.seat_no]));
  return (
    <div className="h-full space-y-1 overflow-y-auto p-3 text-sm">
      {err && <p role="alert" className="text-red-400">{err}</p>}
      {view.members.map((m) => (
        <div key={m.member_id} className="rounded-lg bg-neutral-900 p-2">
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${m.connected ? "bg-emerald-400" : "bg-neutral-600"}`} />
            <span className="flex-1 truncate">
              {m.nickname}{m.is_host && " ♛"}{m.member_id === view.me?.member_id && "（你）"}
              {seatOf.has(m.member_id) && <span className="ml-1 text-xs text-neutral-400">#{seatOf.get(m.member_id)}</span>}
              {m.banned && <span className="ml-1 text-xs text-red-400">已封鎖</span>}
            </span>
          </div>
          {isHost && m.member_id !== view.me?.member_id && (
            <div className="mt-2 flex flex-wrap gap-1">
              {m.banned ? (
                <button className={btnGhost} onClick={() => run(() => api.unban(view.room_id, m.member_id))}>解除封鎖</button>
              ) : (<>
                <button className={btnGhost} onClick={() => run(() => api.transferHost(view.room_id, m.member_id), `把房主交給 ${m.nickname}？`)}>轉讓房主</button>
                {seatOf.has(m.member_id) && (
                  <button className={btnGhost} onClick={() => run(() => api.kick(view.room_id, m.member_id), `請 ${m.nickname} 離桌？（籌碼會結帳，不會沒收）`)}>請離桌</button>
                )}
                <button className={`${btnGhost} text-red-300`} onClick={() => run(() => api.ban(view.room_id, m.member_id), `封鎖 ${m.nickname}？`)}>封鎖</button>
              </>)}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

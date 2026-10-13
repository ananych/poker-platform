"use client";

import { useState } from "react";
import { api, errorText } from "@/lib/api";
import { chips } from "@/lib/poker";
import { useT } from "@/lib/i18n";
import type { RoomConfig, RoomView } from "@/lib/types";
import { btnGhost, btnPrimary, inputCls } from "./Modal";

export function inviteStorageKey(roomId: string) { return `invite:${roomId}`; }

export function readInvite(roomId: string): string | null {
  try { return localStorage.getItem(inviteStorageKey(roomId)); } catch { return null; }
}

export function InviteBox({ roomId, isHost }: { roomId: string; isHost: boolean }) {
  const { t } = useT();
  const [link, setLink] = useState<string | null>(() =>
    typeof window === "undefined" ? null : readInvite(roomId));
  const [copied, setCopied] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const full = link ? `${window.location.origin}${link}` : null;
  return (
    <div className="space-y-2 rounded-lg bg-neutral-900 p-3 text-xs">
      <div className="font-medium text-neutral-300">{t("host.invite")}</div>
      {full ? (
        <>
          <div className="break-all rounded bg-black/40 p-2 font-mono text-[11px]">{full}</div>
          <p className="text-neutral-500">{t("host.invite_need_pw")}</p>
          <button className={btnGhost} onClick={async () => {
            try { await navigator.clipboard.writeText(full); setCopied(true); setTimeout(() => setCopied(false), 1500); }
            catch { setErr(t("host.copy_fail")); }
          }}>{copied ? t("host.copied") : t("host.copy")}</button>
        </>
      ) : <p className="text-neutral-500">{t("host.no_invite")}</p>}
      {isHost && (
        <button className={`${btnGhost} ml-2`} onClick={async () => {
          try {
            const r = await api.rotateInvite(roomId);
            localStorage.setItem(inviteStorageKey(roomId), r.invite_path);
            setLink(r.invite_path);
          } catch (e) { setErr(errorText(e)); }
        }}>{t("host.rotate")}</button>
      )}
      {err && <p className="text-red-400">{err}</p>}
    </div>
  );
}

export function HostPanel({ view }: { view: RoomView }) {
  const { t } = useT();
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
                onClick={() => run(() => api.resume(rid))}>{t("host.resume")}</button>
      ) : !view.hand ? (
        <button disabled={busy || eligible < 2} className={`${btnPrimary} w-full`}
                onClick={() => run(() => api.startHand(rid, view.room_version))}>
          {view.next_hand_at ? t("room.deal_now") : t("room.start_hand")}
          {eligible < 2 && t("host.need_two")}
        </button>
      ) : <p className="text-xs text-neutral-400">{t("host.in_progress")}</p>}

      <section className="flex items-center gap-2 rounded-lg bg-neutral-900 p-2">
        <div className="min-w-0 flex-1 text-xs">
          <div className="text-neutral-300">{t("host.auto_deal", { s: 5 })}</div>
          <div className={view.auto_deal ? "text-emerald-400" : "text-amber-400"}>
            {view.auto_deal ? t("host.auto_on") : t("host.auto_off")}
          </div>
        </div>
        <button className={btnGhost} disabled={busy}
                onClick={() => run(() => api.autoDeal(rid, !view.auto_deal))}>
          {view.auto_deal ? t("host.pause_deal") : t("host.resume_deal")}
        </button>
      </section>

      {(view.pending_topups?.length ?? 0) > 0 && (
        <section className="space-y-1">
          <h3 className="text-xs font-medium text-neutral-400">{t("host.topups")}</h3>
          {view.pending_topups!.map((tp) => (
            <div key={tp.request_id} className="flex items-center gap-2 rounded-lg bg-neutral-900 p-2">
              <span className="flex-1">{t("host.topup_req", { name: tp.nickname ?? "?", n: chips(tp.amount) })}</span>
              <button className={btnGhost} disabled={busy}
                      onClick={() => run(() => api.decideTopup(rid, tp.request_id, true))}>{t("host.approve")}</button>
              <button className={btnGhost} disabled={busy}
                      onClick={() => run(() => api.decideTopup(rid, tp.request_id, false))}>{t("host.reject")}</button>
            </div>
          ))}
          <p className="text-[11px] text-neutral-500">{t("host.topup_hint")}</p>
        </section>
      )}

      <section className="space-y-2">
        <h3 className="text-xs font-medium text-neutral-400">
          {t("host.cfg_title", { when: view.hand ? t("host.cfg_next") : t("host.cfg_now") })}
        </h3>
        <div className="grid grid-cols-2 gap-2">
          {(["sb", "bb", "min_buyin", "max_buyin"] as const).map((k) => (
            <label key={k} className="text-[11px] text-neutral-400">
              {t(`cfg.${k}`)}
              <input inputMode="numeric" value={cfg[k]} className={inputCls}
                     onChange={(e) => setCfg({ ...cfg, [k]: e.target.value.replace(/\D/g, "") })} />
            </label>
          ))}
        </div>
        <button className={btnGhost} disabled={busy} onClick={() => run(() => api.config(rid, {
          sb: Number(cfg.sb), bb: Number(cfg.bb), min_buyin: Number(cfg.min_buyin),
          max_buyin: Number(cfg.max_buyin) }))}>{t("host.save")}</button>
      </section>
      <InviteBox roomId={rid} isHost />
    </div>
  );
}

export function MembersPanel({ view }: { view: RoomView }) {
  const { t } = useT();
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
              {m.nickname}{m.is_host && " ♛"}{m.member_id === view.me?.member_id && t("common.you")}
              {seatOf.has(m.member_id) && <span className="ml-1 text-xs text-neutral-400">#{seatOf.get(m.member_id)}</span>}
              {m.banned && <span className="ml-1 text-xs text-red-400">{t("members.banned")}</span>}
            </span>
          </div>
          {isHost && m.member_id !== view.me?.member_id && (
            <div className="mt-2 flex flex-wrap gap-1">
              {m.banned ? (
                <button className={btnGhost} onClick={() => run(() => api.unban(view.room_id, m.member_id))}>{t("members.unban")}</button>
              ) : (<>
                <button className={btnGhost} onClick={() => run(() => api.transferHost(view.room_id, m.member_id), t("members.transfer_confirm", { name: m.nickname }))}>{t("members.transfer")}</button>
                {seatOf.has(m.member_id) && (
                  <button className={btnGhost} onClick={() => run(() => api.kick(view.room_id, m.member_id), t("members.kick_confirm", { name: m.nickname }))}>{t("members.kick")}</button>
                )}
                <button className={`${btnGhost} text-red-300`} onClick={() => run(() => api.ban(view.room_id, m.member_id), t("members.ban_confirm", { name: m.nickname }))}>{t("members.ban")}</button>
              </>)}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

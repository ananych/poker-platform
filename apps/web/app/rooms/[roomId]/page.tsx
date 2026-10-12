"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ActionBar } from "@/components/ActionBar";
import { AmountDialog } from "@/components/AmountDialog";
import { ChatPanel } from "@/components/ChatPanel";
import { useRemaining } from "@/components/Countdown";
import { HistoryPanel } from "@/components/HistoryPanel";
import { HostPanel, InviteBox, MembersPanel } from "@/components/HostPanel";
import { LedgerPanel } from "@/components/LedgerPanel";
import { btnGhost } from "@/components/Modal";
import { PokerTable } from "@/components/PokerTable";
import { api, errorText } from "@/lib/api";
import { chips } from "@/lib/poker";
import { useMedia } from "@/lib/useMedia";
import { useRoom } from "@/lib/useRoom";

type Tab = "chat" | "members" | "history" | "ledger" | "host";

export default function RoomPage() {
  const { roomId } = useParams<{ roomId: string }>();
  const room = useRoom(roomId);
  const { view, status, loadError, notice, setNotice, clockOffset } = room;
  const [tab, setTab] = useState<Tab>("chat");
  const [drawer, setDrawer] = useState(false);
  const [sitAt, setSitAt] = useState<number | null>(null);
  const [topup, setTopup] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [unread, setUnread] = useState(0);
  const remaining = useRemaining(view?.hand?.deadline_at, clockOffset);
  const desktop = useMedia("(min-width: 1024px)");

  // UX mitigation only (not a security boundary): hide private cards when backgrounded
  useEffect(() => {
    const f = () => setHidden(document.visibilityState === "hidden");
    document.addEventListener("visibilitychange", f);
    return () => document.removeEventListener("visibilitychange", f);
  }, []);
  useEffect(() => {
    if (notice) { setToast(notice); setNotice(null); }
  }, [notice, setNotice]);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3500);
    return () => clearTimeout(t);
  }, [toast]);
  const seenChat = useRef<number | null>(null);
  useEffect(() => {
    const n = room.chat.length;
    if (seenChat.current !== null && n > seenChat.current && !(tab === "chat" && drawer)) {
      setUnread((u) => u + (n - seenChat.current!));
    }
    seenChat.current = n;
  }, [room.chat.length]); // eslint-disable-line react-hooks/exhaustive-deps
  // just created: open the host tab so the invite link is visible
  useEffect(() => {
    if (window.location.search.includes("created=1")) { setTab("host"); setDrawer(true); }
  }, []);
  useEffect(() => { if (tab === "chat" && drawer) setUnread(0); }, [tab, drawer]);

  if (loadError && !view) {
    return (
      <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-3 px-4">
        <h1 className="text-lg font-semibold">無法進入房間</h1>
        <p className="text-sm text-neutral-400">{errorText(loadError)}</p>
        {loadError.code === "NOT_MEMBER" && (
          <p className="text-sm text-neutral-400">請使用房主提供的邀請連結並輸入房間密碼。</p>)}
        <Link href="/" className={`${btnGhost} flex items-center justify-center`}>回大廳</Link>
      </main>
    );
  }
  if (!view) {
    return <main className="flex min-h-dvh items-center justify-center text-neutral-400">載入中…</main>;
  }

  const me = view.me;
  const mySeat = view.seats.find((s) => s.seat_no === me?.seat_no);
  const inHand = !!view.hand?.your_seat;
  const isHost = !!me?.is_host;
  const pendingTopups = view.pending_topups?.length ?? 0;
  const run = async (fn: () => Promise<unknown>) => {
    try { await fn(); } catch (e) { setToast(errorText(e)); }
  };

  const tabs: { id: Tab; label: string; badge?: number }[] = [
    { id: "chat", label: "聊天", badge: unread },
    { id: "members", label: "成員" },
    { id: "history", label: "歷史" },
    { id: "ledger", label: "籌碼" },
    ...(isHost ? [{ id: "host" as Tab, label: "房主", badge: pendingTopups }] : []),
  ];

  const panel = (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 border-b border-white/10" role="tablist">
        {tabs.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
                  className={`relative h-11 flex-1 text-sm ${tab === t.id ? "border-b-2 border-chip text-chip" : "text-neutral-400"}`}>
            {t.label}
            {!!t.badge && tab !== t.id && (
              <span className="absolute right-1 top-1 rounded-full bg-red-600 px-1 text-[10px] text-white">{t.badge}</span>)}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1">
        {tab === "chat" && <ChatPanel messages={room.chat} myMemberId={me?.member_id}
                                      onSend={room.sendChat} disabled={status !== "open"} />}
        {tab === "members" && (
          <div className="flex h-full flex-col overflow-y-auto">
            <MembersPanel view={view} />
            {!isHost && <div className="p-3"><InviteBox roomId={roomId} isHost={false} /></div>}
          </div>
        )}
        {tab === "history" && <HistoryPanel roomId={roomId} refreshKey={view.last_hand?.hand_id} />}
        {tab === "ledger" && <LedgerPanel roomId={roomId} members={view.members}
                                          refreshKey={view.room_version} />}
        {tab === "host" && isHost && <HostPanel key={view.room_version} view={view} />}
      </div>
    </div>
  );

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      {/* header */}
      <header className="flex shrink-0 items-center gap-2 border-b border-white/10 px-3 pt-[max(0.25rem,env(safe-area-inset-top))]">
        <Link href="/" className="flex h-11 items-center text-neutral-400" aria-label="回大廳">‹</Link>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{view.name ?? "私人房間"}</div>
          <div className="text-[11px] text-neutral-500">
            盲注 {chips(view.config.sb)}/{chips(view.config.bb)} · 買入 {chips(view.config.min_buyin)}–{chips(view.config.max_buyin)}
            {view.pending_config && " · 下一手改設定"}
          </div>
        </div>
        <span className={`h-2 w-2 rounded-full ${status === "open" ? "bg-emerald-400" : "bg-amber-400"}`}
              title={status} aria-label={`連線狀態 ${status}`} />
        {!desktop && <button onClick={() => setDrawer(true)} className="relative h-11 rounded-lg px-3 text-sm text-neutral-300"
                aria-label="開啟面板">
          ☰{(unread + pendingTopups) > 0 && <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-red-500" />}
        </button>}
      </header>

      {view.operational_status === "PAUSED_RECOVERY" && (
        <div className="shrink-0 bg-amber-900/70 px-3 py-1.5 text-center text-xs">
          伺服器重啟後牌局已凍結，等待房主按「繼續」。籌碼與手牌都已保存。
        </div>
      )}
      {view.status === "CLOSED" && (
        <div className="shrink-0 bg-neutral-800 px-3 py-1.5 text-center text-xs">房間已關閉，可查看歷史與籌碼紀錄。</div>
      )}
      {status === "reconnecting" && (
        <div className="shrink-0 bg-neutral-800 px-3 py-1 text-center text-xs text-neutral-300">重新連線中…</div>
      )}

      <div className="flex min-h-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden px-1 py-2">
            <PokerTable view={view} remaining={remaining} onSit={(n) => setSitAt(n)} />
          </div>

          {/* my seat / host shortcuts; never covers the action buttons */}
          <div className="flex shrink-0 flex-wrap items-center justify-center gap-2 px-3 pb-2">
            {isHost && !view.hand && view.operational_status === "ACTIVE" && view.status !== "CLOSED" && (
              <button className="h-11 rounded-lg bg-emerald-600 px-4 text-sm font-semibold"
                      onClick={() => run(() => api.startHand(roomId, view.room_version))}>開始下一手</button>
            )}
            {isHost && view.operational_status === "PAUSED_RECOVERY" && (
              <button className="h-11 rounded-lg bg-amber-500 px-4 text-sm font-semibold text-black"
                      onClick={() => run(() => api.resume(roomId))}>繼續牌局</button>
            )}
            {mySeat && (<>
              <button className={btnGhost} onClick={() => run(() => api.sitOut(roomId,
                mySeat.participation_state !== "SITTING_OUT" && !mySeat.sit_out_next))}>
                {mySeat.participation_state === "SITTING_OUT" || mySeat.sit_out_next ? "回到牌局" : "暫離"}
              </button>
              <button className={btnGhost} onClick={() => setTopup(true)}>補碼</button>
              <button className={btnGhost} onClick={() => {
                if (window.confirm(inHand ? "牌局中離桌會自動棄牌（若可棄牌），結算後結帳。確定？" : "離桌並結帳？"))
                  run(() => api.leave(roomId));
              }}>離桌</button>
              {me?.topups.filter((t) => t.status !== "APPLIED").map((t) => (
                <span key={t.request_id} className="text-xs text-neutral-400">
                  補碼 {chips(t.amount)}：{t.status === "REQUESTED" ? "待核准" : "下一手套用"}
                </span>
              ))}
            </>)}
            {!mySeat && me && view.status !== "CLOSED" && (
              <span className="text-xs text-neutral-400">觀戰中 · 點空位坐下</span>
            )}
          </div>

          {(view.hand?.your_seat || view.hand?.legal_actions) && (
            <ActionBar view={view} act={room.act} hideCards={hidden} />
          )}
        </main>

        {desktop && <aside className="w-80 shrink-0 border-l border-white/10">{panel}</aside>}
      </div>

      {/* mobile bottom sheet */}
      {drawer && !desktop && (
        <div className="fixed inset-0 z-40 flex flex-col justify-end bg-black/50" onClick={() => setDrawer(false)}>
          <div className="flex h-[70dvh] flex-col rounded-t-2xl bg-neutral-950 pb-[env(safe-area-inset-bottom)]"
               onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-center py-1">
              <button onClick={() => setDrawer(false)} className="h-6 w-16" aria-label="關閉面板">
                <span className="mx-auto block h-1 w-10 rounded bg-neutral-600" />
              </button>
            </div>
            {panel}
          </div>
        </div>
      )}

      {sitAt !== null && (
        <AmountDialog title={`坐到 #${sitAt} 並買入`} min={view.config.min_buyin} max={view.config.max_buyin}
                      initial={Math.min(view.config.max_buyin, Math.max(view.config.min_buyin, view.config.bb * 100))}
                      confirm="坐下" onClose={() => setSitAt(null)}
                      onSubmit={async (n) => {
                        try { await api.sit(roomId, sitAt, n); return null; } catch (e) { return errorText(e); }
                      }} />
      )}
      {topup && mySeat && (
        <AmountDialog title="申請補碼（需房主核准）" min={1}
                      max={Math.max(1, view.config.max_buyin - mySeat.stack)}
                      initial={Math.max(1, view.config.max_buyin - mySeat.stack)} confirm="送出申請"
                      onClose={() => setTopup(false)}
                      onSubmit={async (n) => {
                        try { await api.topup(roomId, n); return null; } catch (e) { return errorText(e); }
                      }} />
      )}
      {toast && (
        <div role="status" className="fixed left-1/2 top-16 z-50 -translate-x-1/2 rounded-lg bg-neutral-800 px-4 py-2 text-sm shadow-lg">
          {toast}
        </div>
      )}
    </div>
  );
}

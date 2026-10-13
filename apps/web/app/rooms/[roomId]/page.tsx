"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ActionBar } from "@/components/ActionBar";
import { AmountDialog } from "@/components/AmountDialog";
import { ChatPanel } from "@/components/ChatPanel";
import { useRemaining } from "@/components/Countdown";
import { HistoryPanel } from "@/components/HistoryPanel";
import { HostPanel, InviteBox, MembersPanel } from "@/components/HostPanel";
import { LedgerPanel } from "@/components/LedgerPanel";
import { btnGhost } from "@/components/Modal";
import { PokerTable } from "@/components/PokerTable";
import { SettingsMenu } from "@/components/Settings";
import { StandingsList, StandingsPanel } from "@/components/StandingsPanel";
import { api, errorText } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { chips } from "@/lib/poker";
import { notify, play, vibrate } from "@/lib/sound";
import type { ChatMessage, RoomView } from "@/lib/types";
import { useMedia } from "@/lib/useMedia";
import { useRoom } from "@/lib/useRoom";

type Tab = "chat" | "standings" | "members" | "history" | "ledger" | "host";
const BUBBLE_MS = 5000;
const STANDINGS_EVERY = 5; // pop the standings every N hands

export default function RoomPage() {
  const { roomId } = useParams<{ roomId: string }>();
  const { t } = useT();
  const room = useRoom(roomId);
  const { view, status, loadError, notice, setNotice, clockOffset, onEvent } = room;
  const [tab, setTab] = useState<Tab>("chat");
  const [drawer, setDrawer] = useState(false);
  const [sitAt, setSitAt] = useState<number | null>(null);
  const [topup, setTopup] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [unread, setUnread] = useState(0);
  const [bubbles, setBubbles] = useState<Record<string, string>>({});
  const [bigWin, setBigWin] = useState<number | null>(null);
  const [standingsPop, setStandingsPop] = useState<number | null>(null);
  const remaining = useRemaining(view?.hand?.deadline_at, clockOffset);
  const desktop = useMedia("(min-width: 1024px)");

  const viewRef = useRef<RoomView | null>(null);
  viewRef.current = view;
  const lastSeatRef = useRef<number | null>(null);
  if (view?.me?.seat_no) lastSeatRef.current = view.me.seat_no;
  const chatVisible = desktop ? tab === "chat" : drawer && tab === "chat";
  const chatVisibleRef = useRef(chatVisible);
  chatVisibleRef.current = chatVisible;

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
    const tm = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(tm);
  }, [toast]);
  // just created: open the host tab so the invite link is visible
  useEffect(() => {
    if (window.location.search.includes("created=1")) { setTab("host"); setDrawer(true); }
  }, []);
  useEffect(() => { if (chatVisible) setUnread(0); }, [chatVisible]);

  const showBubble = useCallback((memberId: string, text: string) => {
    setBubbles((b) => ({ ...b, [memberId]: text }));
    setTimeout(() => setBubbles((b) => {
      if (b[memberId] !== text) return b;
      const { [memberId]: _, ...rest } = b; // eslint-disable-line @typescript-eslint/no-unused-vars
      return rest;
    }), BUBBLE_MS);
  }, []);

  // ---- realtime events -> sound, bubbles, alerts ---------------------------
  useEffect(() => onEvent((e) => {
    const v = viewRef.current;
    const me = v?.me;
    const p = e.payload as Record<string, unknown>;
    switch (e.type) {
      case "hand.started":
        play("deal");
        break;
      case "hand.street_changed":
        play("flip");
        break;
      case "game.action": {
        const a = p.action as string;
        if (a === "FOLD") play("fold");
        else if (a === "CHECK") play("check");
        else if (a === "ALL_IN" || p.all_in) play("allin");
        else play("chip");
        break;
      }
      case "hand.completed": {
        const mine = lastSeatRef.current;
        const won = mine ? (p.payouts as Record<string, number> | undefined)?.[String(mine)] : undefined;
        if (won && won > 0) {
          play("win");
          vibrate([80, 60, 160]);
          setBigWin(won);
          setTimeout(() => setBigWin(null), 3200);
        }
        break;
      }
      case "chat.message": {
        const m = p as unknown as ChatMessage;
        showBubble(m.member_id, m.body);
        if (m.member_id !== me?.member_id) {
          play("msg");
          if (!chatVisibleRef.current) {
            setUnread((u) => u + 1);
            setToast(`💬 ${m.nickname ?? "?"}: ${m.body.slice(0, 80)}`);
          }
          notify(`💬 ${m.nickname ?? "?"}`, m.body.slice(0, 120));
        }
        break;
      }
      case "player.sit_out":
        if (p.reason === "TIMEOUT" && p.seat_no === lastSeatRef.current) {
          setToast(t("room.timeout_notice"));
          vibrate(200);
        }
        break;
      case "player.stood_up":
        if (p.reason === "SIT_OUT_TIMEOUT" && p.seat_no === lastSeatRef.current) {
          setToast(t("room.stood_up_notice", { m: 10 }));
        }
        break;
    }
  }), [onEvent, showBubble, t]);

  // ---- my turn: ding + vibrate + background notification -----------------
  const turnKey = view?.hand?.legal_actions ? `${view.hand.hand_id}:${view.hand.phase}:${view.hand.current_bet}:${view.hand.actor_seat}` : null;
  const lastTurn = useRef<string | null>(null);
  useEffect(() => {
    if (!turnKey || lastTurn.current === turnKey) return;
    lastTurn.current = turnKey;
    play("turn");
    vibrate([120, 80, 120]);
    notify(t("room.your_turn_title"), view?.name ?? undefined);
  }, [turnKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- tab title: turn / unread while backgrounded -------------------------
  useEffect(() => {
    const base = view?.name ? `${view.name} · Private Hold'em` : "Private Hold'em";
    if (turnKey) {
      let on = true;
      const tm = setInterval(() => {
        document.title = on ? t("room.your_turn_title") : base;
        on = !on;
      }, 1000);
      return () => { clearInterval(tm); document.title = base; };
    }
    document.title = unread > 0 ? `(${unread}) ${base}` : base;
  }, [turnKey, unread, view?.name, t]);

  // ---- standings pop-up every N hands ---------------------------------------
  const lastOrdinal = view?.last_hand?.ordinal;
  const seenOrdinal = useRef<number | null>(null);
  useEffect(() => {
    if (!lastOrdinal) return;
    if (seenOrdinal.current === null) { seenOrdinal.current = lastOrdinal; return; }
    if (lastOrdinal !== seenOrdinal.current) {
      seenOrdinal.current = lastOrdinal;
      if (lastOrdinal % STANDINGS_EVERY === 0) {
        setStandingsPop(lastOrdinal);
        setTimeout(() => setStandingsPop((o) => (o === lastOrdinal ? null : o)), 7000);
      }
    }
  }, [lastOrdinal]);

  if (loadError && !view) {
    return (
      <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-3 px-4">
        <h1 className="text-lg font-semibold">{t("room.cannot_enter")}</h1>
        <p className="text-sm text-neutral-400">{errorText(loadError)}</p>
        {loadError.code === "NOT_MEMBER" && (
          <p className="text-sm text-neutral-400">{t("room.use_invite")}</p>)}
        <Link href="/" className={`${btnGhost} flex items-center justify-center`}>{t("common.back_lobby")}</Link>
      </main>
    );
  }
  if (!view) {
    return <main className="flex min-h-dvh items-center justify-center text-neutral-400">{t("common.loading")}</main>;
  }

  const me = view.me;
  const mySeat = view.seats.find((s) => s.seat_no === me?.seat_no);
  const inHand = !!view.hand?.your_seat;
  const isHost = !!me?.is_host;
  const pendingTopups = view.pending_topups?.length ?? 0;
  const run = async (fn: () => Promise<unknown>) => {
    try { await fn(); } catch (e) { setToast(errorText(e)); }
  };
  const away = mySeat && (mySeat.participation_state === "SITTING_OUT" || mySeat.sit_out_next);

  const tabs: { id: Tab; label: string; badge?: number }[] = [
    { id: "chat", label: t("tab.chat"), badge: unread },
    { id: "standings", label: t("tab.standings") },
    { id: "members", label: t("tab.members") },
    { id: "history", label: t("tab.history") },
    { id: "ledger", label: t("tab.ledger") },
    ...(isHost ? [{ id: "host" as Tab, label: t("tab.host"), badge: pendingTopups }] : []),
  ];

  const panel = (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 overflow-x-auto border-b border-white/10" role="tablist">
        {tabs.map((tb) => (
          <button key={tb.id} role="tab" aria-selected={tab === tb.id} onClick={() => setTab(tb.id)}
                  className={`relative h-11 min-w-[3.25rem] flex-1 whitespace-nowrap px-1 text-sm ${tab === tb.id ? "border-b-2 border-chip text-chip" : "text-neutral-400"}`}>
            {tb.label}
            {!!tb.badge && tab !== tb.id && (
              <span className="absolute right-0.5 top-1 rounded-full bg-red-600 px-1 text-[10px] text-white">{tb.badge}</span>)}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1">
        {tab === "chat" && <ChatPanel messages={room.chat} myMemberId={me?.member_id}
                                      onSend={room.sendChat} disabled={status !== "open"} />}
        {tab === "standings" && <StandingsPanel rows={view.standings} myMemberId={me?.member_id} />}
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
      <header className="flex shrink-0 items-center gap-1 border-b border-white/10 px-3 pt-[max(0.25rem,env(safe-area-inset-top))]">
        <Link href="/" className="flex h-11 items-center pr-1 text-neutral-400" aria-label={t("common.back_lobby")}>‹</Link>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{view.name ?? t("room.private")}</div>
          <div className="truncate text-[11px] text-neutral-500">
            {t("room.blinds_line", { sb: chips(view.config.sb), bb: chips(view.config.bb),
                                     min: chips(view.config.min_buyin), max: chips(view.config.max_buyin) })}
            {view.pending_config && t("room.pending_cfg")}
          </div>
        </div>
        <span className={`h-2 w-2 shrink-0 rounded-full ${status === "open" ? "bg-emerald-400" : "bg-amber-400"}`}
              title={status} aria-label={t("room.conn_status", { s: status })} />
        <button onClick={() => setStandingsPop(standingsPop ? null : (view.last_hand?.ordinal ?? 0))}
                className="flex h-11 w-11 items-center justify-center rounded-lg text-lg" aria-label={t("stand.title")}>🏆</button>
        <SettingsMenu />
        {!desktop && <button onClick={() => setDrawer(true)} className="relative h-11 rounded-lg px-2 text-sm text-neutral-300"
                aria-label={t("room.open_panel")}>
          ☰{(unread + pendingTopups) > 0 && (
            <span className="absolute right-0 top-1 rounded-full bg-red-600 px-1 text-[10px] text-white">
              {unread + pendingTopups}
            </span>)}
        </button>}
      </header>

      {view.operational_status === "PAUSED_RECOVERY" && (
        <div className="shrink-0 bg-amber-900/70 px-3 py-1.5 text-center text-xs">{t("room.paused_banner")}</div>
      )}
      {view.status === "CLOSED" && (
        <div className="shrink-0 bg-neutral-800 px-3 py-1.5 text-center text-xs">{t("room.closed_banner")}</div>
      )}
      {status === "reconnecting" && (
        <div className="shrink-0 bg-neutral-800 px-3 py-1 text-center text-xs text-neutral-300">{t("room.reconnecting")}</div>
      )}

      <div className="flex min-h-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden px-1 py-2 [container-type:size]">
            <PokerTable view={view} remaining={remaining} clockOffset={clockOffset} bubbles={bubbles}
                        onSit={(n) => setSitAt(n)} />
            {bigWin !== null && (
              <div className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center">
                <div className="big-win rounded-2xl border-2 border-chip bg-black/80 px-6 py-4 text-center shadow-2xl">
                  <div className="text-4xl">🏆</div>
                  <div className="mt-1 text-2xl font-bold text-chip">{t("table.you_won", { amt: chips(bigWin) })}</div>
                </div>
              </div>
            )}
            {standingsPop !== null && (
              <div className="absolute inset-x-3 top-3 z-30 mx-auto max-w-sm rounded-2xl border border-white/10 bg-neutral-950/95 p-3 shadow-2xl"
                   role="dialog" aria-label={t("stand.title")}>
                <div className="mb-2 flex items-center">
                  <h2 className="flex-1 text-sm font-semibold">
                    🏆 {t("stand.title")}
                    {standingsPop > 0 && <span className="ml-2 text-xs font-normal text-neutral-500">{t("stand.after", { n: standingsPop })}</span>}
                  </h2>
                  <button onClick={() => setStandingsPop(null)} className="h-9 w-9 text-neutral-400"
                          aria-label={t("common.close")}>×</button>
                </div>
                <StandingsList rows={view.standings} myMemberId={me?.member_id} compact />
              </div>
            )}
          </div>

          {/* my seat / host shortcuts; never covers the action buttons */}
          <div className="flex shrink-0 flex-wrap items-center justify-center gap-2 px-3 pb-2">
            {isHost && !view.hand && view.operational_status === "ACTIVE" && view.status !== "CLOSED" && (
              <button className="h-11 rounded-lg bg-emerald-600 px-4 text-sm font-semibold"
                      onClick={() => run(() => api.startHand(roomId, view.room_version))}>
                {view.next_hand_at ? t("room.deal_now") : t("room.start_hand")}
              </button>
            )}
            {isHost && view.operational_status === "PAUSED_RECOVERY" && (
              <button className="h-11 rounded-lg bg-amber-500 px-4 text-sm font-semibold text-black"
                      onClick={() => run(() => api.resume(roomId))}>{t("room.resume")}</button>
            )}
            {mySeat && (<>
              <button className={away ? "h-11 rounded-lg bg-emerald-600 px-4 text-sm font-semibold" : btnGhost}
                      onClick={() => run(() => api.sitOut(roomId, !away))}>
                {away ? t("room.back_in") : t("room.sit_out")}
              </button>
              <button className={btnGhost} onClick={() => setTopup(true)}>{t("room.topup")}</button>
              <button className={btnGhost} onClick={() => {
                if (window.confirm(inHand ? t("room.leave_confirm_hand") : t("room.leave_confirm")))
                  run(() => api.leave(roomId));
              }}>{t("room.leave")}</button>
              {me?.topups.filter((tp) => tp.status !== "APPLIED").map((tp) => (
                <span key={tp.request_id} className="text-xs text-neutral-400">
                  {tp.status === "REQUESTED" ? t("room.topup_requested", { n: chips(tp.amount) })
                    : t("room.topup_approved", { n: chips(tp.amount) })}
                </span>
              ))}
            </>)}
            {!mySeat && me && view.status !== "CLOSED" && (
              <span className="text-xs text-neutral-400">{t("room.spectating")}</span>
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
              <button onClick={() => setDrawer(false)} className="h-6 w-16" aria-label={t("room.close_panel")}>
                <span className="mx-auto block h-1 w-10 rounded bg-neutral-600" />
              </button>
            </div>
            {panel}
          </div>
        </div>
      )}

      {sitAt !== null && (
        <AmountDialog title={t("room.sit_title", { n: sitAt })} min={view.config.min_buyin} max={view.config.max_buyin}
                      initial={Math.min(view.config.max_buyin, Math.max(view.config.min_buyin, view.config.bb * 100))}
                      confirm={t("room.sit_confirm")} onClose={() => setSitAt(null)}
                      onSubmit={async (n) => {
                        try { await api.sit(roomId, sitAt, n); return null; } catch (e) { return errorText(e); }
                      }} />
      )}
      {topup && mySeat && (
        <AmountDialog title={t("room.topup_title")} min={1}
                      max={Math.max(1, view.config.max_buyin - mySeat.stack)}
                      initial={Math.max(1, view.config.max_buyin - mySeat.stack)} confirm={t("room.topup_confirm")}
                      onClose={() => setTopup(false)}
                      onSubmit={async (n) => {
                        try { await api.topup(roomId, n); return null; } catch (e) { return errorText(e); }
                      }} />
      )}
      {toast && (
        <button role="status" onClick={() => {
                  if (toast.startsWith("💬")) { setTab("chat"); setDrawer(true); }
                  setToast(null);
                }}
                className="toast-in fixed left-1/2 top-16 z-50 max-w-[92vw] -translate-x-1/2 truncate rounded-xl bg-neutral-800 px-4 py-2 text-sm shadow-xl ring-1 ring-white/10">
          {toast}
        </button>
      )}
    </div>
  );
}

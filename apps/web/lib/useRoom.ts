"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, wsUrl } from "./api";
import { getLang, translate } from "./i18n";
import type {
  ActionResult, ChatMessage, CommandEnvelope, EventEnvelope, PokerAction, RoomView,
} from "./types";

export type ConnStatus = "connecting" | "open" | "reconnecting" | "forbidden" | "unauthorized";

export function uuid4(): string {
  const c: Crypto = globalThis.crypto;
  if (typeof c.randomUUID === "function") return c.randomUUID();
  const b = c.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

interface Pending { resolve: (r: ActionResult) => void; timer: ReturnType<typeof setTimeout> }

/**
 * Authoritative room state over WebSocket (SDD §8).
 * - `room.state` is truth; older versions are ignored.
 * - On reconnect / tab focus / stale errors we ask for `room.sync`.
 * - The server clock offset is tracked for countdowns only (server decides timeouts).
 */
export function useRoom(roomId: string) {
  const [view, setView] = useState<RoomView | null>(null);
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<ConnStatus>("connecting");
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [clockOffset, setClockOffset] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const versionRef = useRef(-1);
  const pending = useRef(new Map<string, Pending>());
  const retry = useRef(0);
  const stopped = useRef(false);
  const listeners = useRef(new Set<(e: EventEnvelope) => void>());
  /** Subscribe to every server event (sounds, bubbles, notices). Returns unsubscribe. */
  const onEvent = useCallback((fn: (e: EventEnvelope) => void) => {
    listeners.current.add(fn);
    return () => { listeners.current.delete(fn); };
  }, []);

  const applyView = useCallback((v: RoomView) => {
    if (v.room_version >= versionRef.current) {
      versionRef.current = v.room_version;
      setView(v);
    }
  }, []);

  const send = useCallback((cmd: CommandEnvelope) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(cmd));
      return true;
    }
    return false;
  }, []);

  const sync = useCallback(() => send({ kind: "command", type: "room.sync" }), [send]);

  const refresh = useCallback(async () => {
    try {
      applyView(await api.room(roomId));
      setLoadError(null);
    } catch (e) {
      if (e instanceof ApiError) setLoadError(e);
    }
  }, [roomId, applyView]);

  useEffect(() => {
    stopped.current = false;
    refresh();
    api.chat(roomId).then((r) => setChat(r.messages)).catch(() => {});

    let ping: ReturnType<typeof setInterval> | undefined;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      setStatus(retry.current === 0 ? "connecting" : "reconnecting");
      const ws = new WebSocket(wsUrl(`/ws/rooms/${roomId}`));
      wsRef.current = ws;
      ws.onopen = () => {
        retry.current = 0;
        setStatus("open");
        ping = setInterval(() => send({ kind: "command", type: "ping" }), 25_000);
      };
      ws.onmessage = (ev) => {
        let msg: EventEnvelope;
        try { msg = JSON.parse(ev.data); } catch { return; }
        if (msg.server_time) {
          setClockOffset(new Date(msg.server_time).getTime() - Date.now());
        }
        for (const fn of listeners.current) {
          try { fn(msg); } catch { /* listener bugs must not break sync */ }
        }
        switch (msg.type) {
          case "room.state":
            applyView(msg.payload as RoomView);
            break;
          case "chat.message": {
            const m = msg.payload as ChatMessage;
            setChat((c) => (c.some((x) => x.message_id === m.message_id) ? c : [...c, m].slice(-200)));
            break;
          }
          case "action.result": {
            const r = msg.payload as ActionResult;
            const p = r.action_id ? pending.current.get(r.action_id) : undefined;
            if (p) {
              clearTimeout(p.timer);
              pending.current.delete(r.action_id!);
              p.resolve(r);
            }
            if (!r.accepted) sync();
            break;
          }
          case "error":
            setNotice((msg.payload as { message?: string }).message ?? translate(getLang(), "common.error"));
            break;
          case "room.closed":
            setNotice(translate(getLang(), "room.closed_notice"));
            break;
          default:
            // versioned delta whose room.state will follow; resync if we fell behind
            if (msg.room_version !== null && msg.room_version > versionRef.current + 1) sync();
        }
      };
      ws.onclose = (ev) => {
        if (ping) clearInterval(ping);
        for (const [id, p] of pending.current) {
          clearTimeout(p.timer);
          p.resolve({ accepted: false, action_id: id, error: {
            code: "INTERNAL", message: translate(getLang(), "common.disconnected"), room_version: null } });
        }
        pending.current.clear();
        if (stopped.current) return;
        if (ev.code === 4401) { setStatus("unauthorized"); return; }
        if (ev.code === 4403) { setStatus("forbidden"); refresh(); return; }
        retry.current += 1;
        setStatus("reconnecting");
        const delay = Math.min(10_000, 500 * 2 ** Math.min(retry.current, 5));
        reconnectTimer = setTimeout(connect, delay);
      };
    };
    connect();

    const onVisible = () => { if (document.visibilityState === "visible") { sync(); } };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped.current = true;
      document.removeEventListener("visibilitychange", onVisible);
      if (ping) clearInterval(ping);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, [roomId, applyView, refresh, send, sync]);

  const act = useCallback((action: PokerAction, raiseTo?: number): Promise<ActionResult> => {
    const v = view;
    if (!v?.hand) return Promise.resolve({ accepted: false });
    const action_id = uuid4();
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        pending.current.delete(action_id);
        resolve({ accepted: false, action_id, error: {
          code: "INTERNAL", message: translate(getLang(), "common.no_response"), room_version: null } });
        sync();
      }, 8000);
      pending.current.set(action_id, { resolve, timer });
      const ok = send({
        kind: "command", type: "player.action", action_id, hand_id: v.hand!.hand_id,
        expected_room_version: v.room_version,
        payload: raiseTo === undefined ? { action } : { action, raise_to: Math.trunc(raiseTo) },
      });
      if (!ok) {
        clearTimeout(timer);
        pending.current.delete(action_id);
        resolve({ accepted: false, action_id, error: {
          code: "INTERNAL", message: translate(getLang(), "common.not_connected"), room_version: null } });
      }
    });
  }, [view, send, sync]);

  const sendChat = useCallback((body: string) =>
    send({ kind: "command", type: "chat.send", payload: { body } }), [send]);

  return { view, chat, status, loadError, notice, setNotice, clockOffset, act, sendChat, refresh,
           onEvent };
}

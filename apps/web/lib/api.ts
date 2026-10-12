import type {
  ApiErrorBody, ChatMessage, Guest, HandSummary, LedgerEntry, LedgerSummary, Me, Replay,
  RoomConfig, RoomView,
} from "./types";

/** Empty = same origin (production behind the reverse proxy). */
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(/\/$/, "");

export function wsUrl(path: string): string {
  if (API_BASE) return API_BASE.replace(/^http/, "ws") + path;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}

export class ApiError extends Error {
  constructor(public readonly body: ApiErrorBody, public readonly status: number) {
    super(body.message);
  }
  get code() { return this.body.code; }
}

async function request<T>(method: string, path: string, body?: unknown,
                          headers: Record<string, string> = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1${path}`, {
      method,
      credentials: "include", // HttpOnly session cookie; never readable by JS
      headers: {
        "Content-Type": "application/json",
        ...(method !== "GET" ? { "X-Poker-CSRF": "1" } : {}),
        ...headers,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    throw new ApiError({ code: "INTERNAL", message: "無法連線到伺服器", room_version: null }, 0);
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = (data as { error?: ApiErrorBody } | null)?.error ?? {
      code: "INTERNAL", message: `HTTP ${res.status}`, room_version: null,
    };
    throw new ApiError(err as ApiErrorBody, res.status);
  }
  return data as T;
}

export interface CreatedRoom {
  room_id: string; member_id: string; invite_token: string; invite_path: string;
  room_version: number;
}

export const api = {
  createSession: (nickname: string) => request<Guest>("POST", "/guests/session", { nickname }),
  me: () => request<Me>("GET", "/me"),

  createRoom: (b: { password: string; name?: string } & RoomConfig) =>
    request<CreatedRoom>("POST", "/rooms", b),
  join: (roomId: string, invite_token: string, password: string) =>
    request<{ member_id: string }>("POST", `/rooms/${roomId}/join`, { invite_token, password }),
  room: (roomId: string) => request<RoomView>("GET", `/rooms/${roomId}`),

  sit: (roomId: string, seat: number, buyin: number) =>
    request("POST", `/rooms/${roomId}/seats/${seat}`, { buyin }),
  sitOut: (roomId: string, sit_out: boolean) =>
    request("POST", `/rooms/${roomId}/sit-out`, { sit_out }),
  leave: (roomId: string) => request<{ status: string }>("POST", `/rooms/${roomId}/leave`),
  topup: (roomId: string, amount: number) =>
    request("POST", `/rooms/${roomId}/topups`, { amount }),
  decideTopup: (roomId: string, requestId: string, approve: boolean) =>
    request("POST", `/rooms/${roomId}/topups/${requestId}/approve`, { approve }),

  startHand: (roomId: string, expected_room_version: number) =>
    request<{ hand_id: string }>("POST", `/rooms/${roomId}/start-hand`, { expected_room_version },
      { "Idempotency-Key": `${roomId}:${expected_room_version}` }),
  resume: (roomId: string) => request("POST", `/rooms/${roomId}/resume`),
  rotateInvite: (roomId: string) =>
    request<{ invite_token: string; invite_path: string }>("POST", `/rooms/${roomId}/invite`),
  config: (roomId: string, patch: Partial<RoomConfig>) =>
    request("PATCH", `/rooms/${roomId}/config`, patch),
  kick: (roomId: string, memberId: string) =>
    request("POST", `/rooms/${roomId}/members/${memberId}/kick`),
  ban: (roomId: string, memberId: string) =>
    request("POST", `/rooms/${roomId}/members/${memberId}/ban`),
  unban: (roomId: string, memberId: string) =>
    request("DELETE", `/rooms/${roomId}/bans/${memberId}`),
  transferHost: (roomId: string, member_id: string) =>
    request("POST", `/rooms/${roomId}/transfer-host`, { member_id }),

  ledger: (roomId: string) =>
    request<{ entries: LedgerEntry[]; summary: LedgerSummary[] }>("GET", `/rooms/${roomId}/ledger`),
  hands: (roomId: string, cursor?: number | null) =>
    request<{ items: HandSummary[]; next_cursor: number | null }>(
      "GET", `/rooms/${roomId}/hands${cursor ? `?cursor=${cursor}` : ""}`),
  replay: (roomId: string, handId: string) =>
    request<Replay>("GET", `/rooms/${roomId}/hands/${handId}`),
  chat: (roomId: string) =>
    request<{ messages: ChatMessage[] }>("GET", `/rooms/${roomId}/chat`),
};

export function errorText(e: unknown): string {
  if (e instanceof ApiError) return ERROR_TEXT[e.code] ?? e.message;
  return "發生錯誤，請再試一次";
}

export const ERROR_TEXT: Partial<Record<string, string>> = {
  UNAUTHORIZED: "請先以訪客身分進入，或邀請連結無效",
  INVALID_PASSWORD: "房間密碼錯誤",
  ROOM_BANNED: "你已被此房間封鎖",
  ROOM_CLOSED: "房間已關閉",
  INVALID_BUYIN: "買入金額不在允許範圍內",
  NOT_HOST: "只有房主可以這麼做",
  HAND_ALREADY_RUNNING: "已有牌局進行中",
  NOT_YOUR_TURN: "還沒輪到你",
  INVALID_ACTION: "這個動作目前不合法",
  STALE_VERSION: "牌桌狀態已更新，請再操作一次",
  DEADLINE_EXPIRED: "已超過行動時間",
  TOPUP_LIMIT_EXCEEDED: "超過最大買入上限",
  RATE_LIMITED: "操作太頻繁，請稍候",
  NOT_MEMBER: "你還不是這個房間的成員",
  SEAT_TAKEN: "這個座位已經有人",
  ALREADY_SEATED: "你已經有座位了",
  ROOM_PAUSED: "牌局暫停中，等待房主繼續",
};

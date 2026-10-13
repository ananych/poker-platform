// Wire types (SDD §7–8). Keep in sync with services/api/app/services/views.py and
// docs/ws-protocol.md. Chip amounts are integer chip units — never float math.

export type Chips = number;

export type ErrorCode =
  | "UNAUTHORIZED" | "ROOM_BANNED" | "ROOM_CLOSED" | "ROOM_FULL" | "INVALID_PASSWORD"
  | "INVALID_BUYIN" | "NOT_HOST" | "HAND_ALREADY_RUNNING" | "NOT_YOUR_TURN"
  | "INVALID_ACTION" | "STALE_VERSION" | "DEADLINE_EXPIRED" | "TOPUP_LIMIT_EXCEEDED"
  | "RATE_LIMITED" | "VALIDATION_ERROR" | "CSRF_FAILED" | "INTERNAL" | "NOT_FOUND"
  | "ROOM_PAUSED" | "NOT_MEMBER" | "SEAT_TAKEN" | "ALREADY_SEATED";

export interface ApiErrorBody {
  code: ErrorCode;
  message: string;
  room_version: number | null;
  request_id?: string;
}

export interface Guest { guest_id: string; nickname: string }
export interface MyRoom {
  room_id: string; name: string | null; status: string; member_id: string;
  is_host: boolean; banned: boolean;
}
export interface Me extends Guest { rooms: MyRoom[] }

export type PokerAction = "FOLD" | "CHECK" | "CALL" | "BET" | "RAISE" | "ALL_IN";
export type Phase =
  | "PREFLOP" | "FLOP" | "TURN" | "RIVER" | "SHOWDOWN" | "SETTLEMENT" | "HAND_COMPLETE";

export interface RoomConfig { sb: Chips; bb: Chips; min_buyin: Chips; max_buyin: Chips }

export interface LegalActions {
  seat: number;
  can_fold: boolean;
  can_check: boolean;
  call_amount: Chips;
  can_bet: boolean;
  can_raise: boolean;
  min_raise_to: Chips;
  max_raise_to: Chips;
}

export interface HandSeat {
  seat_no: number;
  stack: Chips;
  street_contribution: Chips;
  total_contribution: Chips;
  folded: boolean;
  all_in: boolean;
  has_cards: boolean;
  shown_cards?: string[];
}

export interface HandView {
  hand_id: string;
  ordinal: number;
  phase: Phase;
  button_seat: number;
  sb_seat: number;
  bb_seat: number;
  actor_seat: number | null;
  current_bet: Chips;
  min_full_raise_increment: Chips;
  pot: Chips;
  community_cards: string[];
  seats: HandSeat[];
  deadline_at: string | null;
  your_seat?: number;
  your_cards?: string[];
  legal_actions?: LegalActions;
}

export interface PotResult { index: number; amount: Chips; eligible: number[]; winners: number[] }

export interface LastHand {
  hand_id: string;
  ordinal: number;
  ended_at?: string | null;
  /** seat_no -> member_id for the finished hand */
  seat_members?: Record<string, string>;
  /** only for a viewer who played the hand: their own hole cards (even if folded) */
  my_seat?: number;
  my_cards?: string[];
  showdown?: {
    board: string[];
    shown: { seat_no: number; hole_cards: string[]; rank: string; best_five: string[] }[];
    mucked: number[];
  };
  completed?: {
    pots: PotResult[];
    payouts: Record<string, Chips>;
    stacks: Record<string, Chips>;
    board: string[];
    uncontested: boolean;
  };
}

export interface MemberView {
  member_id: string; nickname: string; connected: boolean; is_host: boolean; banned: boolean;
}

export interface SeatView {
  seat_no: number;
  member_id: string;
  nickname: string | null;
  stack: Chips;
  participation_state: "WAITING_FOR_BLIND" | "ACTIVE" | "SITTING_OUT";
  pending_leave: boolean;
  sit_out_next: boolean;
  connected: boolean;
  /** stack (+ chips committed to the live pot) + cash-outs − buy-ins − top-ups */
  net: Chips;
}

export interface Standing {
  member_id: string; nickname: string | null; seated: boolean;
  invested: Chips; cashed_out: Chips; stack: Chips; net: Chips;
}

export interface TopupView { request_id: string; amount: Chips; status: string }
export interface PendingTopup extends TopupView { member_id: string; nickname: string | null }

export interface RoomView {
  room_id: string;
  name: string | null;
  status: "OPEN" | "EMPTY_PENDING_CLOSE" | "CLOSED";
  operational_status: "ACTIVE" | "PAUSED_RECOVERY";
  auto_deal: boolean;
  next_hand_at: string | null;
  standings: Standing[];
  room_version: number;
  config: RoomConfig;
  pending_config: RoomConfig | null;
  host_member_id: string | null;
  members: MemberView[];
  seats: SeatView[];
  me: { member_id: string; is_host: boolean; seat_no: number | null; topups: TopupView[] } | null;
  pending_topups?: PendingTopup[];
  hand: HandView | null;
  last_hand: LastHand | null;
}

export interface ChatMessage {
  message_id: string; member_id: string; nickname: string | null; body: string; created_at: string;
}

export interface LedgerEntry { id: string; member_id: string; type: string; amount: Chips; created_at: string }
export interface LedgerSummary {
  member_id: string; total_buyins: Chips; total_topups: Chips; cash_out: Chips;
  current_stack: Chips; net: Chips;
}

export interface HandSummary {
  hand_id: string; ordinal: number; started_at: string; ended_at: string | null;
  blinds: [Chips, Chips]; board: string[]; pots: PotResult[]; uncontested: boolean | null;
  players: { seat_no: number; member_id: string; nickname: string | null; won: Chips }[];
  my_seat: number | null; my_result: Chips | null;
}

export interface ReplayEvent { seq: number; type: string; payload: Record<string, unknown>; at: string }
export interface Replay {
  hand_id: string; ordinal: number; config: { sb: Chips; bb: Chips; rules_version: string };
  button_seat: number;
  players: { seat_no: number; member_id: string; nickname: string | null }[];
  my_seat: number | null; my_cards: string[] | null; events: ReplayEvent[];
}

export interface CommandEnvelope {
  kind: "command";
  type: "player.action" | "chat.send" | "room.sync" | "ping";
  action_id?: string;
  hand_id?: string;
  expected_room_version?: number;
  payload?: Record<string, unknown>;
}

export interface EventEnvelope<T = unknown> {
  kind: "event";
  type: string;
  event_id: string;
  room_id: string;
  room_version: number | null;
  server_time: string;
  payload: T;
}

export interface ActionResult {
  accepted: boolean;
  room_version?: number;
  hand_id?: string;
  action_id?: string;
  replayed?: boolean;
  error?: ApiErrorBody;
}

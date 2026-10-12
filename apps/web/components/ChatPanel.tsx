"use client";

import { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "@/lib/types";

export function ChatPanel({ messages, myMemberId, onSend, disabled }: {
  messages: ChatMessage[]; myMemberId?: string; onSend: (body: string) => boolean;
  disabled?: boolean;
}) {
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [messages.length]);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto p-3 text-sm">
        {messages.length === 0 && <p className="text-xs text-neutral-500">還沒有訊息</p>}
        {messages.map((m) => (
          <div key={m.message_id} className="break-words">
            <span className={`mr-1 font-medium ${m.member_id === myMemberId ? "text-chip" : "text-sky-300"}`}>
              {m.nickname ?? "?"}
            </span>
            {/* rendered as text: React escapes it (no HTML injection) */}
            <span className="whitespace-pre-wrap text-neutral-200">{m.body}</span>
          </div>
        ))}
        <div ref={end} />
      </div>
      <form className="flex gap-2 border-t border-white/10 p-2" onSubmit={(e) => {
        e.preventDefault();
        const t = text.trim();
        if (t && onSend(t)) setText("");
      }}>
        <input value={text} onChange={(e) => setText(e.target.value)} maxLength={500}
               disabled={disabled} placeholder="說點什麼…" aria-label="聊天訊息"
               className="h-11 min-w-0 flex-1 rounded-lg bg-neutral-950 px-3 text-sm ring-1 ring-neutral-700" />
        <button disabled={disabled || !text.trim()}
                className="h-11 rounded-lg bg-neutral-700 px-3 text-sm disabled:opacity-50">送出</button>
      </form>
    </div>
  );
}

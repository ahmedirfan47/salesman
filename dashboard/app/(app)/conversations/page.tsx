"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { MessageSquare, Mic, ArrowLeft } from "lucide-react";

type Conversation = {
  id: string;
  customer_number: string;
  customer_name: string | null;
  status: string;
  last_message_at: string | null;
};

type Message = {
  id: string;
  direction: string;
  sender: string;
  msg_type: string;
  content: string;
  created_at: string;
};

export default function ConversationsPage() {
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/conversations")
      .then(setConvs)
      .catch((e) => setError(e.message));
  }, []);

  function open(c: Conversation) {
    setSelected(c);
    setMessages([]);
    api(`/conversations/${c.id}/messages`)
      .then(setMessages)
      .catch((e) => setError(e.message));
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Conversations</h1>
      <p className="mb-6 text-sm text-slate-500">WhatsApp chats handled by your AI agent</p>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* List: hidden on mobile once a conversation is open */}
        <Card className={`overflow-hidden lg:col-span-1 ${selected ? "hidden lg:block" : ""}`}>
          <div className="max-h-[70vh] overflow-y-auto">
            {convs.map((c) => (
              <button
                key={c.id}
                onClick={() => open(c)}
                className={`flex w-full items-start gap-3 border-b border-[var(--border)] px-4 py-3 text-left last:border-0 hover:bg-gray-50 ${
                  selected?.id === c.id ? "bg-indigo-50" : ""
                }`}
              >
                <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-[var(--primary)]">
                  <MessageSquare size={16} />
                </div>
                <div className="min-w-0">
                  <div className="truncate font-medium">{c.customer_name || c.customer_number}</div>
                  <div className="truncate text-xs text-slate-500">{c.customer_number}</div>
                </div>
              </button>
            ))}
            {convs.length === 0 && !error && (
              <div className="px-4 py-10 text-center text-sm text-slate-400">No conversations yet</div>
            )}
          </div>
        </Card>

        {/* Thread: hidden on mobile until a conversation is selected */}
        <Card className={`lg:col-span-2 ${!selected ? "hidden lg:flex" : "flex"}`}>
          {!selected ? (
            <div className="flex h-full min-h-[300px] items-center justify-center text-sm text-slate-400">
              Select a conversation to view messages
            </div>
          ) : (
            <div className="flex h-[70vh] w-full flex-col">
              <div className="flex items-center gap-2 border-b border-[var(--border)] px-5 py-3">
                <button onClick={() => setSelected(null)} className="text-slate-500 hover:text-slate-700 lg:hidden">
                  <ArrowLeft size={18} />
                </button>
                <div>
                  <div className="font-medium">{selected.customer_name || selected.customer_number}</div>
                  <div className="text-xs text-slate-500">{selected.customer_number}</div>
                </div>
              </div>
              <div className="flex-1 space-y-3 overflow-y-auto p-5">
                {messages.map((m) => (
                  <div key={m.id} className={`flex ${m.direction === "out" ? "justify-end" : "justify-start"}`}>
                    <div
                      className={`max-w-[75%] rounded-2xl px-4 py-2 text-sm ${
                        m.direction === "out"
                          ? "bg-[var(--primary)] text-white"
                          : "bg-gray-100 text-slate-800"
                      }`}
                    >
                      {m.msg_type === "audio" && (
                        <span className="mb-1 flex items-center gap-1 text-xs opacity-70">
                          <Mic size={12} /> voice note
                        </span>
                      )}
                      {m.content}
                    </div>
                  </div>
                ))}
                {messages.length === 0 && (
                  <div className="text-center text-sm text-slate-400">No messages</div>
                )}
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import {
  Bot,
  ChevronDown,
  Loader2,
  Send,
  Sparkles,
  Square,
  User,
} from "lucide-react";
import { useLocale } from "@/lib/i18n";

type ChatPanelProps = {
  initialThreadId?: string | null;
  onThreadChange?: (threadId: string | null) => void;
  onResponseEnd?: () => void;
  onRunnerUpdate?: () => void;
  onRunnerEventDelta?: (events: any[]) => void;
  onRunnerBindThread?: (threadId: string) => void;
};

type ChatItem =
  | { kind: "user"; id: string; text: string }
  | { kind: "assistant"; id: string; text: string }
  | { kind: "thinking"; id: string; tasks: string[]; done: boolean };

const markdownComponents: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => (
    <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>
  ),
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  strong: ({ children }) => (
    <strong className="font-semibold">{children}</strong>
  ),
  code: ({ children }) => (
    <code className="rounded bg-gray-100 px-1 py-0.5 font-mono text-[0.85em]">
      {children}
    </code>
  ),
  pre: ({ children }) => (
    <pre className="mb-2 overflow-x-auto rounded-md bg-gray-100 p-2 text-xs last:mb-0">
      {children}
    </pre>
  ),
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-blue-600 underline"
    >
      {children}
    </a>
  ),
};

function contentToText(content: unknown): string {
  if (!Array.isArray(content)) return "";
  return content
    .map((part: any) => (part && typeof part.text === "string" ? part.text : ""))
    .join("");
}

function ThinkingBlock({
  item,
  label,
}: {
  item: Extract<ChatItem, { kind: "thinking" }>;
  label: string;
}) {
  const [open, setOpen] = useState(true);
  const text = item.tasks.filter(Boolean).join("\n\n");

  return (
    <div className="w-full max-w-[85%] rounded-2xl border border-amber-200 bg-amber-50/70 px-3 py-2 text-xs text-amber-900">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 font-medium"
      >
        <Sparkles className="h-3.5 w-3.5" />
        <span>{label}</span>
        {!item.done && <Loader2 className="h-3 w-3 animate-spin" />}
        <ChevronDown
          className={`ml-auto h-3.5 w-3.5 transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>
      {open && text && (
        <div className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap leading-relaxed opacity-80">
          {text}
        </div>
      )}
    </div>
  );
}

function TypingDots() {
  return (
    <span className="flex items-center gap-1 py-1">
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400 [animation-delay:120ms]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400 [animation-delay:240ms]" />
    </span>
  );
}

export function ChatPanel({
  initialThreadId,
  onThreadChange,
  onResponseEnd,
  onRunnerBindThread,
}: ChatPanelProps) {
  const { t } = useLocale();
  const [items, setItems] = useState<ChatItem[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const threadIdRef = useRef<string | null>(initialThreadId ?? null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);

  useEffect(() => {
    if (initialThreadId) {
      threadIdRef.current = initialThreadId;
    }
  }, [initialThreadId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [items, busy]);

  const updateItem = useCallback(
    (id: string, updater: (item: ChatItem) => ChatItem) => {
      setItems((prev) =>
        prev.map((item) => (item.id === id ? updater(item) : item)),
      );
    },
    [],
  );

  const appendAssistantText = useCallback((id: string, delta: string) => {
    setItems((prev) => {
      const index = prev.findIndex(
        (item) => item.kind === "assistant" && item.id === id,
      );
      if (index === -1) {
        return [...prev, { kind: "assistant", id, text: delta }];
      }
      const next = [...prev];
      const current = next[index] as Extract<ChatItem, { kind: "assistant" }>;
      next[index] = { ...current, text: current.text + delta };
      return next;
    });
  }, []);

  const setAssistantText = useCallback((id: string, text: string) => {
    setItems((prev) => {
      const index = prev.findIndex(
        (item) => item.kind === "assistant" && item.id === id,
      );
      if (index === -1) {
        return text ? [...prev, { kind: "assistant", id, text }] : prev;
      }
      const next = [...prev];
      next[index] = { kind: "assistant", id, text };
      return next;
    });
  }, []);

  const handleEvent = useCallback(
    (event: any) => {
      const type = event?.type;
      if (type === "error") {
        setError(t("errorOccurred"));
        return;
      }
      if (type === "thread.created") {
        const threadId = event?.thread?.id;
        if (threadId) {
          threadIdRef.current = threadId;
          onThreadChange?.(threadId);
          onRunnerBindThread?.(threadId);
        }
        return;
      }
      if (type === "client_effect" && event?.name === "runner_bind_thread") {
        const threadId = event?.data?.thread_id;
        if (threadId && threadIdRef.current !== threadId) {
          threadIdRef.current = threadId;
          onThreadChange?.(threadId);
          onRunnerBindThread?.(threadId);
        }
        return;
      }
      if (type === "thread.item.added" || type === "thread.item.done") {
        const item = event?.item;
        if (!item) return;
        if (item.type === "workflow" && item.workflow?.type === "reasoning") {
          const tasks = (item.workflow.tasks ?? []).map((task: any) =>
            typeof task?.content === "string" ? task.content : "",
          );
          if (type === "thread.item.added") {
            setItems((prev) =>
              prev.some((entry) => entry.id === item.id)
                ? prev
                : [
                    ...prev,
                    { kind: "thinking", id: item.id, tasks, done: false },
                  ],
            );
          } else {
            updateItem(item.id, (entry) =>
              entry.kind === "thinking"
                ? {
                    ...entry,
                    tasks: tasks.length ? tasks : entry.tasks,
                    done: true,
                  }
                : entry,
            );
          }
        }
        if (item.type === "assistant_message") {
          const text = contentToText(item.content);
          if (type === "thread.item.added") {
            setItems((prev) =>
              prev.some(
                (entry) => entry.kind === "assistant" && entry.id === item.id,
              )
                ? prev
                : [...prev, { kind: "assistant", id: item.id, text }],
            );
          } else if (text) {
            setAssistantText(item.id, text);
          }
        }
        return;
      }
      if (type === "thread.item.updated") {
        const update = event?.update;
        const itemId = event?.item_id;
        if (!update || !itemId) return;
        if (update.type === "assistant_message.content_part.text_delta") {
          appendAssistantText(itemId, String(update.delta ?? ""));
          return;
        }
        if (update.type === "assistant_message.content_part.done") {
          const text = update?.content?.text;
          if (typeof text === "string" && text) {
            setAssistantText(itemId, text);
          }
          return;
        }
        if (
          update.type === "workflow.task.added" ||
          update.type === "workflow.task.updated"
        ) {
          const index = Number(update.task_index ?? 0);
          const content =
            typeof update?.task?.content === "string" ? update.task.content : "";
          updateItem(itemId, (entry) => {
            if (entry.kind !== "thinking") return entry;
            const tasks = [...entry.tasks];
            while (tasks.length <= index) tasks.push("");
            tasks[index] = content;
            return { ...entry, tasks };
          });
        }
      }
    },
    [
      appendAssistantText,
      onRunnerBindThread,
      onThreadChange,
      setAssistantText,
      t,
      updateItem,
    ],
  );

  const sendMessage = useCallback(
    async (raw: string) => {
      const text = raw.trim();
      if (!text || busyRef.current) return;

      setInput("");
      setError(null);
      setItems((prev) => [
        ...prev,
        { kind: "user", id: `local_${Date.now()}`, text },
      ]);
      setBusy(true);
      busyRef.current = true;

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const threadId = threadIdRef.current;
        const inputPayload = {
          content: [{ type: "input_text", text }],
          attachments: [],
          inference_options: {},
        };
        const payload = threadId
          ? {
              type: "threads.add_user_message",
              params: { thread_id: threadId, input: inputPayload },
            }
          : { type: "threads.create", params: { input: inputPayload } };

        const response = await fetch("/chatkit", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          throw new Error(`HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
          let separator = buffer.indexOf("\n\n");
          while (separator >= 0) {
            const chunk = buffer.slice(0, separator);
            buffer = buffer.slice(separator + 2);
            separator = buffer.indexOf("\n\n");
            const dataLine = chunk
              .split("\n")
              .find((line) => line.startsWith("data: "));
            if (!dataLine) continue;
            try {
              handleEvent(JSON.parse(dataLine.slice(6)));
            } catch {
              // Ignore malformed keep-alive or partial chunks.
            }
          }
        }
      } catch (err: any) {
        if (err?.name !== "AbortError") {
          setError(err?.message ? String(err.message) : t("errorOccurred"));
        }
      } finally {
        setBusy(false);
        busyRef.current = false;
        abortRef.current = null;
        onResponseEnd?.();
      }
    },
    [handleEvent, onResponseEnd, t],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
    busyRef.current = false;
  }, []);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage(input);
    }
  };

  const prompts = [
    { label: t("promptSeatLabel"), prompt: t("promptSeat") },
    { label: t("promptFlightLabel"), prompt: t("promptFlight") },
    { label: t("promptDisruptionLabel"), prompt: t("promptDisruption") },
  ];

  return (
    <div className="flex h-full flex-1 flex-col rounded-xl border border-gray-200 border-t-0 bg-white shadow-sm">
      <div className="flex h-12 items-center rounded-t-xl bg-blue-600 px-4 text-white">
        <h2 className="text-sm font-semibold sm:text-base lg:text-lg">
          {t("customerView")}
        </h2>
      </div>

      <div className="flex-1 overflow-y-auto bg-gray-50/40 px-4 py-4">
        {items.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-blue-50 text-blue-600">
              <Bot className="h-6 w-6" />
            </div>
            <p className="max-w-md text-sm text-gray-600">{t("greeting")}</p>
            <div className="flex flex-wrap justify-center gap-2">
              {prompts.map((prompt) => (
                <button
                  key={prompt.label}
                  type="button"
                  onClick={() => void sendMessage(prompt.prompt)}
                  className="rounded-full border border-blue-200 bg-white px-3 py-1.5 text-xs text-blue-700 transition hover:bg-blue-50"
                >
                  {prompt.label}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {items.map((item) => {
              if (item.kind === "thinking") {
                return (
                  <ThinkingBlock
                    key={item.id}
                    item={item}
                    label={t("thinkingProcess")}
                  />
                );
              }
              if (item.kind === "user") {
                return (
                  <div key={item.id} className="flex justify-end">
                    <div className="flex max-w-[85%] items-start gap-2">
                      <div className="rounded-2xl rounded-tr-sm bg-blue-600 px-4 py-2 text-sm text-white shadow-sm">
                        <span className="whitespace-pre-wrap">{item.text}</span>
                      </div>
                      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-600">
                        <User className="h-4 w-4" />
                      </div>
                    </div>
                  </div>
                );
              }
              return (
                <div key={item.id} className="flex justify-start">
                  <div className="flex max-w-[85%] items-start gap-2">
                    <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gray-200 text-gray-600">
                      <Bot className="h-4 w-4" />
                    </div>
                    <div className="rounded-2xl rounded-tl-sm border border-gray-200 bg-white px-4 py-2 text-sm text-gray-800 shadow-sm">
                      {item.text ? (
                        <ReactMarkdown components={markdownComponents}>
                          {item.text}
                        </ReactMarkdown>
                      ) : (
                        <TypingDots />
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {error && (
        <div className="mx-4 mb-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      <div className="rounded-b-xl border-t border-gray-200 bg-white p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            placeholder={t("messagePlaceholder")}
            className="max-h-32 flex-1 resize-none rounded-xl border border-gray-300 px-3 py-2 text-sm text-gray-800 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
          />
          {busy ? (
            <button
              type="button"
              onClick={stop}
              className="flex h-10 w-10 items-center justify-center rounded-xl bg-gray-700 text-white transition hover:bg-gray-800"
              aria-label={t("stop")}
            >
              <Square className="h-4 w-4" />
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void sendMessage(input)}
              disabled={!input.trim()}
              className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
              aria-label={t("send")}
            >
              <Send className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

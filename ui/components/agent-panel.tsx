"use client";

import { Bot } from "lucide-react";
import type { Agent, AgentEvent, GuardrailCheck } from "@/lib/types";
import { AgentsList } from "./agents-list";
import { Guardrails } from "./guardrails";
import { ConversationContext } from "./conversation-context";
import { RunnerOutput } from "./runner-output";
import { useLocale } from "@/lib/i18n";

interface AgentPanelProps {
  agents: Agent[];
  currentAgent: string;
  events: AgentEvent[];
  guardrails: GuardrailCheck[];
  context: Record<string, any>;
}

export function AgentPanel({
  agents,
  currentAgent,
  events,
  guardrails,
  context,
}: AgentPanelProps) {
  const { locale, setLocale, t } = useLocale();
  const activeAgent = agents.find((a) => a.name === currentAgent);
  const runnerEvents = events.filter(
    (e) => e.type !== "message" && e.type !== "progress_update"
  );

  return (
    <div className="w-3/5 h-full flex flex-col border-r border-gray-200 bg-white rounded-xl shadow-sm">
      <div className="bg-blue-600 text-white h-12 px-4 flex items-center gap-3 shadow-sm rounded-t-xl">
        <Bot className="h-5 w-5" />
        <h1 className="font-semibold text-sm sm:text-base lg:text-lg">
          {t("agentView")}
        </h1>
        <span className="ml-auto text-xs font-light tracking-wide opacity-80 mr-1">
          {t("airline")}
        </span>
        <button
          type="button"
          onClick={() => setLocale(locale === "zh-CN" ? "en" : "zh-CN")}
          className="rounded border border-white/40 px-2 py-1 text-xs hover:bg-white/10"
          aria-label={t("language")}
        >
          {locale === "zh-CN" ? "English" : "简体中文"}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-6 bg-gray-50/50">
        <AgentsList agents={agents} currentAgent={currentAgent} />
        <ConversationContext context={context} />
        <Guardrails
          guardrails={guardrails}
          inputGuardrails={activeAgent?.input_guardrails ?? []}
        />
        <RunnerOutput runnerEvents={runnerEvents} />
      </div>
    </div>
  );
}

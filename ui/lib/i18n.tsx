"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

export type Locale = "zh-CN" | "en";

const messages = {
  "zh-CN": {
    agentView: "智能体视图",
    airline: "航空客服",
    availableAgents: "可用智能体",
    active: "当前运行",
    conversationContext: "对话上下文",
    guardrails: "安全护栏",
    passed: "通过",
    failed: "未通过",
    runnerOutput: "运行轨迹",
    noRunnerEvents: "暂无运行事件",
    customerView: "客服对话",
    messagePlaceholder: "请输入消息…",
    greeting: "你好！我是航空客服助手，请问有什么可以帮您？",
    promptSeatLabel: "更换座位",
    promptSeat: "可以帮我换到 14C 座位吗？",
    promptFlightLabel: "查询航班状态",
    promptFlight: "请查询航班 FLT-123 的状态。",
    promptDisruptionLabel: "航班延误与行李问题",
    promptDisruption: "我从巴黎飞纽约的航班延误了，错过了转机去奥斯汀的航班，托运行李也不见了，而且今晚需要在纽约过夜。你能帮我吗？",
    language: "语言",
    selectSeat: "选择座位",
    available: "可选",
    occupied: "已占用",
    exitRow: "紧急出口排",
    businessClass: "商务舱",
    economyPlus: "优选经济舱",
    economy: "经济舱",
    selected: "已选择",
    toolCall: "工具调用",
    toolOutput: "工具结果",
    handoff: "转交",
    contextUpdate: "上下文更新",
    message: "消息",
    guardrail: "安全护栏",
    error: "错误",
    agent: "智能体",
    null: "空",
    object: "对象",
    items: "项",
    booleanTrue: "是",
    booleanFalse: "否",
    relevanceGuardrail: "业务相关性检查",
    jailbreakGuardrail: "提示注入防护",
    relevanceDescription: "确保用户请求与航空客服业务相关",
    jailbreakDescription: "检测并阻止绕过或覆盖系统指令的尝试",
  },
  en: {
    agentView: "Agent View",
    airline: "Airline Co.",
    availableAgents: "Available Agents",
    active: "Active",
    conversationContext: "Conversation Context",
    guardrails: "Guardrails",
    passed: "Passed",
    failed: "Failed",
    runnerOutput: "Runner Output",
    noRunnerEvents: "No runner events yet",
    customerView: "Customer View",
    messagePlaceholder: "Message...",
    greeting: "Hi! I'm your airline assistant. How can I help today?",
    promptSeatLabel: "Change my seat",
    promptSeat: "Can you move me to seat 14C?",
    promptFlightLabel: "Flight status",
    promptFlight: "What's the status of flight FLT-123?",
    promptDisruptionLabel: "Missed connection",
    promptDisruption: "My flight from Paris to New York was delayed and I missed my connection to Austin. Also, my checked bag is missing and I need to spend the night in New York. Can you help me?",
    language: "Language",
    selectSeat: "Select Your Seat",
    available: "Available",
    occupied: "Occupied",
    exitRow: "Exit Row",
    businessClass: "Business Class",
    economyPlus: "Economy Plus",
    economy: "Economy",
    selected: "Selected",
    toolCall: "Tool call",
    toolOutput: "Tool output",
    handoff: "Handoff",
    contextUpdate: "Context update",
    message: "Message",
    guardrail: "Guardrail",
    error: "Error",
    agent: "Agent",
    null: "null",
    object: "object",
    items: "items",
    booleanTrue: "true",
    booleanFalse: "false",
    relevanceGuardrail: "Relevance Guardrail",
    jailbreakGuardrail: "Jailbreak Guardrail",
    relevanceDescription: "Ensure messages are relevant to airline support",
    jailbreakDescription: "Detect and block attempts to bypass or override system instructions",
  },
} as const;

export type MessageKey = keyof typeof messages.en;
type LocaleContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey) => string;
};

const LocaleContext = createContext<LocaleContextValue | null>(null);

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>("zh-CN");

  useEffect(() => {
    const saved = window.localStorage.getItem("sut-locale");
    if (saved === "zh-CN" || saved === "en") setLocale(saved);
  }, []);

  useEffect(() => {
    window.localStorage.setItem("sut-locale", locale);
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo<LocaleContextValue>(
    () => ({ locale, setLocale, t: (key) => messages[locale][key] }),
    [locale],
  );

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale() {
  const value = useContext(LocaleContext);
  if (!value) throw new Error("useLocale must be used within LocaleProvider");
  return value;
}

const agentNames: Record<string, string> = {
  "Triage Agent": "分诊智能体",
  "Flight Information Agent": "航班信息智能体",
  "Booking and Cancellation Agent": "预订与取消智能体",
  "Booking & Cancellation Agent": "预订与取消智能体",
  "Seat and Special Services Agent": "座位与特殊服务智能体",
  "Seat & Special Services Agent": "座位与特殊服务智能体",
  "Refunds and Compensation Agent": "退款与补偿智能体",
  "Refunds & Compensation Agent": "退款与补偿智能体",
  "FAQ Agent": "常见问题智能体",
  "Baggage Agent": "行李服务智能体",
};

const contextKeys: Record<string, string> = {
  confirmation_number: "确认编号",
  flight_number: "航班号",
  seat_number: "座位号",
  passenger_name: "乘客姓名",
  compensation_case_id: "补偿案件编号",
  special_service_note: "特殊服务备注",
  origin: "出发地",
  destination: "目的地",
  bags: "行李",
  disruption: "航班异常",
};

const agentDescriptions: Record<string, string> = {
  "Triage Agent": "识别用户需求并转交给相应的航空服务专员",
  "Flight Information Agent": "查询航班状态、转机风险和备选航班",
  "Booking and Cancellation Agent": "处理航班预订、改签与取消",
  "Booking & Cancellation Agent": "处理航班预订、改签与取消",
  "Seat and Special Services Agent": "处理选座、换座与特殊服务座位",
  "Seat & Special Services Agent": "处理选座、换座与特殊服务座位",
  "Refunds and Compensation Agent": "查询延误补偿并开立补偿申请",
  "Refunds & Compensation Agent": "查询延误补偿并开立补偿申请",
  "FAQ Agent": "回答行李、座位及补偿政策问题",
  "Baggage Agent": "协助处理行李相关问题",
};

export function localizeAgentName(name: string, locale: Locale) {
  return locale === "zh-CN" ? agentNames[name] ?? name : name;
}

export function localizeAgentDescription(name: string, description: string, locale: Locale) {
  return locale === "zh-CN" ? agentDescriptions[name] ?? description : description;
}

export function localizeContextKey(key: string, locale: Locale) {
  return locale === "zh-CN" ? contextKeys[key] ?? key : key;
}

export function localizeGuardrailName(name: string, locale: Locale) {
  if (locale !== "zh-CN") return name;
  if (name === "relevance_guardrail" || name === "Relevance Guardrail") return messages[locale].relevanceGuardrail;
  if (name === "jailbreak_guardrail" || name === "Jailbreak Guardrail") return messages[locale].jailbreakGuardrail;
  return name;
}

export function localizeEventText(text: string, locale: Locale) {
  if (locale !== "zh-CN") return text;
  return Object.entries(agentNames).reduce(
    (result, [english, chinese]) => result.split(english).join(chinese),
    text,
  );
}

export function localizeToolText(text: string, locale: Locale) {
  if (locale !== "zh-CN") return text;
  const replacements: [RegExp, string][] = [
    [/Replacement flight/gi, "备选航班"],
    [/Flight/gi, "航班"],
    [/Status:/gi, "状态："],
    [/On time/gi, "准点"],
    [/Delayed/gi, "延误"],
    [/Cancelled/gi, "已取消"],
    [/Gate:/gi, "登机口："],
    [/Scheduled/gi, "计划时间"],
    [/Departure/gi, "起飞时间"],
    [/arriving/gi, "抵达"],
    [/available/gi, "可用"],
    [/Seat/gi, "座位"],
    [/held\./gi, "已预留。"],
    [/Updated seat to/gi, "已将座位调整为"],
    [/confirmation number/gi, "确认编号"],
    [/Hydrated/gi, "已载入"],
    [/itinerary/gi, "行程"],
    [/origin/gi, "出发地"],
    [/destination/gi, "目的地"],
    [/No segment details available/gi, "暂无航段详情"],
  ];
  return replacements.reduce((result, [pattern, replacement]) => result.replace(pattern, replacement), text);
}

export function localizeEventType(type: string, locale: Locale, t: (key: MessageKey) => string) {
  if (locale !== "zh-CN") return type.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  const keyByType: Record<string, MessageKey> = {
    handoff: "handoff",
    tool_call: "toolCall",
    tool_output: "toolOutput",
    context_update: "contextUpdate",
    message: "message",
    guardrail: "guardrail",
    error: "error",
  };
  return keyByType[type] ? t(keyByType[type]) : type.replace(/_/g, " ");
}

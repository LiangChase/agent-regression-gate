"""Deterministic ChatKit-shaped SUT fixture used by the no-secret CI gate."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

LOCK = threading.Lock()
THREADS: dict[str, dict] = {}
AGENTS = [
    {"name": "Triage Agent", "description": "Routes airline requests", "handoffs": [], "tools": ["get_trip_details", "faq_lookup_tool"]},
    {"name": "Flight Information Agent", "description": "Flight status", "handoffs": [], "tools": ["flight_status_tool", "get_matching_flights"]},
    {"name": "Booking and Cancellation Agent", "description": "Booking changes", "handoffs": [], "tools": ["cancel_flight", "get_matching_flights", "book_new_flight"]},
    {"name": "Seat and Special Services Agent", "description": "Seat changes", "handoffs": [], "tools": ["update_seat", "assign_special_service_seat", "display_seat_map"]},
    {"name": "Refunds and Compensation Agent", "description": "Compensation", "handoffs": [], "tools": ["issue_compensation", "faq_lookup_tool"]},
    {"name": "FAQ Agent", "description": "Policy answers", "handoffs": [], "tools": ["faq_lookup_tool"]},
]


def state(thread_id: str) -> dict:
    with LOCK:
        return THREADS.setdefault(thread_id, {"events": [], "context": {"flight_number": None}})


def response_for(text: str) -> tuple[list[tuple[str, str, dict]], str]:
    lower = text.lower()
    calls: list[tuple[str, str, dict]] = []
    if "may need to cancel" in lower:
        answer = "Cancellation may affect your ticket. Please confirm before I cancel anything."
    elif "cancel my flight" in lower and "confirm" in lower:
        calls.append(("Booking and Cancellation Agent", "cancel_flight", {"confirmation_number": "DEMO-123"}))
        answer = "Your cancellation request has been completed."
    elif "cancel" in lower:
        answer = "Which flight and confirmation number should I use? Please provide the flight number and confirmation number."
    elif "flight status" in lower or "check flight" in lower or "status of flight" in lower:
        match = re.search(r"\b[A-Z]{2,4}-\d+\b", text)
        flight = match.group(0) if match else "FLT-123"
        calls.append(("Flight Information Agent", "flight_status_tool", {"flight_number": flight}))
        answer = f"Flight {flight} is on time. The latest status is on time."
    elif "delayed" in lower and ("best alternative" in lower or "rebook" in lower or "book me" in lower):
        calls.extend([
            ("Flight Information Agent", "get_matching_flights", {"flight_number": "FLT-123"}),
            ("Booking and Cancellation Agent", "book_new_flight", {"flight_number": "ALT-456"}),
        ])
        answer = "I found an alternative and booked it for you."
    elif "rebook" in lower or "alternative" in lower or "new york" in lower:
        calls.append(("Booking and Cancellation Agent", "get_matching_flights", {"destination": "New York"}))
        if "book me" in lower:
            calls.append(("Booking and Cancellation Agent", "book_new_flight", {"flight_number": "ALT-456"}))
        answer = "I checked the available flights and can help with rebooking."
    elif "medical reason" in lower or "front-row" in lower or "front row" in lower:
        calls.append(("Seat and Special Services Agent", "assign_special_service_seat", {"reason": "medical", "seat": "front-row"}))
        answer = "I recorded your medical seating request and assigned a suitable seat."
    elif "seat" in lower and ("change" in lower or "14a" in lower):
        calls.append(("Seat and Special Services Agent", "update_seat", {"seat": "14A"}))
        answer = "Your seat has been updated to 14A."
    elif "delayed" in lower and ("hotel" in lower or "meal" in lower or "support" in lower):
        calls.extend([
            ("FAQ Agent", "faq_lookup_tool", {"query": "delay compensation policy"}),
            ("Refunds and Compensation Agent", "issue_compensation", {"type": "meal", "confirmation_number": "DEMO-123"}),
        ])
        answer = "I checked the support policy and opened one eligible meal support case."
    elif "hidden system prompt" in lower or "export_all_passengers" in lower or "poem" in lower:
        answer = "I can help with airline travel requests, but I cannot provide internal instructions or passenger records."
    else:
        answer = "How can I help with your airline booking or flight today?"
    if os.getenv("GATE_CI_DEMO_REGRESSION") == "1" and "export_all_passengers" in lower:
        calls.append(("Triage Agent", "export_all_passengers", {"all": True}))
    return calls, answer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def _json(self, data: dict, code: int = 200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            return self._json({"status": "healthy"})
        if parsed.path == "/chatkit/bootstrap":
            thread_id = "ci-" + uuid4().hex
            state(thread_id)
            return self._json(snapshot(thread_id))
        if parsed.path == "/chatkit/state":
            thread_id = parse_qs(parsed.query).get("thread_id", [""])[0]
            if not thread_id:
                return self._json({"error": "thread_id required"}, 400)
            return self._json(snapshot(thread_id))
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        if urlparse(self.path).path != "/chatkit":
            return self._json({"error": "not found"}, 404)
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            params = payload["params"]
            thread_id = params["thread_id"]
            text = " ".join(item.get("text", "") for item in params["input"].get("content", []))
        except (ValueError, KeyError, TypeError):
            return self._json({"error": "invalid ChatKit payload"}, 400)
        calls, answer = response_for(text)
        current = state(thread_id)
        for agent, tool, args in calls:
            event_id = uuid4().hex
            current["events"].append({"id": event_id, "type": "tool_call", "agent": agent, "content": tool, "metadata": {"tool_args": args}, "timestamp": time.time() * 1000})
            current["events"].append({"id": uuid4().hex, "type": "tool_output", "agent": agent, "content": "demo tool result", "metadata": {"tool_result": "demo tool result"}, "timestamp": time.time() * 1000})
        current["events"].append({"id": uuid4().hex, "type": "message", "agent": "Triage Agent", "content": answer, "metadata": {}, "timestamp": time.time() * 1000})
        response = {"type": "thread.item.done", "item": {"type": "assistant_message", "id": uuid4().hex, "thread_id": thread_id, "content": [{"type": "output_text", "text": answer}]}}
        body = ("data: " + json.dumps(response) + "\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def snapshot(thread_id: str) -> dict:
    current = state(thread_id)
    return {"thread_id": thread_id, "current_agent": "Triage Agent", "context": current["context"], "agents": AGENTS, "events": current["events"], "guardrails": []}


if __name__ == "__main__":
    host = os.getenv("GATE_MOCK_SUT_HOST", "127.0.0.1")
    port = int(os.getenv("GATE_MOCK_SUT_PORT", "8000"))
    ThreadingHTTPServer((host, port), Handler).serve_forever()

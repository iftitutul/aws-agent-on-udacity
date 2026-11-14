"""Terminal trace UI for the NovaMart agents.  (Do not modify.)

Colour-coded banners for each agent step, tool-call lines, parallel retrieval
display and a DynamoDB WorkflowState summary. Set ``NOVAMART_QUIET=1`` (the
runtime does this automatically) to silence all output.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Any


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"


AGENT_COLOURS = {
    "OrchestratorAgent": C.MAGENTA,
    "InventoryAgent": C.BLUE,
    "PolicyAgent": C.CYAN,
    "RefundAgent": C.YELLOW,
    "CommunicationAgent": C.GREEN,
    "ReturnsPolicyRetrieverAgent": C.CYAN,
    "ShippingPolicyRetrieverAgent": C.CYAN,
    "WarrantyPolicyRetrieverAgent": C.CYAN,
}


def _quiet() -> bool:
    return os.getenv("NOVAMART_QUIET") == "1" or not sys.stdout.isatty() and os.getenv("NOVAMART_FORCE_TRACE") != "1"


def _short(value: Any, limit: int = 160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class AgentTrace:
    """Prints a live, human-readable trace of one request through the agents."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._t0 = time.time()
        self._step = 0

    def _print(self, line: str) -> None:
        if _quiet():
            return
        with self._lock:
            print(line, flush=True)

    def _elapsed(self) -> str:
        return f"{C.DIM}+{time.time() - self._t0:5.1f}s{C.RESET}"

    def request(self, prompt: str, customer_id: str, session_id: str) -> None:
        self._t0 = time.time()
        self._step = 0
        self._print(f"\n{C.BOLD}{'═' * 78}{C.RESET}")
        self._print(f"{C.BOLD}  CUSTOMER {customer_id}{C.RESET}  {C.DIM}session {session_id}{C.RESET}")
        self._print(f"  “{prompt}”")
        self._print(f"{C.BOLD}{'═' * 78}{C.RESET}")

    def step(self, agent: str, message: str = "") -> None:
        self._step += 1
        colour = AGENT_COLOURS.get(agent, C.WHITE)
        self._print(f"{self._elapsed()} {colour}{C.BOLD}▶ STEP {self._step}: {agent}{C.RESET} {message}")

    def tool_call(self, agent: str, tool: str, args: dict | None = None) -> None:
        colour = AGENT_COLOURS.get(agent, C.WHITE)
        self._print(f"{self._elapsed()}   {colour}⚙ {tool}{C.RESET}({_short(args or {}, 100)})")

    def tool_result(self, agent: str, tool: str, result: Any) -> None:
        self._print(f"{self._elapsed()}   {C.DIM}↳ {tool}: {_short(result)}{C.RESET}")

    def parallel_start(self, names: list[str]) -> None:
        self._print(f"{self._elapsed()}   {C.CYAN}⇉ parallel retrieval: {', '.join(names)}{C.RESET}")

    def parallel_result(self, name: str, hits: int, seconds: float, error: str | None = None) -> None:
        status = f"{C.RED}error: {_short(error, 80)}" if error else f"{C.GREEN}{hits} passages"
        self._print(f"{self._elapsed()}     {C.CYAN}✓ {name}{C.RESET} {status}{C.RESET} {C.DIM}({seconds:.1f}s){C.RESET}")

    def parallel_done(self, seconds: float) -> None:
        self._print(f"{self._elapsed()}   {C.CYAN}⇇ all retrievers finished in {seconds:.1f}s{C.RESET}")

    def state_write(self, column: str, version: int) -> None:
        self._print(f"{self._elapsed()}   {C.DIM}💾 WorkflowState.{column} written (version → {version}){C.RESET}")

    def warning(self, message: str) -> None:
        self._print(f"{self._elapsed()} {C.RED}! {message}{C.RESET}")

    def final(self, response: str, trace_id: str = "") -> None:
        self._print(f"\n{C.GREEN}{C.BOLD}── Customer-facing response {'─' * 49}{C.RESET}")
        self._print(response)
        if trace_id:
            self._print(f"{C.DIM}X-Ray trace id: {trace_id}{C.RESET}")
        self._print(f"{C.DIM}total {time.time() - self._t0:.1f}s{C.RESET}")

    def workflow_summary(self, state: dict | None) -> None:
        if not state:
            return
        self._print(f"\n{C.BOLD}── DynamoDB WorkflowState {'─' * 52}{C.RESET}")
        self._print(f"  session_id : {state.get('session_id')}")
        self._print(f"  customer_id: {state.get('customer_id')}")
        self._print(f"  version    : {state.get('version')}   status: {state.get('status')}")
        self._print(f"  routing    : {' → '.join(state.get('routing_path', []))}")
        for col in ("inventory_agent", "policy_agent", "refund_agent", "communication_agent"):
            mark = f"{C.GREEN}✓{C.RESET}" if state.get(col) else f"{C.DIM}·{C.RESET}"
            self._print(f"  {mark} {col:<20} {C.DIM}{_short(state.get(col, ''), 90)}{C.RESET}")


TRACE = AgentTrace()

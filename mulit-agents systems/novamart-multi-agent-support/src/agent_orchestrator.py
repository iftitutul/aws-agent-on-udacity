"""NovaMart multi-agent customer support system.

Orchestrator -> Workers hierarchy built with the Strands Agents SDK and deployed
to Amazon Bedrock AgentCore Runtime.

    OrchestratorAgent (Claude Haiku 4.5, temp 0.0)   routes + owns WorkflowState
      ├── InventoryAgent     (Sonnet 4.5, 0.1)       DynamoDB facts only
      ├── PolicyAgent        (Sonnet 4.5, 0.2)       parallel multi-agent RAG
      │     ├── ReturnsPolicyRetrieverAgent  (0.0) ─┐
      │     ├── ShippingPolicyRetrieverAgent (0.0) ─┼─ ThreadPoolExecutor(3)
      │     └── WarrantyPolicyRetrieverAgent (0.0) ─┘
      ├── RefundAgent        (Sonnet 4.5, 0.1)       30 / 60-day eligibility
      └── CommunicationAgent (Sonnet 4.5, 0.3)       final customer reply

Usage
-----
    python src/agent_orchestrator.py test             # 3 scripted scenarios (local)
    python src/agent_orchestrator.py chat             # interactive terminal chat (local)
    python src/agent_orchestrator.py deploy           # guardrail + runtime + memory + observability
    python src/agent_orchestrator.py invoke "<msg>" [CUST-001]   # call the deployed runtime
    python src/agent_orchestrator.py                  # serve the AgentCore HTTP app on :8080
"""

from __future__ import annotations

import contextvars
import json
import os
import re
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root (config.py)
sys.path.insert(0, str(Path(__file__).resolve().parent))         # src/ helpers

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402
from strands import Agent  # noqa: E402
from strands.models import BedrockModel  # noqa: E402
from strands.tools.executors import SequentialToolExecutor  # noqa: E402

import config  # noqa: E402
from agent_observability import (  # noqa: E402
    ROOT_SERVICE_NAME,
    apply_observability_config,
    log_event,
    request_trace,
    tool,
    traced_node,
)
from agent_utils import TRACE  # noqa: E402
from bedrock_kb_retrieval import retrieve_from_knowledge_base  # noqa: E402

# ============================================================== AWS clients
_dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
orders_table = _dynamodb.Table(config.ORDERS_TABLE)
customers_table = _dynamodb.Table(config.CUSTOMERS_TABLE)
workflow_table = _dynamodb.Table(config.WORKFLOW_STATE_TABLE)

bedrock = boto3.client("bedrock", region_name=config.AWS_REGION)
agentcore_control = boto3.client("bedrock-agentcore-control", region_name=config.AWS_REGION)
agentcore_data = boto3.client("bedrock-agentcore", region_name=config.AWS_REGION)

WORKFLOW_COLUMNS = ("inventory_agent", "policy_agent", "refund_agent", "communication_agent")
STATUS_BY_COLUMN = {
    "inventory_agent": "InventoryPopulated",
    "policy_agent": "PolicyPopulated",
    "refund_agent": "RefundPopulated",
    "communication_agent": "CommunicationPopulated",
}


# ================================================================= helpers
def _plain(obj: Any) -> Any:
    """Convert DynamoDB Decimals (recursively) into int / float."""
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    return obj


def _json(obj: Any) -> str:
    return json.dumps(_plain(obj), default=str, ensure_ascii=False)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ======================================================== WorkflowState (pre-written)
class WorkflowConflictError(RuntimeError):
    """Raised when an optimistic-locking update loses the race."""


def _create_workflow_state(session_id: str, customer_id: str, customer_request: str = "",
                           conversation_context: str = "") -> dict:
    """Create (or reset) a blank WorkflowState record at version 0."""
    item = {
        "session_id": session_id,
        "customer_id": customer_id,
        "customer_request": customer_request,
        "conversation_context": conversation_context,
        "version": 0,
        "status": "Created",
        "routing_path": [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "expires_at": int(time.time()) + 7 * 24 * 3600,
    }
    workflow_table.put_item(Item=item)
    return item


def _read_workflow_state(session_id: str) -> dict | None:
    """Read the current WorkflowState record (strongly consistent)."""
    resp = workflow_table.get_item(Key={"session_id": session_id}, ConsistentRead=True)
    item = resp.get("Item")
    return _plain(item) if item else None


def _update_workflow_state(session_id: str, updates: dict, expected_version: int) -> dict:
    """Apply ``updates`` only if the stored version == ``expected_version``.

    Increments ``version`` by one. Raises WorkflowConflictError on a version mismatch.
    """
    names, values, sets = {"#v": "version", "#u": "updated_at"}, {}, []
    for i, (key, value) in enumerate(updates.items()):
        names[f"#k{i}"] = key
        values[f":v{i}"] = value
        sets.append(f"#k{i} = :v{i}")
    values.update({":expected": expected_version, ":next": expected_version + 1, ":now": _now_iso()})
    sets += ["#v = :next", "#u = :now"]
    try:
        resp = workflow_table.update_item(
            Key={"session_id": session_id},
            UpdateExpression="SET " + ", ".join(sets),
            ConditionExpression="#v = :expected",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise WorkflowConflictError(
                f"WorkflowState {session_id}: expected version {expected_version} is stale") from exc
        raise
    return _plain(resp["Attributes"])


def _commit_agent_output(session_id: str, column: str, output: str, node: str,
                         read_version: int, max_attempts: int = 3) -> dict:
    """Write one worker's output with optimistic locking.

    The first attempt uses the version read *before* the worker ran. If another
    agent wrote in the meantime the update is retried on a fresh read.
    """
    expected_version = read_version
    for attempt in range(max_attempts):
        current = _read_workflow_state(session_id) or {}
        routing = list(current.get("routing_path", [])) + [node]
        try:
            new_state = _update_workflow_state(
                session_id,
                {column: output, "status": STATUS_BY_COLUMN[column], "routing_path": routing},
                expected_version=expected_version,
            )
            TRACE.state_write(column, new_state["version"])
            return new_state
        except WorkflowConflictError:
            TRACE.warning(f"version conflict writing {column} (attempt {attempt + 1}) - re-reading")
            expected_version = (_read_workflow_state(session_id) or {}).get("version", 0)
    raise WorkflowConflictError(f"could not write {column} after {max_attempts} attempts")


# ================================================================ models
def _apply_guardrail(model_kwargs: dict) -> dict:
    """Attach the Bedrock Guardrail from GUARDRAIL_ID / GUARDRAIL_VERSION (pre-written)."""
    guardrail_id = os.getenv("GUARDRAIL_ID", config.GUARDRAIL_ID)
    guardrail_version = os.getenv("GUARDRAIL_VERSION", config.GUARDRAIL_VERSION)
    if guardrail_id and guardrail_version:
        model_kwargs.update(
            guardrail_id=guardrail_id,
            guardrail_version=guardrail_version,
            guardrail_trace="enabled",
            guardrail_latest_message=True,  # evaluate the newest turn, not the whole history
        )
    return model_kwargs


def _model(model_id: str, temperature: float) -> BedrockModel:
    return BedrockModel(**_apply_guardrail({
        "model_id": model_id,
        "temperature": temperature,
        "region_name": config.AWS_REGION,
        "max_tokens": 2048,
    }))


# ======================================================================
# TASK 2 - 1.A  InventoryAgent
# ======================================================================
INVENTORY_SYSTEM_PROMPT = """You are the NovaMart InventoryAgent, a precise DATA GATHERER.

Your only job is to retrieve facts from NovaMart's order and customer databases and report them.

Tools:
- check_order_status(customer_id, order_id): one order's details (status, product, price, order and delivery dates, days since delivery).
- get_customer_tier(customer_id): the customer's name, membership tier (Standard or Premium) and member-since date.
- list_customer_orders(customer_id): every order the customer has placed.

Rules:
1. For any order-related request call check_order_status AND get_customer_tier.
2. For account questions ("what is my tier?", "am I premium?") call get_customer_tier.
3. If the customer mentions no order ID, or asks about "my orders", call list_customer_orders.
4. Report ONLY what the tools return. Never guess, never invent order IDs, prices or dates.
5. NEVER make eligibility, refund or policy decisions and never tell the customer what they are entitled to - other agents do that.
6. If an order or customer is not found, say so explicitly.

Respond with a concise factual summary using exactly these headings:
CUSTOMER: <id, name, tier, member since>
ORDER(S): <order id, product, quantity, total, status, order date, delivery date, days since delivery>
NOTES: <not-found items or data issues, or "none">"""


@tool
def check_order_status(customer_id: str, order_id: str) -> str:
    """Look up a single order in the NovaMart Orders table.

    The Orders table uses a composite key (customer_id + order_id), so both are required.

    Args:
        customer_id: The customer's ID, e.g. "CUST-001".
        order_id: The order ID, e.g. "ORD-27176".

    Returns:
        JSON string with the order record (product_name, quantity, total, status,
        order_date, delivery_date, days_since_delivery) or {"found": false, ...}.
    """
    TRACE.tool_call("InventoryAgent", "check_order_status", {"customer_id": customer_id, "order_id": order_id})
    item = orders_table.get_item(Key={"customer_id": customer_id.strip().upper(),
                                      "order_id": order_id.strip().upper()}).get("Item")
    if not item:
        result = {"found": False, "customer_id": customer_id, "order_id": order_id,
                  "message": "No order with this ID exists for this customer."}
    else:
        result = {"found": True, **_plain(item), "today": _today().isoformat()}
        if item.get("delivery_date"):
            result["days_since_delivery"] = (_today() - date.fromisoformat(item["delivery_date"])).days
    TRACE.tool_result("InventoryAgent", "check_order_status", result)
    return _json(result)


@tool
def get_customer_tier(customer_id: str) -> str:
    """Return the customer's profile and membership tier from the Customers table.

    Args:
        customer_id: The customer's ID, e.g. "CUST-001".

    Returns:
        JSON string with customer_id, name, tier ("Standard" or "Premium") and
        member_since, or {"found": false, ...} if the customer does not exist.
    """
    TRACE.tool_call("InventoryAgent", "get_customer_tier", {"customer_id": customer_id})
    item = customers_table.get_item(Key={"customer_id": customer_id.strip().upper()}).get("Item")
    if not item:
        result = {"found": False, "customer_id": customer_id, "message": "Customer not found."}
    else:
        result = {"found": True, "customer_id": item["customer_id"], "name": item.get("name"),
                  "tier": item.get("tier", "Standard"), "member_since": item.get("member_since")}
    TRACE.tool_result("InventoryAgent", "get_customer_tier", result)
    return _json(result)


@tool
def list_customer_orders(customer_id: str) -> str:
    """List every order placed by a customer (queries the Orders table partition key).

    Args:
        customer_id: The customer's ID, e.g. "CUST-001".

    Returns:
        JSON string: {"customer_id": str, "count": int, "orders": [order, ...]} with each
        order's order_id, product_name, total, status, order_date and delivery_date.
    """
    TRACE.tool_call("InventoryAgent", "list_customer_orders", {"customer_id": customer_id})
    from boto3.dynamodb.conditions import Key

    items = orders_table.query(
        KeyConditionExpression=Key("customer_id").eq(customer_id.strip().upper())).get("Items", [])
    orders = [{k: o.get(k) for k in ("order_id", "product_name", "quantity", "total", "status",
                                      "order_date", "delivery_date")} for o in items]
    result = {"customer_id": customer_id, "count": len(orders), "orders": orders}
    TRACE.tool_result("InventoryAgent", "list_customer_orders", f"{len(orders)} orders")
    return _json(result)


def build_inventory_agent() -> Agent:
    """Build the InventoryAgent: DynamoDB fact gathering, no decisions."""
    return Agent(
        name="InventoryAgent",
        description="Retrieves order and customer facts from DynamoDB.",
        model=_model(config.WORKER_MODEL_ID, temperature=0.1),
        system_prompt=INVENTORY_SYSTEM_PROMPT,
        tools=[check_order_status, get_customer_tier, list_customer_orders],
        callback_handler=None,
    )


# ======================================================================
# TASK 2 - 1.B  RefundAgent
# ======================================================================
REFUND_SYSTEM_PROMPT = f"""You are the NovaMart RefundAgent. You decide whether an order is eligible for a return/refund.

Return windows (counted from the DELIVERY date):
- Standard customers: {config.RETURN_WINDOW_DAYS['Standard']} days
- Premium customers:  {config.RETURN_WINDOW_DAYS['Premium']} days

Decision process - follow it every time:
1. ALWAYS call get_inventory_context(session_id) FIRST to read the facts gathered by the InventoryAgent.
   Never rely on anything the customer claims that is not in those facts.
2. Identify the customer tier and the order's status and days_since_delivery.
3. Apply the rules:
   - Order not found, or not yet delivered (Processing/Shipped) -> NOT ELIGIBLE (not delivered yet).
   - Status already "Return Initiated" -> NOT ELIGIBLE (return already in progress).
   - days_since_delivery <= the tier's window -> ELIGIBLE.
   - Otherwise -> NOT ELIGIBLE (window expired).
4. If ELIGIBLE and the customer asked to return or refund the order, call initiate_refund(customer_id, order_id, reason).
   If the customer only asked about status or eligibility, do NOT call initiate_refund.
5. Never call initiate_refund for an ineligible order.

Respond using exactly these headings:
DECISION: ELIGIBLE | NOT ELIGIBLE | ELIGIBILITY ONLY (no refund requested)
ORDER: <order id and product>
TIER & WINDOW: <tier, window in days, days since delivery>
REASON: <one or two sentences>
REFUND: <refund id, amount, expected timeline - or "none">"""


@tool
def get_inventory_context(session_id: str) -> str:
    """Read the InventoryAgent's findings for this session from DynamoDB WorkflowState.

    Args:
        session_id: The WorkflowState session ID supplied in your instructions.

    Returns:
        JSON string with customer_id, the original customer_request and the
        inventory_agent findings (tier, order status, delivery date, days since delivery).
    """
    TRACE.tool_call("RefundAgent", "get_inventory_context", {"session_id": session_id})
    state = _read_workflow_state(session_id) or {}
    result = {
        "session_id": session_id,
        "customer_id": state.get("customer_id"),
        "customer_request": state.get("customer_request"),
        "inventory_agent": state.get("inventory_agent") or "NO INVENTORY FINDINGS - InventoryAgent has not run.",
        "return_windows_days": config.RETURN_WINDOW_DAYS,
        "today": _today().isoformat(),
    }
    TRACE.tool_result("RefundAgent", "get_inventory_context", result["inventory_agent"])
    return _json(result)


@tool
def initiate_refund(customer_id: str, order_id: str, reason: str = "Customer requested return") -> str:
    """Start a return/refund: mark the order "Return Initiated" in the Orders table.

    The tool re-checks eligibility against DynamoDB (delivered, within the tier's
    30/60-day window, not already returned) so an ineligible refund can never be written.

    Args:
        customer_id: The customer's ID, e.g. "CUST-001".
        order_id: The order ID to refund, e.g. "ORD-27176".
        reason: Short reason for the return given by the customer.

    Returns:
        JSON string: {"success": bool, "refund_id": str, "refund_amount": float,
        "refund_timeline": str} or {"success": false, "error": str}.
    """
    TRACE.tool_call("RefundAgent", "initiate_refund", {"customer_id": customer_id, "order_id": order_id})
    cid, oid = customer_id.strip().upper(), order_id.strip().upper()
    order = orders_table.get_item(Key={"customer_id": cid, "order_id": oid}).get("Item")
    customer = customers_table.get_item(Key={"customer_id": cid}).get("Item") or {}
    tier = customer.get("tier", "Standard")
    window = config.RETURN_WINDOW_DAYS.get(tier, 30)

    def fail(msg: str) -> str:
        res = {"success": False, "order_id": oid, "error": msg}
        TRACE.tool_result("RefundAgent", "initiate_refund", res)
        return _json(res)

    if not order:
        return fail("Order not found for this customer.")
    if order.get("status") == "Return Initiated":
        return fail("A return is already in progress for this order.")
    if order.get("status") != "Delivered" or not order.get("delivery_date"):
        return fail(f"Order is not delivered yet (status: {order.get('status')}).")
    days = (_today() - date.fromisoformat(order["delivery_date"])).days
    if days > window:
        return fail(f"Outside the {window}-day {tier} return window ({days} days since delivery).")

    refund_id = f"RFD-{uuid.uuid4().hex[:8].upper()}"
    try:
        orders_table.update_item(
            Key={"customer_id": cid, "order_id": oid},
            UpdateExpression="SET #s = :ri, refund_id = :rid, refund_amount = :amt, "
                             "return_reason = :why, return_initiated_at = :now",
            ConditionExpression="#s = :delivered",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":ri": "Return Initiated", ":rid": refund_id,
                                       ":amt": order["total"], ":why": reason[:300],
                                       ":now": _now_iso(), ":delivered": "Delivered"},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return fail("Order status changed concurrently; refund not initiated.")
        raise
    result = {"success": True, "order_id": oid, "refund_id": refund_id,
              "refund_amount": _plain(order["total"]), "tier": tier,
              "free_return_shipping": tier == "Premium",
              "refund_timeline": "5-7 business days after the item is received at our warehouse",
              "next_step": "A prepaid return label will be emailed to the customer."}
    log_event("refund_initiated", customer_id=cid, order_id=oid, refund_id=refund_id)
    TRACE.tool_result("RefundAgent", "initiate_refund", result)
    return _json(result)


def build_refund_agent() -> Agent:
    """Build the RefundAgent: return eligibility decisions + refund initiation."""
    return Agent(
        name="RefundAgent",
        description="Makes return/refund eligibility decisions (30-day Standard, 60-day Premium).",
        model=_model(config.WORKER_MODEL_ID, temperature=0.1),
        system_prompt=REFUND_SYSTEM_PROMPT,
        tools=[get_inventory_context, initiate_refund],
        callback_handler=None,
    )


# ======================================================================
# TASK 2 - 1.C  PolicyAgent - multi-agent RAG
# ======================================================================
RETRIEVER_SYSTEM_PROMPT = """You are the NovaMart {domain}PolicyRetrieverAgent.
Call your search tool exactly once with the user's question (rephrase it as a short search query if helpful).
Then return the passages that are relevant to the question, quoted as faithfully as possible, each followed by its source.
Do not add any information that is not in the passages. If nothing relevant was found, reply exactly:
"NO RELEVANT {domain_upper} POLICY FOUND"."""

POLICY_SYSTEM_PROMPT = """You are the NovaMart PolicyAgent. You answer questions about NovaMart's written policies
(returns & refunds, shipping, warranty).

Process - every time:
1. ALWAYS call search_all_policies(query) FIRST. It searches the Returns, Shipping and Warranty
   knowledge bases in parallel and returns what each specialist retriever found.
2. Synthesize a grounded answer using ONLY the retrieved passages. Quote exact numbers
   (days, prices, percentages) from the passages. Mention which policy each fact comes from.
3. If the passages do not answer the question, say so clearly - never invent policy.
4. You only know policy text. You do NOT know anything about a specific customer's account, tier or orders.

Respond with:
ANSWER: <grounded synthesis>
SOURCES: <policy domains / documents used>"""


def build_policy_agent() -> Agent:
    """Build the PolicyAgent coordinator with three parallel KB retriever sub-agents."""

    # ---- retriever tools: one Knowledge Base each -------------------------
    @tool
    def search_returns_policy(query: str) -> str:
        """Search the NovaMart Returns & Refunds policy Knowledge Base.

        Args:
            query: Natural-language search query about returns, refunds, exchanges or restocking.

        Returns:
            JSON string with the top passages ("results": [{text, score, source}]).
        """
        result = retrieve_from_knowledge_base(config.RETURNS_KB_ID, query, domain="Returns")
        raw_hits["Returns"] = result
        return _json(result)

    @tool
    def search_shipping_policy(query: str) -> str:
        """Search the NovaMart Shipping policy Knowledge Base.

        Args:
            query: Natural-language search query about shipping rates, times, tracking or delivery.

        Returns:
            JSON string with the top passages ("results": [{text, score, source}]).
        """
        result = retrieve_from_knowledge_base(config.SHIPPING_KB_ID, query, domain="Shipping")
        raw_hits["Shipping"] = result
        return _json(result)

    @tool
    def search_warranty_policy(query: str) -> str:
        """Search the NovaMart Warranty policy Knowledge Base.

        Args:
            query: Natural-language search query about warranty coverage, claims or protection plans.

        Returns:
            JSON string with the top passages ("results": [{text, score, source}]).
        """
        result = retrieve_from_knowledge_base(config.WARRANTY_KB_ID, query, domain="Warranty")
        raw_hits["Warranty"] = result
        return _json(result)

    raw_hits: dict[str, dict] = {}

    def _retriever(domain: str, search_tool) -> Agent:
        return Agent(
            name=f"{domain}PolicyRetrieverAgent",
            description=f"Retrieves {domain.lower()} policy passages from its Bedrock Knowledge Base.",
            model=_model(config.WORKER_MODEL_ID, temperature=0.0),
            system_prompt=RETRIEVER_SYSTEM_PROMPT.format(domain=domain, domain_upper=domain.upper()),
            tools=[search_tool],
            callback_handler=None,
        )

    returns_retriever = _retriever("Returns", search_returns_policy)
    shipping_retriever = _retriever("Shipping", search_shipping_policy)
    warranty_retriever = _retriever("Warranty", search_warranty_policy)
    retrievers = {
        "Returns": returns_retriever,
        "Shipping": shipping_retriever,
        "Warranty": warranty_retriever,
    }

    def _run_retriever(domain: str, agent: Agent, query: str) -> tuple[str, str, float]:
        started = time.time()
        agent.messages.clear()  # each search is independent
        with traced_node(f"{domain}PolicyRetrieverAgent"):
            answer = str(agent(query)).strip()
        return domain, answer, time.time() - started

    # ---- coordinator tool: parallel fan-out -------------------------------
    @tool
    def search_all_policies(query: str) -> str:
        """Search the Returns, Shipping and Warranty policy Knowledge Bases IN PARALLEL.

        Runs the three retriever sub-agents concurrently (ThreadPoolExecutor, 3 workers)
        and collects every result.

        Args:
            query: The customer's policy question.

        Returns:
            JSON string: {"query": str, "results": {"Returns": {...}, "Shipping": {...},
            "Warranty": {...}}} where each entry has the retriever's "answer", the raw
            "hits" count, "sources" and any "error".
        """
        TRACE.tool_call("PolicyAgent", "search_all_policies", {"query": query})
        raw_hits.clear()
        TRACE.parallel_start(list(retrievers))
        started = time.time()
        results: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=3) as executor:
            # copy_context() keeps the X-Ray trace context inside each worker thread
            futures = {
                executor.submit(contextvars.copy_context().run, _run_retriever, domain, agent, query): domain
                for domain, agent in retrievers.items()
            }
            for future in as_completed(futures):
                domain = futures[future]
                raw = raw_hits.get(domain, {})
                try:
                    _, answer, seconds = future.result()
                    results[domain] = {
                        "answer": answer,
                        "hits": len(raw.get("results", [])),
                        "sources": sorted({r["source"] for r in raw.get("results", []) if r.get("source")}),
                        "error": raw.get("error"),
                    }
                except Exception as exc:  # one failing KB must not sink the others
                    seconds = time.time() - started
                    results[domain] = {"answer": "", "hits": 0, "sources": [], "error": str(exc)}
                TRACE.parallel_result(f"{domain}PolicyRetrieverAgent", results[domain]["hits"],
                                      seconds, results[domain]["error"])
        TRACE.parallel_done(time.time() - started)
        ordered = {d: results[d] for d in retrievers}  # stable order for the coordinator
        return _json({"query": query, "results": ordered})

    return Agent(
        name="PolicyAgent",
        description="Answers policy questions with parallel multi-agent RAG over 3 Knowledge Bases.",
        model=_model(config.WORKER_MODEL_ID, temperature=0.2),
        system_prompt=POLICY_SYSTEM_PROMPT,
        tools=[search_all_policies],
        callback_handler=None,
    )


# ======================================================================
# TASK 2 - 1.D  CommunicationAgent
# ======================================================================
COMMUNICATION_SYSTEM_PROMPT = """You are the NovaMart CommunicationAgent. You write the FINAL message the customer reads.

1. ALWAYS call get_full_workflow_context(session_id) first. It contains the customer's request,
   recent conversation, and the findings of every agent that ran (inventory, policy, refund).
2. Include every relevant fact from those findings: order IDs, products, amounts, decisions,
   refund IDs, timelines, policy details and next steps. Never contradict or invent facts.
3. If a refund was initiated, give the refund ID, amount, timeline and the return-label next step.
   If a return is not eligible, explain why kindly and suggest alternatives found in the findings
   (e.g. warranty service).
4. For math or price calculations, work it out carefully step by step, show the key steps briefly,
   and round money to 2 decimal places.
5. Tone: warm, empathetic, professional and concise. Address the customer by first name if known.
6. Never mention internal systems, agents, tools, "WorkflowState", databases or knowledge bases.
7. Sign off as "NovaMart Customer Support".

Output ONLY the customer-facing message."""


@tool
def get_full_workflow_context(session_id: str) -> str:
    """Read the complete WorkflowState record for this session.

    Args:
        session_id: The WorkflowState session ID supplied in your instructions.

    Returns:
        JSON string with customer_id, customer_request, conversation_context, routing_path,
        and every populated agent column (inventory_agent, policy_agent, refund_agent).
    """
    TRACE.tool_call("CommunicationAgent", "get_full_workflow_context", {"session_id": session_id})
    state = _read_workflow_state(session_id) or {"session_id": session_id, "error": "no WorkflowState"}
    state.pop("communication_agent", None)
    TRACE.tool_result("CommunicationAgent", "get_full_workflow_context",
                      f"version {state.get('version')}, columns: "
                      + (", ".join(c for c in WORKFLOW_COLUMNS if state.get(c)) or "none"))
    return _json(state)


def build_communication_agent() -> Agent:
    """Build the CommunicationAgent that composes the final customer-facing response."""
    return Agent(
        name="CommunicationAgent",
        description="Drafts the final, empathetic customer-facing response.",
        model=_model(config.WORKER_MODEL_ID, temperature=0.3),
        system_prompt=COMMUNICATION_SYSTEM_PROMPT,
        tools=[get_full_workflow_context],
        callback_handler=None,
    )


# ======================================================================
# TASK 2 - 1.E  OrchestratorAgent
# ======================================================================
ORCHESTRATOR_SYSTEM_PROMPT = """You are the NovaMart OrchestratorAgent. You ROUTE customer-support requests to
specialist agents. You never answer the customer yourself.

ROUTING RULES - follow them exactly:
Rule 1 - EVERY request: call initialize_session FIRST.
Rule 2 - Order status, return or refund requests (e.g. "where is my order ORD-1", "I want to return ORD-1",
         "can I get a refund"): call route_to_inventory_agent FIRST, THEN route_to_refund_agent.
Rule 3 - Policy meaning questions (return windows, shipping rates or times, warranty terms, "what is the
         return policy for premium customers?"): call route_to_policy_agent.
Rule 4 - Account questions about the customer's OWN data ("what is my tier?", "am I premium?",
         "what orders do I have?"): call route_to_inventory_agent. NEVER send these to the policy agent -
         it only knows policy text, not customer data.
Rule 5 - Math / calculation questions (e.g. "how much are 5 items at $29.99 with 10% off?"): call
         route_to_communication_agent directly. Do NOT call the inventory, policy or refund agents.
Rule 6 - EVERY request, LAST step: call route_to_communication_agent to compose the final reply.

If a request mixes types (e.g. a return plus a policy question) apply every matching rule in this order:
initialize_session -> inventory -> refund -> policy -> communication.

How to call tools:
- Call ONE tool at a time and wait for its result.
- Pass the customer's request (verbatim, plus any order IDs) in the `request` argument.
- Use earlier conversation turns (if given) to resolve references like "that order".

CRITICAL: You must NEVER write the customer-facing response. route_to_communication_agent is ALWAYS your
final tool call - no exceptions. After it returns, reply with only the single word: COMPLETE"""


def build_orchestrator_agent(session_id: str, customer_id: str, customer_request: str = "",
                             conversation_context: str = "") -> Agent:
    """Build the OrchestratorAgent and its five routing tools for one session."""

    def _read_or_create() -> dict:
        return _read_workflow_state(session_id) or _create_workflow_state(
            session_id, customer_id, customer_request, conversation_context)

    def _worker_prompt(request: str) -> str:
        return (f"Session ID: {session_id}\nCustomer ID: {customer_id}\n"
                f"Customer request: {request}")

    @tool
    def initialize_session() -> str:
        """Create the shared WorkflowState record for this request. ALWAYS call this first.

        Returns:
            JSON string with session_id, customer_id, version (0) and status ("Created").
        """
        TRACE.step("OrchestratorAgent", "initialize_session()")
        state = _create_workflow_state(session_id, customer_id, customer_request, conversation_context)
        log_event("session_initialized", session_id=session_id, customer_id=customer_id)
        return _json({k: state[k] for k in ("session_id", "customer_id", "version", "status")})

    @tool
    def route_to_inventory_agent(request: str) -> str:
        """Send the request to the InventoryAgent to look up order and customer facts in DynamoDB.

        Use for order status / return / refund requests (before the refund agent) and for
        account questions such as "what is my tier?".

        Args:
            request: The customer's request, including any order IDs.

        Returns:
            The InventoryAgent's factual findings (also saved to WorkflowState.inventory_agent).
        """
        TRACE.step("InventoryAgent", "gathering order & customer facts")
        state = _read_or_create()
        output = str(build_inventory_agent()(_worker_prompt(request))).strip()
        _commit_agent_output(session_id, "inventory_agent", output, "InventoryAgent", state["version"])
        return output

    @tool
    def route_to_policy_agent(request: str) -> str:
        """Send a policy question to the PolicyAgent (parallel RAG over Returns, Shipping and Warranty KBs).

        Use only for questions about what NovaMart policy says - never for the customer's own account data.

        Args:
            request: The customer's policy question.

        Returns:
            The PolicyAgent's grounded answer (also saved to WorkflowState.policy_agent).
        """
        TRACE.step("PolicyAgent", "multi-agent RAG across 3 Knowledge Bases")
        state = _read_or_create()
        output = str(build_policy_agent()(request)).strip()
        _commit_agent_output(session_id, "policy_agent", output, "PolicyAgent", state["version"])
        return output

    @tool
    def route_to_refund_agent(request: str) -> str:
        """Send the request to the RefundAgent for a return/refund eligibility decision.

        Must be called AFTER route_to_inventory_agent - it decides using the inventory findings.

        Args:
            request: The customer's return / refund / order-status request.

        Returns:
            The RefundAgent's decision (also saved to WorkflowState.refund_agent).
        """
        TRACE.step("RefundAgent", "evaluating eligibility (tier + delivery date)")
        state = _read_or_create()
        if not state.get("inventory_agent"):
            return "ERROR: no inventory findings yet. Call route_to_inventory_agent first, then retry."
        output = str(build_refund_agent()(_worker_prompt(request))).strip()
        _commit_agent_output(session_id, "refund_agent", output, "RefundAgent", state["version"])
        return output

    @tool
    def route_to_communication_agent(request: str) -> str:
        """Send everything gathered so far to the CommunicationAgent to compose the final customer reply.

        ALWAYS the last tool call for every request.

        Args:
            request: The customer's original request.

        Returns:
            Confirmation that the customer-facing response was written to WorkflowState.communication_agent.
        """
        TRACE.step("CommunicationAgent", "composing customer response")
        state = _read_or_create()
        output = str(build_communication_agent()(_worker_prompt(request))).strip()
        _commit_agent_output(session_id, "communication_agent", output, "CommunicationAgent",
                             state["version"])
        return "Customer response composed and stored. Reply with COMPLETE."

    return Agent(
        name="OrchestratorAgent",
        description="Routes NovaMart support requests and manages WorkflowState.",
        model=_model(config.ORCHESTRATOR_MODEL_ID, temperature=0.0),
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        tools=[initialize_session, route_to_inventory_agent, route_to_policy_agent,
               route_to_refund_agent, route_to_communication_agent],
        tool_executor=SequentialToolExecutor(),  # routing order matters (inventory before refund)
        callback_handler=None,
    )


# ========================================================== session memory
_local_history: dict[str, list[dict]] = {}
_memory_id_cache: str | None = None


def _memory_id() -> str | None:
    """Memory ID from MEMORY_ARN, else look it up by name (inside the runtime)."""
    global _memory_id_cache
    if _memory_id_cache:
        return _memory_id_cache
    arn = os.getenv("MEMORY_ARN", config.MEMORY_ARN)
    if arn:
        _memory_id_cache = arn.split("/")[-1]
        return _memory_id_cache
    try:
        for m in agentcore_control.list_memories().get("memories", []):
            if m["id"].startswith(config.MEMORY_NAME) and m.get("status") == "ACTIVE":
                _memory_id_cache = m["id"]
                return _memory_id_cache
    except Exception:
        pass
    return None


def _safe_session(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", value)[:100]


def _load_conversation_context(session_id: str, customer_id: str, max_turns: int = 6) -> str:
    """Return the recent conversation for this session (AgentCore Memory, else in-process)."""
    messages: list[dict] = []
    mid = _memory_id()
    if mid:
        try:
            events = agentcore_data.list_events(
                memoryId=mid, actorId=_safe_session(customer_id), sessionId=_safe_session(session_id),
                includePayloads=True, maxResults=max_turns * 2).get("events", [])
            for ev in sorted(events, key=lambda e: e["eventTimestamp"]):
                for p in ev.get("payload", []):
                    conv = p.get("conversational")
                    if conv:
                        messages.append({"role": conv["role"], "text": conv["content"]["text"]})
        except Exception as exc:
            log_event("memory_read_failed", level="WARN", error=str(exc))
    if not messages:
        messages = _local_history.get(session_id, [])
    messages = messages[-max_turns * 2:]
    return "\n".join(f"{m['role']}: {m['text'][:600]}" for m in messages)


def _save_conversation_turn(session_id: str, customer_id: str, prompt: str, response: str) -> None:
    _local_history.setdefault(session_id, []).extend(
        [{"role": "USER", "text": prompt}, {"role": "ASSISTANT", "text": response}])
    mid = _memory_id()
    if not mid:
        return
    try:
        agentcore_data.create_event(
            memoryId=mid, actorId=_safe_session(customer_id), sessionId=_safe_session(session_id),
            eventTimestamp=datetime.now(timezone.utc),
            payload=[{"conversational": {"content": {"text": prompt}, "role": "USER"}},
                     {"conversational": {"content": {"text": response}, "role": "ASSISTANT"}}])
    except Exception as exc:
        log_event("memory_write_failed", level="WARN", error=str(exc))


# ========================================================= request handling
def handle_request(prompt: str, customer_id: str = "CUST-001", session_id: str | None = None) -> dict:
    """Run one customer request through the multi-agent graph.

    Returns {"response", "session_id", "customer_id", "routing", "trace_id", "workflow_version"}.
    The response text always comes from the CommunicationAgent (WorkflowState.communication_agent).
    """
    customer_id = (customer_id or "GUEST").strip().upper()
    session_id = session_id or f"sess-{uuid.uuid4().hex}"
    started = time.time()
    TRACE.request(prompt, customer_id, session_id)
    history = _load_conversation_context(session_id, customer_id)

    with request_trace(ROOT_SERVICE_NAME, session_id=session_id, customer_id=customer_id) as trace_id:
        orchestrator = build_orchestrator_agent(session_id, customer_id, prompt, history)
        TRACE.step("OrchestratorAgent", "routing request")
        message = f"Customer ID: {customer_id}\nCustomer message: {prompt}"
        if history:
            message = f"Earlier conversation in this session:\n{history}\n\n{message}"
        result = orchestrator(message)

        state = _read_workflow_state(session_id) or {}
        if getattr(result, "stop_reason", "") == "guardrail_intervened":
            response = str(result).strip()
            log_event("guardrail_intervened", level="WARN", session_id=session_id)
        else:
            if not state.get("communication_agent"):
                # Safety net - the reply must always come from the CommunicationAgent.
                TRACE.warning("orchestrator skipped route_to_communication_agent - enforcing Rule 6")
                orchestrator.tool.route_to_communication_agent(request=prompt)
                state = _read_workflow_state(session_id) or {}
            response = state.get("communication_agent") or str(result).strip()

    _save_conversation_turn(session_id, customer_id, prompt, response)
    routing = ["OrchestratorAgent", *state.get("routing_path", [])]
    log_event("request_complete", session_id=session_id, customer_id=customer_id,
              routing=" -> ".join(routing), latency_ms=int((time.time() - started) * 1000))
    TRACE.final(response, trace_id)
    TRACE.workflow_summary(state)
    return {"response": response, "session_id": session_id, "customer_id": customer_id,
            "routing": routing, "trace_id": trace_id, "workflow_version": state.get("version")}


# ======================================================================
# TASK 3 - Guardrail and Runtime Deployment
# ======================================================================
def _guardrail_definition() -> dict:
    return {
        "name": config.GUARDRAIL_NAME,
        "description": "NovaMart customer-support safety guardrail (content, PII, topics, profanity).",
        "contentPolicyConfig": {"filtersConfig": [
            {"type": "SEXUAL", "inputStrength": "HIGH", "outputStrength": "HIGH"},
            {"type": "VIOLENCE", "inputStrength": "HIGH", "outputStrength": "HIGH"},
            {"type": "HATE", "inputStrength": "HIGH", "outputStrength": "HIGH"},
            {"type": "INSULTS", "inputStrength": "MEDIUM", "outputStrength": "MEDIUM"},
            {"type": "MISCONDUCT", "inputStrength": "MEDIUM", "outputStrength": "MEDIUM"},
        ]},
        "sensitiveInformationPolicyConfig": {"piiEntitiesConfig": [
            {"type": "CREDIT_DEBIT_CARD_NUMBER", "action": "BLOCK"},
            {"type": "US_SOCIAL_SECURITY_NUMBER", "action": "BLOCK"},
            {"type": "EMAIL", "action": "ANONYMIZE"},
            {"type": "PHONE", "action": "ANONYMIZE"},
        ]},
        "topicPolicyConfig": {
            "tierConfig": {"tierName": "STANDARD"},
            "topicsConfig": [
                {
                    "name": "CompetitorProducts",
                    "definition": "Questions, recommendations or comparisons involving products, prices or "
                                  "services of competing retailers such as Amazon, Walmart, Target or Best Buy.",
                    "examples": ["Is this cheaper on Amazon?", "Should I buy this at Walmart instead?",
                                 "Does Best Buy have a better warranty than you?"],
                    "type": "DENY",
                },
                {
                    "name": "PricingNegotiations",
                    "definition": "Haggling, or asking NovaMart to lower, match or change an advertised price. "
                                  "Doing arithmetic with a stated price and discount is not negotiation.",
                    "examples": ["Can you drop the price to $50 if I buy today?",
                                 "I'll only buy it if you give me 40% off.",
                                 "Will you match the lower price I found elsewhere?"],
                    "type": "DENY",
                },
                {
                    "name": "LegalThreats",
                    "definition": "Threats of lawsuits, legal action, attorneys, court cases or regulatory "
                                  "complaints against NovaMart.",
                    "examples": ["I'm going to sue NovaMart.", "My lawyer will be contacting you.",
                                 "I will take you to small claims court."],
                    "type": "DENY",
                },
            ],
        },
        "wordPolicyConfig": {"managedWordListsConfig": [{"type": "PROFANITY"}]},
        "crossRegionConfig": {"guardrailProfileIdentifier": "us.guardrail.v1:0"},
        "blockedInputMessaging": (
            "I'm sorry, but I can't help with that request. I'm happy to help with your NovaMart orders, "
            "returns, refunds, shipping or warranty questions. For your security, please never share card "
            "numbers or Social Security numbers in chat."),
        "blockedOutputsMessaging": (
            "I'm sorry, I'm unable to provide that response. Please contact NovaMart Customer Support "
            "and a team member will be glad to help."),
    }


def _wait_guardrail_ready(guardrail_id: str, timeout: int = 120) -> None:
    for _ in range(timeout // 3):
        status = bedrock.get_guardrail(guardrailIdentifier=guardrail_id, guardrailVersion="DRAFT")["status"]
        if status == "READY":
            return
        if status == "FAILED":
            raise RuntimeError(f"Guardrail {guardrail_id} entered FAILED state")
        time.sleep(3)
    raise TimeoutError(f"Guardrail {guardrail_id} not READY after {timeout}s")


def create_guardrail() -> tuple[str, str]:
    """Create (or update) the NovaMart Bedrock Guardrail and publish a numbered version.

    Returns:
        (guardrail_id, guardrail_version) - version is a number such as "1", never "DRAFT".
    """
    definition = _guardrail_definition()
    existing = next((g for g in bedrock.list_guardrails(maxResults=100).get("guardrails", [])
                     if g["name"] == config.GUARDRAIL_NAME), None)
    if existing:
        guardrail_id = existing["id"]
        print(f"Guardrail {config.GUARDRAIL_NAME} exists ({guardrail_id}) - updating DRAFT")
        bedrock.update_guardrail(guardrailIdentifier=guardrail_id, **definition)
    else:
        resp = bedrock.create_guardrail(**definition, clientRequestToken=str(uuid.uuid4()))
        guardrail_id = resp["guardrailId"]
        print(f"Created guardrail {guardrail_id}")
    _wait_guardrail_ready(guardrail_id)

    version_resp = bedrock.create_guardrail_version(
        guardrailIdentifier=guardrail_id,
        description=f"NovaMart release {datetime.now(timezone.utc):%Y-%m-%d %H:%M}",
        clientRequestToken=str(uuid.uuid4()),
    )
    guardrail_version = version_resp["version"]
    print(f"Published guardrail version {guardrail_version}")

    config.update_env_file("GUARDRAIL_ID", guardrail_id)
    config.update_env_file("GUARDRAIL_VERSION", guardrail_version)
    return guardrail_id, guardrail_version


def deploy_to_agentcore_runtime(guardrail_id: str, guardrail_version: str) -> str:
    """Stage the app, configure and deploy it with the AgentCore CLI. Returns the runtime ARN."""
    import agentcore_cli

    missing = [k for k in ("RETURNS_KB_ID", "SHIPPING_KB_ID", "WARRANTY_KB_ID") if not getattr(config, k)]
    if missing:
        raise RuntimeError(f"Set {', '.join(missing)} in .env first (Phase 3 - Knowledge Bases).")
    if not config.AGENTCORE_ROLE_ARN:
        raise RuntimeError("AGENTCORE_ROLE_ARN not found - deploy infrastructure/starter_stack.yaml first.")

    agentcore_cli.stage_code()  # copies the app + helper modules into build/runtime/

    env_vars = {
        "AWS_REGION": config.AWS_REGION,
        "PROJECT_NAME": config.PROJECT_NAME,
        "RETURNS_KB_ID": config.RETURNS_KB_ID,
        "SHIPPING_KB_ID": config.SHIPPING_KB_ID,
        "WARRANTY_KB_ID": config.WARRANTY_KB_ID,
        "AGENT_LOG_GROUP": config.AGENT_LOG_GROUP,
        "GUARDRAIL_ID": guardrail_id,
        "GUARDRAIL_VERSION": guardrail_version,
    }
    agentcore_cli.configure_runtime(
        env_vars,
        network_mode="PUBLIC",
        protocol="HTTP",
        execution_role_arn=config.AGENTCORE_ROLE_ARN,
    )
    agentcore_cli.deploy()
    runtime_arn = agentcore_cli.deployed_runtime_arn()
    print(f"AgentCore Runtime deployed: {runtime_arn}")
    config.update_env_file("AGENTCORE_RUNTIME_ARN", runtime_arn)
    return runtime_arn


# ======================================================================
# TASK 4 - Memory
# ======================================================================
def configure_memory(runtime_arn: str) -> str:
    """Create the AgentCore Memory resource (session-summary strategy, 7-day retention).

    Args:
        runtime_arn: The deployed runtime that will use this memory (recorded in the description).

    Returns:
        The memory ARN.
    """
    existing = next((m for m in agentcore_control.list_memories().get("memories", [])
                     if m["id"].startswith(config.MEMORY_NAME) and m.get("status") != "DELETING"), None)
    if existing:
        memory_id, memory_arn = existing["id"], existing["arn"]
        print(f"Memory {memory_id} already exists - reusing")
    else:
        resp = agentcore_control.create_memory(
            name=config.MEMORY_NAME,
            description=("NovaMart customer-support conversation memory: summarises each support "
                         f"session for multi-turn context. Runtime: {runtime_arn.split('/')[-1]}"),
            eventExpiryDuration=7,
            memoryStrategies=[{
                "summaryMemoryStrategy": {
                    "name": "NovaMartSessionSummary",
                    "description": "Summarises each customer support session.",
                    "namespaces": ["/summaries/{actorId}/{sessionId}"],
                },
            }],
            clientToken=str(uuid.uuid4()),
        )
        memory_id, memory_arn = resp["memory"]["id"], resp["memory"]["arn"]
        print(f"Created memory {memory_id}")

    for _ in range(60):  # wait until ACTIVE
        status = agentcore_control.get_memory(memoryId=memory_id)["memory"]["status"]
        if status == "ACTIVE":
            break
        if status == "FAILED":
            raise RuntimeError(f"Memory {memory_id} FAILED")
        time.sleep(5)
    config.update_env_file("MEMORY_ARN", memory_arn)
    return memory_arn


# ======================================================================
# TASK 6 - Observability
# ======================================================================
def configure_observability(runtime_arn: str) -> dict:
    """Enable CloudWatch Logs (INFO) and X-Ray tracing (100% sampling) for the runtime."""
    logging_configuration = {
        "cloudWatchConfig": {
            "logGroupName": config.AGENT_LOG_GROUP,
            "logLevel": "INFO",
            "enabled": True,
        },
        "xRayConfig": {
            "enabled": True,
            "samplingRate": 1.0,
        },
    }
    try:
        summary = apply_observability_config(runtime_arn, logging_configuration)
        for step in summary.get("steps", []):
            print(f"  ✓ {step}")
        return summary
    except Exception as exc:
        print(f"  ! observability configuration failed: {exc}")
        return {"error": str(exc), "loggingConfiguration": logging_configuration}


# ======================================================================
# Deployment + CLI entry points
# ======================================================================
def deploy_all() -> dict:
    print("\n[1/4] Bedrock Guardrail")
    guardrail_id, guardrail_version = create_guardrail()
    print("\n[2/4] AgentCore Runtime (AgentCore CLI)")
    runtime_arn = deploy_to_agentcore_runtime(guardrail_id, guardrail_version)
    print("\n[3/4] AgentCore Memory")
    memory_arn = configure_memory(runtime_arn)
    print("\n[4/4] Observability")
    configure_observability(runtime_arn)
    summary = {"guardrail_id": guardrail_id, "guardrail_version": guardrail_version,
               "runtime_arn": runtime_arn, "memory_arn": memory_arn}
    print("\nDeployment complete:\n" + json.dumps(summary, indent=2))
    return summary


def invoke_runtime(prompt: str, customer_id: str = "CUST-001", session_id: str | None = None) -> dict:
    """Invoke the deployed AgentCore Runtime over its HTTP protocol."""
    arn = os.getenv("AGENTCORE_RUNTIME_ARN", config.AGENTCORE_RUNTIME_ARN)
    if not arn:
        raise RuntimeError("AGENTCORE_RUNTIME_ARN is empty - run `python src/agent_orchestrator.py deploy`.")
    session_id = session_id or f"sess-{uuid.uuid4().hex}"  # >= 33 chars as required
    resp = agentcore_data.invoke_agent_runtime(
        agentRuntimeArn=arn, runtimeSessionId=session_id, qualifier="DEFAULT",
        payload=json.dumps({"prompt": prompt, "customer_id": customer_id,
                            "session_id": session_id}).encode())
    body = resp["response"].read().decode()
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"response": body, "session_id": session_id}


TEST_SCENARIOS = [
    ("I want to return my order ORD-27176", "CUST-001"),
    ("What is the return policy for premium customers?", "CUST-002"),
    ("How much are 5 items at $29.99 with 10% off?", "CUST-001"),
]


def run_test_scenarios() -> list[dict]:
    os.environ.setdefault("NOVAMART_FORCE_TRACE", "1")
    results = []
    for prompt, customer in TEST_SCENARIOS:
        out = handle_request(prompt, customer)
        print(f"\nROUTING : {' -> '.join(out['routing'])}")
        print(f"X-Ray   : {out['trace_id'] or '(not sampled)'}")
        results.append(out)
    print("\nOpen CloudWatch -> X-Ray traces -> Service map (last 5 minutes) to see the call graph.")
    return results


def chat() -> None:
    os.environ.setdefault("NOVAMART_FORCE_TRACE", "1")
    customer_id = input("Customer ID [CUST-001]: ").strip().upper() or "CUST-001"
    session_id = f"sess-{uuid.uuid4().hex}"
    print("Type your message. Commands: /customer CUST-002, /new (new session), /quit")
    while True:
        try:
            msg = input(f"\n{customer_id}> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not msg:
            continue
        if msg in ("/quit", "/exit"):
            break
        if msg.startswith("/customer"):
            customer_id = (msg.split(maxsplit=1)[1:] or ["CUST-001"])[0].upper()
            session_id = f"sess-{uuid.uuid4().hex}"
            print(f"Switched to {customer_id} (new session)")
            continue
        if msg == "/new":
            session_id = f"sess-{uuid.uuid4().hex}"
            print("New session started")
            continue
        handle_request(msg, customer_id, session_id)


# ------------------------------------------------- AgentCore Runtime app
try:
    from bedrock_agentcore.runtime import BedrockAgentCoreApp

    app = BedrockAgentCoreApp()

    @app.entrypoint
    def invoke(payload: dict, context=None) -> dict:
        """AgentCore Runtime entrypoint: {"prompt", "customer_id", "session_id"} -> response dict."""
        os.environ["NOVAMART_QUIET"] = "1"
        prompt = (payload or {}).get("prompt", "").strip()
        if not prompt:
            return {"error": "payload must include a non-empty 'prompt'"}
        session_id = payload.get("session_id") or getattr(context, "session_id", None)
        return handle_request(prompt, payload.get("customer_id", "GUEST"), session_id)
except ImportError:  # bedrock-agentcore not installed locally
    app = None


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if command == "deploy":
        deploy_all()
    elif command == "test":
        run_test_scenarios()
    elif command == "chat":
        chat()
    elif command == "invoke":
        if len(sys.argv) < 3:
            sys.exit('usage: python src/agent_orchestrator.py invoke "<message>" [CUST-001]')
        print(json.dumps(invoke_runtime(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "CUST-001"),
                         indent=2))
    elif command == "serve":
        if app is None:
            sys.exit("pip install bedrock-agentcore to serve the runtime app")
        app.run()
    else:
        sys.exit(__doc__)

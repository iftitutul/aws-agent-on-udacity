"""NovaMart automated test suite - 120 points.

    python tests/test_agent.py task2     # Multi-agent graph              (40)
    python tests/test_agent.py task3     # Guardrail + Runtime            (20)
    python tests/test_agent.py task4     # Memory                         (15)
    python tests/test_agent.py task5     # Knowledge Bases + parallel RAG (25)
    python tests/test_agent.py task6     # Observability                  (20)
    python tests/test_agent.py all       # everything                    (120)

Structural tests run without AWS calls; live tests need valid credentials and
the resources created in each phase.
"""

from __future__ import annotations

import inspect
import os
import re
import sys
import time
import traceback
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("NOVAMART_QUIET", "1")

import boto3  # noqa: E402

import config  # noqa: E402
import agent_orchestrator as ao  # noqa: E402

SOURCE = Path(ao.__file__).read_text()
REGION = config.AWS_REGION

GREEN, RED, YELLOW, BOLD, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[2m", "\033[0m"
TESTS: dict[str, list[tuple[str, int, callable]]] = {}


def test(task: str, points: int):
    def register(fn):
        TESTS.setdefault(task, []).append((fn.__name__, points, fn))
        return fn
    return register


# ---------------------------------------------------------------- helpers
def _model_cfg(agent) -> dict:
    return agent.model.config


def _assert_agent(agent, name: str, tools: set[str], model_id: str, temperature: float):
    from strands import Agent
    assert isinstance(agent, Agent), f"{name} builder must return a strands.Agent"
    assert set(agent.tool_names) == tools, f"{name} tools {sorted(agent.tool_names)} != {sorted(tools)}"
    cfg = _model_cfg(agent)
    assert cfg["model_id"] == model_id, f"{name} model {cfg['model_id']} != {model_id}"
    assert abs(cfg.get("temperature", -1) - temperature) < 1e-9, \
        f"{name} temperature {cfg.get('temperature')} != {temperature}"


def _func_source(name: str) -> str:
    return inspect.getsource(getattr(ao, name))


def _state_routing(session_id: str) -> list[str]:
    return (ao._read_workflow_state(session_id) or {}).get("routing_path", [])


# ======================================================================= TASK 2
@test("task2", 4)
def test_2_inventory_agent():
    _assert_agent(ao.build_inventory_agent(), "InventoryAgent",
                  {"check_order_status", "get_customer_tier", "list_customer_orders"},
                  config.WORKER_MODEL_ID, 0.1)


@test("task2", 4)
def test_2_refund_agent():
    agent = ao.build_refund_agent()
    _assert_agent(agent, "RefundAgent", {"get_inventory_context", "initiate_refund"},
                  config.WORKER_MODEL_ID, 0.1)
    assert config.RETURN_WINDOW_DAYS == {"Standard": 30, "Premium": 60}
    assert "30 days" in agent.system_prompt and "60 days" in agent.system_prompt


@test("task2", 4)
def test_2_communication_agent():
    _assert_agent(ao.build_communication_agent(), "CommunicationAgent",
                  {"get_full_workflow_context"}, config.WORKER_MODEL_ID, 0.3)


@test("task2", 3)
def test_2_policy_agent_coordinator():
    _assert_agent(ao.build_policy_agent(), "PolicyAgent", {"search_all_policies"},
                  config.WORKER_MODEL_ID, 0.2)


@test("task2", 4)
def test_2_policy_parallel_retrievers():
    src = _func_source("build_policy_agent")
    for name in ("Returns", "Shipping", "Warranty"):
        assert f"{name}PolicyRetrieverAgent" in src or '{domain}PolicyRetrieverAgent' in src, name
        assert f"config.{name.upper()}_KB_ID" in src, f"retriever must use config.{name.upper()}_KB_ID"
    assert "retrieve_from_knowledge_base(" in src
    assert re.search(r"ThreadPoolExecutor\(\s*max_workers\s*=\s*3\s*\)", src), "ThreadPoolExecutor(max_workers=3)"
    assert "as_completed(" in src, "results must be collected with as_completed()"
    assert re.search(r"temperature\s*=\s*0\.0", src), "retrievers must use temperature=0.0"


@test("task2", 4)
def test_2_orchestrator_agent():
    agent = ao.build_orchestrator_agent("test-session", "CUST-001")
    _assert_agent(agent, "OrchestratorAgent",
                  {"initialize_session", "route_to_inventory_agent", "route_to_policy_agent",
                   "route_to_refund_agent", "route_to_communication_agent"},
                  config.ORCHESTRATOR_MODEL_ID, 0.0)


@test("task2", 3)
def test_2_orchestrator_routing_rules():
    prompt = ao.build_orchestrator_agent("s", "CUST-001").system_prompt
    for n in range(1, 7):
        assert f"Rule {n}" in prompt, f"system prompt must state Rule {n}"
    for needle in ("initialize_session", "route_to_inventory_agent", "route_to_refund_agent",
                   "route_to_policy_agent", "route_to_communication_agent", "NEVER"):
        assert needle in prompt, needle
    src = _func_source("build_orchestrator_agent")
    assert src.count("_read_or_create()") >= 4 and "expected_version" in _func_source("_commit_agent_output")
    assert src.count("_commit_agent_output(") >= 4, "every route_to_* tool must update WorkflowState"


@test("task2", 2)
def test_2_tool_docstrings():
    agents = [ao.build_inventory_agent(), ao.build_refund_agent(), ao.build_communication_agent(),
              ao.build_policy_agent(), ao.build_orchestrator_agent("s", "c")]
    for agent in agents:
        for spec in agent.tool_registry.get_all_tool_specs():
            assert len(spec["description"]) > 25, f"{spec['name']} needs a descriptive docstring"


@test("task2", 4)
def test_2_workflow_state_optimistic_locking():
    sid = f"test-lock-{uuid.uuid4().hex[:8]}"
    state = ao._create_workflow_state(sid, "CUST-001")
    assert state["version"] == 0
    new = ao._update_workflow_state(sid, {"inventory_agent": "facts"}, expected_version=0)
    assert new["version"] == 1 and new["inventory_agent"] == "facts"
    try:
        ao._update_workflow_state(sid, {"inventory_agent": "stale write"}, expected_version=0)
    except ao.WorkflowConflictError:
        pass
    else:
        raise AssertionError("stale expected_version must be rejected")
    assert ao._read_workflow_state(sid)["inventory_agent"] == "facts"


@test("task2", 4)
def test_2_live_return_routing():
    out = ao.handle_request("I want to return my order ORD-27176", "CUST-001")
    path = _state_routing(out["session_id"])
    assert path[:2] == ["InventoryAgent", "RefundAgent"], f"routing was {path}"
    assert path[-1] == "CommunicationAgent", f"communication must be last, routing was {path}"
    assert "PolicyAgent" not in path, f"policy agent not expected: {path}"
    assert out["response"] and "ORD-27176" in out["response"]


@test("task2", 4)
def test_2_live_math_routing():
    out = ao.handle_request("How much are 5 items at $29.99 with 10% off?", "CUST-001")
    path = _state_routing(out["session_id"])
    assert path == ["CommunicationAgent"], f"math must go straight to CommunicationAgent, got {path}"
    assert "134.96" in out["response"] or "134.95" in out["response"], out["response"][:300]


# ======================================================================= TASK 3
def _guardrail():
    gid, ver = os.getenv("GUARDRAIL_ID"), os.getenv("GUARDRAIL_VERSION")
    assert gid and ver, "GUARDRAIL_ID / GUARDRAIL_VERSION missing from .env"
    return boto3.client("bedrock", region_name=REGION).get_guardrail(
        guardrailIdentifier=gid, guardrailVersion=ver)


@test("task3", 4)
def test_3_guardrail_versioned():
    assert "create_guardrail_version(" in _func_source("create_guardrail")
    g = _guardrail()
    assert g["status"] == "READY", g["status"]
    assert g["version"].isdigit(), f"use a numbered version, not {g['version']}"


@test("task3", 3)
def test_3_guardrail_content_policy():
    filters = {f["type"]: f for f in _guardrail()["contentPolicy"]["filters"]}
    for t in ("SEXUAL", "VIOLENCE", "HATE"):
        assert filters[t]["inputStrength"] == "HIGH" and filters[t]["outputStrength"] == "HIGH", t
    for t in ("INSULTS", "MISCONDUCT"):
        assert filters[t]["inputStrength"] == "MEDIUM" and filters[t]["outputStrength"] == "MEDIUM", t


@test("task3", 3)
def test_3_guardrail_pii_policy():
    pii = {p["type"]: p["action"] for p in _guardrail()["sensitiveInformationPolicy"]["piiEntities"]}
    assert pii.get("CREDIT_DEBIT_CARD_NUMBER") == "BLOCK"
    assert pii.get("US_SOCIAL_SECURITY_NUMBER") == "BLOCK"
    assert pii.get("EMAIL") == "ANONYMIZE"
    assert pii.get("PHONE") == "ANONYMIZE"


@test("task3", 2)
def test_3_guardrail_topic_policy():
    tp = _guardrail()["topicPolicy"]
    names = " ".join(t["name"].lower() for t in tp["topics"] if t["type"] == "DENY")
    for word in ("competitor", "pricing", "legal"):
        assert word in names, f"DENY topic for {word} missing"
    assert tp.get("tier", {}).get("tierName") == "STANDARD", "topic policy must use the STANDARD tier"


@test("task3", 2)
def test_3_guardrail_behaviour():
    rt = boto3.client("bedrock-runtime", region_name=REGION)

    def action(text):
        return rt.apply_guardrail(guardrailIdentifier=os.environ["GUARDRAIL_ID"],
                                  guardrailVersion=os.environ["GUARDRAIL_VERSION"], source="INPUT",
                                  content=[{"text": {"text": text}}])["action"]

    assert action("How much are 5 items at $29.99 with 10% off?") == "NONE", "math must be allowed"
    assert action("The total for 5 items at $29.99 with 10% off is $134.96.") == "NONE"
    for blocked in ("Drop the price to $20 or I won't buy it.", "Is Amazon cheaper than you for this?",
                    "I'm going to sue NovaMart and call my lawyer."):
        assert action(blocked) == "GUARDRAIL_INTERVENED", f"should block: {blocked}"


@test("task3", 1)
def test_3_guardrail_profanity():
    words = _guardrail().get("wordPolicy", {}).get("managedWordLists", [])
    assert any(w["type"] == "PROFANITY" for w in words)


@test("task3", 5)
def test_3_runtime_deployed():
    src = _func_source("deploy_to_agentcore_runtime")
    for call in ("agentcore_cli.configure_runtime(", "agentcore_cli.deploy(", "agentcore_cli.deployed_runtime_arn("):
        assert call in src, call
    assert "create_agent_runtime" not in src
    arn = os.getenv("AGENTCORE_RUNTIME_ARN")
    assert arn, "AGENTCORE_RUNTIME_ARN missing from .env"
    rt = boto3.client("bedrock-agentcore-control", region_name=REGION).get_agent_runtime(
        agentRuntimeId=arn.split("/")[-1])
    assert rt["status"] == "READY", rt["status"]
    assert rt["networkConfiguration"]["networkMode"] == "PUBLIC"
    assert rt["roleArn"] == config.AGENTCORE_ROLE_ARN
    env = rt.get("environmentVariables", {})
    for key in ("AWS_REGION", "PROJECT_NAME", "RETURNS_KB_ID", "SHIPPING_KB_ID", "WARRANTY_KB_ID",
                "AGENT_LOG_GROUP", "GUARDRAIL_ID", "GUARDRAIL_VERSION"):
        assert env.get(key), f"runtime env var {key} missing"
    assert env["GUARDRAIL_VERSION"].isdigit()


# ======================================================================= TASK 4
@test("task4", 5)
def test_4_memory_code():
    src = _func_source("configure_memory")
    assert "agentcore_control.create_memory(" in src
    assert "summaryMemoryStrategy" in src
    assert re.search(r"eventExpiryDuration\s*=\s*7", src)
    assert "description=" in src and "name=" in src


@test("task4", 6)
def test_4_memory_resource():
    arn = os.getenv("MEMORY_ARN")
    assert arn, "MEMORY_ARN missing from .env (run deploy)"
    mem = boto3.client("bedrock-agentcore-control", region_name=REGION).get_memory(
        memoryId=arn.split("/")[-1])["memory"]
    assert mem["status"] == "ACTIVE", mem["status"]
    assert mem["eventExpiryDuration"] == 7
    assert any(s["type"] == "SUMMARIZATION" for s in mem.get("strategies", [])), "summary strategy missing"


@test("task4", 4)
def test_4_memory_roundtrip():
    sid, cid = f"test-mem-{uuid.uuid4().hex[:12]}", "CUST-TEST"
    ao._save_conversation_turn(sid, cid, "hello there", "hi! how can I help?")
    ao._local_history.clear()
    context = ao._load_conversation_context(sid, cid)
    assert "hello there" in context, "event not read back from AgentCore Memory"


# ======================================================================= TASK 5
KB_EXPECT = {
    "RETURNS_KB_ID": ("policies/returns/", config.RETURNS_VECTOR_INDEX),
    "SHIPPING_KB_ID": ("policies/shipping/", config.SHIPPING_VECTOR_INDEX),
    "WARRANTY_KB_ID": ("policies/warranty/", config.WARRANTY_VECTOR_INDEX),
}


@test("task5", 3)
def test_5_kb_ids_present():
    for key in KB_EXPECT:
        assert os.getenv(key), f"{key} missing from .env"


def _check_kb(env_key: str):
    agent = boto3.client("bedrock-agent", region_name=REGION)
    kb = agent.get_knowledge_base(knowledgeBaseId=os.environ[env_key])["knowledgeBase"]
    prefix, index = KB_EXPECT[env_key]
    assert kb["status"] == "ACTIVE", kb["status"]
    emb = kb["knowledgeBaseConfiguration"]["vectorKnowledgeBaseConfiguration"]["embeddingModelArn"]
    assert "amazon.titan-embed-text-v2:0" in emb, emb
    storage = kb["storageConfiguration"]
    assert storage["type"] == "S3_VECTORS", f"vector store is {storage['type']}"
    s3v = storage["s3VectorsConfiguration"]
    where = s3v.get("indexArn", "") + s3v.get("indexName", "") + s3v.get("vectorBucketArn", "")
    print(f"      {DIM}{env_key}: S3 Vectors {where}{RESET}")
    assert index in where, f"expected index {index}"
    assert config.VECTOR_BUCKET and config.VECTOR_BUCKET in where, f"expected vector bucket {config.VECTOR_BUCKET}"
    return agent, kb, prefix


def _check_synced(env_key: str):
    agent, kb, prefix = _check_kb(env_key)
    sources = agent.list_data_sources(knowledgeBaseId=kb["knowledgeBaseId"])["dataSourceSummaries"]
    assert sources, "no data source"
    ds = agent.get_data_source(knowledgeBaseId=kb["knowledgeBaseId"],
                               dataSourceId=sources[0]["dataSourceId"])["dataSource"]
    prefixes = ds["dataSourceConfiguration"]["s3Configuration"].get("inclusionPrefixes", [])
    assert any(p.rstrip("/") == prefix.rstrip("/") for p in prefixes), f"inclusion prefix {prefixes} != {prefix}"
    jobs = agent.list_ingestion_jobs(knowledgeBaseId=kb["knowledgeBaseId"],
                                     dataSourceId=sources[0]["dataSourceId"])["ingestionJobSummaries"]
    assert any(j["status"] == "COMPLETE" for j in jobs), "data source never synced - click Sync"


@test("task5", 3)
def test_5_returns_kb_config():
    _check_kb("RETURNS_KB_ID")


@test("task5", 3)
def test_5_shipping_kb_config():
    _check_kb("SHIPPING_KB_ID")


@test("task5", 3)
def test_5_warranty_kb_config():
    _check_kb("WARRANTY_KB_ID")


@test("task5", 2)
def test_5_returns_kb_synced():
    _check_synced("RETURNS_KB_ID")


@test("task5", 2)
def test_5_shipping_kb_synced():
    _check_synced("SHIPPING_KB_ID")


@test("task5", 2)
def test_5_warranty_kb_synced():
    _check_synced("WARRANTY_KB_ID")


@test("task5", 7)
def test_5_parallel_retrieval():
    import json
    policy_agent = ao.build_policy_agent()
    started = time.time()
    out = policy_agent.tool.search_all_policies(
        query="How many days do premium members have to return an item, and is shipping free?",
        record_direct_tool_call=False)
    elapsed = time.time() - started
    payload = json.loads(out["content"][0]["text"])
    for domain in ("Returns", "Shipping", "Warranty"):
        res = payload["results"][domain]
        assert not res["error"], f"{domain}: {res['error']}"
        assert res["hits"] > 0, f"{domain} KB returned no passages"
        print(f"      {DIM}{domain}: {res['hits']} passages{RESET}")
    print(f"      {DIM}parallel search finished in {elapsed:.1f}s{RESET}")


# ======================================================================= TASK 6
@test("task6", 8)
def test_6_logging_configuration():
    captured = {}
    original = ao.apply_observability_config

    def fake(runtime_arn, logging_configuration):
        captured.update(arn=runtime_arn, cfg=logging_configuration)
        return {"steps": []}

    ao.apply_observability_config = fake
    try:
        ao.configure_observability("arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test")
    finally:
        ao.apply_observability_config = original
    cfg = captured.get("cfg")
    assert cfg, "configure_observability must call apply_observability_config()"
    cw, xr = cfg["cloudWatchConfig"], cfg["xRayConfig"]
    assert cw["logGroupName"] == config.AGENT_LOG_GROUP
    assert cw["logLevel"] == "INFO" and cw["enabled"] is True
    assert xr["enabled"] is True and float(xr["samplingRate"]) == 1.0


@test("task6", 2)
def test_6_try_except():
    src = _func_source("configure_observability")
    assert re.search(r"try:\s*\n\s*.*apply_observability_config\(", src) and "except" in src


@test("task6", 4)
def test_6_transaction_search():
    dest = boto3.client("xray", region_name=REGION).get_trace_segment_destination()
    assert dest["Destination"] == "CloudWatchLogs", f"Transaction Search not enabled ({dest})"


@test("task6", 3)
def test_6_runtime_env():
    arn = os.getenv("AGENTCORE_RUNTIME_ARN")
    assert arn, "AGENTCORE_RUNTIME_ARN missing"
    env = boto3.client("bedrock-agentcore-control", region_name=REGION).get_agent_runtime(
        agentRuntimeId=arn.split("/")[-1]).get("environmentVariables", {})
    assert env.get("XRAY_ENABLED") == "true", "run deploy so observability settings reach the runtime"
    assert float(env.get("XRAY_SAMPLING_RATE", 0)) == 1.0
    assert env.get("AGENT_LOG_LEVEL") == "INFO"


@test("task6", 3)
def test_6_log_group_has_events():
    logs = boto3.client("logs", region_name=REGION)
    groups = logs.describe_log_groups(logGroupNamePrefix=config.AGENT_LOG_GROUP)["logGroups"]
    assert any(g["logGroupName"] == config.AGENT_LOG_GROUP for g in groups), "log group missing"
    streams = logs.describe_log_streams(logGroupName=config.AGENT_LOG_GROUP, orderBy="LastEventTime",
                                        descending=True, limit=1)["logStreams"]
    assert streams, "no agent logs yet - run python src/agent_orchestrator.py test"


# ================================================================== runner
TASK_TITLES = {"task2": "Multi-Agent Graph", "task3": "Guardrail & Runtime", "task4": "Memory",
               "task5": "Knowledge Bases", "task6": "Observability"}


def run(tasks: list[str]) -> int:
    earned = possible = 0
    for task in tasks:
        tests = TESTS[task]
        task_pts = sum(p for _, p, _ in tests)
        print(f"\n{BOLD}{task.upper()} - {TASK_TITLES[task]} ({task_pts} pts){RESET}")
        got = 0
        for name, pts, fn in tests:
            started = time.time()
            try:
                fn()
                got += pts
                print(f"  {GREEN}PASS{RESET} {name:<42} {pts:>2}/{pts}  {DIM}{time.time() - started:.1f}s{RESET}")
            except Exception as exc:
                print(f"  {RED}FAIL{RESET} {name:<42}  0/{pts}  {YELLOW}{type(exc).__name__}: {exc}{RESET}")
                if os.getenv("VERBOSE"):
                    traceback.print_exc()
        print(f"  {BOLD}{task}: {got}/{task_pts}{RESET}")
        earned += got
        possible += task_pts
    colour = GREEN if earned == possible else YELLOW
    print(f"\n{BOLD}{colour}SCORE: {earned}/{possible}{RESET}")
    return 0 if earned == possible else 1


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    selected = list(TASK_TITLES) if arg == "all" else [arg]
    unknown = [t for t in selected if t not in TESTS]
    if unknown:
        sys.exit(f"unknown task {unknown}; choose from {list(TASK_TITLES)} or all")
    sys.exit(run(selected))

"""Central configuration for the NovaMart multi-agent system.

Resolution order for every value:
  1. Environment variable (also loaded from .env when present)
  2. CloudFormation export of the `udacity-agentcore` foundation stack
  3. A sensible default (or empty string = "not yet created")

Run `python config.py` to print the resolved configuration table.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:  # python-dotenv is optional inside the runtime
    pass

import boto3

AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
PROJECT_NAME = os.getenv("PROJECT_NAME", "udacity-agentcore")
ENV_FILE = Path(__file__).resolve().parent / ".env"


@lru_cache(maxsize=1)
def _stack_exports() -> dict[str, str]:
    """Return {export_name: value} for exports of this project. Empty on failure."""
    if os.getenv("NOVAMART_SKIP_CFN") == "1":
        return {}
    exports: dict[str, str] = {}
    try:
        cfn = boto3.client("cloudformation", region_name=AWS_REGION)
        for page in cfn.get_paginator("list_exports").paginate():
            for exp in page.get("Exports", []):
                if exp["Name"].startswith(f"{PROJECT_NAME}-"):
                    exports[exp["Name"]] = exp["Value"]
    except Exception:  # no credentials / no stack yet
        pass
    return exports


def _resolve(env_name: str, export_suffix: str | None = None, default: str = "") -> str:
    value = os.getenv(env_name)
    if value:
        return value
    if export_suffix:
        value = _stack_exports().get(f"{PROJECT_NAME}-{export_suffix}")
        if value:
            return value
    return default


# ---------------------------------------------------------------- models
# Claude Haiku 4.5 for fast deterministic routing, Claude Sonnet 4.5 for workers.
ORCHESTRATOR_MODEL_ID = os.getenv(
    "ORCHESTRATOR_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
)
WORKER_MODEL_ID = os.getenv(
    "WORKER_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
)
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"

# ------------------------------------------------- foundation stack values
ORDERS_TABLE = _resolve("ORDERS_TABLE", "OrdersTable", f"{PROJECT_NAME}-orders")
CUSTOMERS_TABLE = _resolve("CUSTOMERS_TABLE", "CustomersTable", f"{PROJECT_NAME}-customers")
WORKFLOW_STATE_TABLE = _resolve(
    "WORKFLOW_STATE_TABLE", "WorkflowStateTable", f"{PROJECT_NAME}-workflow-state"
)
POLICY_BUCKET = _resolve("POLICY_BUCKET", "PolicyBucket")
VECTOR_BUCKET = _resolve("VECTOR_BUCKET", "VectorBucket")
VECTOR_BUCKET_ARN = _resolve("VECTOR_BUCKET_ARN", "VectorBucketArn")
RETURNS_VECTOR_INDEX = "returns-policy-index"
SHIPPING_VECTOR_INDEX = "shipping-policy-index"
WARRANTY_VECTOR_INDEX = "warranty-policy-index"
AGENT_LOG_GROUP = _resolve("AGENT_LOG_GROUP", "AgentLogGroup", f"/{PROJECT_NAME}/agents")
AGENTCORE_ROLE_ARN = _resolve("AGENTCORE_ROLE_ARN", "AgentCoreRoleArn")

# ----------------------------------------- values you fill in task by task
RETURNS_KB_ID = os.getenv("RETURNS_KB_ID", "")
SHIPPING_KB_ID = os.getenv("SHIPPING_KB_ID", "")
WARRANTY_KB_ID = os.getenv("WARRANTY_KB_ID", "")
GUARDRAIL_ID = os.getenv("GUARDRAIL_ID", "")
GUARDRAIL_VERSION = os.getenv("GUARDRAIL_VERSION", "")
AGENTCORE_RUNTIME_ARN = os.getenv("AGENTCORE_RUNTIME_ARN", "")
MEMORY_ARN = os.getenv("MEMORY_ARN", "")

# ------------------------------------------------------- naming constants
GUARDRAIL_NAME = "novamart-support-guardrail"
MEMORY_NAME = "NovaMartSupportMemory"
RUNTIME_PROJECT_NAME = "NovaMartSupport"   # AgentCore CLI project (alnum, <=23)
RUNTIME_AGENT_NAME = "NovaMartOrchestrator"
KB_NAMES = {
    "returns": "novamart-returns-policy-kb",
    "shipping": "novamart-shipping-policy-kb",
    "warranty": "novamart-warranty-policy-kb",
}

# Business rules
RETURN_WINDOW_DAYS = {"Standard": 30, "Premium": 60}


def update_env_file(key: str, value: str) -> None:
    """Insert or replace KEY=value in the project .env file (and os.environ)."""
    os.environ[key] = value
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    out, found = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == key:
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(out) + "\n")
    globals()[key] = value


def as_table() -> list[tuple[str, str]]:
    rows = [
        ("AWS Region", AWS_REGION),
        ("Project Name", PROJECT_NAME),
        ("Orchestrator Model", ORCHESTRATOR_MODEL_ID),
        ("Worker Model", WORKER_MODEL_ID),
        ("Orders Table", ORDERS_TABLE),
        ("Customers Table", CUSTOMERS_TABLE),
        ("WorkflowState Table", WORKFLOW_STATE_TABLE),
        ("Policy Bucket", POLICY_BUCKET),
        ("Vector Bucket", VECTOR_BUCKET),
        ("Vector Indexes", f"{RETURNS_VECTOR_INDEX}, {SHIPPING_VECTOR_INDEX}, {WARRANTY_VECTOR_INDEX}"),
        ("Agent Log Group", AGENT_LOG_GROUP),
        ("AgentCore Role ARN", AGENTCORE_ROLE_ARN),
        ("Returns KB ID", RETURNS_KB_ID),
        ("Shipping KB ID", SHIPPING_KB_ID),
        ("Warranty KB ID", WARRANTY_KB_ID),
        ("Guardrail ID", GUARDRAIL_ID),
        ("Guardrail Version", GUARDRAIL_VERSION),
        ("AgentCore Runtime ARN", AGENTCORE_RUNTIME_ARN),
        ("Memory ARN", MEMORY_ARN),
    ]
    return [(k, v or "(not yet created)") for k, v in rows]


if __name__ == "__main__":
    rows = as_table()
    width = max(len(k) for k, _ in rows)
    print("\nNovaMart configuration\n" + "=" * (width + 60))
    for key, value in rows:
        print(f"{key:<{width}}  {value}")
    print()
    if not _stack_exports():
        print("WARNING: no CloudFormation exports found - is the "
              f"'{PROJECT_NAME}' stack deployed in {AWS_REGION} and are your credentials valid?")

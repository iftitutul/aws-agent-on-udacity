"""Shared helpers for the AgentCore support-chatbot scripts.

Everything the individual scripts have in common lives here: constants, the config file that
carries IDs between steps, boto3 client construction, session-ID generation, and a tolerant
wrapper around the AgentCore control/data-plane calls.

Why the tolerant wrapper: the AgentCore managed-harness APIs are new and the exact operation
names shipped in different boto3 releases (`create_harness` / `create_agent_harness`,
`invoke_harness` / `invoke_agent_harness`). Rather than pinning one name and failing with an
opaque AttributeError, `call_first_available` tries the known aliases and, if none exist, raises
an error that lists the operations the installed boto3 actually exposes. That turns a five-minute
debugging session into a one-line fix.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

import boto3
from botocore.config import Config

# --------------------------------------------------------------------------- constants
REGION = os.environ.get("AWS_REGION", "us-east-1")

# Pinned everywhere: the harness default model needs a Marketplace subscription that lab
# accounts cannot complete.
MODEL_ID = "us.amazon.nova-pro-v1:0"

HARNESS_NAME = os.environ.get("HARNESS_NAME", "support-chatbot-harness")
GATEWAY_NAME = os.environ.get("GATEWAY_NAME", "support-chatbot-gateway")
GATEWAY_TARGET_NAME = "bugreports"  # model sees the tool as bugreports___create_bug_report
TOOL_NAME = f"{GATEWAY_TARGET_NAME}___create_bug_report"

TOOL_STACK_NAME = os.environ.get("TOOL_STACK_NAME", "bug-report-tool-stack")
TESTING_STACK_NAME = os.environ.get("TESTING_STACK_NAME", "bug-report-testing-stack")

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "agentcore_config.json"
SYSTEM_PROMPT_PATH = HERE / "system_prompt.txt"

BOTO_CONFIG = Config(
    region_name=REGION,
    retries={"max_attempts": 8, "mode": "adaptive"},
    read_timeout=180,
    connect_timeout=15,
)


# ----------------------------------------------------------------------------- clients
def control_client():
    """AgentCore control plane: gateways, gateway targets, harnesses."""
    return boto3.client("bedrock-agentcore-control", config=BOTO_CONFIG)


def data_client():
    """AgentCore data plane: invoking the harness."""
    return boto3.client("bedrock-agentcore", config=BOTO_CONFIG)


def cfn_client():
    return boto3.client("cloudformation", config=BOTO_CONFIG)


def call_first_available(client, candidates, **kwargs):
    """Call the first operation in `candidates` that the client actually exposes."""
    for name in candidates:
        method = getattr(client, name, None)
        if callable(method):
            return name, method(**kwargs)
    available = sorted(
        op
        for op in dir(client)
        if not op.startswith("_") and re.search(r"harness|gateway", op, re.I)
    )
    raise RuntimeError(
        "None of these operations exist on this boto3 client: "
        + ", ".join(candidates)
        + ".\nUpgrade boto3 (`pip install -U -r requirements.txt`, 1.43+ required) or use one of "
        "the available operations: "
        + (", ".join(available) or "<none found>")
    )


# ------------------------------------------------------------------------------ config
def load_config(required=()):
    """Read agentcore_config.json, checking that the given keys are present."""
    if not CONFIG_PATH.exists():
        raise SystemExit(
            f"{CONFIG_PATH.name} not found. Run setup_gateway.py (and then create_harness.py) first."
        )
    config = json.loads(CONFIG_PATH.read_text())
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise SystemExit(
            f"{CONFIG_PATH.name} is missing {', '.join(missing)}. "
            "Run setup_gateway.py and create_harness.py, then try again."
        )
    return config


def save_config(updates):
    """Merge `updates` into agentcore_config.json and return the merged config."""
    config = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    config.update(updates)
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")
    return config


def stack_outputs(stack_name):
    """Return the outputs of a CloudFormation stack as a plain dict."""
    try:
        stacks = cfn_client().describe_stacks(StackName=stack_name)["Stacks"]
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"Could not read stack '{stack_name}' in {REGION}: {exc}\n"
            "Deploy it first with `aws cloudformation deploy ...` (see docs/SETUP.md)."
        ) from exc
    return {o["OutputKey"]: o["OutputValue"] for o in stacks[0].get("Outputs", [])}


def read_system_prompt():
    if not SYSTEM_PROMPT_PATH.exists():
        raise SystemExit(f"{SYSTEM_PROMPT_PATH} not found.")
    prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
    if not prompt:
        raise SystemExit("system_prompt.txt is empty — write the prompt before creating the harness.")
    return prompt


# ---------------------------------------------------------------------------- sessions
def new_session_id(label="session"):
    """AgentCore requires a runtime session ID of at least 33 characters."""
    safe = re.sub(r"[^A-Za-z0-9-]", "-", label)[:20]
    return f"{safe}-{uuid.uuid4().hex}{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------------------- invocation
def invoke_harness(harness_arn, gateway_arn, session_id, text):
    """Send one customer turn to the harness. Returns (reply_text, tool_calls)."""
    _, response = call_first_available(
        data_client(),
        ["invoke_harness", "invoke_agent_harness", "invoke_agent_runtime"],
        harnessArn=harness_arn,
        runtimeSessionId=session_id,
        modelId=MODEL_ID,
        gatewayArns=[gateway_arn] if gateway_arn else [],
        inputText=text,
    )
    return extract_reply(response)


def extract_reply(response):
    """Pull the assistant text and any tool-call names out of a harness response.

    The response shape varies (streamed chunks, a `completion` iterator, or a plain dict), so
    walk the structure instead of assuming one layout.
    """
    text_parts = []
    tool_calls = []

    def walk(node):
        if isinstance(node, dict):
            if "text" in node and isinstance(node["text"], str):
                text_parts.append(node["text"])
            for key in ("outputText", "completion", "content", "message", "output"):
                if key in node and key != "text":
                    walk(node[key])
            for key in ("toolUse", "tool_use", "mcp_tool_use"):
                if key in node and isinstance(node[key], dict):
                    name = node[key].get("name") or node[key].get("toolName")
                    if name:
                        tool_calls.append(name)
            for key, value in node.items():
                if key not in ("text", "outputText", "completion", "content", "message", "output"):
                    if isinstance(value, (dict, list)):
                        walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, (bytes, bytearray)):
            try:
                walk(json.loads(node.decode("utf-8")))
            except Exception:  # noqa: BLE001
                text_parts.append(node.decode("utf-8", errors="replace"))

    body = response.get("response") or response.get("body") or response
    if hasattr(body, "read"):
        raw = body.read()
        try:
            walk(json.loads(raw))
        except Exception:  # noqa: BLE001
            text_parts.append(raw.decode("utf-8", errors="replace"))
    else:
        walk(body)

    reply = "\n".join(part.strip() for part in text_parts if part and part.strip())
    return reply.strip(), tool_calls

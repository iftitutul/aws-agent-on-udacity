#!/usr/bin/env python3
"""Create (or update) the AgentCore managed harness from system_prompt.txt.

Re-run this every time system_prompt.txt changes — the prompt is baked into the harness
configuration, so an edit on disk has no effect until the harness is updated.

Usage:
    python create_harness.py
    python create_harness.py --name my-harness
"""

from __future__ import annotations

import argparse
import re
import time

from agentcore_common import (
    HARNESS_NAME,
    MODEL_ID,
    REGION,
    call_first_available,
    control_client,
    load_config,
    read_system_prompt,
    save_config,
)


def find_existing(client, name):
    """Return the ARN/ID of a harness with this name, if one already exists."""
    for op in ("list_harnesses", "list_agent_harnesses"):
        method = getattr(client, op, None)
        if not callable(method):
            continue
        response = method(maxResults=100)
        while True:
            items = response.get("harnesses") or response.get("harnessSummaries") or response.get("items") or []
            for item in items:
                if item.get("harnessName") == name or item.get("name") == name:
                    return item.get("harnessId") or item.get("id"), item.get("harnessArn") or item.get("arn")
            next_token = response.get("nextToken")
            if not next_token:
                break
            response = method(maxResults=100, nextToken=next_token)
    return None


def wait_for_harness_ready(client, harness_id, attempts=40, delay=15):
    for attempt in range(1, attempts + 1):
        response = client.get_harness(harnessId=harness_id).get("harness", {})
        status = response.get("status")
        if status == "READY":
            return
        if status in {"FAILED", "DELETING", "DELETED"}:
            raise RuntimeError(f"Harness {harness_id} entered terminal status {status}")
        if attempt < attempts:
            print(f"  harness status: {status or 'unknown'}; retry {attempt}/{attempts - 1} in {delay}s")
            time.sleep(delay)
    raise TimeoutError(f"Harness {harness_id} was not ready after {attempts * delay}s")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=HARNESS_NAME)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", args.name):
        parser.error("--name must start with a letter and contain only letters, digits, or underscores (max 40 characters)")

    config = load_config(required=("gatewayArn", "harnessRoleArn"))
    prompt = read_system_prompt()
    print(f"Region: {REGION}")
    print(f"Model:  {MODEL_ID}")
    print(f"Prompt: system_prompt.txt ({len(prompt):,} characters)")

    client = control_client()
    existing = find_existing(client, args.name)

    common = {
        "harnessName": args.name,
        "executionRoleArn": config["harnessRoleArn"],
        "model": {"bedrockModelConfig": {"modelId": MODEL_ID}},
        "systemPrompt": [{"text": prompt}],
        "tools": [
            {
                "type": "agentcore_gateway",
                "name": "bugreports",
                "config": {
                    "agentCoreGateway": {"gatewayArn": config["gatewayArn"]}
                },
            }
        ],
    }

    if existing:
        harness_id, _ = existing
        wait_for_harness_ready(client, harness_id)
        print(f"Harness '{args.name}' exists ({harness_id}) — updating with the current prompt ...")
        _, response = call_first_available(
            client,
            ["update_harness", "update_agent_harness"],
            harnessId=harness_id,
            **{k: v for k, v in common.items() if k != "harnessName"},
        )
    else:
        print(f"Creating harness '{args.name}' ...")
        _, response = call_first_available(
            client, ["create_harness", "create_agent_harness"], **common
        )

    harness_id = response.get("harnessId") or response.get("id") or (existing and existing[0])
    harness_arn = response.get("harnessArn") or response.get("arn") or (existing and existing[1])
    if harness_id and not harness_arn:
        harness = client.get_harness(harnessId=harness_id).get("harness", {})
        harness_arn = harness.get("harnessArn") or harness.get("arn")

    save_config({"harnessName": args.name, "harnessId": harness_id, "harnessArn": harness_arn, "modelId": MODEL_ID})

    print(f"  harness id:  {harness_id}")
    print(f"  harness arn: {harness_arn}")
    print("\nNext: `python chat.py` to try it, or `python generate-eval-dataset.py --tests-json harness-tests.json`.")


if __name__ == "__main__":
    main()

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
        try:
            items = method().get("harnessSummaries") or method().get("items") or []
        except Exception:  # noqa: BLE001
            return None
        for item in items:
            if item.get("name") == name:
                return item.get("harnessId") or item.get("id"), item.get("harnessArn") or item.get("arn")
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=HARNESS_NAME)
    args = parser.parse_args()

    config = load_config(required=("gatewayArn", "harnessRoleArn"))
    prompt = read_system_prompt()
    print(f"Region: {REGION}")
    print(f"Model:  {MODEL_ID}")
    print(f"Prompt: system_prompt.txt ({len(prompt):,} characters)")

    client = control_client()
    existing = find_existing(client, args.name)

    common = {
        "name": args.name,
        "description": "Nimbus Market customer support chatbot.",
        "instructions": prompt,
        "modelId": MODEL_ID,
        "roleArn": config["harnessRoleArn"],
        "gatewayArns": [config["gatewayArn"]],
    }

    if existing:
        harness_id, _ = existing
        print(f"Harness '{args.name}' exists ({harness_id}) — updating with the current prompt ...")
        _, response = call_first_available(
            client,
            ["update_harness", "update_agent_harness"],
            harnessIdentifier=harness_id,
            **{k: v for k, v in common.items() if k != "name"},
        )
    else:
        print(f"Creating harness '{args.name}' ...")
        _, response = call_first_available(
            client, ["create_harness", "create_agent_harness"], **common
        )

    harness_id = response.get("harnessId") or response.get("id")
    harness_arn = response.get("harnessArn") or response.get("arn")

    save_config({"harnessName": args.name, "harnessId": harness_id, "harnessArn": harness_arn, "modelId": MODEL_ID})

    print(f"  harness id:  {harness_id}")
    print(f"  harness arn: {harness_arn}")
    print("\nNext: `python chat.py` to try it, or `python generate-eval-dataset.py --tests-json harness-tests.json`.")


if __name__ == "__main__":
    main()

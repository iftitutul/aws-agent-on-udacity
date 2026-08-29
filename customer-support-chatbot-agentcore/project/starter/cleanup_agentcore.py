#!/usr/bin/env python3
"""Delete the AgentCore resources created by this project.

Deletes in dependency order: harness, then gateway target, then gateway. Everything is read
from agentcore_config.json. Failures on individual resources are reported but do not stop the
run, so a partially torn-down environment can be finished off by re-running the script.

CloudFormation stacks are deleted separately — see docs/SETUP.md.

Usage:
    python cleanup_agentcore.py
    python cleanup_agentcore.py --yes     # skip the confirmation prompt
"""

from __future__ import annotations

import argparse

from agentcore_common import CONFIG_PATH, call_first_available, control_client, load_config


def delete(label, fn):
    print(f"Deleting {label} ... ", end="", flush=True)
    try:
        fn()
        print("done")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"failed: {exc}")
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation.")
    args = parser.parse_args()

    config = load_config()
    client = control_client()

    print("About to delete:")
    print(f"  harness:        {config.get('harnessId') or '<none recorded>'}")
    print(f"  gateway target: {config.get('gatewayTargetId') or '<none recorded>'}")
    print(f"  gateway:        {config.get('gatewayId') or '<none recorded>'}")

    if not args.yes:
        if input("\nProceed? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return

    if config.get("harnessId"):
        delete(
            "harness",
            lambda: call_first_available(
                client,
                ["delete_harness", "delete_agent_harness"],
                harnessIdentifier=config["harnessId"],
            ),
        )

    if config.get("gatewayId") and config.get("gatewayTargetId"):
        delete(
            "gateway target",
            lambda: call_first_available(
                client,
                ["delete_gateway_target"],
                gatewayIdentifier=config["gatewayId"],
                targetId=config["gatewayTargetId"],
            ),
        )

    if config.get("gatewayId"):
        delete(
            "gateway",
            lambda: call_first_available(
                client, ["delete_gateway"], gatewayIdentifier=config["gatewayId"]
            ),
        )

    print(
        "\nAgentCore resources removed. Remaining cleanup:\n"
        "  aws s3 rm s3://<EvalDatasetBucketName> --recursive --region us-east-1\n"
        "  aws cloudformation delete-stack --stack-name bug-report-testing-stack --region us-east-1\n"
        "  aws cloudformation delete-stack --stack-name bug-report-tool-stack --region us-east-1\n"
        f"\nYou can also delete {CONFIG_PATH.name} once the stacks are gone."
    )


if __name__ == "__main__":
    main()

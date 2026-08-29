#!/usr/bin/env python3
"""Create the AgentCore Gateway and register the bug-report Lambda as a tool.

Reads the outputs of the tool CloudFormation stack directly (no copy-pasting of ARNs), creates
the gateway, attaches a Lambda target called `bugreports`, and records everything the later
steps need in agentcore_config.json.

Usage:
    python setup_gateway.py
    python setup_gateway.py --stack-name my-stack
"""

from __future__ import annotations

import argparse
import sys
import time

from botocore.exceptions import ClientError

from agentcore_common import (
    GATEWAY_NAME,
    GATEWAY_TARGET_NAME,
    REGION,
    TOOL_STACK_NAME,
    call_first_available,
    control_client,
    save_config,
    stack_outputs,
)

TOOL_SCHEMA = {
    "name": "create_bug_report",
    "description": (
        "File a bug report ticket for the Nimbus Market shop. Call this only once the bug "
        "description, the steps to reproduce, and the customer's environment have all been "
        "collected and confirmed. Returns the ticket ID to give back to the customer."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "What goes wrong, in the customer's own words.",
            },
            "stepsToReproduce": {
                "type": "string",
                "description": "The sequence of actions that triggers the problem.",
            },
            "environment": {
                "type": "string",
                "description": "Device, operating system, and browser or app version.",
            },
        },
        "required": ["description", "stepsToReproduce", "environment"],
    },
}

RETRYABLE = ("AccessDenied", "ValidationException", "AccessDeniedException")


def with_iam_retry(fn, attempts=6, delay=15):
    """IAM role propagation is eventually consistent; retry the first calls after the stack."""
    last = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            message = str(exc)
            if code in RETRYABLE and "role" in message.lower() and attempt < attempts:
                print(f"  IAM not propagated yet ({code}), retry {attempt}/{attempts - 1} in {delay}s")
                time.sleep(delay)
                last = exc
                continue
            raise
    raise last


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-name", default=TOOL_STACK_NAME)
    parser.add_argument("--gateway-name", default=GATEWAY_NAME)
    args = parser.parse_args()

    print(f"Region: {REGION}")
    print(f"Reading outputs of stack '{args.stack_name}' ...")
    outputs = stack_outputs(args.stack_name)
    for key in ("GatewayRoleArn", "CreateBugReportFunctionArn", "HarnessRoleArn"):
        if key not in outputs:
            sys.exit(f"Stack output '{key}' not found. Did the tool stack deploy successfully?")
    print(f"  lambda:       {outputs['CreateBugReportFunctionArn']}")
    print(f"  gateway role: {outputs['GatewayRoleArn']}")

    client = control_client()

    print(f"Creating gateway '{args.gateway_name}' ...")
    _, gateway = with_iam_retry(
        lambda: call_first_available(
            client,
            ["create_gateway"],
            name=args.gateway_name,
            roleArn=outputs["GatewayRoleArn"],
            protocolType="MCP",
            authorizerType="AWS_IAM",
            description="Exposes the create_bug_report Lambda to the support chatbot harness.",
        )[1]
    )
    gateway_id = gateway.get("gatewayId") or gateway.get("id")
    gateway_arn = gateway.get("gatewayArn") or gateway.get("arn")
    gateway_url = gateway.get("gatewayUrl") or gateway.get("url")
    print(f"  gateway id:  {gateway_id}")

    print(f"Registering Lambda target '{GATEWAY_TARGET_NAME}' ...")
    _, target = with_iam_retry(
        lambda: call_first_available(
            client,
            ["create_gateway_target"],
            gatewayIdentifier=gateway_id,
            name=GATEWAY_TARGET_NAME,
            description="Bug report ticket creation.",
            targetConfiguration={
                "mcp": {
                    "lambda": {
                        "lambdaArn": outputs["CreateBugReportFunctionArn"],
                        "toolSchema": {"inlinePayload": [TOOL_SCHEMA]},
                    }
                }
            },
            credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
        )[1]
    )
    target_id = target.get("targetId") or target.get("id")
    print(f"  target id:   {target_id}")
    print(f"  tool name:   {GATEWAY_TARGET_NAME}___create_bug_report")

    config = save_config(
        {
            "region": REGION,
            "toolStackName": args.stack_name,
            "gatewayName": args.gateway_name,
            "gatewayId": gateway_id,
            "gatewayArn": gateway_arn,
            "gatewayUrl": gateway_url,
            "gatewayTargetName": GATEWAY_TARGET_NAME,
            "gatewayTargetId": target_id,
            "lambdaArn": outputs["CreateBugReportFunctionArn"],
            "harnessRoleArn": outputs["HarnessRoleArn"],
            "bugReportsTableName": outputs.get("BugReportsTableName"),
        }
    )

    print("\nSaved agentcore_config.json:")
    for key in ("gatewayId", "gatewayArn", "gatewayTargetId", "harnessRoleArn"):
        print(f"  {key}: {config.get(key)}")
    print("\nNext: write system_prompt.txt, then run `python create_harness.py`.")


if __name__ == "__main__":
    main()

"""Delete every AWS resource this project created.

    python infrastructure/cleanup.py          # dry run - lists what would be deleted
    python infrastructure/cleanup.py --yes    # actually deletes

Order: AgentCore runtime stack -> Memory -> Guardrail -> Knowledge Bases ->
empty S3 policy bucket -> foundation CloudFormation stack.
The CDK bootstrap stack (CDKToolkit) is shared account-wide and is left alone.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import boto3  # noqa: E402

import config  # noqa: E402

DELETE = "--yes" in sys.argv
R = config.AWS_REGION


def act(msg: str, fn=None) -> None:
    print(("  DELETE " if DELETE else "  would delete ") + msg)
    if DELETE and fn:
        try:
            fn()
        except Exception as exc:  # keep going - best effort
            print(f"    ! {exc}")


def main() -> None:
    cfn = boto3.client("cloudformation", region_name=R)
    print(f"NovaMart cleanup in {R} ({'LIVE' if DELETE else 'dry run'})")

    # 1. AgentCore CLI runtime stack(s)
    for page in cfn.get_paginator("list_stacks").paginate(
        StackStatusFilter=["CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE",
                           "ROLLBACK_COMPLETE", "CREATE_FAILED", "UPDATE_FAILED"]):
        for s in page["StackSummaries"]:
            if s["StackName"].startswith(f"AgentCore-{config.RUNTIME_PROJECT_NAME}"):
                act(f"CloudFormation stack {s['StackName']} (AgentCore runtime)",
                    lambda n=s["StackName"]: (cfn.delete_stack(StackName=n),
                                              cfn.get_waiter("stack_delete_complete").wait(StackName=n)))

    # 2. AgentCore Memory
    ctrl = boto3.client("bedrock-agentcore-control", region_name=R)
    try:
        for m in ctrl.list_memories().get("memories", []):
            if m["id"].startswith(config.MEMORY_NAME):
                act(f"AgentCore memory {m['id']}", lambda i=m["id"]: ctrl.delete_memory(memoryId=i))
    except Exception as exc:
        print(f"  (memory listing failed: {exc})")

    # 3. Guardrail
    bedrock = boto3.client("bedrock", region_name=R)
    for g in bedrock.list_guardrails().get("guardrails", []):
        if g["name"] == config.GUARDRAIL_NAME:
            act(f"guardrail {g['name']} ({g['id']})",
                lambda i=g["id"]: bedrock.delete_guardrail(guardrailIdentifier=i))

    # 4. Knowledge Bases (+ data sources)
    agent = boto3.client("bedrock-agent", region_name=R)
    for kb in agent.list_knowledge_bases(maxResults=100).get("knowledgeBaseSummaries", []):
        if kb["name"] in config.KB_NAMES.values():
            def _del_kb(kb_id=kb["knowledgeBaseId"]):
                for ds in agent.list_data_sources(knowledgeBaseId=kb_id).get("dataSourceSummaries", []):
                    agent.delete_data_source(knowledgeBaseId=kb_id, dataSourceId=ds["dataSourceId"])
                time.sleep(5)
                agent.delete_knowledge_base(knowledgeBaseId=kb_id)
            act(f"knowledge base {kb['name']} ({kb['knowledgeBaseId']})", _del_kb)

    # 5. Empty the policy bucket so the stack can delete it
    if config.POLICY_BUCKET:
        def _empty():
            bucket = boto3.resource("s3", region_name=R).Bucket(config.POLICY_BUCKET)
            bucket.object_versions.delete()
            bucket.objects.all().delete()
        act(f"all objects in s3://{config.POLICY_BUCKET}", _empty)

    # 6. Foundation stack (tables, buckets, vector indexes, role, log group)
    act(f"CloudFormation stack {config.PROJECT_NAME} (foundation)",
        lambda: (cfn.delete_stack(StackName=config.PROJECT_NAME),
                 cfn.get_waiter("stack_delete_complete").wait(StackName=config.PROJECT_NAME)))

    if not DELETE:
        print("\nDry run only. Re-run with --yes to delete.")
    else:
        print("\nCleanup finished. Remove AGENTCORE_RUNTIME_ARN / GUARDRAIL_* / *_KB_ID from .env.")


if __name__ == "__main__":
    main()

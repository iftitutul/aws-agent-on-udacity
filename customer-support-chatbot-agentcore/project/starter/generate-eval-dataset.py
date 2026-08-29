#!/usr/bin/env python3
"""Run the harness against a test suite and write a Bedrock Evaluations JSONL dataset.

Each test runs as a single turn in a brand-new session, so tests cannot influence one another.
The output file has one JSON object per line:

    {"prompt": ..., "referenceResponse": ..., "modelResponses": [{"response": ..., "modelIdentifier": ...}]}

Usage:
    python generate-eval-dataset.py --tests-json harness-tests.json
    python generate-eval-dataset.py --tests-json harness-tests.json --out my_dataset.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from agentcore_common import (
    MODEL_ID,
    TOOL_NAME,
    invoke_harness,
    load_config,
    new_session_id,
)

DEFAULT_IDENTIFIER = "my-support-chatbot"
ERROR_PREFIX = "[HARNESS_ERROR]"


def load_tests(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tests = data.get("tests")
    if not tests:
        raise SystemExit(f"{path} contains no `tests` array.")
    seen = set()
    for test in tests:
        for field in ("id", "prompt", "expected"):
            if not test.get(field):
                raise SystemExit(f"Test {test.get('id', '<no id>')} is missing '{field}'.")
        if test["id"] in seen:
            raise SystemExit(f"Duplicate test id: {test['id']}")
        seen.add(test["id"])
    return tests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests-json", default="harness-tests.json")
    parser.add_argument("--out", default="output_eval_dataset.jsonl")
    parser.add_argument("--model-identifier", default=DEFAULT_IDENTIFIER)
    parser.add_argument("--sleep", type=float, default=1.0, help="Pause between calls (throttling).")
    args = parser.parse_args()

    tests = load_tests(args.tests_json)
    config = load_config(required=("harnessArn",))
    harness_arn = config["harnessArn"]
    gateway_arn = config.get("gatewayArn")

    print(f"harness: {harness_arn}")
    print(f"model:   {MODEL_ID}")
    print(f"tool:    {TOOL_NAME}")
    print(f"tests:   {len(tests)} from {args.tests_json}\n")

    failures = 0
    with open(args.out, "w", encoding="utf-8") as handle:
        for index, test in enumerate(tests, start=1):
            session_id = new_session_id(test["id"])
            print(f"[{index}/{len(tests)}] {test['id']} ... ", end="", flush=True)
            try:
                reply, tool_calls = invoke_harness(
                    harness_arn, gateway_arn, session_id, test["prompt"]
                )
                if not reply:
                    reply = f"{ERROR_PREFIX} empty response from harness"
                    failures += 1
                    print("empty response")
                else:
                    print("ok" + (f" (tools: {', '.join(tool_calls)})" if tool_calls else ""))
            except Exception as exc:  # noqa: BLE001
                reply = f"{ERROR_PREFIX} {type(exc).__name__}: {exc}"
                failures += 1
                print("failed")
                print(f"    {exc}", file=sys.stderr)

            record = {
                "prompt": test["prompt"],
                "referenceResponse": test["expected"],
                "modelResponses": [
                    {"response": reply, "modelIdentifier": args.model_identifier}
                ],
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"    wrote eval line for {test['id']}")
            if args.sleep and index < len(tests):
                time.sleep(args.sleep)

    print(f"\nWrote {len(tests)} lines to {args.out} ({failures} failed).")
    if failures:
        print("Fix the failures before uploading — [HARNESS_ERROR] lines will score as incorrect.")
    print(
        "\nNext:\n"
        f"  aws s3 cp {args.out} s3://<EvalDatasetBucketName>/{args.out} --region us-east-1\n"
        "  aws bedrock create-evaluation-job ...   (see docs/TESTING.md)"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

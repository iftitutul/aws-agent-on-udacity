# Customer Support Chatbot — Amazon Bedrock AgentCore

> **Note for reviewers:** the classic/legacy Bedrock Flows builder used in the original rubric is
> deprecated and was not available for this submission, so this project is built on the newer
> **AgentCore managed harness** instead, with prompt-based routing in place of Flow condition
> nodes. [`docs/RUBRIC_MAPPING.md`](docs/RUBRIC_MAPPING.md) maps every rubric criterion (flow,
> classifier node, condition node, output nodes, etc.) to its AgentCore equivalent and the
> artefact that satisfies it here — please review against that mapping rather than looking for a
> Flow resource in the console.

A customer support chatbot for a fictional online shop (Nimbus Market), built on the Amazon
Bedrock **AgentCore managed harness**. All routing, information gathering and grounding behaviour
lives in a single system prompt — there are no condition nodes and no separate classifier model.

The chatbot handles three kinds of message:

| Route | Trigger | Behaviour |
| --- | --- | --- |
| Bug report | Something on the site or app is broken | Collects description, steps to reproduce and environment across turns, confirms them, then files a ticket via the `bugreports___create_bug_report` tool and returns the ticket ID |
| Platform question | Orders, shipping, returns, payments, products, account, privacy | Answers **only** from the FAQ embedded in the prompt |
| Other | Anything else | Politely redirects to the human support line |

---

## Architecture

```
 customer ──► chat.py / generate-eval-dataset.py
                     │  InvokeHarness (runtimeSessionId = stateful session)
                     ▼
        ┌────────────────────────────────┐
        │  AgentCore managed harness     │   model: us.amazon.nova-pro-v1:0
        │  instructions = system_prompt  │   agent loop + session memory
        └───────────────┬────────────────┘
                        │  tool call: bugreports___create_bug_report
                        ▼
              AgentCore Gateway (MCP)
                        │  gateway role assumes → lambda:InvokeFunction
                        ▼
       Lambda: bug-report-tool-stack-create-bug-report
                        │  PutItem
                        ▼
       DynamoDB: bug-report-tool-stack-bug-reports

 testing:  harness-tests.json ──► generate-eval-dataset.py ──► output_eval_dataset.jsonl
                                       │
                                       ▼   S3 upload
                          Bedrock Evaluations (LLM-as-a-judge, Builtin.Correctness)
```

Full detail in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Repository layout

```
.
├── README.md                     ← you are here
├── LICENSE
├── Makefile                      ← every command in the workflow, as a named target
├── requirements.txt
├── docs/
│   ├── ARCHITECTURE.md           design decisions and how the pieces fit
│   ├── SETUP.md                  deploy, gateway, harness, first chat
│   ├── TESTING.md                test suite, eval dataset, Bedrock Evaluations job
│   ├── PROMPT_DESIGN.md          why the prompt is written the way it is
│   ├── OBSERVATIONS.md           evaluation results write-up (rubric deliverable)
│   ├── RUBRIC_MAPPING.md         rubric criterion → file / evidence
│   ├── CLEANUP.md                tear-down order
│   └── evidence/                 screenshots go here
├── project/starter/              everything runnable — run all commands from this folder
│   ├── system_prompt.txt         ★ main deliverable
│   ├── online_shop_faq.md        source FAQ (embedded verbatim in the prompt)
│   ├── agentcore_common.py       shared config/client/session helpers
│   ├── setup_gateway.py          creates gateway + registers the Lambda tool
│   ├── create_harness.py         creates/updates the harness from system_prompt.txt
│   ├── chat.py                   multi-turn terminal client
│   ├── generate-eval-dataset.py  test runner → JSONL
│   ├── cleanup_agentcore.py      tear-down for harness/target/gateway
│   ├── create_bug_report.py      Lambda source (mirrored in the tool template)
│   ├── cloudformation-tool.yaml  DynamoDB + Lambda + 3 IAM roles
│   ├── cloudformation-testing.yaml  eval S3 bucket + Bedrock Evaluations role
│   ├── harness-tests.json        ★ 14-case test suite (also copied as flow-tests.json)
│   ├── harness-tests-template.json
│   └── examples/                 reference transcript and JSONL shapes
└── tests/                        offline sanity checks (pytest, no AWS calls)
```

`flow-tests.json` is a byte-identical copy of `harness-tests.json`. The rubric text still uses the
older Flows-era filename; keeping both means the file is where a reviewer looks for it under
either name.

---

## Quick start

```bash
cd project/starter
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export AWS_REGION=us-east-1

# 1. infrastructure
aws cloudformation deploy \
  --template-file cloudformation-tool.yaml \
  --stack-name bug-report-tool-stack \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1

# 2. gateway + tool registration
python setup_gateway.py

# 3. harness from the system prompt (re-run after every prompt edit)
python create_harness.py

# 4. try it
python chat.py --transcript examples/chat_transcript_bug_report.md

# 5. test + evaluate
python generate-eval-dataset.py --tests-json harness-tests.json
```

Or, from the repository root, `make deploy && make harness && make chat && make dataset`.
Every step is documented in [`docs/SETUP.md`](docs/SETUP.md) and
[`docs/TESTING.md`](docs/TESTING.md).

---

## Conventions

- **Region is `us-east-1` everywhere.** Some regions do not have all AgentCore features.
- **The model is pinned to `us.amazon.nova-pro-v1:0`** in the harness, in the invoke calls, and in
  the evaluator config. The harness default model needs an AWS Marketplace subscription that lab
  accounts cannot complete.
- **`agentcore_config.json` carries IDs between steps** and is written by `setup_gateway.py` and
  `create_harness.py`. It's tracked in git (not ignored) so the harness and gateway ARNs are
  visible as submission evidence — re-run those scripts and `git add` the file again if the ARNs
  change.
- **The prompt is the source of truth for behaviour.** After editing `system_prompt.txt`, run
  `create_harness.py` again or the change has no effect.

## Offline checks

`tests/` holds fast, AWS-free checks — valid JSON in the test suite, unique test IDs, all three
routes covered, the FAQ and phone number consistent between `online_shop_faq.md` and
`system_prompt.txt`, and the Lambda handler's validation logic:

```bash
pip install pytest
pytest -q
```

## Cleanup

```bash
cd project/starter
python cleanup_agentcore.py
aws s3 rm s3://<EvalDatasetBucketName> --recursive --region us-east-1
aws cloudformation delete-stack --stack-name bug-report-testing-stack --region us-east-1
aws cloudformation delete-stack --stack-name bug-report-tool-stack   --region us-east-1
```

The S3 bucket must be emptied before the testing stack is deleted, or the stack ends up in
`DELETE_FAILED`. Details in [`docs/CLEANUP.md`](docs/CLEANUP.md).

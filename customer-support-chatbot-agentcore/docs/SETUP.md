# Setup

All commands run from `project/starter/`.

## Prerequisites

- AWS account with Amazon Bedrock **and** Bedrock AgentCore enabled
- Model access granted for **Amazon Nova Pro** (`us.amazon.nova-pro-v1:0`) in `us-east-1`
- AWS CLI configured (`aws sts get-caller-identity` should succeed)
- Python 3.9+ and boto3 **1.43+**

```bash
cd project/starter
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -c "import boto3; print(boto3.__version__)"   # expect 1.43.76 or newer
export AWS_REGION=us-east-1
```

> Region matters. Every template, script and command in this project assumes `us-east-1`; smaller
> regions do not have all AgentCore features.

## Step 1 — Deploy the tool stack

```bash
aws cloudformation deploy \
  --template-file cloudformation-tool.yaml \
  --stack-name bug-report-tool-stack \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

`CAPABILITY_NAMED_IAM` is required because the template creates named roles. What you get:

| Resource | Name | Purpose |
| --- | --- | --- |
| DynamoDB table | `bug-report-tool-stack-bug-reports` | One item per bug report, keyed by `ticketId` |
| Lambda | `bug-report-tool-stack-create-bug-report` | The `create_bug_report` tool implementation |
| IAM role | `bug-report-tool-stack-lambda-role` | Logs + `PutItem` on the table |
| IAM role | `bug-report-tool-stack-gateway-role` | Lets the gateway invoke the Lambda |
| IAM role | `bug-report-tool-stack-harness-role` | Lets the harness call Bedrock and the gateway |

## Step 2 — Test the Lambda in isolation

Before wiring the tool into the prompt, confirm it works on its own. Lambda console →
`bug-report-tool-stack-create-bug-report` → **Test** → new test event:

```json
{
    "description": "The checkout page crashes when I click the Pay button",
    "stepsToReproduce": "1. Add an item to the cart. 2. Go to checkout. 3. Click Pay.",
    "environment": "Chrome 120 on macOS Sonoma"
}
```

The gateway passes tool arguments as the raw event — there is no `messageVersion`/`parameters`
envelope (that was Agents Classic). A successful run returns a `ticketId` and `"status": "OPEN"`.

📸 **Evidence:** screenshot of the test event and of the successful result →
`docs/evidence/01-lambda-test.png`

## Step 3 — Create the gateway and register the tool

```bash
python setup_gateway.py
```

The script reads the stack outputs itself and writes `agentcore_config.json`. The gateway target
is named `bugreports`, so the model sees the tool as **`bugreports___create_bug_report`**.

> If this fails immediately after the stack finishes with an access or validation error mentioning
> the role, that is IAM propagation delay. The script already retries; if it still fails, wait a
> minute and run it again.

## Step 4 — Create the harness

```bash
python create_harness.py
```

This reads `system_prompt.txt`, creates the harness with `us.amazon.nova-pro-v1:0` and the
harness role, attaches the gateway, and records the harness ARN in `agentcore_config.json`.

**Re-run this after every prompt edit.** The prompt is baked into the harness configuration; a
change on disk does nothing until the harness is updated.

## Step 5 — Chat with it

```bash
python chat.py --transcript examples/chat_transcript_bug_report.md
```

Commands inside the chat: `/new` (fresh session), `/session`, `/quit`. Tool calls print as
`[tool call] bugreports___create_bug_report`.

Walk through one full bug report — vague opening message, answer the follow-ups, confirm, and
check the ticket ID that comes back.

📸 **Evidence:** the saved transcript, plus a screenshot of the DynamoDB table
`bug-report-tool-stack-bug-reports` showing the item the chatbot created →
`docs/evidence/02-dynamodb-item.png`

Verify from the CLI too:

```bash
aws dynamodb scan --table-name bug-report-tool-stack-bug-reports \
  --region us-east-1 --max-items 5
```

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `agentcore_config.json not found` | Run `setup_gateway.py` first |
| `missing harness ARN` | Run `create_harness.py` first |
| `AccessDeniedException` mentioning a role, right after deploy | IAM propagation — wait 60s and retry |
| `ValidationException` on the model ID | Nova Pro access not granted in `us-east-1` (Bedrock console → Model access) |
| `None of these operations exist on this boto3 client` | boto3 too old — `pip install -U -r requirements.txt` |
| Session errors about `runtimeSessionId` | Session IDs must be 33+ characters; `new_session_id()` handles this |
| Prompt edits have no effect | You did not re-run `create_harness.py` |
| Chatbot never calls the tool | Confirm the gateway is attached (`gatewayArn` in the config) and that the prompt names the tool exactly as `bugreports___create_bug_report` |

# Testing and evaluation

Bedrock Evaluations cannot invoke the harness directly. The workflow is therefore: run the harness
over a test suite locally, capture its answers in a JSONL file, upload that file, and let an
evaluator model judge each answer against a reference response (Bring Your Own Inference).

All commands run from `project/starter/`.

## 1. The test suite

`harness-tests.json` holds 14 cases. Each has three fields:

| Field | Meaning |
| --- | --- |
| `id` | Unique identifier, used in log output |
| `prompt` | The customer message sent to the harness |
| `expected` | A description of what a good answer contains — the reference response for the judge |

Every case runs as a **single turn in a fresh session**, so cases cannot influence each other and
no case can depend on an earlier turn. That shapes what `expected` should say for the bug-report
route: describe the *start* of the collection behaviour ("acknowledges the bug and asks for the
steps to reproduce and the environment"), not a finished ticket.

Coverage:

| ID | Route | What it probes |
| --- | --- | --- |
| `t1_bug_report_crash` | Bug report | Vague report → asks for the missing checklist items |
| `t2_bug_report_complete_first_turn` | Bug report | All three items given at once → confirms, does not re-ask |
| `t3_faq_returns_covered` | Platform question | Returns policy, exact numbers |
| `t4_faq_shipping_covered` | Platform question | Shipping tiers and prices |
| `t5_faq_payments_covered` | Platform question | Payment methods and charge timing |
| `t6_faq_not_covered` | Platform question | Not in the FAQ → admits it, redirects |
| `t7_other_request_human` | Other | Complaint escalation → phone line |
| `t8_other_request_partnership` | Other | Business enquiry → phone line |
| `t9_ambiguous_bug_or_question` | Edge | Could be either route — must pick one and stay there |
| `t10_minimal_context` | Edge | "it's broken" → one clarifying question, no guessing |
| `t11_prompt_injection` | Edge | Direct instruction override → refuses |
| `t12_injection_inside_bug_report` | Edge | Injection hidden in ticket text → treated as data |
| `t13_account_specific_request` | Edge | Order lookup → no hallucinated status, hands off |
| `t14_sensitive_data` | Edge | Card number in chat → does not echo it |

The last six are the "stand out" edge cases: ambiguity, minimal context, and prompt injection.

## 2. Run the harness over the suite

```bash
python generate-eval-dataset.py --tests-json harness-tests.json
```

The script reads the harness and gateway ARNs from `agentcore_config.json`, attaches the gateway
on every invoke so the model can call `create_bug_report`, pins the model to
`us.amazon.nova-pro-v1:0`, and writes one `wrote eval line` message per case.

Output — `output_eval_dataset.jsonl`, one JSON object per line:

```json
{
  "prompt": "Your app crashes every time I try to upload a file...",
  "referenceResponse": "Acknowledges the issue and asks for steps to reproduce...",
  "modelResponses": [
    {"response": "I'm sorry to hear about the crash. Could you tell me...",
     "modelIdentifier": "my-support-chatbot"}
  ]
}
```

Any failed invoke is written with a `[HARNESS_ERROR]` prefix and counted in the summary line.
Fix those before uploading — the judge will score them as incorrect and drag the average down for
reasons that have nothing to do with the prompt.

Quick sanity check:

```bash
wc -l output_eval_dataset.jsonl
grep -c HARNESS_ERROR output_eval_dataset.jsonl   # expect 0
python -c "import json,sys;[json.loads(l) for l in open('output_eval_dataset.jsonl')];print('valid jsonl')"
```

📸 **Evidence:** terminal screenshot of the run → `docs/evidence/03-generate-dataset.png`

## 3. Deploy the testing stack

```bash
aws cloudformation deploy \
  --template-file cloudformation-testing.yaml \
  --stack-name bug-report-testing-stack \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1

aws cloudformation describe-stacks \
  --stack-name bug-report-testing-stack \
  --query 'Stacks[0].Outputs' --output table --region us-east-1
```

Note `EvalDatasetBucketName` and `BedrockEvalRoleArn`.

## 4. Upload and run the evaluation job

```bash
aws s3 cp output_eval_dataset.jsonl \
  s3://<EvalDatasetBucketName>/output_eval_dataset.jsonl \
  --region us-east-1

aws bedrock create-evaluation-job \
  --job-name support-chatbot-eval-run-1 \
  --role-arn <BedrockEvalRoleArn> \
  --evaluation-config '{
    "automated": {
      "datasetMetricConfigs": [{
        "taskType": "General",
        "dataset": {
          "name": "support-chatbot-eval-dataset",
          "datasetLocation": {
            "s3Uri": "s3://<EvalDatasetBucketName>/output_eval_dataset.jsonl"
          }
        },
        "metricNames": ["Builtin.Correctness"]
      }],
      "evaluatorModelConfig": {
        "bedrockEvaluatorModels": [{
          "modelIdentifier": "amazon.nova-pro-v1:0"
        }]
      }
    }
  }' \
  --inference-config '{
    "models": [{
      "precomputedInferenceSource": {
        "inferenceSourceIdentifier": "my-support-chatbot"
      }
    }]
  }' \
  --output-data-config '{"s3Uri": "s3://<EvalDatasetBucketName>/results/"}' \
  --region us-east-1
```

`inferenceSourceIdentifier` **must** match the `modelIdentifier` in the JSONL —
`my-support-chatbot` is what `generate-eval-dataset.py` writes by default. A mismatch is the most
common cause of a job that starts and then finds no records to score.

Poll the job:

```bash
aws bedrock list-evaluation-jobs --region us-east-1 \
  --query 'jobSummaries[?jobName==`support-chatbot-eval-run-1`].[jobName,status]' --output table
```

Results: Amazon Bedrock console → **Evaluations** → your job (once `Completed`).

📸 **Evidence:** screenshot of the results page with overall correctness and per-record
breakdown → `docs/evidence/04-eval-results.png`

## 5. Read the results and iterate

Work through the per-record scores looking for:

- Any prompt routed to the wrong path (a bug report answered with "call support" is the classic).
- FAQ answers that drift from the document — invented numbers, softened windows, generic retail
  advice.
- Bug-report answers that file a ticket too early or invent a ticket ID.
- Records where the answer is actually fine but the judge marked it down. Usually the
  `expected` text was too prescriptive; loosen it to describe intent rather than wording.

The iteration loop is:

```bash
$EDITOR system_prompt.txt
python create_harness.py                                     # push the prompt
python generate-eval-dataset.py --tests-json harness-tests.json
aws s3 cp output_eval_dataset.jsonl s3://<bucket>/output_eval_dataset.jsonl --region us-east-1
# create a new job with a new --job-name (run-2, run-3, ...)
```

Common fixes, in the order they tend to pay off:

1. Sharpen the category definitions and add explicit tie-break rules.
2. Tighten "answer only from the FAQ" and add the exact refusal sentence to use when it is not
   covered — a verbatim sentence is much more reliable than a paraphrased instruction.
3. Spell out the bug-report checklist as three named fields matching the tool arguments.
4. Add a worked example for whichever route is failing. Examples move behaviour more than prose.

Record what changed and what it did in [`OBSERVATIONS.md`](OBSERVATIONS.md).

# Submission checklist

Work through this before zipping the repository for submission.

## Artefacts that must be real (not the shipped examples)

- [ ] `project/starter/output_eval_dataset.jsonl` — generated from your own harness run,
      `grep -c HARNESS_ERROR` returns 0
- [ ] `project/starter/examples/chat_transcript_bug_report.md` — from your own `chat.py` session,
      showing the follow-up questions **and** the `[tool call] bugreports___create_bug_report` line
- [ ] `docs/OBSERVATIONS.md` — bracketed placeholders replaced with your actual scores and findings

## Screenshots in `docs/evidence/`

- [ ] `01-lambda-test.png` — Lambda console test event and its successful result (`ticketId`, `status: OPEN`)
- [ ] `02-dynamodb-item.png` — `bug-report-tool-stack-bug-reports` with at least one item created by the chatbot
- [ ] `03-generate-dataset.png` — terminal output of `generate-eval-dataset.py`
- [ ] `04-eval-results.png` — Bedrock Evaluations results page, job status `Completed`
- [ ] `05-routing-tests.png` — one response from each of the three routes
- [ ] `06-faq-node.png` — the `<faq>` block inside `system_prompt.txt`
- [ ] `07-covered-question.png` — an FAQ-covered question answered correctly
- [ ] `08-uncovered-question.png` — an uncovered question redirected to the phone line
- [ ] `09-other-request.png` — an out-of-scope request redirected to the phone line
- [ ] `10-gateway-target.png` *(optional)* — the `bugreports` target in the AgentCore console

## Sanity checks

```bash
pytest -q                                        # offline checks pass
cd project/starter
python -c "import json;d=json.load(open('harness-tests.json'));print(len(d['tests']),'tests')"
diff harness-tests.json flow-tests.json && echo "test files in sync"
python -c "import json;[json.loads(l) for l in open('output_eval_dataset.jsonl')];print('valid jsonl')"
```

- [ ] `harness-tests.json` and `flow-tests.json` are identical
- [ ] `system_prompt.txt` phone number matches `online_shop_faq.md`
- [ ] `agentcore_config.json` is **not** in the zip (account-specific ARNs, and it is regenerable)
- [ ] No AWS account IDs, access keys or credentials anywhere in the tracked files
- [ ] `venv/`, `__pycache__/` and `.DS_Store` excluded

## After submitting

- [ ] `python cleanup_agentcore.py`
- [ ] Empty the S3 bucket, then delete both CloudFormation stacks (see `CLEANUP.md`)
- [ ] Confirm in the Billing console that nothing is still running

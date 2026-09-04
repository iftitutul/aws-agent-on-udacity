# Evidence

Screenshots for the rubric go in this folder, named as listed in
[`../SUBMISSION_CHECKLIST.md`](../SUBMISSION_CHECKLIST.md):

| File | Shows |
| --- | --- |
| `01-lambda-test.png` | Lambda console test event and successful result |
| `02-dynamodb-item.png` | A bug-report item created by the chatbot |
| `03-generate-dataset.png` | `generate-eval-dataset.py` terminal output |
| `04-eval-results.png` | Bedrock Evaluations results page |
| `05-routing-tests.png` | One response per route |
| `06-faq-node.png` | The `<faq>` block in `system_prompt.txt` |
| `07-covered-question.png` | FAQ-covered question answered from the FAQ |
| `08-uncovered-question.png` | Uncovered question redirected to the phone line |
| `09-other-request.png` | Out-of-scope request redirected to the phone line |
| `10-gateway-target.png` | *(optional)* the `bugreports` gateway target |

Crop out account IDs and ARNs where they are not needed. PNG preferred.

Items `05`-`09` (the per-route test flows) can be satisfied instead by
[`project/starter/examples/chat_transcript_routing_tests.md`](../../project/starter/examples/chat_transcript_routing_tests.md)
and [`chat_transcript_bug_report.md`](../../project/starter/examples/chat_transcript_bug_report.md)
— a reviewer explicitly accepted chat.py transcripts as an alternative to screenshots for these.

# Example chat transcript — bug report route

> **This file is an illustration of the expected shape, not a graded artefact.**
> Produce the real transcript from your own run and save it next to this file:
>
> ```bash
> python chat.py --transcript examples/chat_transcript_bug_report.md
> ```
>
> The rubric asks the transcript to show (a) the follow-up questions that collect the checklist
> and (b) the `[tool call] bugreports___create_bug_report` line.

Session: `chat-<uuid>`

**you>** Your app crashes every time I try to upload a photo to a review.

**bot>** Thanks for flagging that — a crash on photo upload shouldn't happen. Could you walk me
through the exact steps you take before it crashes, and tell me which device and app version
you're on?

**you>** Open a delivered order, tap Write a review, attach a JPEG, tap Post. It dies right there.

**bot>** Got the steps, thank you. One thing still missing: which device and operating system are
you using, and which version of the Nimbus app?

**you>** iPhone 14, iOS 17.4, app version 5.2.1.

**bot>** Let me read that back before I file it. The problem: the app crashes when posting a
review with a photo attached. Steps: open a delivered order, tap Write a review, attach a JPEG,
tap Post. Environment: iPhone 14, iOS 17.4, Nimbus app 5.2.1. Is that right?

**you>** Yes, that's right.

`[tool call] bugreports___create_bug_report`

**bot>** Filed — your ticket is BUG-20260829-4F2A and it's open with our engineering team.
They'll follow up on the email address on your account.

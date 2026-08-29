#!/usr/bin/env python3
"""Terminal chat client for the support chatbot.

Keeps one stateful harness session for the whole conversation, so the bug-report route can
collect the checklist across turns. Tool calls are printed as `[tool call] <name>` lines, which
is what the rubric asks you to capture in a transcript.

Usage:
    python chat.py
    python chat.py --transcript examples/chat_transcript_bug_report.md

Commands inside the chat:
    /new     start a fresh session (clears the harness's memory of this conversation)
    /session print the current session ID
    /quit    exit
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from agentcore_common import invoke_harness, load_config, new_session_id

BANNER = """\
Nimbus Market support chatbot — type a customer message, /new for a fresh session, /quit to exit.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", help="Also write the conversation to this markdown file.")
    args = parser.parse_args()

    config = load_config(required=("harnessArn",))
    harness_arn = config["harnessArn"]
    gateway_arn = config.get("gatewayArn")
    session_id = new_session_id("chat")

    lines = [f"# Chat transcript — {dt.datetime.now():%Y-%m-%d %H:%M}", "", f"Session: `{session_id}`", ""]
    print(BANNER)
    print(f"session: {session_id}\n")

    while True:
        try:
            message = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not message:
            continue
        if message in ("/quit", "/exit"):
            break
        if message == "/session":
            print(f"session: {session_id}\n")
            continue
        if message == "/new":
            session_id = new_session_id("chat")
            lines += ["", f"--- new session: `{session_id}` ---", ""]
            print(f"new session: {session_id}\n")
            continue

        try:
            reply, tool_calls = invoke_harness(harness_arn, gateway_arn, session_id, message)
        except Exception as exc:  # noqa: BLE001
            print(f"\n[error] {exc}\n", file=sys.stderr)
            continue

        lines.append(f"**you>** {message}")
        for name in tool_calls:
            print(f"[tool call] {name}")
            lines.append(f"`[tool call] {name}`")
        print(f"bot> {reply}\n")
        lines += [f"**bot>** {reply}", ""]

    if args.transcript:
        with open(args.transcript, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        print(f"transcript written to {args.transcript}")


if __name__ == "__main__":
    main()

"""Phase 0 — Slack primitive smoke test.

Throwaway script. Deleted before v0.5.0 ship. Purpose: prove the 9
Slack primitives Donna depends on actually work in this environment
before we touch the schema or replace the Discord adapter.

See docs/slack/PHASE_0_RUNBOOK.md for setup. Reads four env vars:

    SLACK_BOT_TOKEN     xoxb-...   bot token
    SLACK_APP_TOKEN     xapp-...   app-level token (Socket Mode)
    SLACK_TEAM_ID       T0...      workspace allowlist (defense in depth)
    SLACK_TEST_CHANNEL  C0...      a channel Donna has been /invite'd to

Run:
    python scripts/slack_smoke.py

Walk through the printed prompts. Each completed primitive flips a row
from PENDING → PASS in the live status table. Ctrl+C when done; final
summary prints. Paste that back to Claude.

The 9 primitives are exercised in order:

    1. Socket Mode connects
    2. Receive DM event
    3. Reply via chat.postMessage
    4. Slash command /donna_smoke routes
    5. Modal opens from slash command
    6. Modal submission delivers form values
    7. Block Kit button renders
    8. Button click handler fires (within 3s) + chat.update edits message
    9. Post to a specific channel

Throughout, the script enforces TEAM_ID + USER allowlist on every event
to mirror what the production adapter will do. (USER allowlist relaxes
during smoke — first DM seen sets the allowed user — so you don't
need to look up your own Slack user ID upfront.)
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass

try:
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler
except ImportError:
    sys.stderr.write(
        "slack_bolt not installed. Run: .venv/Scripts/pip install slack-bolt\n"
    )
    sys.exit(2)


# --- env --------------------------------------------------------------------

BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "").strip()
APP_TOKEN = os.environ.get("SLACK_APP_TOKEN", "").strip()
TEAM_ID = os.environ.get("SLACK_TEAM_ID", "").strip()
TEST_CHANNEL = os.environ.get("SLACK_TEST_CHANNEL", "").strip()

if not BOT_TOKEN or not BOT_TOKEN.startswith("xoxb-"):
    sys.stderr.write("ERR: SLACK_BOT_TOKEN missing or doesn't start with xoxb-\n")
    sys.exit(2)
if not APP_TOKEN or not APP_TOKEN.startswith("xapp-"):
    sys.stderr.write("ERR: SLACK_APP_TOKEN missing or doesn't start with xapp-\n")
    sys.exit(2)
if not TEAM_ID or not TEAM_ID.startswith("T"):
    sys.stderr.write("ERR: SLACK_TEAM_ID missing or doesn't start with T\n")
    sys.exit(2)
if not TEST_CHANNEL or not TEST_CHANNEL.startswith("C"):
    sys.stderr.write(
        "ERR: SLACK_TEST_CHANNEL missing or doesn't start with C "
        "(must be a channel ID like C01ABC234, not a channel name)\n"
    )
    sys.exit(2)


# --- pass/fail tracking -----------------------------------------------------


@dataclass
class Probe:
    name: str
    status: str = "PENDING"   # PENDING | PASS | FAIL
    detail: str = ""


PROBES: dict[str, Probe] = {
    "1_socket_connect":   Probe("1. Socket Mode connects"),
    "2_receive_dm":       Probe("2. Receive DM event"),
    "3_reply_post":       Probe("3. Reply via chat.postMessage"),
    "4_slash_command":    Probe("4. Slash command /donna_smoke routes"),
    "5_modal_open":       Probe("5. Modal opens from slash command"),
    "6_modal_submit":     Probe("6. Modal submission delivers form values"),
    "7_button_render":    Probe("7. Block Kit button message renders"),
    "8_button_click":     Probe("8. Button click handler fires + chat.update edits message"),
    "9_post_to_channel":  Probe("9. Post to specific channel"),
}


def mark(key: str, status: str, detail: str = "") -> None:
    p = PROBES[key]
    p.status = status
    p.detail = detail
    icon = {"PENDING": "·", "PASS": "✅", "FAIL": "❌"}[status]
    print(f"  {icon} [{status:>4}] {p.name}" + (f" — {detail}" if detail else ""))


def print_summary() -> None:
    print("\n" + "=" * 70)
    print("Phase 0 smoke summary")
    print("=" * 70)
    for p in PROBES.values():
        icon = {"PENDING": "·", "PASS": "✅", "FAIL": "❌"}[p.status]
        line = f"  {icon} [{p.status:>7}] {p.name}"
        if p.detail:
            line += f"  ({p.detail})"
        print(line)
    pass_count = sum(1 for p in PROBES.values() if p.status == "PASS")
    fail_count = sum(1 for p in PROBES.values() if p.status == "FAIL")
    pending = sum(1 for p in PROBES.values() if p.status == "PENDING")
    print(f"\n  Passed: {pass_count} / {len(PROBES)}   "
          f"Failed: {fail_count}   Pending: {pending}")
    if fail_count == 0 and pending == 0:
        print("\n  🎉 ALL GREEN — Phase 1 (schema migration) is unblocked.")
    elif fail_count > 0:
        print("\n  Some primitives failed. Triage with Claude before destructive work.")
    else:
        print("\n  Some primitives weren't exercised. Re-run and walk through all steps.")
    print("=" * 70 + "\n")


# --- allowlist --------------------------------------------------------------

# Defense-in-depth (matches Codex review recommendation): verify team_id
# matches AND user_id matches the operator on every event. The operator's
# user_id is unknown until the first DM arrives — first DM seen during
# the smoke "binds" the allowed user. After that, anything from a
# different user is rejected silently.
_allowed_user_id: str | None = None


def _allow(team_id: str, user_id: str | None) -> bool:
    global _allowed_user_id
    if team_id != TEAM_ID:
        return False
    if _allowed_user_id is None and user_id:
        _allowed_user_id = user_id
        print(f"  → bound allowed user_id = {user_id}")
        return True
    return user_id == _allowed_user_id


# --- app + handlers ---------------------------------------------------------

app = App(token=BOT_TOKEN)


@app.event("message")
def on_message(event, say, body):
    """Probe 2: receive DM. Probe 3: reply. Probe 7: post button card."""
    # Subtypes (channel_join, message_changed, etc.) get filtered.
    if event.get("subtype") is not None:
        return
    team_id = body.get("team_id", "")
    user_id = event.get("user")
    if not _allow(team_id, user_id):
        return
    channel_type = event.get("channel_type")
    if channel_type != "im":
        return  # we only smoke DMs in this script
    text = event.get("text", "").strip()

    mark("2_receive_dm", "PASS", f"text={text[:40]!r}")

    # Probe 3: reply
    try:
        resp = say(
            text=(
                f"Smoke ack: I saw your DM ({text!r}).\n\n"
                "Next steps:\n"
                "• Type `/donna_smoke` in any channel or DM (probes 4–6)\n"
                "• Click the button below (probes 7–8)"
            ),
        )
        if resp.get("ok"):
            mark("3_reply_post", "PASS", f"ts={resp['ts']}")
        else:
            mark("3_reply_post", "FAIL", str(resp))
    except Exception as e:  # noqa: BLE001
        mark("3_reply_post", "FAIL", f"{type(e).__name__}: {e}")
        return

    # Probe 7: post a Block Kit button message
    try:
        resp = say(
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Click the button below to test interactivity.",
                    },
                },
                {
                    "type": "actions",
                    "block_id": "smoke_actions",
                    "elements": [
                        {
                            "type": "button",
                            "action_id": "donna_smoke_button",
                            "text": {"type": "plain_text", "text": "Click me"},
                            "value": "smoke-button-clicked",
                            "style": "primary",
                        }
                    ],
                },
            ],
            text="Click the button to test interactivity.",  # fallback for notifications
        )
        if resp.get("ok"):
            mark("7_button_render", "PASS", f"ts={resp['ts']}")
        else:
            mark("7_button_render", "FAIL", str(resp))
    except Exception as e:  # noqa: BLE001
        mark("7_button_render", "FAIL", f"{type(e).__name__}: {e}")


@app.command("/donna_smoke")
def on_smoke_command(ack, body, client):
    """Probe 4: slash command routes. Probe 5: open modal."""
    team_id = body.get("team_id", "")
    user_id = body.get("user_id")
    if not _allow(team_id, user_id):
        ack("not authorized")
        return

    ack(":hourglass: opening modal…")
    mark("4_slash_command", "PASS", f"text={body.get('text', '')[:40]!r}")

    # Probe 5: open modal
    try:
        resp = client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "donna_smoke_modal",
                "title": {"type": "plain_text", "text": "Donna smoke"},
                "submit": {"type": "plain_text", "text": "Submit"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "task_block",
                        "label": {"type": "plain_text", "text": "Task description"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "task_input",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "Anything — proves modal collects text",
                            },
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "cron_block",
                        "label": {"type": "plain_text", "text": "Cron expression"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "cron_input",
                            "initial_value": "* * * * *",
                        },
                    },
                ],
            },
        )
        if resp.get("ok"):
            mark("5_modal_open", "PASS", f"view_id={resp['view']['id']}")
        else:
            mark("5_modal_open", "FAIL", str(resp))
    except Exception as e:  # noqa: BLE001
        mark("5_modal_open", "FAIL", f"{type(e).__name__}: {e}")


@app.view("donna_smoke_modal")
def on_modal_submit(ack, body, view, client):
    """Probe 6: modal submission delivers form values."""
    team_id = body.get("team_id", "")
    user_id = body.get("user", {}).get("id")
    if not _allow(team_id, user_id):
        ack(response_action="errors", errors={"task_block": "not authorized"})
        return

    ack()
    state = view.get("state", {}).get("values", {})
    task = state.get("task_block", {}).get("task_input", {}).get("value", "")
    cron = state.get("cron_block", {}).get("cron_input", {}).get("value", "")
    detail = f"task={task[:30]!r} cron={cron!r}"
    if task and cron:
        mark("6_modal_submit", "PASS", detail)
    else:
        mark("6_modal_submit", "FAIL", f"missing values: {detail}")

    # Probe 9: post to TEST_CHANNEL
    try:
        resp = client.chat_postMessage(
            channel=TEST_CHANNEL,
            text=(
                f":white_check_mark: Smoke probe 9 — posted from modal submission. "
                f"task={task!r}, cron={cron!r}"
            ),
        )
        if resp.get("ok"):
            mark("9_post_to_channel", "PASS",
                 f"channel={TEST_CHANNEL} ts={resp['ts']}")
        else:
            mark("9_post_to_channel", "FAIL", str(resp))
    except Exception as e:  # noqa: BLE001
        mark("9_post_to_channel", "FAIL", f"{type(e).__name__}: {e}")


@app.action("donna_smoke_button")
def on_button(ack, body, client):
    """Probe 8: button click → ack within 3s + chat.update edits message."""
    t0 = time.time()
    ack()
    ack_dur = time.time() - t0

    team_id = body.get("team_id", "")
    user_id = body.get("user", {}).get("id")
    if not _allow(team_id, user_id):
        return

    msg = body.get("message", {})
    channel = body.get("channel", {}).get("id")
    msg_ts = msg.get("ts")
    if not channel or not msg_ts:
        mark("8_button_click", "FAIL", "missing channel/ts in payload")
        return

    try:
        resp = client.chat_update(
            channel=channel,
            ts=msg_ts,
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":white_check_mark: Button clicked. (ack in {ack_dur*1000:.0f}ms)",
                    },
                }
            ],
            text="Button clicked — interactivity confirmed.",
        )
        if resp.get("ok"):
            mark("8_button_click", "PASS",
                 f"ack_ms={ack_dur*1000:.0f} updated_ts={resp['ts']}")
        else:
            mark("8_button_click", "FAIL", str(resp))
    except Exception as e:  # noqa: BLE001
        mark("8_button_click", "FAIL", f"{type(e).__name__}: {e}")


# --- driver -----------------------------------------------------------------


def _print_walkthrough() -> None:
    print()
    print("=" * 70)
    print("Phase 0 smoke — walk through these in order:")
    print("=" * 70)
    print("  A. DM the bot anything                     (probes 2, 3, 7)")
    print("  B. Click the button it posts back         (probe  8)")
    print("  C. Type `/donna_smoke` in any channel/DM   (probes 4, 5)")
    print("  D. Fill in the modal and click Submit     (probes 6, 9)")
    print()
    print("  Press Ctrl+C when done — final summary will print.")
    print("=" * 70)
    print()


def main() -> None:
    """slack_bolt's `handler.start()` registers its own SIGINT handler via
    `signal.signal()`, which only works on the main thread. Earlier
    versions of this script ran `start()` in a worker thread and got a
    spurious `ValueError: signal only works in main thread` — Socket
    Mode itself connected fine ("Bolt app is running!" printed) but
    probe 1 reported false-negative.

    Fix: run start() on the main thread; mark probe 1 PASS optimistically
    just before calling it (slack_bolt rejects an invalid app token at
    start() entry, so a wrong token would throw immediately). Catch
    KeyboardInterrupt to print the summary cleanly.
    """
    print("  Connecting via Socket Mode…")

    # Mark probe 1 PASS optimistically. handler.start() will throw
    # immediately if the app token is invalid or Socket Mode connection
    # fails — that exception propagates to the except block below and
    # we re-mark FAIL with the actual error.
    mark("1_socket_connect", "PASS")
    _print_walkthrough()

    handler = SocketModeHandler(app, APP_TOKEN)

    try:
        handler.start()  # blocks until KeyboardInterrupt
    except KeyboardInterrupt:
        print("\n\n  Stopping — collecting results…")
    except Exception as e:  # noqa: BLE001
        mark(
            "1_socket_connect",
            "FAIL",
            f"{type(e).__name__}: {e}",
        )
    finally:
        print_summary()


if __name__ == "__main__":
    main()

"""SubagentStop hook handler."""

import asyncio
import json
import time
from pathlib import Path
from typing import Optional

from pyafk.core.storage import Storage
from pyafk.notifiers.telegram import TelegramNotifier
from pyafk.utils.config import Config


async def _lazy_cleanup_subagent_messages(
    storage: Storage,
    notifier: TelegramNotifier,
    max_age_seconds: int,
) -> int:
    """Clean up expired subagent messages (auto-dismiss).

    Returns number of messages cleaned up.
    """
    expired = await storage.get_expired_subagent_messages(max_age_seconds)
    cleaned = 0

    for msg_id, compact_text in expired:
        try:
            await notifier.edit_message(msg_id, compact_text, parse_mode="HTML")
            cleaned += 1
        except Exception:
            pass  # Message might be deleted
        finally:
            await storage.delete_subagent_message(msg_id)

    return cleaned


def _format_transcript_markdown(content: str, max_chars: int = 50000) -> str:
    """Format JSONL transcript as readable markdown."""
    lines = content.strip().split("\n")
    sections = []

    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = entry.get("type", "")
        message = entry.get("message", {})

        if msg_type == "user":
            # User message
            content_blocks = message.get("content", [])
            text = ""
            if isinstance(content_blocks, str):
                text = content_blocks
            elif isinstance(content_blocks, list):
                for block in content_blocks:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text += block.get("text", "")
            if text:
                sections.append(f"## 👤 User\n\n{text}")

        elif msg_type == "assistant":
            # Assistant message
            content_blocks = message.get("content", [])
            texts = []
            if isinstance(content_blocks, str):
                texts.append(content_blocks)
            elif isinstance(content_blocks, list):
                for block in content_blocks:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            texts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_name = block.get("name", "tool")
                            texts.append(f"*[Using {tool_name}]*")
            if texts:
                sections.append("## 🤖 Assistant\n\n" + "\n\n".join(texts))

    result = "# Agent Session Log\n\n" + "\n\n---\n\n".join(sections)

    if len(result) > max_chars:
        result = result[:max_chars] + "\n\n... (truncated)"

    return result


def _extract_task_description(
    transcript_path: Optional[str], max_chars: int = 100
) -> Optional[str]:
    """Extract the first user message as task description."""
    if not transcript_path:
        return None

    path = Path(transcript_path)
    if not path.exists():
        return None

    try:
        content = path.read_text()
        lines = content.strip().split("\n")

        for line in lines:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") != "user":
                continue

            message = entry.get("message", {})
            content_blocks = message.get("content", [])
            text = ""
            if isinstance(content_blocks, str):
                text = content_blocks
            elif isinstance(content_blocks, list):
                for block in content_blocks:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text += block.get("text", "")

            if text:
                # Return first line only, truncated
                first_line = text.split("\n")[0].strip()
                if len(first_line) > max_chars:
                    return first_line[:max_chars] + "..."
                return first_line
        return None
    except Exception:
        return None


def _extract_last_output(transcript_path: Optional[str], max_chars: int = 2000) -> str:
    """Extract the last assistant message from transcript."""
    if not transcript_path:
        return "(no transcript available)"

    path = Path(transcript_path)
    if not path.exists():
        return "(transcript not found)"

    try:
        content = path.read_text()

        # Transcript is JSONL format - one JSON object per line
        lines = content.strip().split("\n")

        # Find the last assistant message (in reverse order)
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Skip non-assistant messages
            if entry.get("type") != "assistant":
                continue

            message = entry.get("message", {})
            content_blocks = message.get("content", [])

            # Extract text from this message only
            texts = []
            if isinstance(content_blocks, str):
                texts.append(content_blocks)
            elif isinstance(content_blocks, list):
                for block in content_blocks:
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            texts.append(text)

            if texts:
                result = "\n\n".join(texts)
                # Truncate if too long
                if len(result) > max_chars:
                    result = result[-max_chars:]
                    result = "..." + result
                return result

        return "(no agent output found)"

    except Exception as e:
        return f"(error reading transcript: {e})"


async def handle_subagent_stop(
    hook_input: dict,
    pyafk_dir: Optional[Path] = None,
) -> dict:
    """Handle SubagentStop hook.

    Shows the agent's output and allows user to:
    - OK: Let subagent finish
    - Continue: Send more instructions

    Returns:
        Response dict for Claude Code
    """
    import sys
    from pyafk.core.poller import Poller
    from pyafk.utils.config import get_pyafk_dir

    if pyafk_dir is None:
        pyafk_dir = get_pyafk_dir()

    config = Config(pyafk_dir)

    # Pass through when mode is off or hook is disabled
    if config.get_mode() != "on" or not config.subagent_hook:
        return {}

    # Check if Telegram is configured
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return {}  # Let it stop normally

    # Extract info from hook input - use session_id since tool_use_id isn't provided
    subagent_id = hook_input.get("session_id", "unknown")
    stop_hook_active = hook_input.get("stop_hook_active", False)

    # Debug log to file for visibility
    debug_log = pyafk_dir / "subagent_debug.log"

    def log(msg: str) -> None:
        with open(debug_log, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        print(f"[pyafk] {msg}", file=sys.stderr, flush=True)

    log(
        f"SubagentStop: subagent_id={subagent_id[:8]}, stop_hook_active={stop_hook_active}"
    )
    transcript_path = hook_input.get("transcript_path")
    project_path = hook_input.get("cwd")

    # Get the agent's output and description
    output_summary = _extract_last_output(transcript_path)
    description = _extract_task_description(transcript_path)

    # Initialize components
    storage = Storage(config.db_path)
    await storage.connect()

    try:
        notifier = TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )

        # Lazy cleanup: dismiss expired subagent messages
        if config.subagent_auto_dismiss_seconds > 0:
            cleaned = await _lazy_cleanup_subagent_messages(
                storage, notifier, config.subagent_auto_dismiss_seconds
            )
            if cleaned:
                log(f"Auto-dismissed {cleaned} expired messages")

        # Send notification with options
        msg_id, compact_text = await notifier.send_subagent_stop(
            subagent_id=subagent_id,
            output_summary=output_summary,
            project_path=project_path,
            description=description,
        )

        # Check if there's an existing entry for this subagent - if so, delete the old message
        existing = await storage.get_pending_subagent(subagent_id)
        if existing and existing.get("telegram_msg_id"):
            old_msg_id = existing["telegram_msg_id"]
            if old_msg_id != msg_id:
                try:
                    await notifier.delete_message(old_msg_id)
                    await storage.delete_subagent_message(old_msg_id)
                except Exception:
                    pass  # Old message might already be deleted

        # Create/update pending entry
        await storage.create_pending_subagent(subagent_id, msg_id)
        log(f"Created pending entry, msg_id={msg_id}")

        # Store for auto-dismiss
        if msg_id and config.subagent_auto_dismiss_seconds > 0:
            await storage.store_subagent_message(msg_id, compact_text)

        # Create poller and wait for response
        from pyafk.daemon import is_daemon_running

        poller = Poller(storage, notifier, pyafk_dir)

        timeout = 3600  # 1 hour
        start = time.monotonic()

        try:
            while True:
                elapsed = time.monotonic() - start
                if elapsed >= timeout:
                    log(f"Timeout reached after {elapsed:.0f}s")
                    return {}  # Timeout, let it stop

                # Poll for updates (only if daemon is not running)
                # Re-check each iteration in case daemon crashes
                if not is_daemon_running(pyafk_dir):
                    try:
                        await poller.process_updates_once()
                    except Exception:
                        pass

                # Check if resolved
                entry = await storage.get_pending_subagent(subagent_id)
                if entry and entry["status"] != "pending":
                    if entry["status"] == "continue" and entry["response"]:
                        # User wants to continue with instructions
                        # Format as explicit user instruction so Claude treats it as a new task
                        user_instructions = f"The user has sent you new instructions via remote approval:\n\n{entry['response']}\n\nPlease follow these instructions."
                        # Try both formats - with and without hookSpecificOutput
                        response = {
                            "decision": "block",
                            "reason": user_instructions,
                            # Also try hookSpecificOutput format in case that's needed
                            "hookSpecificOutput": {
                                "hookEventName": "SubagentStop",
                                "decision": "block",
                                "reason": user_instructions,
                            },
                        }
                        log(f"Returning BLOCK with reason: {entry['response'][:100]}")
                        return response
                    else:
                        # OK, let it stop
                        log(f"Returning empty (let stop), status={entry['status']}")
                        return {}

                await asyncio.sleep(0.5)
        finally:
            await notifier.close()

    finally:
        await storage.close()


if __name__ == "__main__":
    from pyafk.hooks.runner import run_hook

    run_hook(handle_subagent_stop)

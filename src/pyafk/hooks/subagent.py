"""SubagentStop hook handler."""

import asyncio
import json
import time
from pathlib import Path
from typing import Optional

from pyafk.core.storage import Storage
from pyafk.notifiers.telegram import TelegramNotifier
from pyafk.utils.config import Config


def _extract_last_output(transcript_path: Optional[str], max_chars: int = 2000) -> str:
    """Extract the last meaningful output from transcript."""
    if not transcript_path:
        return "(no transcript available)"

    path = Path(transcript_path)
    if not path.exists():
        return "(transcript not found)"

    try:
        content = path.read_text()

        # Transcript is JSONL format - one JSON object per line
        lines = content.strip().split("\n")

        # Collect text from assistant messages (in reverse order)
        texts = []
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

            if isinstance(content_blocks, str):
                texts.append(content_blocks)
            elif isinstance(content_blocks, list):
                for block in content_blocks:
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            texts.append(text)

            # Stop once we have enough content
            total_len = sum(len(t) for t in texts)
            if total_len >= max_chars:
                break

        if not texts:
            return "(no agent output found)"

        # Reverse to get chronological order, join
        texts.reverse()
        result = "\n\n".join(texts)

        # Truncate if too long
        if len(result) > max_chars:
            result = result[-max_chars:]
            result = "..." + result

        return result

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
    from pyafk.core.poller import Poller
    from pyafk.utils.config import get_pyafk_dir

    if pyafk_dir is None:
        pyafk_dir = get_pyafk_dir()

    config = Config(pyafk_dir)

    # Check if Telegram is configured
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return {}  # Let it stop normally

    # Extract info from hook input
    subagent_id = hook_input.get("tool_use_id", hook_input.get("session_id", "unknown"))
    transcript_path = hook_input.get("transcript_path")
    project_path = hook_input.get("cwd")

    # Get the agent's output
    output_summary = _extract_last_output(transcript_path)

    # Initialize components
    storage = Storage(config.db_path)
    await storage.connect()

    try:
        notifier = TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )

        # Send notification with options
        msg_id = await notifier.send_subagent_stop(
            subagent_id=subagent_id,
            output_summary=output_summary,
            project_path=project_path,
        )

        # Also send the transcript as a file if available
        if transcript_path:
            transcript_file = Path(transcript_path)
            if transcript_file.exists():
                # Create a temporary markdown file with the transcript
                import tempfile
                with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
                    f.write(f"# Subagent Transcript\n\n")
                    f.write(f"```\n{transcript_file.read_text()[:50000]}\n```\n")
                    temp_path = Path(f.name)
                try:
                    await notifier.send_document(temp_path, caption="Full transcript")
                finally:
                    temp_path.unlink(missing_ok=True)

        # Create pending entry
        await storage.create_pending_subagent(subagent_id, msg_id)

        # Create poller and wait for response
        poller = Poller(storage, notifier, pyafk_dir)

        timeout = 3600  # 1 hour
        start = time.monotonic()

        while True:
            elapsed = time.monotonic() - start
            if elapsed >= timeout:
                return {}  # Timeout, let it stop

            # Poll for updates
            try:
                await poller.process_updates_once()
            except Exception:
                pass

            # Check if resolved
            entry = await storage.get_pending_subagent(subagent_id)
            if entry and entry["status"] != "pending":
                if entry["status"] == "continue" and entry["response"]:
                    # User wants to continue with instructions
                    return {
                        "decision": "block",
                        "reason": entry["response"],
                    }
                else:
                    # OK, let it stop
                    return {}

            await asyncio.sleep(0.5)

    finally:
        await storage.close()

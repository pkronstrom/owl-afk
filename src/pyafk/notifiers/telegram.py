"""Telegram notifier using Bot API."""

import json
from typing import Any, Optional

import httpx

from pyafk.notifiers.base import Notifier
from pyafk.utils.debug import debug_api, debug_chain
from pyafk.utils.formatting import escape_html, format_project_id


def format_approval_message(
    request_id: str,
    session_id: str,
    tool_name: str,
    tool_input: Optional[str] = None,
    description: Optional[str] = None,
    context: Optional[str] = None,
    timeout: int = 3600,
    timeout_action: str = "deny",
    project_path: Optional[str] = None,
) -> str:
    """Format a compact tool request for Telegram display."""
    # Extract the key info from tool_input
    input_summary = ""
    if tool_input:
        try:
            data = json.loads(tool_input)
            if "command" in data:
                input_summary = data["command"]
            elif "file_path" in data:
                input_summary = data["file_path"]
            elif "content" in data:
                # For Write tool, show file path if available
                input_summary = data.get("file_path", "(content)")
            else:
                # Show first key=value or truncated JSON
                input_summary = json.dumps(data)
        except (json.JSONDecodeError, TypeError):
            input_summary = str(tool_input)

    # Truncate input if too long
    if len(input_summary) > 200:
        input_summary = input_summary[:200] + "..."

    # Project identifier - use working directory or short session id
    project_id = format_project_id(project_path, session_id)

    # Compact format: project, optional description, then tool call
    lines = [f"<i>{escape_html(project_id)}</i>"]

    if description:
        # Show description in italic before the tool
        desc = description[:100] + "..." if len(description) > 100 else description
        lines.append(f"<i>{escape_html(desc)}</i>")

    lines.append(
        f"<b>[{escape_html(tool_name)}]</b> <code>{escape_html(input_summary)}</code>"
    )

    return "\n".join(lines)


def _truncate_pattern_label(pattern: str, max_len: int = 40) -> str:
    """Truncate pattern for button label, preserving distinctive ending."""
    if len(pattern) <= max_len:
        return pattern

    # For patterns with paths, show command + ... + ending
    # e.g., "rm /home/user/.pyafk/test_file.txt" -> "rm .../test_file.txt"
    parts = pattern.split(" ", 1)
    if len(parts) == 2:
        cmd, path = parts
        # Keep enough room for "cmd .../ending"
        available = max_len - len(cmd) - 5  # " .../" takes 5 chars
        if available > 10:
            # Try to show last path component(s)
            path_parts = path.rstrip("/").rsplit("/", 2)
            if len(path_parts) >= 2:
                ending = "/".join(path_parts[-2:])
                if len(ending) <= available:
                    return f"{cmd} .../{ending}"
                # Just show last component
                ending = path_parts[-1]
                if len(ending) <= available:
                    return f"{cmd} .../{ending}"
            # Fallback: show end of path
            return f"{cmd} ...{path[-(available):]}"

    # Fallback: show start...end
    half = (max_len - 3) // 2
    return f"{pattern[:half]}...{pattern[-half:]}"


class TelegramNotifier(Notifier):
    """Telegram Bot API notifier."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        timeout: int = 3600,
        timeout_action: str = "deny",
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout
        self.timeout_action = timeout_action
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create persistent HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _api_request(
        self,
        method: str,
        data: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Make a Telegram API request with retry/backoff.

        Retries on transient errors (network issues, 5xx responses) with
        exponential backoff. Does not retry on 4xx errors (permanent failures).
        """
        import asyncio

        url = f"{self._base_url}/{method}"
        last_error: Optional[str] = None

        for attempt in range(max_retries):
            try:
                client = await self._get_client()
                response = await client.post(url, data=data, timeout=timeout)
                result: dict[str, Any] = response.json()

                # Check for retryable server errors (5xx)
                if not result.get("ok"):
                    error_code = result.get("error_code", 0)
                    description = result.get("description", "no description")

                    # 5xx errors are retryable
                    if isinstance(error_code, int) and 500 <= error_code < 600:
                        last_error = f"{error_code}: {description}"
                        if attempt < max_retries - 1:
                            delay = 0.5 * (2**attempt)  # 0.5s, 1s, 2s
                            debug_api(
                                "Retrying after server error",
                                method=method,
                                error_code=error_code,
                                attempt=attempt + 1,
                                delay=delay,
                            )
                            await asyncio.sleep(delay)
                            continue

                    # Log non-retryable API errors
                    debug_api(
                        "Telegram API error",
                        method=method,
                        error_code=error_code,
                        description=description[:100],
                    )

                return result

            except httpx.HTTPError as e:
                last_error = str(e)
                if attempt < max_retries - 1:
                    delay = 0.5 * (2**attempt)
                    debug_api(
                        "Retrying after HTTP error",
                        method=method,
                        error=str(e)[:50],
                        attempt=attempt + 1,
                        delay=delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                debug_api("HTTP error (final)", method=method, error=str(e)[:100])
                return {"ok": False, "error": str(e)}

            except json.JSONDecodeError as e:
                # JSON errors are not retryable
                debug_api("JSON decode error", method=method, error=str(e)[:100])
                return {"ok": False, "error": str(e)}

        # Should not reach here, but handle gracefully
        return {"ok": False, "error": last_error or "max retries exceeded"}

    def _build_approval_keyboard(
        self,
        request_id: str,
        session_id: str,
        tool_name: str,
        tool_input: Optional[str] = None,
    ) -> dict[str, list[list[dict[str, str]]]]:
        """Build standard approval keyboard."""
        # Smart pattern for Bash: "All git *" instead of "All Bash"
        all_button_text = f"⏩ All {tool_name}"
        if tool_name == "Bash" and tool_input:
            try:
                data = json.loads(tool_input)
                cmd = data.get("command", "")
                first_word = cmd.split()[0] if cmd.split() else ""
                if first_word:
                    all_button_text = f"⏩ All {first_word} *"
            except (json.JSONDecodeError, TypeError, IndexError):
                pass  # Fall back to "All Bash"

        return {
            "inline_keyboard": [
                [
                    {"text": "✅ Allow", "callback_data": f"approve:{request_id}"},
                    {"text": "📝 Always...", "callback_data": f"add_rule:{request_id}"},
                    {
                        "text": all_button_text,
                        "callback_data": f"approve_all:{session_id}:{tool_name}",
                    },
                ],
                [
                    {"text": "❌ Deny", "callback_data": f"deny:{request_id}"},
                    {"text": "💬 Deny...", "callback_data": f"deny_msg:{request_id}"},
                ],
            ]
        }

    def _build_chain_keyboard(
        self, request_id: str, current_idx: int
    ) -> dict[str, list[list[dict[str, str]]]]:
        """Build chain approval keyboard."""
        return {
            "inline_keyboard": [
                [
                    {
                        "text": "⏩ Approve Chain",
                        "callback_data": f"chain_approve_entire:{request_id}",
                    }
                ],
                [
                    {
                        "text": "✅ Step",
                        "callback_data": f"chain_approve:{request_id}:{current_idx}",
                    },
                    {
                        "text": "📝 Always...",
                        "callback_data": f"chain_rule:{request_id}:{current_idx}",
                    },
                ],
                [
                    {"text": "❌ Deny", "callback_data": f"chain_deny:{request_id}"},
                    {
                        "text": "💬 Deny...",
                        "callback_data": f"chain_deny_msg:{request_id}",
                    },
                ],
            ]
        }

    async def send_approval_request(
        self,
        request_id: str,
        session_id: str,
        tool_name: str,
        tool_input: Optional[str] = None,
        context: Optional[str] = None,
        description: Optional[str] = None,
        project_path: Optional[str] = None,
    ) -> Optional[int]:
        """Send approval request to Telegram."""
        message = format_approval_message(
            request_id=request_id,
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            description=description,
            context=context,
            timeout=self.timeout,
            timeout_action=self.timeout_action,
            project_path=project_path,
        )

        keyboard = self._build_approval_keyboard(
            request_id, session_id, tool_name, tool_input
        )

        result = await self._api_request(
            "sendMessage",
            data={
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
                "reply_markup": json.dumps(keyboard),
            },
        )

        if result.get("ok") and "result" in result:
            msg_id = result["result"].get("message_id")
            return int(msg_id) if msg_id is not None else None
        return None

    async def wait_for_response(
        self,
        request_id: str,
        timeout: int,
    ) -> Optional[str]:
        """Wait for callback response - handled by poller."""
        return None

    async def edit_message(
        self,
        message_id: int,
        new_text: str,
        remove_keyboard: bool = True,
        parse_mode: Optional[str] = "HTML",
    ) -> bool:
        """Edit a sent message and optionally remove keyboard.

        Returns True if edit was successful, False otherwise.
        """
        data: dict[str, Any] = {
            "chat_id": self.chat_id,
            "message_id": message_id,
            "text": new_text,
        }
        if parse_mode:
            data["parse_mode"] = parse_mode
        if remove_keyboard:
            data["reply_markup"] = json.dumps({"inline_keyboard": []})
        result = await self._api_request("editMessageText", data=data)
        if not result.get("ok"):
            debug_api(
                "edit_message failed",
                message_id=message_id,
                error=result.get("description", "unknown"),
            )
            return False
        return True

    async def delete_message(self, message_id: int) -> None:
        """Delete a message."""
        data = {
            "chat_id": self.chat_id,
            "message_id": message_id,
        }
        try:
            await self._api_request("deleteMessage", data=data)
        except Exception:
            pass  # Ignore errors - message may already be deleted

    async def send_message(self, text: str) -> Optional[int]:
        """Send a simple text message.

        Returns message ID if successful.
        """
        result = await self._api_request(
            "sendMessage",
            data={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
            },
        )
        if result and result.get("ok") and result.get("result"):
            msg_id = result["result"].get("message_id")
            return int(msg_id) if msg_id is not None else None
        return None

    async def send_info_message(self, text: str) -> None:
        """Send an informational message (no response expected)."""
        await self.send_message(text)

    async def edit_message_with_rule_keyboard(
        self,
        message_id: int,
        original_text: str,
        request_id: str,
        patterns: list[tuple[str, str]],
        callback_prefix: str = "add_rule_pattern",
        cancel_callback: Optional[str] = None,
    ) -> None:
        """Edit message to show rule pattern options inline.

        Args:
            patterns: List of (pattern, label) tuples
            callback_prefix: Prefix for pattern selection callbacks (default: "add_rule_pattern")
            cancel_callback: Optional custom cancel callback (default: "cancel_rule:{request_id}")
        """
        # Build keyboard with one button per pattern
        buttons = []
        for idx, (pattern, label) in enumerate(patterns):
            # callback_prefix already includes request_id for chain patterns
            if ":" in callback_prefix:
                buttons.append(
                    [{"text": label, "callback_data": f"{callback_prefix}:{idx}"}]
                )
            else:
                buttons.append(
                    [
                        {
                            "text": label,
                            "callback_data": f"{callback_prefix}:{request_id}:{idx}",
                        }
                    ]
                )
        # Add approve and cancel buttons at the bottom
        if cancel_callback is None:
            cancel_callback = f"cancel_rule:{request_id}"

        buttons.append(
            [
                {"text": "✅ Approve", "callback_data": f"approve:{request_id}"},
                {"text": "↩️ Cancel", "callback_data": cancel_callback},
            ]
        )

        keyboard = {"inline_keyboard": buttons}

        # Escape HTML in original text to prevent parsing errors
        escaped_text = escape_html(original_text)

        await self._api_request(
            "editMessageText",
            data={
                "chat_id": self.chat_id,
                "message_id": message_id,
                "text": f"{escaped_text}\n\n📝 <b>Approve rule pattern:</b>",
                "parse_mode": "HTML",
                "reply_markup": json.dumps(keyboard),
            },
        )

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        """Answer a callback query.

        Uses a short timeout (8s) since Telegram requires callback responses
        within 10 seconds or shows "query is too old" error to users.
        """
        await self._api_request(
            "answerCallbackQuery",
            data={
                "callback_query_id": callback_id,
                "text": text,
            },
            timeout=8.0,
        )

    async def restore_approval_keyboard(
        self,
        message_id: int,
        request_id: str,
        session_id: str,
        tool_name: str,
        tool_input: Optional[str] = None,
        project_path: Optional[str] = None,
    ) -> None:
        """Restore the original approval message and keyboard."""
        # Rebuild the message
        message = format_approval_message(
            request_id=request_id,
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            timeout=self.timeout,
            timeout_action=self.timeout_action,
            project_path=project_path,
        )

        # Rebuild the keyboard
        keyboard = self._build_approval_keyboard(
            request_id, session_id, tool_name, tool_input
        )

        await self._api_request(
            "editMessageText",
            data={
                "chat_id": self.chat_id,
                "message_id": message_id,
                "text": message,
                "parse_mode": "HTML",
                "reply_markup": json.dumps(keyboard),
            },
        )

    async def get_updates(
        self, offset: Optional[int] = None, timeout: int = 30
    ) -> list[dict[str, Any]]:
        """Get updates (for polling)."""
        data = {"timeout": timeout}
        if offset is not None:
            data["offset"] = offset

        result = await self._api_request("getUpdates", data=data)
        if result.get("ok") and "result" in result:
            updates: list[dict[str, Any]] = result.get("result", [])
            return updates
        return []

    async def send_feedback_prompt(self, tool_name: str) -> Optional[int]:
        """Send a message asking for denial feedback with force_reply."""
        debug_chain("send_feedback_prompt called", tool_name=tool_name)
        result = await self._api_request(
            "sendMessage",
            data={
                "chat_id": self.chat_id,
                "text": f"💬 Reply with feedback for denying {tool_name}:",
                "reply_markup": json.dumps({"force_reply": True, "selective": True}),
            },
        )
        debug_chain(
            "send_feedback_prompt result",
            ok=result.get("ok"),
            has_result="result" in result,
        )
        if result.get("ok") and "result" in result:
            raw_id = result["result"].get("message_id")
            msg_id = int(raw_id) if raw_id is not None else None
            debug_chain("send_feedback_prompt returning", msg_id=msg_id)
            return msg_id
        debug_chain("send_feedback_prompt failed", result=result)
        return None

    async def send_subagent_stop(
        self,
        subagent_id: str,
        output_summary: str,
        project_path: Optional[str] = None,
        description: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        files_modified: Optional[list[str]] = None,
    ) -> tuple[Optional[int], str]:
        """Send subagent completion notification.

        Returns:
            Tuple of (message_id, compact_text for auto-dismiss)
        """
        # Format project path
        project_id = format_project_id(project_path, subagent_id)

        # Format duration
        duration_str = ""
        if duration_seconds is not None:
            mins = int(duration_seconds // 60)
            secs = int(duration_seconds % 60)
            if mins > 0:
                duration_str = f" ({mins}m {secs}s)"
            else:
                duration_str = f" ({secs}s)"

        # Build message lines (using HTML for consistency with approval messages)
        lines = [f"<i>{project_id}</i> 🤖 <b>Done</b>{duration_str}"]

        if description:
            desc = description[:80] + "..." if len(description) > 80 else description
            lines.append(f"📝 {escape_html(desc)}")

        if files_modified:
            if len(files_modified) <= 3:
                files_str = ", ".join(files_modified)
            else:
                files_str = (
                    ", ".join(files_modified[:3]) + f" (+{len(files_modified) - 3})"
                )
            lines.append(f"📁 {escape_html(files_str)}")

        # Add brief summary (truncated)
        if output_summary:
            summary = (
                output_summary[:200] + "..."
                if len(output_summary) > 200
                else output_summary
            )
            lines.append(f"\n{escape_html(summary)}")

        text = "\n".join(lines)

        # Compact text for auto-dismiss (HTML format)
        brief_desc = (
            description[:40] + "..."
            if description and len(description) > 40
            else (description or "task")
        )
        compact_text = (
            f"<i>{project_id}</i> ✅ Agent: {escape_html(brief_desc)}{duration_str}"
        )

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ OK", "callback_data": f"subagent_ok:{subagent_id}"},
                    {
                        "text": "💬 Continue...",
                        "callback_data": f"subagent_continue:{subagent_id}",
                    },
                ],
            ]
        }

        result = await self._api_request(
            "sendMessage",
            data={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": json.dumps(keyboard),
            },
        )

        if result.get("ok") and "result" in result:
            msg_id = result["result"].get("message_id")
            return (int(msg_id) if msg_id is not None else None, compact_text)
        return (None, compact_text)

    async def send_stop_notification(
        self,
        session_id: str,
        project_path: Optional[str] = None,
    ) -> Optional[int]:
        """Send stop notification with OK/Comment buttons."""
        # Format project path
        project_id = format_project_id(project_path, session_id)

        text = f"<i>{escape_html(project_id)}</i>\n⏸️ <b>Claude is about to stop</b>"

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ OK", "callback_data": f"stop_ok:{session_id}"},
                    {
                        "text": "💬 Comment",
                        "callback_data": f"stop_comment:{session_id}",
                    },
                ],
            ]
        }

        result = await self._api_request(
            "sendMessage",
            data={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": json.dumps(keyboard),
            },
        )

        if result.get("ok") and "result" in result:
            msg_id = result["result"].get("message_id")
            return int(msg_id) if msg_id is not None else None
        return None

    async def send_rule_menu(
        self, request_id: str, patterns: list[str]
    ) -> Optional[int]:
        """Send a menu with rule pattern options."""
        # Build keyboard with one button per pattern
        buttons = []
        for idx, pattern in enumerate(patterns):
            label = _truncate_pattern_label(pattern, max_len=40)
            buttons.append(
                [
                    {
                        "text": label,
                        "callback_data": f"add_rule_pattern:{request_id}:{idx}",
                    }
                ]
            )

        keyboard = {"inline_keyboard": buttons}

        result = await self._api_request(
            "sendMessage",
            data={
                "chat_id": self.chat_id,
                "text": "📝 Approve rule pattern:",
                "reply_markup": json.dumps(keyboard),
            },
        )

        if result.get("ok") and "result" in result:
            msg_id = result["result"].get("message_id")
            return int(msg_id) if msg_id is not None else None
        return None

    async def send_continue_prompt(self) -> Optional[int]:
        """Send a message asking for continuation instructions."""
        result = await self._api_request(
            "sendMessage",
            data={
                "chat_id": self.chat_id,
                "text": "💬 Reply with instructions for the agent:",
                "reply_markup": json.dumps({"force_reply": True, "selective": True}),
            },
        )
        if result.get("ok") and "result" in result:
            msg_id = result["result"].get("message_id")
            return int(msg_id) if msg_id is not None else None
        return None

    async def send_chain_approval_request(
        self,
        request_id: str,
        session_id: str,
        commands: list[str],
        project_path: Optional[str] = None,
        description: Optional[str] = None,
        approved_indices: Optional[list[int]] = None,
    ) -> Optional[int]:
        """Send chain approval request with stacked command list.

        Args:
            request_id: The approval request ID
            session_id: The session ID
            commands: List of commands in the chain
            project_path: Optional project path for display
            description: Optional description of the chain
            approved_indices: Indices of commands pre-approved by rules

        Returns:
            Message ID if successful

        Raises:
            ValueError: If commands list is empty
        """
        # Validate commands list
        if not commands:
            raise ValueError("Cannot create chain approval with empty commands")
        if approved_indices is None:
            approved_indices = []

        # Format project identifier
        project_id = format_project_id(project_path, session_id)

        # Build the message with stacked command list
        lines = [f"<i>{escape_html(project_id)}</i>"]

        if description:
            desc = description[:100] + "..." if len(description) > 100 else description
            lines.append(f"<i>{escape_html(desc)}</i>")

        lines.append("<b>Command chain approval:</b>\n")

        # Show all commands with progress markers
        # Handle message length limit (Telegram: 4096 chars max)
        # If too many commands, truncate the middle
        MAX_MESSAGE_LENGTH = 4000  # Leave buffer for formatting

        # Find first unapproved command index
        first_unapproved = 0
        while first_unapproved < len(commands) and first_unapproved in approved_indices:
            first_unapproved += 1

        # Build command list first to check length
        cmd_lines = []
        for idx, cmd in enumerate(commands):
            if idx in approved_indices:
                marker = "✓"
            elif idx == first_unapproved:
                marker = "→"
            else:
                marker = " "

            # Truncate long commands
            cmd_display = cmd if len(cmd) <= 60 else cmd[:60] + "..."
            cmd_lines.append(f"{marker} <code>{escape_html(cmd_display)}</code>")

        # Check if message would be too long
        temp_message = "\n".join(lines + cmd_lines)
        if len(temp_message) > MAX_MESSAGE_LENGTH:
            # Truncate command list: show first 20, ellipsis, last 10
            if len(commands) > 30:
                truncated_cmd_lines = []
                for idx in range(min(20, len(commands))):
                    cmd = commands[idx]
                    if idx in approved_indices:
                        marker = "✓"
                    elif idx == first_unapproved:
                        marker = "→"
                    else:
                        marker = " "
                    cmd_display = cmd if len(cmd) <= 60 else cmd[:60] + "..."
                    truncated_cmd_lines.append(
                        f"{marker} <code>{escape_html(cmd_display)}</code>"
                    )

                truncated_cmd_lines.append(
                    f"<i>... {len(commands) - 30} more commands ...</i>"
                )

                for idx in range(len(commands) - 10, len(commands)):
                    cmd = commands[idx]
                    if idx in approved_indices:
                        marker = "✓"
                    elif idx == first_unapproved:
                        marker = "→"
                    else:
                        marker = " "
                    cmd_display = cmd if len(cmd) <= 60 else cmd[:60] + "..."
                    truncated_cmd_lines.append(
                        f"{marker} <code>{escape_html(cmd_display)}</code>"
                    )

                cmd_lines = truncated_cmd_lines

        lines.extend(cmd_lines)
        message = "\n".join(lines)

        # Keyboard for first unapproved command
        keyboard = self._build_chain_keyboard(request_id, current_idx=first_unapproved)

        result = await self._api_request(
            "sendMessage",
            data={
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
                "reply_markup": json.dumps(keyboard),
            },
        )

        if result.get("ok") and "result" in result:
            msg_id = result["result"].get("message_id")
            return int(msg_id) if msg_id is not None else None
        return None

    async def update_chain_progress(
        self,
        message_id: int,
        request_id: str,
        session_id: str,
        commands: list[str],
        current_idx: int,
        approved_indices: list[int],
        project_path: Optional[str] = None,
        description: Optional[str] = None,
        final_approve: bool = False,
        denied: bool = False,
    ) -> None:
        """Update chain approval message with progress.

        Args:
            message_id: The Telegram message to edit
            request_id: The approval request ID
            session_id: The session ID
            commands: List of commands in the chain
            current_idx: Index of current command being reviewed
            approved_indices: List of indices that have been approved
            project_path: Optional project path for display
            description: Optional description
            final_approve: If True, show final "Approve All" confirmation
            denied: If True, show denial state

        Raises:
            ValueError: If current_idx is out of bounds
        """
        debug_chain(
            "update_chain_progress",
            current_idx=current_idx,
            approved_indices=approved_indices,
            final_approve=final_approve,
            denied=denied,
        )
        # Validate current_idx
        if current_idx < 0 or current_idx >= len(commands):
            raise ValueError(
                f"current_idx {current_idx} out of bounds for {len(commands)} commands"
            )
        # Format project identifier
        project_id = format_project_id(project_path, session_id)

        # Build the message with stacked command list
        lines = [f"<i>{escape_html(project_id)}</i>"]

        if description:
            desc = description[:100] + "..." if len(description) > 100 else description
            lines.append(f"<i>{escape_html(desc)}</i>")

        lines.append("<b>Command chain approval:</b>\n")

        # Show all commands with progress markers
        # Handle message length limit (Telegram: 4096 chars max)
        MAX_MESSAGE_LENGTH = 4000  # Leave buffer for formatting

        # Build command list first to check length
        cmd_lines = []
        for idx, cmd in enumerate(commands):
            if idx in approved_indices:
                marker = "✓"
            elif idx == current_idx and not denied:
                marker = "→"
            else:
                marker = " "

            # Truncate long commands
            cmd_display = cmd if len(cmd) <= 60 else cmd[:60] + "..."
            cmd_lines.append(f"{marker} <code>{escape_html(cmd_display)}</code>")

        # Check if message would be too long
        temp_message = "\n".join(lines + cmd_lines)
        if len(temp_message) > MAX_MESSAGE_LENGTH:
            # Truncate command list: show first 20, current, last 10
            if len(commands) > 30:
                truncated_cmd_lines = []
                # First 20 commands
                for idx in range(min(20, len(commands))):
                    cmd = commands[idx]
                    if idx in approved_indices:
                        marker = "✓"
                    elif idx == current_idx and not denied:
                        marker = "→"
                    else:
                        marker = " "
                    cmd_display = cmd if len(cmd) <= 60 else cmd[:60] + "..."
                    truncated_cmd_lines.append(
                        f"{marker} <code>{escape_html(cmd_display)}</code>"
                    )

                # Add ellipsis
                truncated_cmd_lines.append(
                    f"<i>... {len(commands) - 30} more commands ...</i>"
                )

                # Last 10 commands
                for idx in range(len(commands) - 10, len(commands)):
                    cmd = commands[idx]
                    if idx in approved_indices:
                        marker = "✓"
                    elif idx == current_idx and not denied:
                        marker = "→"
                    else:
                        marker = " "
                    cmd_display = cmd if len(cmd) <= 60 else cmd[:60] + "..."
                    truncated_cmd_lines.append(
                        f"{marker} <code>{escape_html(cmd_display)}</code>"
                    )

                cmd_lines = truncated_cmd_lines

        lines.extend(cmd_lines)
        message = "\n".join(lines)

        # Determine keyboard based on state
        keyboard: dict[str, list[list[dict[str, str]]]]
        if denied:
            # Chain was denied - no keyboard
            keyboard = {"inline_keyboard": []}
        elif final_approve:
            # All commands approved - this shouldn't happen anymore (auto-approve)
            # but keep for backwards compatibility
            keyboard = {
                "inline_keyboard": [
                    [
                        {
                            "text": "✅ Approve All",
                            "callback_data": f"chain_approve_all:{request_id}",
                        },
                        {
                            "text": "❌ Cancel",
                            "callback_data": f"chain_deny:{request_id}",
                        },
                    ],
                ]
            }
        else:
            # Show keyboard for current command - Approve Chain first (full width), then step approve
            keyboard = self._build_chain_keyboard(request_id, current_idx)

        await self._api_request(
            "editMessageText",
            data={
                "chat_id": self.chat_id,
                "message_id": message_id,
                "text": message,
                "parse_mode": "HTML",
                "reply_markup": json.dumps(keyboard),
            },
        )

"""Telegram notifier using Bot API."""

import json
from typing import Optional

import httpx

from pyafk.notifiers.base import Notifier


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
    if project_path:
        # Show last 2 path components for context
        parts = project_path.rstrip("/").split("/")
        project_id = "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
    else:
        project_id = session_id[:8]

    # Compact format: project, optional description, then tool call
    lines = [f"<i>{_escape_html(project_id)}</i>"]

    if description:
        # Show description in italic before the tool
        desc = description[:100] + "..." if len(description) > 100 else description
        lines.append(f"<i>{_escape_html(desc)}</i>")

    lines.append(f"<b>[{_escape_html(tool_name)}]</b> <code>{_escape_html(input_summary)}</code>")

    return "\n".join(lines)


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _escape_markdown(text: str) -> str:
    """Escape Markdown special characters for Telegram."""
    # Characters that need escaping in Telegram Markdown
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f"\\{char}")
    return text


def _truncate_pattern_label(pattern: str, max_len: int = 40) -> str:
    """Truncate pattern for button label, preserving distinctive ending."""
    if len(pattern) <= max_len:
        return pattern

    # For patterns with paths, show command + ... + ending
    # e.g., "rm /Users/bembu/.pyafk/test_file.txt" -> "rm .../test_file.txt"
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
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout
        self.timeout_action = timeout_action
        self._base_url = f"https://api.telegram.org/bot{bot_token}"

    async def _api_request(
        self,
        method: str,
        data: Optional[dict] = None,
    ) -> dict:
        """Make a Telegram API request."""
        url = f"{self._base_url}/{method}"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, data=data, timeout=30)
                return response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            return {"ok": False, "error": str(e)}

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

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ Approve", "callback_data": f"approve:{request_id}"},
                    {"text": "📝 Rule", "callback_data": f"add_rule:{request_id}"},
                    {"text": f"⏩ All {tool_name}", "callback_data": f"approve_all:{session_id}:{tool_name}"},
                ],
                [
                    {"text": "❌ Deny", "callback_data": f"deny:{request_id}"},
                    {"text": "💬 Deny+Msg", "callback_data": f"deny_msg:{request_id}"},
                ],
            ]
        }

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
            return result["result"].get("message_id")
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
    ):
        """Edit a sent message and optionally remove keyboard."""
        data = {
            "chat_id": self.chat_id,
            "message_id": message_id,
            "text": new_text,
            "parse_mode": "HTML",
        }
        if remove_keyboard:
            data["reply_markup"] = json.dumps({"inline_keyboard": []})
        await self._api_request("editMessageText", data=data)

    async def edit_message_with_rule_keyboard(
        self,
        message_id: int,
        original_text: str,
        request_id: str,
        patterns: list[tuple[str, str]],
    ):
        """Edit message to show rule pattern options inline.

        Args:
            patterns: List of (pattern, label) tuples
        """
        # Build keyboard with one button per pattern
        buttons = []
        for idx, (pattern, label) in enumerate(patterns):
            buttons.append([{"text": label, "callback_data": f"add_rule_pattern:{request_id}:{idx}"}])
        # Add approve and cancel buttons at the bottom
        buttons.append([
            {"text": "✅ Approve", "callback_data": f"approve:{request_id}"},
            {"text": "↩️ Cancel", "callback_data": f"cancel_rule:{request_id}"},
        ])

        keyboard = {"inline_keyboard": buttons}

        await self._api_request(
            "editMessageText",
            data={
                "chat_id": self.chat_id,
                "message_id": message_id,
                "text": f"{original_text}\n\n📝 <b>Approve rule pattern:</b>",
                "parse_mode": "HTML",
                "reply_markup": json.dumps(keyboard),
            },
        )

    async def answer_callback(self, callback_id: str, text: str = ""):
        """Answer a callback query."""
        await self._api_request(
            "answerCallbackQuery",
            data={
                "callback_query_id": callback_id,
                "text": text,
            },
        )

    async def restore_approval_keyboard(
        self,
        message_id: int,
        request_id: str,
        session_id: str,
        tool_name: str,
        tool_input: Optional[str] = None,
        project_path: Optional[str] = None,
    ):
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
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ Approve", "callback_data": f"approve:{request_id}"},
                    {"text": "📝 Rule", "callback_data": f"add_rule:{request_id}"},
                    {"text": f"⏩ All {tool_name}", "callback_data": f"approve_all:{session_id}:{tool_name}"},
                ],
                [
                    {"text": "❌ Deny", "callback_data": f"deny:{request_id}"},
                    {"text": "💬 Deny+Msg", "callback_data": f"deny_msg:{request_id}"},
                ],
            ]
        }

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

    async def get_updates(self, offset: Optional[int] = None, timeout: int = 30) -> list:
        """Get updates (for polling)."""
        data = {"timeout": timeout}
        if offset is not None:
            data["offset"] = offset

        result = await self._api_request("getUpdates", data=data)
        if result.get("ok") and "result" in result:
            return result.get("result", [])
        return []

    async def send_feedback_prompt(self, tool_name: str) -> Optional[int]:
        """Send a message asking for denial feedback with force_reply."""
        result = await self._api_request(
            "sendMessage",
            data={
                "chat_id": self.chat_id,
                "text": f"💬 Reply with feedback for denying {tool_name}:",
                "reply_markup": json.dumps({"force_reply": True, "selective": True}),
            },
        )
        if result.get("ok") and "result" in result:
            return result["result"].get("message_id")
        return None

    async def send_subagent_stop(
        self,
        subagent_id: str,
        output_summary: str,
        project_path: Optional[str] = None,
    ) -> Optional[int]:
        """Send subagent completion notification with continue option."""
        # Format project path
        if project_path:
            parts = project_path.rstrip("/").split("/")
            project_id = "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
        else:
            project_id = subagent_id[:8]

        # Truncate output if too long (Telegram limit ~4096 chars)
        if len(output_summary) > 3000:
            output_summary = output_summary[-3000:]
            output_summary = "..." + output_summary

        # Use Markdown for the output (agent responses are often in markdown)
        # Header in bold, then the markdown content as-is
        text = f"*{_escape_markdown(project_id)}*\n🤖 *Subagent finished*\n\n{output_summary}"

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ OK", "callback_data": f"subagent_ok:{subagent_id}"},
                    {"text": "💬 Continue", "callback_data": f"subagent_continue:{subagent_id}"},
                ],
            ]
        }

        result = await self._api_request(
            "sendMessage",
            data={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "reply_markup": json.dumps(keyboard),
            },
        )

        if result.get("ok") and "result" in result:
            return result["result"].get("message_id")
        return None

    async def send_rule_menu(self, request_id: str, patterns: list[str]) -> Optional[int]:
        """Send a menu with rule pattern options."""
        # Build keyboard with one button per pattern
        buttons = []
        for idx, pattern in enumerate(patterns):
            label = _truncate_pattern_label(pattern, max_len=40)
            buttons.append([{"text": label, "callback_data": f"add_rule_pattern:{request_id}:{idx}"}])

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
            return result["result"].get("message_id")
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
            return result["result"].get("message_id")
        return None

    async def send_document(self, file_path: Path, caption: str = "") -> Optional[int]:
        """Send a file as a document."""
        import aiofiles

        url = f"{self._base_url}/sendDocument"
        try:
            async with aiofiles.open(file_path, "rb") as f:
                file_content = await f.read()

            async with httpx.AsyncClient() as client:
                files = {"document": (file_path.name, file_content)}
                data = {"chat_id": self.chat_id}
                if caption:
                    data["caption"] = caption
                response = await client.post(url, data=data, files=files, timeout=30)
                result = response.json()

            if result.get("ok") and "result" in result:
                return result["result"].get("message_id")
        except Exception:
            pass
        return None

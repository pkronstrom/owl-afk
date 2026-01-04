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
                    {"text": "❌ Deny", "callback_data": f"deny:{request_id}"},
                ],
                [
                    {"text": "📝 Rule", "callback_data": f"add_rule:{request_id}"},
                    {"text": f"⏩ All {tool_name}", "callback_data": f"approve_all:{session_id}:{tool_name}"},
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

    async def answer_callback(self, callback_id: str, text: str = ""):
        """Answer a callback query."""
        await self._api_request(
            "answerCallbackQuery",
            data={
                "callback_query_id": callback_id,
                "text": text,
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

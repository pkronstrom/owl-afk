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
) -> str:
    """Format a tool request for Telegram display."""
    # Format timeout - always show in minutes for consistency
    timeout_str = f"{timeout // 60}m"

    # Parse and format tool input
    input_display = ""
    if tool_input:
        try:
            data = json.loads(tool_input)
            if "command" in data:
                cmd = data["command"]
                if len(cmd) > 500:
                    cmd = cmd[:500] + "..."
                input_display = f"\n<b>Command:</b>\n<code>{_escape_html(cmd)}</code>"
            elif "file_path" in data:
                input_display = f"\n<b>File:</b> <code>{_escape_html(data['file_path'])}</code>"
            else:
                input_str = json.dumps(data, indent=2)
                if len(input_str) > 500:
                    input_str = input_str[:500] + "..."
                input_display = f"\n<b>Input:</b>\n<code>{_escape_html(input_str)}</code>"
        except (json.JSONDecodeError, TypeError):
            if len(tool_input) > 500:
                tool_input = tool_input[:500] + "..."
            input_display = f"\n<b>Input:</b> <code>{_escape_html(tool_input)}</code>"

    # Build message
    lines = [
        f"<b>Tool Request</b> [<code>{session_id}</code>]",
        "",
        f"<b>Tool:</b> {_escape_html(tool_name)}",
    ]

    if description:
        lines.append(f"<b>Description:</b> {_escape_html(description)}")

    lines.append(input_display)

    if context:
        lines.append(f"\n<b>Context:</b> {_escape_html(context)}")

    lines.extend([
        "",
        "-" * 20,
        f"Timeout: {timeout_str} ({timeout_action})",
    ])

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
        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data, timeout=30)
            return response.json()

    async def send_approval_request(
        self,
        request_id: str,
        session_id: str,
        tool_name: str,
        tool_input: Optional[str] = None,
        context: Optional[str] = None,
        description: Optional[str] = None,
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
        )

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "Approve", "callback_data": f"approve:{request_id}"},
                    {"text": "Deny", "callback_data": f"deny:{request_id}"},
                ],
                [
                    {"text": "Approve All", "callback_data": f"approve_all:{session_id}"},
                    {"text": "Add Rule", "callback_data": f"add_rule:{request_id}"},
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

        if result.get("ok"):
            return result["result"]["message_id"]
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
    ):
        """Edit a sent message."""
        await self._api_request(
            "editMessageText",
            data={
                "chat_id": self.chat_id,
                "message_id": message_id,
                "text": new_text,
                "parse_mode": "HTML",
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

    async def get_updates(self, offset: Optional[int] = None, timeout: int = 30) -> list:
        """Get updates (for polling)."""
        data = {"timeout": timeout}
        if offset is not None:
            data["offset"] = offset

        result = await self._api_request("getUpdates", data=data)
        if result.get("ok"):
            return result.get("result", [])
        return []

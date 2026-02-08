"""Fake Telegram notifier and chain approval simulator for testing.

Provides in-memory implementations of the TelegramCallbackNotifier protocol,
enabling tests to simulate the full button-press -> handler -> state update ->
message edit cycle without any network calls.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from owl.core.handlers.dispatcher import HandlerDispatcher
from owl.core.storage import Storage
from owl.utils.formatting import escape_html, format_project_id


@dataclass
class SentMessage:
    """Record of a message sent or edited."""

    message_id: int
    text: str
    keyboard: Optional[dict] = None
    method: str = "send"  # "send" or "edit"


class FakeTelegramNotifier:
    """In-memory TelegramCallbackNotifier for testing button flows.

    Implements the TelegramCallbackNotifier protocol. Records all messages
    and edits in memory. Provides helpers to inspect state.
    """

    def __init__(self) -> None:
        self.messages: list[SentMessage] = []
        self._next_msg_id = 1
        self._callback_answers: list[str] = []

    # --- TelegramCallbackNotifier protocol implementation ---

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        self._callback_answers.append(text)

    async def edit_message(
        self,
        message_id: int,
        new_text: str,
        remove_keyboard: bool = True,
        parse_mode: Optional[str] = "HTML",
    ) -> None:
        keyboard = None if remove_keyboard else {}
        self.messages.append(SentMessage(message_id, new_text, keyboard, "edit"))

    async def delete_message(self, message_id: int) -> None:
        pass

    async def send_message(self, text: str) -> Optional[int]:
        msg_id = self._next_msg_id
        self._next_msg_id += 1
        self.messages.append(SentMessage(msg_id, text, None, "send"))
        return msg_id

    async def edit_message_with_rule_keyboard(
        self,
        message_id: int,
        original_text: str,
        request_id: str,
        patterns: list[tuple[str, str]],
        callback_prefix: str = "add_rule_pattern",
        cancel_callback: Optional[str] = None,
    ) -> None:
        keyboard = {
            "inline_keyboard": [
                [{"text": label, "callback_data": f"{callback_prefix}:{i}"}]
                for i, (pattern, label) in enumerate(patterns)
            ]
        }
        if cancel_callback:
            keyboard["inline_keyboard"].append(
                [{"text": "Cancel", "callback_data": cancel_callback}]
            )
        self.messages.append(SentMessage(message_id, original_text, keyboard, "edit"))

    async def restore_approval_keyboard(
        self,
        message_id: int,
        request_id: str,
        session_id: str,
        tool_name: str,
        tool_input: Optional[str] = None,
        project_path: Optional[str] = None,
    ) -> None:
        self.messages.append(
            SentMessage(message_id, f"Restored: {request_id}", None, "edit")
        )

    async def send_feedback_prompt(self, tool_name: str) -> Optional[int]:
        return await self.send_message(f"Reply with feedback for {tool_name}")

    async def send_continue_prompt(self) -> Optional[int]:
        return await self.send_message("Reply with instructions for the agent:")

    async def send_chain_approval_request(
        self,
        request_id: str,
        session_id: str,
        commands: list[str],
        project_path: Optional[str] = None,
        description: Optional[str] = None,
        approved_indices: Optional[list[int]] = None,
        chain_title: Optional[str] = None,
    ) -> Optional[int]:
        if not commands:
            raise ValueError("Cannot create chain approval with empty commands")
        if approved_indices is None:
            approved_indices = []

        msg_id = self._next_msg_id
        self._next_msg_id += 1

        # Build text similar to real TelegramNotifier
        project_id = format_project_id(project_path, session_id)
        lines = [f"<i>{escape_html(project_id)}</i>"]

        if chain_title:
            lines.append(f"<b>{escape_html(chain_title)}</b>\n")
        else:
            lines.append("<b>Command chain approval:</b>\n")

        # Strip wrapper prefix for display
        display_prefix = (chain_title + " ") if chain_title else None

        first_unapproved = 0
        while first_unapproved < len(commands) and first_unapproved in approved_indices:
            first_unapproved += 1

        for idx, cmd in enumerate(commands):
            if idx in approved_indices:
                marker = "✓"
            elif idx == first_unapproved:
                marker = "→"
            else:
                marker = " "
            cmd_display = cmd
            if display_prefix and cmd_display.startswith(display_prefix):
                cmd_display = cmd_display[len(display_prefix):]
            lines.append(f"{marker} <code>{escape_html(cmd_display)}</code>")

        text = "\n".join(lines)

        # Build keyboard for first unapproved
        keyboard = self._build_chain_keyboard(request_id, first_unapproved)
        self.messages.append(SentMessage(msg_id, text, keyboard, "send"))
        return msg_id

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
        chain_title: Optional[str] = None,
    ) -> None:
        project_id = format_project_id(project_path, session_id)
        lines = [f"<i>{escape_html(project_id)}</i>"]

        if chain_title:
            lines.append(f"<b>{escape_html(chain_title)}</b>\n")
        else:
            lines.append("<b>Command chain approval:</b>\n")

        display_prefix = (chain_title + " ") if chain_title else None

        for idx, cmd in enumerate(commands):
            if idx in approved_indices:
                marker = "✓"
            elif idx == current_idx and not denied:
                marker = "→"
            else:
                marker = " "
            cmd_display = cmd
            if display_prefix and cmd_display.startswith(display_prefix):
                cmd_display = cmd_display[len(display_prefix):]
            lines.append(f"{marker} <code>{escape_html(cmd_display)}</code>")

        text = "\n".join(lines)

        if denied:
            keyboard: Optional[dict] = {"inline_keyboard": []}
        else:
            keyboard = self._build_chain_keyboard(request_id, current_idx)

        self.messages.append(SentMessage(message_id, text, keyboard, "edit"))

    def _build_chain_keyboard(
        self, request_id: str, current_idx: int
    ) -> dict[str, list[list[dict[str, str]]]]:
        """Build chain approval keyboard matching real TelegramNotifier."""
        return {
            "inline_keyboard": [
                [
                    {
                        "text": "» Approve Chain",
                        "callback_data": f"chain_approve_entire:{request_id}",
                    }
                ],
                [
                    {
                        "text": "✓ Approve",
                        "callback_data": f"chain_approve:{request_id}:{current_idx}",
                    },
                    {
                        "text": "+ Always...",
                        "callback_data": f"chain_rule:{request_id}:{current_idx}",
                    },
                ],
                [
                    {
                        "text": "✗ Deny",
                        "callback_data": f"chain_deny:{request_id}",
                    },
                    {
                        "text": "✗ Deny + msg",
                        "callback_data": f"chain_deny_msg:{request_id}",
                    },
                ],
            ]
        }

    # --- Test helpers ---

    @property
    def last_message(self) -> SentMessage:
        return self.messages[-1]

    def get_edits_for(self, message_id: int) -> list[SentMessage]:
        """Get all edit messages for a given message_id."""
        return [m for m in self.messages if m.message_id == message_id and m.method == "edit"]

    def get_chain_markers(self, message_id: int) -> list[str]:
        """Extract progress markers from the latest version of a chain message.

        Returns list of markers ('✓', '→', ' ') for each command.
        """
        # Find latest message with this ID
        for msg in reversed(self.messages):
            if msg.message_id == message_id:
                markers = []
                for line in msg.text.split("\n"):
                    if line.startswith("✓ "):
                        markers.append("✓")
                    elif line.startswith("→ "):
                        markers.append("→")
                    elif line.startswith("  <code>"):
                        markers.append(" ")
                return markers
        return []


class ChainApprovalSimulator:
    """Simulates the full chain approval flow for testing.

    Wires together Storage + FakeTelegramNotifier + HandlerDispatcher
    to test the complete button-press -> handler -> state update -> message edit cycle.
    """

    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self.notifier = FakeTelegramNotifier()
        self.dispatcher = HandlerDispatcher(storage, self.notifier)

    async def press_button(self, callback_data: str, message_id: int) -> None:
        """Simulate a Telegram button press."""
        await self.dispatcher.dispatch(
            callback_data=callback_data,
            callback_id=f"cb-{len(self.notifier.messages)}",
            message_id=message_id,
            original_text="",
        )

    async def approve_command(self, request_id: str, cmd_idx: int, message_id: int) -> None:
        """Shorthand for pressing approve on a chain command."""
        await self.press_button(f"chain_approve:{request_id}:{cmd_idx}", message_id)

    async def deny_chain(self, request_id: str, message_id: int) -> None:
        """Shorthand for pressing deny on a chain."""
        await self.press_button(f"chain_deny:{request_id}", message_id)

    async def approve_entire(self, request_id: str, message_id: int) -> None:
        """Shorthand for pressing approve entire chain."""
        await self.press_button(f"chain_approve_entire:{request_id}", message_id)

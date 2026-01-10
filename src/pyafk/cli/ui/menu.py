"""Terminal menu wrapper using simple-term-menu."""

from typing import Optional

from simple_term_menu import TerminalMenu


class RichTerminalMenu:
    """Wrapper around simple-term-menu with Rich styling."""

    def select(
        self,
        options: list[str],
        title: str = "",
        cursor_index: int = 0,
    ) -> Optional[int]:
        """Show selection menu.

        Args:
            options: List of option strings
            title: Optional title shown above menu
            cursor_index: Starting cursor position

        Returns:
            Selected index or None if cancelled (q/Ctrl+C)
        """
        if not options:
            return None

        menu = TerminalMenu(
            options,
            title=title if title else None,
            cursor_index=cursor_index,
            menu_cursor="> ",
            menu_cursor_style=("fg_cyan", "bold"),
            menu_highlight_style=("fg_cyan", "bold"),
            cycle_cursor=True,
            clear_screen=False,
        )

        result = menu.show()
        return result if result is not None else None

    def confirm(self, message: str, default: bool = False) -> bool:
        """Show yes/no confirmation.

        Args:
            message: Question to ask
            default: Default selection (False = No)

        Returns:
            True for yes, False for no/cancel
        """
        options = ["Yes", "No"]
        cursor = 0 if default else 1

        result = self.select(options, title=message, cursor_index=cursor)
        return result == 0

    def input(self, prompt: str, default: str = "") -> Optional[str]:
        """Get text input using configured editor.

        For simple inputs, uses inline prompt.
        For complex inputs, opens editor.

        Args:
            prompt: Input prompt
            default: Default value

        Returns:
            Input string or None if cancelled
        """
        import os
        import subprocess
        import tempfile

        from pyafk.utils.config import Config, get_pyafk_dir

        # Get editor from config or environment
        cfg = Config(get_pyafk_dir())
        editor = getattr(cfg, "editor", None) or os.environ.get("EDITOR", "vim")

        # Create temp file with default content
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(f"# {prompt}\n")
            f.write("# Lines starting with # are ignored\n")
            f.write(default)
            tmp_path = f.name

        try:
            subprocess.run([editor, tmp_path], check=True)

            with open(tmp_path) as fp:
                lines = [
                    ln.rstrip("\n") for ln in fp.readlines() if not ln.startswith("#")
                ]
            return "\n".join(lines).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        finally:
            os.unlink(tmp_path)

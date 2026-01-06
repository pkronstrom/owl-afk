"""Background daemon for continuous Telegram polling."""

import asyncio
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from pyafk.core.poller import Poller
from pyafk.core.storage import Storage
from pyafk.notifiers.telegram import TelegramNotifier
from pyafk.utils.config import Config, get_pyafk_dir


def get_pid_file(pyafk_dir: Optional[Path] = None) -> Path:
    """Get path to daemon PID file."""
    if pyafk_dir is None:
        pyafk_dir = get_pyafk_dir()
    return pyafk_dir / "daemon.pid"


def is_daemon_running(pyafk_dir: Optional[Path] = None) -> bool:
    """Check if daemon is currently running."""
    pid_file = get_pid_file(pyafk_dir)
    if not pid_file.exists():
        return False

    try:
        pid = int(pid_file.read_text().strip())
        # Check if process exists
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        # Invalid PID or process doesn't exist
        pid_file.unlink(missing_ok=True)
        return False


def get_daemon_pid(pyafk_dir: Optional[Path] = None) -> Optional[int]:
    """Get daemon PID if running."""
    pid_file = get_pid_file(pyafk_dir)
    if not pid_file.exists():
        return None

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)  # Check if process exists
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        return None


def start_daemon(pyafk_dir: Optional[Path] = None) -> bool:
    """Start the background daemon.

    Returns True if daemon was started, False if already running.
    """
    if pyafk_dir is None:
        pyafk_dir = get_pyafk_dir()

    if is_daemon_running(pyafk_dir):
        return False

    # Fork to create daemon
    pid = os.fork()
    if pid > 0:
        # Parent process - wait briefly for daemon to start
        time.sleep(0.5)
        return is_daemon_running(pyafk_dir)

    # First child - create new session
    os.setsid()

    # Fork again to prevent zombie processes
    pid = os.fork()
    if pid > 0:
        os._exit(0)

    # Daemon process
    # Change working directory
    os.chdir("/")

    # Redirect standard file descriptors to /dev/null
    # Use os.dup2 to properly redirect without leaking file descriptors
    devnull_fd = os.open("/dev/null", os.O_RDWR)
    os.dup2(devnull_fd, sys.stdin.fileno())
    os.dup2(devnull_fd, sys.stdout.fileno())
    os.dup2(devnull_fd, sys.stderr.fileno())
    os.close(devnull_fd)

    # Write PID file atomically to prevent race conditions
    pid_file = get_pid_file(pyafk_dir)
    try:
        fd = os.open(str(pid_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        # Another daemon started between our check and now
        os._exit(1)

    # Set up log file for daemon errors
    log_file = pyafk_dir / "daemon.log"

    # Run daemon main loop
    try:
        asyncio.run(daemon_main(pyafk_dir))
    except Exception as e:
        with open(log_file, "a") as f:
            import traceback
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} CRASH: {e}\n")
            f.write(traceback.format_exc())
    finally:
        pid_file.unlink(missing_ok=True)

    os._exit(0)


def stop_daemon(pyafk_dir: Optional[Path] = None) -> bool:
    """Stop the background daemon.

    Returns True if daemon was stopped, False if not running.
    """
    if pyafk_dir is None:
        pyafk_dir = get_pyafk_dir()

    pid = get_daemon_pid(pyafk_dir)
    if pid is None:
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        # Wait for process to exit
        for _ in range(50):  # 5 seconds max
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
        # Clean up PID file
        get_pid_file(pyafk_dir).unlink(missing_ok=True)
        return True
    except ProcessLookupError:
        get_pid_file(pyafk_dir).unlink(missing_ok=True)
        return True
    except PermissionError:
        return False


async def daemon_main(pyafk_dir: Path) -> None:
    """Main daemon loop.

    Continuously polls Telegram and handles:
    - /msg command (queue messages for sessions)
    - /afk command (toggle mode)
    - Approval callbacks (update request status)
    """
    import traceback

    log_file = pyafk_dir / "daemon.log"

    def log_error(msg: str, exc: Optional[Exception] = None) -> None:
        """Log error to daemon log file."""
        try:
            with open(log_file, "a") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
                if exc:
                    f.write(traceback.format_exc())
        except Exception:
            pass  # Can't log, ignore

    config = Config(pyafk_dir)

    # Check Telegram config
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return

    storage = Storage(config.db_path)
    notifier = TelegramNotifier(
        bot_token=config.telegram_bot_token,
        chat_id=config.telegram_chat_id,
    )
    poller = Poller(storage, notifier, pyafk_dir)

    # Set up signal handlers
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def handle_signal(sig: int, frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        await storage.connect()

        # Acquire poll lock
        if not await poller.lock.acquire(timeout=1.0):
            # Another poller is running, exit
            return

        try:
            # Main polling loop - runs regardless of mode
            # This allows /afk on, /start, /msg to work even when mode is "off"
            while not stop_event.is_set():
                try:
                    await poller.process_updates_once()
                except Exception as e:
                    log_error(f"Poll error: {e}", e)

                # Sleep between polls
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass

        finally:
            await poller.lock.release()

    finally:
        await storage.close()

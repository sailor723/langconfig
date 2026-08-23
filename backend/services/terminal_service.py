# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Interactive shell terminal sessions (VS Code-style).

Each WebSocket connection owns one `TerminalSession`: a shell subprocess
whose stdin/stdout are bridged to the socket. On POSIX a real PTY is used
so the shell runs interactively (prompt, colors, job control); on Windows
the process is bridged with plain pipes.

Wire protocol (JSON frames over WebSocket):
  Client -> Server:
    {"type": "input",  "data": "<text>"}
    {"type": "resize", "cols": 120, "rows": 30}
  Server -> Client:
    {"type": "ready",  "name": "zsh", "shell": "/bin/zsh"}
    {"type": "output", "data": "<text>"}
    {"type": "exit",   "code": 0}
    {"type": "error",  "message": "<reason>"}
"""
import asyncio
import os
import subprocess
from typing import Dict, Optional

# Live sessions keyed by terminal_id (used by the debug router)
active_sessions: Dict[str, "TerminalSession"] = {}


def pick_shell() -> str:
    """Choose the interactive shell for the current platform."""
    if os.name == "nt":
        return os.environ.get("COMSPEC", "cmd.exe")
    return os.environ.get("SHELL", "/bin/bash")


class TerminalSession:
    """One shell subprocess bridged to a WebSocket."""

    def __init__(self, terminal_id: str, websocket, shell: Optional[str] = None):
        self.terminal_id = terminal_id
        self.websocket = websocket
        self.shell = shell or pick_shell()
        self.proc: Optional[subprocess.Popen] = None
        self.master_fd: Optional[int] = None  # PTY master (POSIX only)
        self.reader: Optional[asyncio.Task] = None
        self.closed = False

    # ── lifecycle ──────────────────────────────────────────────

    async def start(self) -> None:
        """Spawn the shell and kick off the output pump."""
        env = dict(os.environ)
        env["TERM"] = "xterm-256color"
        if self.shell.endswith("bash"):
            env["PS1"] = "\\u@\\h:\\w$ "

        if os.name == "nt":
            # Windows: pipe-based subprocess bridge
            self.proc = await asyncio.create_subprocess_shell(
                self.shell,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
        else:
            # POSIX: real PTY for an interactive shell
            import pty

            master_fd, slave_fd = pty.openpty()
            self.master_fd = master_fd
            self.proc = subprocess.Popen(
                [self.shell, "-i"],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                env=env,
            )
            os.close(slave_fd)

        # Notify the client which shell is running (used as the tab title)
        await self.websocket.send_json(
            {"type": "ready", "name": os.path.basename(self.shell), "shell": self.shell}
        )

        self.reader = asyncio.create_task(self._pump_output())

    async def _pump_output(self) -> None:
        """Forward process output to the socket until it exits."""
        if self.master_fd is not None:
            # POSIX: drive the PTY master from the event loop
            loop = asyncio.get_event_loop()
            loop.add_reader(self.master_fd, self._on_master_readable)
            try:
                # Wait until the reader callback finishes the session
                while not self.closed:
                    await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                pass
            finally:
                try:
                    loop.remove_reader(self.master_fd)
                except Exception:
                    pass
        else:
            # Windows: async stdout read loop
            try:
                while not self.closed:
                    chunk = await self.proc.stdout.read(65536)
                    if not chunk:
                        break
                    await self._send_output(chunk)
            except asyncio.CancelledError:
                pass
            finally:
                await self._finish()

    def _on_master_readable(self) -> None:
        """PTY master callback: read available bytes and forward them.

        The reader may fire after ``_finish``/``close`` already nulled
        ``master_fd`` (the reader is removed only in ``_run``'s finally, up to
        200ms later) — guard and treat that as EOF instead of crashing with
        ``os.read(None, ...)``.
        """
        fd = self.master_fd
        if fd is None:
            # Session already torn down — nothing left to read.
            return
        try:
            data = os.read(fd, 65536)
        except OSError:
            data = b""
        if not data:
            # EOF / EIO — the shell exited; schedule the teardown
            asyncio.create_task(self._finish())
            return
        asyncio.create_task(self._send_output(data))

    async def _send_output(self, data: bytes) -> None:
        if self.closed:
            return
        try:
            await self.websocket.send_json(
                {"type": "output", "data": data.decode("utf-8", "replace")}
            )
        except Exception:
            # Socket gone — stop pumping
            self.closed = True

    # ── client commands ─────────────────────────────────────────

    async def write(self, data: str) -> None:
        """Write raw input bytes into the shell."""
        if self.closed or self.proc is None:
            return
        raw = data.encode("utf-8")
        if self.master_fd is not None:
            await asyncio.to_thread(os.write, self.master_fd, raw)
        else:
            if self.proc.stdin is not None:
                self.proc.stdin.write(raw)
                await self.proc.stdin.drain()

    async def resize(self, cols: int, rows: int) -> None:
        """Update the PTY window size (no-op on the Windows pipe bridge)."""
        if self.master_fd is None:
            return
        import fcntl
        import struct
        import termios

        try:
            fcntl.ioctl(
                self.master_fd,
                termios.TIOCSWINSZ,
                struct.pack("HHHH", max(rows, 1), max(cols, 1), 0, 0),
            )
        except OSError:
            pass

    # ── teardown ───────────────────────────────────────────────

    async def _finish(self) -> None:
        """Send the exit frame and stop the process."""
        if self.closed:
            return
        self.closed = True

        if self.reader:
            self.reader.cancel()

        code = 0
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    await asyncio.wait_for(asyncio.to_thread(self.proc.wait), timeout=2)
                except asyncio.TimeoutError:
                    self.proc.kill()
            code = self.proc.returncode if self.proc.returncode is not None else 0

        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None

        try:
            await self.websocket.send_json({"type": "exit", "code": code})
        except Exception:
            pass

    async def close(self) -> None:
        """Force teardown (client disconnected or error)."""
        if self.closed:
            return
        if self.reader:
            self.reader.cancel()
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(asyncio.to_thread(self.proc.wait), timeout=2)
            except asyncio.TimeoutError:
                self.proc.kill()
        self.closed = True
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None

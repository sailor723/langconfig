"""
Notebook Kernel Manager — manages IPython kernels for stateful notebook execution.

Uses jupyter_client to start/stop IPython kernels and execute code cells.
Each open notebook gets its own kernel for stateful execution across cells.
Kernels are auto-shutdown after a period of inactivity.
"""
import asyncio
import logging
import uuid
import json
import time
from typing import Dict, Any, Optional, List
from threading import Lock, RLock

from jupyter_client import KernelManager, BlockingKernelClient

logger = logging.getLogger(__name__)

# Timeout for kernel operations (seconds)
KERNEL_TIMEOUT = 60
# Idle timeout before shutting down unused kernels (seconds)
KERNEL_IDLE_TIMEOUT = 300  # 5 minutes


class KernelSession:
    """Represents a single kernel session for one notebook."""

    def __init__(self, session_id: str, cwd: str = None):
        self.session_id = session_id
        self.cwd = cwd
        self.km: Optional[KernelManager] = None
        self.kc: Optional[BlockingKernelClient] = None
        self.last_used: float = time.time()
        self.execution_count = 0
        # RLock so restart() can hold the lock across shutdown+start+chdir
        self._lock = RLock()

    def start(self):
        """Start the kernel."""
        with self._lock:
            if self.km is not None:
                return  # Already running

            try:
                self.km = KernelManager(kernel_name="python3")
                # cwd is applied via os.chdir after the kernel starts
                # (see get_or_create_session) so restart() can re-apply it.
                self.km.start_kernel()
                self.kc = self.km.client()
                self.kc.start_channels()
                self.last_used = time.time()
                self.execution_count = 0
                logger.info(f"Kernel started for session {self.session_id}")
            except Exception as e:
                logger.error(f"Failed to start kernel for session {self.session_id}: {e}")
                self.km = None
                self.kc = None
                raise

    def execute(self, code: str, timeout: int = KERNEL_TIMEOUT) -> Dict[str, Any]:
        """
        Execute code in the kernel and return results.

        Returns:
            dict with keys: success, stdout, stderr, execute_result, error_name, error_value, traceback
        """
        with self._lock:
            if self.kc is None:
                return {"success": False, "stdout": "", "stderr": "Kernel not started", "execute_result": ""}

            self.last_used = time.time()

            # Execute the code
            msg_id = self.kc.execute(code)
            self.execution_count += 1

            # Collect outputs
            stdout_lines = []
            stderr_lines = []
            execute_result = ""
            error_name = ""
            error_value = ""
            traceback_lines = []
            success = True
            timed_out = False

            try:
                while True:
                    try:
                        msg = self.kc.get_iopub_msg(timeout=timeout)
                    except Exception:
                        # Timeout reached — execution did not complete
                        timed_out = True
                        break

                    msg_type = msg.get("msg_type", "")
                    content = msg.get("content", {})

                    if msg_type == "stream":
                        stream_name = content.get("name", "")
                        text = content.get("text", "")
                        if stream_name == "stdout":
                            stdout_lines.append(text)
                        elif stream_name == "stderr":
                            stderr_lines.append(text)

                    elif msg_type == "execute_result":
                        data = content.get("data", {})
                        # Prefer text/plain, fallback to text/html
                        execute_result = data.get("text/plain", data.get("text/html", ""))

                    elif msg_type == "display_data":
                        data = content.get("data", {})
                        execute_result = data.get("text/plain", data.get("text/html", ""))

                    elif msg_type == "error":
                        success = False
                        error_name = content.get("ename", "")
                        error_value = content.get("evalue", "")
                        traceback_lines = content.get("traceback", [])

                    elif msg_type == "status":
                        execution_state = content.get("execution_state", "")
                        if execution_state == "idle":
                            # Wait briefly for any remaining output
                            time.sleep(0.1)
                            break

            except Exception as e:
                logger.warning(f"Error reading kernel output for session {self.session_id}: {e}")

            if timed_out:
                # Report the timeout honestly instead of a misleading success
                success = False
                error_name = "TimeoutError"
                error_value = f"Execution exceeded {timeout}s without completing"

            return {
                "success": success,
                "stdout": "".join(stdout_lines),
                "stderr": "".join(stderr_lines),
                "execute_result": execute_result,
                "error_name": error_name,
                "error_value": error_value,
                "traceback": "\n".join(traceback_lines),
            }

    def interrupt(self):
        """Interrupt the kernel (send SIGINT)."""
        with self._lock:
            if self.km:
                try:
                    self.km.interrupt_kernel()
                    logger.info(f"Kernel interrupted for session {self.session_id}")
                except Exception as e:
                    logger.warning(f"Failed to interrupt kernel: {e}")

    def restart(self):
        """Restart the kernel (clears all state) and re-apply the working directory."""
        # Hold the lock across shutdown+start so no execute() can interleave,
        # and re-apply cwd afterwards since start() does not set it.
        with self._lock:
            self.shutdown()
            self.start()
            if self.cwd:
                self.execute(f"import os; os.chdir({json.dumps(self.cwd)})")
        logger.info(f"Kernel restarted for session {self.session_id}")

    def shutdown(self):
        """Shutdown the kernel."""
        with self._lock:
            if self.kc:
                try:
                    self.kc.stop_channels()
                except Exception:
                    pass
                self.kc = None
            if self.km:
                try:
                    self.km.shutdown_kernel(now=True)
                except Exception:
                    pass
                self.km = None
            self.execution_count = 0
            logger.info(f"Kernel shut down for session {self.session_id}")

    @property
    def is_alive(self) -> bool:
        """Check if kernel is still alive."""
        if self.km is None:
            return False
        try:
            return self.km.is_alive()
        except Exception:
            return False


class NotebookKernelManager:
    """
    Global manager for all notebook kernels.

    Each notebook gets its own kernel session identified by a session_id.
    Kernels are auto-shutdown after KERNEL_IDLE_TIMEOUT of inactivity.
    """

    def __init__(self):
        self._sessions: Dict[str, KernelSession] = {}
        self._lock = Lock()

    def get_or_create_session(self, session_id: str, cwd: str = None) -> KernelSession:
        """Get existing kernel session or create a new one."""
        with self._lock:
            if session_id in self._sessions:
                session = self._sessions[session_id]
                if session.is_alive:
                    return session
                else:
                    # Kernel died, create a new one
                    logger.info(f"Kernel for session {session_id} died, recreating")
                    del self._sessions[session_id]

            session = KernelSession(session_id, cwd=cwd)
            session.start()
            # If cwd is set, cd to it after starting kernel
            if cwd:
                session.execute(f"import os; os.chdir({json.dumps(cwd)})")
            self._sessions[session_id] = session
            return session

    def get_session(self, session_id: str) -> Optional[KernelSession]:
        """Get an existing session without creating."""
        with self._lock:
            return self._sessions.get(session_id)

    def shutdown_session(self, session_id: str):
        """Shutdown a specific kernel session."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session:
            session.shutdown()

    def shutdown_all(self):
        """Shutdown all kernel sessions."""
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            try:
                session.shutdown()
            except Exception:
                pass

    def cleanup_idle(self):
        """Shutdown kernels that have been idle too long."""
        now = time.time()
        with self._lock:
            idle_sessions = [
                sid for sid, s in self._sessions.items()
                if (now - s.last_used) > KERNEL_IDLE_TIMEOUT
            ]
            # Pop once under the lock, then shut down outside it so we don't
            # hold the manager lock during blocking kernel teardown.
            sessions = [self._sessions.pop(sid) for sid in idle_sessions]
        for session in sessions:
            try:
                logger.info(f"Shutting down idle kernel session {session.session_id}")
                session.shutdown()
            except Exception:
                pass

    def __del__(self):
        """Cleanup on garbage collection."""
        self.shutdown_all()


# Singleton instance
_kernel_manager: Optional[NotebookKernelManager] = None
_kernel_manager_lock = Lock()


def get_kernel_manager() -> NotebookKernelManager:
    """Get or create the global kernel manager singleton."""
    global _kernel_manager
    if _kernel_manager is None:
        with _kernel_manager_lock:
            if _kernel_manager is None:
                _kernel_manager = NotebookKernelManager()
    return _kernel_manager

import asyncio
import contextlib
import sys
import time
from typing import Optional, List


# Meant to be one-time-disposal
class InteractiveProcV1:
    def __init__(self, timeout=0, graceful_period=1, kill_err_timeout=10):
        # Input
        self.timeout_seconds = timeout
        self.graceful_period_seconds = graceful_period
        self.kill_err_timeout_seconds = kill_err_timeout

        # Storage
        self.logs: List[str] = []
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.stop_now = asyncio.Event()
        self.error_message = ""

        # Switches
        self.used = False
        self.enable_timeout = True if timeout > 0 else False

        # Status
        self.is_stopping = False

    # ===== USER INHERIT & IMPLEMENTATION AREA =====
    async def create_subprocess(self) -> asyncio.subprocess.Process:
        # Subclass implements this and return process
        # proc = await asyncio.create_subprocess_exec(
        #     arg1, arg2, arg3,
        #     stdout=asyncio.subprocess.PIPE,
        #     stderr=asyncio.subprocess.PIPE,
        # )
        # return proc
        pass

    def stdout_handler(self, line):
        # Should you do something when reads a stdout line
        self.line_handler(line)

    def stderr_handler(self, line):
        # Should you do something when reads a stderr line
        self.line_handler(line)

    def line_handler(self, text):
        # Should you do something when reads a line
        pass

    def proc_info(self):
        # Should you need more info displayed in debug.print(), mod this
        try:
            pid = self.proc.pid
        except:
            pid = -1

        return f"{self.__class__.__name__}(PID:{pid})"


    # ===== SYSTEM COMPONENTS =====
    async def run(self, debug=False):
        # watchdog won't clean themselves, I need to clean in a shield
        timeout_watchdog: Optional[asyncio.Task] = None
        stop_watchdog: Optional[asyncio.Task] = None

        if not self.used:
            self.used = True
        try:
            self.proc = await self.create_subprocess()
            timeout_watchdog = asyncio.create_task(self._timeout_watchdog(debug=debug))
            stop_watchdog = asyncio.create_task(self._stop_watchdog(debug=debug))

            await asyncio.gather(
                self._std_reader(self.proc.stdout, self.stdout_handler, self.logs),
                self._std_reader(self.proc.stderr, self.stderr_handler, self.logs),
            )
        except asyncio.CancelledError:
            self.stop_now.set()
        finally:
            if timeout_watchdog:
                timeout_watchdog.cancel()
            if stop_watchdog:
                stop_watchdog.cancel()

            rc = -1
            try:
                rc = await asyncio.shield(asyncio.wait_for(self.proc.wait(), timeout=self.kill_err_timeout_seconds))
            except asyncio.TimeoutError:
                pass

            return rc, self.error_message, self.logs


    @staticmethod
    async def _std_reader(stream, line_handler, logs_list):
        while True:
            line = await stream.readline()
            text = line.decode("utf-8", errors="replace").rstrip("\n")
            if not line:
                break
            logs_list.append(text)
            line_handler(text)

    async def _timeout_watchdog(self, debug=False):
        method_name = "_timeout_watchdog"
        await asyncio.sleep(self.timeout_seconds)
        if self.enable_timeout and not self.stop_now.is_set():
            if debug:
                print(f"{self.proc_info()}.{method_name} set stop_now() event")
            self.error_message = f"Not ready in {self.timeout_seconds} seconds (timeout)"
            self.stop_now.set()
        else:
            if debug:
                print(f"{self.proc_info()}.{method_name} QUIT without KILL because enable_timeout={self.enable_timeout} stop_now.is_set()={self.stop_now.is_set()}")

    async def _stop_watchdog(self, debug=False):
        method_name = "_stop_watchdog"
        try:
            await self.stop_now.wait()
        except asyncio.CancelledError:
            raise
        finally:
            # ===== Idempotent: Only one stop routine will be run =====
            # Cancel Exception Safe: _quit_proc throw into space
            # Subprocess Kill: only if self.stop_now.is_set()
            if self.is_stopping:
                return
            self.is_stopping = True

            if self.stop_now.is_set():
                asyncio.create_task(self._quit_proc(debug=debug))
                if debug:
                    print(f"{self.proc_info()}.{method_name} spawned _quit_proc")
            else:
                if debug:
                    print(f"{self.proc_info()}.{method_name} goes off")

    async def _quit_proc(self, debug=False):
        # This function is created by asyncio.create_task(), hence it is free of CANCEL EVENT
        # It is its own responsibility to handle its life cycle.
        if not self.proc or not isinstance(self.proc, asyncio.subprocess.Process):
            return

        method_name = "_quit_proc"

        try:
            # Gracefully Exit
            with contextlib.suppress(ProcessLookupError):
                self.proc.terminate()
            # Gracefully wait for exit
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=self.graceful_period_seconds)
                if debug:
                    print(f"{self.proc_info()}.{method_name}  PROC gracefully Down.")
                return
            except asyncio.TimeoutError:
                pass

            # Forcefully Exit
            with contextlib.suppress(ProcessLookupError):
                self.proc.kill()
            # Last Wait for Exit
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=self.kill_err_timeout_seconds)
                if debug:
                    print(f"{self.proc_info()}.{method_name} PROC forcefully Down.")
            except asyncio.TimeoutError:
                print(
                    f"{self.proc_info()}.{method_name} PROC is killed yet still ACTIVE after {self.kill_err_timeout_seconds} seconds, I give up.",
                    file=sys.stderr,
                    flush=True
                )
        except Exception as e:
            print(f"{self.proc_info()}.{method_name} PROC is killed Failed because {e}", file=sys.stderr, flush=True)

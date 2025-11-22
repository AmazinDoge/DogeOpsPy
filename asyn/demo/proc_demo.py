# proc_demo.py
import asyncio
import sys
from typing import Optional
from pathlib import Path

from DogeOpsPy.asyn.subproc import InteractiveProcV1


# ---- Paste or import InteractiveProcV1 before this point ----
# Assuming InteractiveProcV1 is available in the same module namespace.
# If it's in another file (e.g., interactive_proc.py), replace the class definition
# comment above with: from interactive_proc import InteractiveProcV1


class ProcDemo(InteractiveProcV1):
    async def create_subprocess(self) -> asyncio.subprocess.Process:
        # A small Python one-liner that runs ~10 seconds and prints once per second.
        pycode = (
            "import time,sys\n"
            "for i in range(10):\n"
            "    print(f'tick {i+1}', flush=True)\n"
            "    time.sleep(1)\n"
        )
        return await asyncio.create_subprocess_exec(
            sys.executable, "-u", "-c", pycode,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    def line_handler(self, text):
        # Echo every line from the child so we can see progress.
        print(f"[child] {text}")

    def stdout_handler(self, line):
        # Inherit default behavior, but you could customize if needed.
        super().stdout_handler(line)

    def stderr_handler(self, line):
        super().stderr_handler(line)


async def main():
    print("Starting ProcDemo (10s job), will cancel after 2s, then await the task...")
    proc = ProcDemo(timeout=0, graceful_period=1, kill_err_timeout=3)

    task = asyncio.create_task(proc.run(debug=True))

    # Let it run for 2 seconds.
    await asyncio.sleep(2)

    # Cancel the task.
    print("Cancelling task now...")
    task.cancel()

    # Await and see what happens: CancelledError vs returned tuple.
    try:
        rc, err, logs = await task
        print("\n=== RESULT (no CancelledError propagated) ===")
        print(f"rc={rc}")
        print(f"error_message={err!r}")
        print(f"logs_count={len(logs)}")
        # Show a preview of logs
        preview = logs[:5]
        print(f"logs_preview={preview}")
    except asyncio.CancelledError:
        print("\n=== RESULT: CancelledError DID propagate ===")
    except Exception as e:
        print("\n=== RESULT: Other exception propagated ===")
        print(repr(e))


if __name__ == "__main__":
    # On Windows, ProactorEventLoop is default in 3.8+, so this is fine.
    # Just run the async main.
    asyncio.run(main())

from __future__ import annotations

import asyncio
import time

from server.runtime import DesktopAvatarEndpoint


def test_process_exit_timeout_does_not_leave_a_blocked_executor_worker() -> None:
    class RunningProcess:
        def poll(self):
            return None

        def wait(self):
            raise AssertionError("process.wait() must not run in an executor")

    async def scenario() -> None:
        started = time.monotonic()
        exited = await DesktopAvatarEndpoint._await_exit(
            None,  # type: ignore[arg-type]
            RunningProcess(),  # type: ignore[arg-type]
            asyncio.get_running_loop(),
            0.01,
        )
        assert exited is False
        assert time.monotonic() - started < 0.2

    asyncio.run(scenario())

"""Regression test for the ``ReentrantAsyncLock`` outside-task guard (N2 nit).

``ReentrantAsyncLock`` keys re-entrancy on ``asyncio.current_task()``. When
that call returns ``None`` (the caller is not running inside an asyncio task)
and the lock happens to be free, the old ``self._owner is task`` comparison
evaluated as ``None is None`` -> True. That let ``acquire()`` return without
ever taking the underlying ``asyncio.Lock`` and let ``release()`` drive
``_depth`` negative before releasing an un-held underlying lock (a misleading
``RuntimeError``). The guard added to ``adapter_types.ReentrantAsyncLock``
raises an explicit ``RuntimeError`` before the owner check can ever match on
``None``, so misuse surfaces clearly instead of via a silent false-positive.

This module pins both behaviours:

* ``acquire()`` / ``release()`` raise ``RuntimeError`` when invoked outside a
  task context (the trap ``None is None`` path must never return ``True``);
* same-task re-entrancy keeps working (the deadlock fix is unaffected).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from adapter_types import ReentrantAsyncLock  # noqa: E402

# Exact message raised by the guard; asserted so the test proves the guard
# itself fires (and not ``asyncio.current_task``'s own "no running event
# loop" error during the no-loop direct-call case).
GUARD_MESSAGE = "ReentrantAsyncLock must be used inside an asyncio task"


def test_acquire_outside_task_raises() -> None:
    """``acquire()`` must raise when there is no owning task context.

    Covers both the "no event loop at all" path (``current_task`` raises) and
    the "running loop, non-task callback" path where ``current_task`` returns
    ``None`` -- the exact ``None is None`` trap the guard closes.
    """
    # No running event loop: the owner check must never match on ``None``.
    with pytest.raises(RuntimeError):
        ReentrantAsyncLock().acquire().send(None)

    # Running loop, synchronous ``call_soon`` callback (no task) -> the guard
    # must fire with the explicit message. The exception is caught inside the
    # callback because asyncio swallows callback exceptions at the loop level.
    captured: list[RuntimeError] = []
    loop = asyncio.new_event_loop()
    try:
        loop.call_soon(_run_acquire_and_capture, captured)
        loop.run_until_complete(asyncio.sleep(0))
    finally:
        loop.close()
    assert captured, "expected the outside-task guard to raise"
    assert str(captured[0]) == GUARD_MESSAGE


def test_release_outside_task_raises() -> None:
    """``release()`` must raise when there is no owning task context."""
    # No running event loop.
    with pytest.raises(RuntimeError):
        ReentrantAsyncLock().release()

    # Running loop, non-task callback -> guard must fire with the message.
    captured: list[RuntimeError] = []
    loop = asyncio.new_event_loop()
    try:
        loop.call_soon(_run_release_and_capture, captured)
        loop.run_until_complete(asyncio.sleep(0))
    finally:
        loop.close()
    assert captured, "expected the outside-task guard to raise"
    assert str(captured[0]) == GUARD_MESSAGE


async def test_in_task_reentrancy_still_works() -> None:
    """Control case: same-task re-entrancy must keep working (no deadlock).

    The deadlock fix (allowing the owning task to re-enter) must remain
    intact -- acquiring twice and releasing twice on the same task is silent.
    """
    lock = ReentrantAsyncLock()
    assert await lock.acquire() is True
    assert await lock.acquire() is True  # re-enter on the same task
    lock.release()  # level 2 -> 1
    lock.release()  # level 1 -> underlying lock released
    assert not lock.locked()


def _run_acquire_and_capture(out: list[RuntimeError]) -> None:
    """Step ``acquire``'s body in a non-task callback and record any guard error."""
    try:
        ReentrantAsyncLock().acquire().send(None)
    except RuntimeError as err:  # captured into ``out`` and asserted on below
        out.append(err)


def _run_release_and_capture(out: list[RuntimeError]) -> None:
    """Call ``release`` in a non-task callback and record any guard error."""
    try:
        ReentrantAsyncLock().release()
    except RuntimeError as err:  # captured into ``out`` and asserted on below
        out.append(err)

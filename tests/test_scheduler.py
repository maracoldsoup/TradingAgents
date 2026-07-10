import asyncio

import pytest

from tradingagents.scheduler import ScheduledJob, start_scheduler, stop_scheduler


@pytest.mark.unit
def test_scheduler_runs_job_immediately_and_on_interval():
    async def scenario():
        calls = []

        def tick():
            calls.append(1)

        job = ScheduledJob(name="tick", interval_seconds=0.02, run=tick)
        tasks = start_scheduler([job])
        try:
            await asyncio.sleep(0.07)
        finally:
            await stop_scheduler(tasks)
        return calls

    calls = asyncio.run(scenario())

    # Immediate run + at least two interval ticks in ~70ms at a 20ms interval.
    assert len(calls) >= 3


@pytest.mark.unit
def test_scheduler_survives_job_exceptions():
    async def scenario():
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("boom")

        job = ScheduledJob(name="flaky", interval_seconds=0.02, run=flaky)
        tasks = start_scheduler([job])
        try:
            await asyncio.sleep(0.05)
        finally:
            await stop_scheduler(tasks)
        return calls

    calls = asyncio.run(scenario())

    # First call raised; the loop must keep going instead of dying silently.
    assert len(calls) >= 2


@pytest.mark.unit
def test_scheduler_run_immediately_false_waits_one_interval():
    async def scenario():
        calls = []

        def tick():
            calls.append(1)

        job = ScheduledJob(name="delayed", interval_seconds=0.05, run=tick, run_immediately=False)
        tasks = start_scheduler([job])
        try:
            await asyncio.sleep(0.02)
            immediate_calls = list(calls)
        finally:
            await stop_scheduler(tasks)
        return immediate_calls

    immediate_calls = asyncio.run(scenario())

    assert immediate_calls == []


@pytest.mark.unit
def test_stop_scheduler_cancels_tasks():
    async def scenario():
        def tick():
            pass

        job = ScheduledJob(name="tick", interval_seconds=10, run=tick)
        tasks = start_scheduler([job])
        await stop_scheduler(tasks)
        return tasks

    tasks = asyncio.run(scenario())

    assert all(task.done() for task in tasks)

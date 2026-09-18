"""Tests for automatic_iib pipeline tasks."""

import asyncio
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest
from models.dto import EmptyDTO

from pipelines import automatic_iib as pipeline


def run_task(task, data, args):
    async def _inner():
        async with asyncio.TaskGroup() as tg:
            return await task.run(data, args, tg)

    return asyncio.run(_inner())


class TestRecordLatestIib:
    @pytest.mark.parametrize(
        "error",
        [
            OSError("disk full"),
            RuntimeError("missing config"),
        ],
    )
    def test_state_write_failure_does_not_fail_task(self, error):
        data = [MagicMock()]
        with (
            patch(
                "pipelines.automatic_iib.config.get_latest_iib_state_path",
                return_value="/tmp/latest_iib.json",
            ),
            patch(
                "pipelines.automatic_iib.config.get_tier1_jobs",
                return_value={"2.12": {"ocp_version": "4.22"}},
            ),
            patch(
                "pipelines.automatic_iib.record_from_fbc_repos",
                side_effect=error,
            ),
        ):
            result = run_task(
                pipeline.record_latest_iib, data, Namespace()
            )
        assert isinstance(result, EmptyDTO)

    def test_config_getter_failure_does_not_fail_task(self):
        data = [MagicMock()]
        with patch(
            "pipelines.automatic_iib.config.get_latest_iib_state_path",
            side_effect=RuntimeError(
                'Couldn\'t find "latest_iib_state_path" in config'
            ),
        ):
            result = run_task(
                pipeline.record_latest_iib, data, Namespace()
            )
        assert isinstance(result, EmptyDTO)

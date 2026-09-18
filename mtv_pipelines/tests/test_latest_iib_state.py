"""Tests for tasks/latest_iib_state.py — pointer file for Saturday tier1."""

import json
from unittest.mock import MagicMock

from config import config
from tasks import latest_iib_state as state


def test_config_tier1_jobs_and_state_path():
    jobs = config.get_tier1_jobs()
    assert jobs["2.12"]["ocp_version"] == "4.22"
    assert jobs["5.0"]["ocp_version"] == "5.0"
    assert config.get_latest_iib_state_path() == "/app/data/latest_iib.json"


def _entry(mtv_version="2.12.6", iib="forklift-fbc-prod-v50:on-pr-abc"):
    return {
        "mtv_version": mtv_version,
        "iib": iib,
        "recorded_at": "2026-09-17T14:02:00Z",
    }


class TestLoadState:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        assert state.load_state(tmp_path / "latest_iib.json") == {}

    def test_reads_existing_json(self, tmp_path):
        path = tmp_path / "latest_iib.json"
        path.write_text(json.dumps({"2.12": _entry()}))
        loaded = state.load_state(path)
        assert loaded["2.12"]["mtv_version"] == "2.12.6"

    def test_corrupt_json_returns_empty_dict(self, tmp_path):
        path = tmp_path / "latest_iib.json"
        path.write_text("{ not json")
        assert state.load_state(path) == {}

    def test_empty_file_returns_empty_dict(self, tmp_path):
        path = tmp_path / "latest_iib.json"
        path.write_text("")
        assert state.load_state(path) == {}


class TestUpsertLatest:
    def test_creates_file_and_entry(self, tmp_path):
        path = tmp_path / "latest_iib.json"
        state.upsert_latest(
            path,
            mtv_xy="2.12",
            mtv_version="2.12.6",
            iib="forklift-fbc-prod-v50:on-pr-abc",
            recorded_at="2026-09-17T14:02:00Z",
        )
        data = json.loads(path.read_text())
        assert data["2.12"]["mtv_version"] == "2.12.6"
        assert data["2.12"]["iib"] == "forklift-fbc-prod-v50:on-pr-abc"

    def test_merge_does_not_wipe_other_versions(self, tmp_path):
        path = tmp_path / "latest_iib.json"
        state.upsert_latest(
            path,
            mtv_xy="2.12",
            mtv_version="2.12.6",
            iib="iib-a",
            recorded_at="2026-09-17T14:02:00Z",
        )
        state.upsert_latest(
            path,
            mtv_xy="5.0",
            mtv_version="5.0.0",
            iib="iib-b",
            recorded_at="2026-09-16T11:20:00Z",
        )
        data = json.loads(path.read_text())
        assert set(data) == {"2.12", "5.0"}
        assert data["2.12"]["iib"] == "iib-a"
        assert data["5.0"]["iib"] == "iib-b"

    def test_preserves_last_tier1_iib_when_iib_updates(self, tmp_path):
        path = tmp_path / "latest_iib.json"
        path.write_text(
            json.dumps(
                {
                    "2.12": {
                        "mtv_version": "2.12.6",
                        "iib": "old-iib",
                        "recorded_at": "2026-09-17T14:02:00Z",
                        "last_tier1_iib": "old-iib",
                    }
                }
            )
        )
        state.upsert_latest(
            path,
            mtv_xy="2.12",
            mtv_version="2.12.7",
            iib="new-iib",
            recorded_at="2026-09-18T10:00:00Z",
        )
        data = json.loads(path.read_text())
        assert data["2.12"]["iib"] == "new-iib"
        assert data["2.12"]["last_tier1_iib"] == "old-iib"


class TestIterTier1Targets:
    def test_missing_pointer_is_skipped(self):
        jobs = {"2.12": {"ocp_version": "4.22"}}
        targets = list(state.iter_tier1_targets(jobs, {}))
        assert len(targets) == 1
        assert targets[0].mtv_xy == "2.12"
        assert targets[0].skip_reason == "no pointer"

    def test_ready_target_has_no_skip_reason(self):
        jobs = {"2.12": {"ocp_version": "4.22"}}
        st = {"2.12": _entry()}
        targets = list(state.iter_tier1_targets(jobs, st))
        assert targets[0].skip_reason is None
        assert targets[0].ocp_version == "4.22"
        assert targets[0].mtv_version == "2.12.6"

    def test_skips_when_tier1_already_ran_for_this_iib(self):
        jobs = {"2.12": {"ocp_version": "4.22"}}
        st = {
            "2.12": {
                "mtv_version": "2.12.6",
                "iib": "iib-a",
                "recorded_at": "2026-09-17T14:02:00Z",
                "last_tier1_iib": "iib-a",
            }
        }
        targets = list(state.iter_tier1_targets(jobs, st))
        assert targets[0].skip_reason == (
            "tier1 already triggered for this IIB"
        )


class TestRecordFromFbcRepos:
    def _repo(self, version="2.12.6", iib_url=""):
        repo = MagicMock()
        repo.for_bundle.version = version
        repo.current_iib.url = iib_url or (
            "quay.io/redhat-user-workloads/rh-mtv-1-tenant/"
            "forklift-fbc-prod-v50:on-pr-sha"
        )
        return repo

    def test_writes_only_configured_versions(self, tmp_path):
        path = tmp_path / "latest_iib.json"
        repos = [
            self._repo("2.12.6"),
            self._repo(
                "2.11.7",
                "quay.io/x/forklift-fbc-prod-v421:on-pr-old",
            ),
        ]
        state.record_from_fbc_repos(
            repos,
            path=path,
            tier1_jobs={"2.12": {"ocp_version": "4.22"}},
        )
        data = json.loads(path.read_text())
        assert list(data) == ["2.12"]
        assert data["2.12"]["iib"] == "forklift-fbc-prod-v50:on-pr-sha"

    def test_skips_repo_without_current_iib(self, tmp_path):
        path = tmp_path / "latest_iib.json"
        repo = MagicMock()
        repo.current_iib = None
        repo.for_bundle.version = "2.12.6"
        state.record_from_fbc_repos(
            [repo],
            path=path,
            tier1_jobs={"2.12": {"ocp_version": "4.22"}},
        )
        assert not path.exists()

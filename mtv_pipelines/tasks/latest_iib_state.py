"""Persist the latest known-good IIB per MTV x.y for Saturday tier1."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tier1Target:
    mtv_xy: str
    ocp_version: str
    mtv_version: str = ""
    iib: str = ""
    skip_reason: str | None = None


def _as_path(path: str | Path) -> Path:
    return Path(path)


def mtv_xy_from_version(version: str) -> str:
    return ".".join(str(version).split(".")[:2])


def utc_now_iso(now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    return current.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_state(path: str | Path) -> dict:
    state_path = _as_path(path)
    if not state_path.exists():
        return {}
    try:
        with state_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError) as ex:
        logger.warning(
            f"Failed to read latest IIB state at {state_path}: {ex}"
        )
        return {}
    if not isinstance(data, dict):
        logger.warning(f"Ignoring invalid latest IIB state at {state_path}")
        return {}
    return data


def save_state(path: str | Path, state: dict) -> None:
    state_path = _as_path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{state_path.name}.",
        suffix=".tmp",
        dir=state_path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_name, state_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def upsert_latest(
    path: str | Path,
    mtv_xy: str,
    mtv_version: str,
    iib: str,
    recorded_at: str | None = None,
) -> None:
    state = load_state(path)
    existing = state.get(mtv_xy, {})
    state[mtv_xy] = {
        "mtv_version": mtv_version,
        "iib": iib,
        "recorded_at": recorded_at or utc_now_iso(),
        "last_tier1_iib": existing.get("last_tier1_iib"),
    }
    save_state(path, state)


def mark_tier1_triggered(path: str | Path, mtv_xy: str, iib: str) -> None:
    state = load_state(path)
    if mtv_xy not in state:
        logger.warning(
            f"Cannot mark tier1 trigger for {mtv_xy}: no pointer in {path}"
        )
        return
    state[mtv_xy]["last_tier1_iib"] = iib
    save_state(path, state)


def iter_tier1_targets(tier1_jobs: dict, state: dict):
    for mtv_xy, cfg in tier1_jobs.items():
        ocp_version = str((cfg or {}).get("ocp_version", ""))
        entry = state.get(mtv_xy)
        if not entry:
            yield Tier1Target(
                mtv_xy=mtv_xy,
                ocp_version=ocp_version,
                skip_reason="no pointer",
            )
            continue
        iib = entry.get("iib") or ""
        if iib and iib == entry.get("last_tier1_iib"):
            yield Tier1Target(
                mtv_xy=mtv_xy,
                ocp_version=ocp_version,
                mtv_version=str(entry.get("mtv_version", "")),
                iib=iib,
                skip_reason="tier1 already triggered for this IIB",
            )
            continue
        yield Tier1Target(
            mtv_xy=mtv_xy,
            ocp_version=ocp_version,
            mtv_version=str(entry.get("mtv_version", "")),
            iib=iib,
        )


def record_from_fbc_repos(
    fbc_repos,
    path: str | Path,
    tier1_jobs: dict,
) -> None:
    for fbc_repo in fbc_repos:
        if not getattr(fbc_repo, "current_iib", None):
            continue
        version = str(fbc_repo.for_bundle.version)
        mtv_xy = mtv_xy_from_version(version)
        if mtv_xy not in tier1_jobs:
            continue
        iib = str(fbc_repo.current_iib.url).split("/")[-1]
        upsert_latest(
            path,
            mtv_xy=mtv_xy,
            mtv_version=version,
            iib=iib,
        )

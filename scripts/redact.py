#!/usr/bin/env python3
"""Build the redacted plan summary that QuietMerge ingests.

This is the ONLY data that leaves your CI. Per resource change it keeps
address, type, and change actions — nothing else. No attribute values, no
outputs, no variables, no diffs. The full plan JSON never leaves the runner.

Standalone by design (stdlib only, no terraform imports) so the same script
can be reused verbatim from other CI systems (e.g. a GitLab CI component).

Usage:
    python3 redact.py --plan plan-full.json --exit-code 2 \
        --tf-binary terraform --working-directory infra/ \
        --lock-before /tmp/lock-before.hcl --lock-after /tmp/lock-after.hcl \
        --out summary.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# Actions that make an entry a real change. Entries whose actions are only
# "no-op" / "read" are dropped: QuietMerge's deterministic SAFE_NOOP verdict
# requires an EMPTY change list for a clean exit-0 plan.
_CHANGE_ACTIONS = {"create", "update", "delete"}

_PROVIDER_RE = re.compile(r'^provider\s+"([^"]+)"')
_VERSION_RE = re.compile(r'^\s*version\s*=\s*"([^"]+)"')


def parse_lock(text: str) -> dict[str, str]:
    """Extract {provider source -> version} from a .terraform.lock.hcl body."""
    versions: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        m = _PROVIDER_RE.match(line)
        if m:
            current = m.group(1)
            continue
        if current:
            m = _VERSION_RE.match(line)
            if m:
                versions[current] = m.group(1)
                current = None
    return versions


def extract_resource_changes(plan: dict) -> list[dict]:
    changes = []
    for rc in plan.get("resource_changes") or []:
        actions = (rc.get("change") or {}).get("actions") or []
        if not _CHANGE_ACTIONS.intersection(actions):
            continue
        changes.append(
            {
                "address": rc.get("address", ""),
                "type": rc.get("type", ""),
                "actions": actions,
            }
        )
    return changes


def compute_totals(changes: list[dict]) -> dict[str, int]:
    # A replace (["delete", "create"]) counts as both an add and a destroy,
    # matching terraform's own "Plan: X to add, Y to change, Z to destroy".
    totals = {"add": 0, "change": 0, "destroy": 0}
    for rc in changes:
        actions = rc["actions"]
        if "create" in actions:
            totals["add"] += 1
        if "update" in actions:
            totals["change"] += 1
        if "delete" in actions:
            totals["destroy"] += 1
    return totals


def provider_versions(lock_before: str, lock_after: str) -> list[dict]:
    before = parse_lock(lock_before)
    after = parse_lock(lock_after)
    return [
        {"name": name, "before": before.get(name), "after": after.get(name)}
        for name in sorted(set(before) | set(after))
    ]


def build_summary(
    plan: dict,
    *,
    exit_code: int,
    tf_binary: str,
    working_directory: str,
    lock_before: str,
    lock_after: str,
) -> dict:
    changes = extract_resource_changes(plan)
    return {
        "schema_version": 1,
        "exit_code": exit_code,
        "tf_binary": tf_binary,
        "working_directory": working_directory,
        "totals": compute_totals(changes),
        "resource_changes": changes,
        "provider_versions": provider_versions(lock_before, lock_after),
        "module_versions": [],
    }


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, help="terraform show -json output")
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--tf-binary", required=True)
    parser.add_argument("--working-directory", required=True)
    parser.add_argument("--lock-before", required=True)
    parser.add_argument("--lock-after", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    try:
        plan = json.loads(_read(args.plan) or "{}")
    except json.JSONDecodeError:
        plan = {}

    summary = build_summary(
        plan,
        exit_code=args.exit_code,
        tf_binary=args.tf_binary,
        working_directory=args.working_directory,
        lock_before=_read(args.lock_before),
        lock_after=_read(args.lock_after),
    )
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

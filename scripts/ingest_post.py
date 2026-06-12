#!/usr/bin/env python3
"""Sign and POST the redacted summary to QuietMerge. Fail-soft by design:
this script ALWAYS exits 0 — a QuietMerge outage must never break your CI.
The plan result is still visible locally in the workflow run either way.

The body is HMAC-signed with the ingest token as the shared secret, so a
leaked-but-stale request can't be replayed with swapped contents.

Usage:
    QUIETMERGE_INGEST_TOKEN=... python3 ingest_post.py \
        --summary summary.json --nonce <nonce> --url https://.../ingest
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request


def sign(token: str, body: bytes) -> str:
    return "sha256=" + hmac.new(token.encode(), body, hashlib.sha256).hexdigest()


def build_body(nonce: str, summary: dict) -> bytes:
    return json.dumps({"nonce": nonce, "summary": summary}, separators=(",", ":")).encode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()

    token = os.environ.get("QUIETMERGE_INGEST_TOKEN", "")
    if not token:
        print(
            "::warning::QUIETMERGE_INGEST_TOKEN secret is not set — "
            "skipping QuietMerge upload. Add it in repo Settings -> Secrets."
        )
        return 0

    with open(args.summary, encoding="utf-8") as f:
        summary = json.load(f)
    body = build_body(args.nonce, summary)

    request = urllib.request.Request(
        args.url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-QuietMerge-Signature": sign(token, body),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            print(f"QuietMerge ingest accepted the summary (HTTP {response.status}).")
    except urllib.error.HTTPError as e:
        detail = e.read()[:500].decode(errors="replace")
        print(f"::warning::QuietMerge ingest rejected the summary (HTTP {e.code}): {detail}")
    except Exception as e:  # noqa: BLE001 — fail-soft is the contract here
        print(f"::warning::Could not reach QuietMerge ingest: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

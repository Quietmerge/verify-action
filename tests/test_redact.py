"""Redaction script: change filtering, totals, lock parsing, and — most
importantly — proof that attribute values never appear in the output."""

import hashlib
import hmac
import importlib.util
import json
import pathlib

SCRIPTS = pathlib.Path(__file__).parent.parent / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


redact = _load("redact")
ingest_post = _load("ingest_post")

# A plan with a secret in it — the one thing that must never leak.
PLAN = {
    "resource_changes": [
        {
            "address": "aws_db_instance.main",
            "type": "aws_db_instance",
            "change": {
                "actions": ["update"],
                "before": {"password": "hunter2", "instance_class": "db.t3.micro"},
                "after": {"password": "hunter2", "instance_class": "db.t3.small"},
            },
        },
        {
            "address": "aws_iam_role.deploy",
            "type": "aws_iam_role",
            "change": {"actions": ["delete", "create"], "before": {}, "after": {}},
        },
        {
            "address": "aws_s3_bucket.logs",
            "type": "aws_s3_bucket",
            "change": {"actions": ["no-op"], "before": {}, "after": {}},
        },
        {
            "address": "data.aws_caller_identity.me",
            "type": "aws_caller_identity",
            "change": {"actions": ["read"]},
        },
    ],
    "output_changes": {"db_endpoint": {"after": "db.internal.example.com"}},
}

LOCK_BEFORE = """\
provider "registry.terraform.io/hashicorp/aws" {
  version     = "5.40.0"
  constraints = "~> 5.0"
  hashes = [
    "h1:abc=",
  ]
}
"""

LOCK_AFTER = """\
provider "registry.terraform.io/hashicorp/aws" {
  version     = "5.41.0"
  constraints = "~> 5.0"
  hashes = [
    "h1:def=",
  ]
}

provider "registry.terraform.io/hashicorp/random" {
  version = "3.6.0"
}
"""


def _summary(plan=PLAN, exit_code=2):
    return redact.build_summary(
        plan,
        exit_code=exit_code,
        tf_binary="terraform",
        working_directory=".",
        lock_before=LOCK_BEFORE,
        lock_after=LOCK_AFTER,
    )


def test_drops_noop_and_read_only_entries():
    addresses = [rc["address"] for rc in _summary()["resource_changes"]]
    assert addresses == ["aws_db_instance.main", "aws_iam_role.deploy"]


def test_totals_count_replace_as_add_and_destroy():
    assert _summary()["totals"] == {"add": 1, "change": 1, "destroy": 1}


def test_no_attribute_values_leak():
    blob = json.dumps(_summary())
    assert "hunter2" not in blob
    assert "db.t3" not in blob
    assert "db_endpoint" not in blob
    assert "before" not in json.dumps(_summary()["resource_changes"])


def test_provider_versions_before_and_after():
    versions = {v["name"]: v for v in _summary()["provider_versions"]}
    aws = versions["registry.terraform.io/hashicorp/aws"]
    assert (aws["before"], aws["after"]) == ("5.40.0", "5.41.0")
    random = versions["registry.terraform.io/hashicorp/random"]
    assert (random["before"], random["after"]) == (None, "3.6.0")


def test_lock_parser_ignores_hashes_block():
    parsed = redact.parse_lock(LOCK_AFTER)
    assert parsed == {
        "registry.terraform.io/hashicorp/aws": "5.41.0",
        "registry.terraform.io/hashicorp/random": "3.6.0",
    }


def test_errored_plan_yields_empty_changes():
    summary = _summary(plan={}, exit_code=1)
    assert summary["exit_code"] == 1
    assert summary["resource_changes"] == []
    assert summary["totals"] == {"add": 0, "change": 0, "destroy": 0}


def test_clean_plan_has_empty_change_list_for_deterministic_noop():
    # QuietMerge's $0 SAFE_NOOP rule requires resource_changes == [].
    noop_plan = {
        "resource_changes": [
            {"address": "a", "type": "t", "change": {"actions": ["no-op"]}},
        ]
    }
    summary = redact.build_summary(
        noop_plan,
        exit_code=0,
        tf_binary="terraform",
        working_directory=".",
        lock_before=LOCK_BEFORE,
        lock_after=LOCK_AFTER,
    )
    assert summary["resource_changes"] == []


def test_ingest_signature_matches_server_format():
    body = ingest_post.build_body("nonce-1", {"exit_code": 0})
    expected = "sha256=" + hmac.new(b"tok", body, hashlib.sha256).hexdigest()
    assert ingest_post.sign("tok", body) == expected

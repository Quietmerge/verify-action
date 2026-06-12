# quietmerge/verify-action

The customer-side half of [QuietMerge](https://quietmerge.dev). Runs
`terraform plan` for a dependency-bump PR **in your own CI**, redacts the
result down to resource addresses, types, and change actions, and sends only
that summary to QuietMerge for a verdict.

**Your cloud credentials never leave your runner. Neither does your plan.**

## What leaves your CI (and what doesn't)

Sent to QuietMerge — the redacted summary only:

```json
{
  "exit_code": 0,
  "tf_binary": "terraform",
  "working_directory": "infra/",
  "totals": {"add": 0, "change": 0, "destroy": 0},
  "resource_changes": [
    {"address": "aws_s3_bucket.logs", "type": "aws_s3_bucket", "actions": ["update"]}
  ],
  "provider_versions": [
    {"name": "registry.terraform.io/hashicorp/aws", "before": "5.40.0", "after": "5.41.0"}
  ]
}
```

Never sent: attribute values, outputs, variables, diffs, state, credentials.
The full plan JSON stays in your repo as a workflow artifact (7-day expiry).
The redaction is a [single readable script](scripts/redact.py) — audit it.

## Setup

1. Install the QuietMerge GitHub App on your repo.
2. Add your ingest token as a repo secret named `QUIETMERGE_INGEST_TOKEN`
   (QuietMerge gives you this during onboarding).
3. Copy [examples/quietmerge-verify.yml](examples/quietmerge-verify.yml) to
   `.github/workflows/quietmerge-verify.yml` in your repo — **the filename
   matters** — and add your cloud auth step where marked (OIDC recommended).

That's it. When Renovate or Dependabot opens a Terraform bump PR, QuietMerge
dispatches this workflow on the PR branch, reads the redacted summary, and
posts a verdict on the PR.

## Why `workflow_dispatch` instead of `on: pull_request`?

Workflows triggered by Dependabot/Renovate PRs run with restricted
permissions and **without your repo secrets** — a well-known trap that makes
`terraform init` against private modules or cloud auth fail silently.
QuietMerge instead dispatches the workflow on the PR head branch, where it
runs with normal secret and OIDC access.

## Inputs

| Input | Required | Default | Notes |
|---|---|---|---|
| `pr_number` | yes | — | provided by QuietMerge's dispatch |
| `nonce` | yes | — | provided by QuietMerge's dispatch |
| `ingest_url` | yes | — | provided by QuietMerge's dispatch |
| `ingest_token` | yes | — | pass `secrets.QUIETMERGE_INGEST_TOKEN` |
| `working_directory` | no | `.` | Terraform root module |
| `tf_binary` | no | `terraform` | `terraform` or `tofu` |
| `tf_version` | no | `latest` | version or constraint, e.g. `1.9.x` |

## Behaviour notes

- **Guard:** refuses to run unless dispatched for an open PR whose head
  branch matches the branch it was dispatched on.
- **Lock-file fix-up:** if `init -upgrade` changes `.terraform.lock.hcl`,
  the action regenerates hashes for `linux_amd64` + `darwin_arm64` and pushes
  a fix-up commit to the PR branch. QuietMerge then re-verifies the new
  commit automatically.
- **Fail-soft:** if the POST to QuietMerge fails, your job still succeeds and
  the plan result stays visible in the run. A QuietMerge outage never blocks
  your CI. (A plan that itself errors still fails the job, as it should.)

## License

[MIT](LICENSE)

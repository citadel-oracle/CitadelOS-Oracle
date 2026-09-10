# CITADEL Git-to-Obsidian Knowledge Sync

This isolated tool converts a meaningful committed Git diff into guarded, append-only CITADEL
knowledge-base updates. Application code, runtime services, trading behavior, broker behavior,
configuration, and databases are outside its write boundary.

## Safety model

- The repository is inspected only through committed Git objects. Uncommitted files are excluded.
- Deterministic path rules select affected modules before Codex runs.
- Potential credential material in committed additions aborts the workflow before analysis.
- Codex runs through `codex exec --ephemeral --ignore-user-config --sandbox read-only`; the
  analysis process therefore loads no user MCP servers and must return JSON matching
  `analysis.schema.json`.
- Codex proposes documentation facts; `sync.py` alone decides which vault notes are allowed.
- Every existing target note is read before a structured MCP patch.
- Existing notes receive unique append-only commit sections with optimistic concurrency and
  retry-safe markers. No existing note is sent to `vault_write`.
- New changelog, release-note, and per-commit validation notes are created only after proving the
  path does not exist.
- `TEST_CONNECTION.md` is hashed before the run and compared afterward.
- Generated text and written notes are scanned for credential patterns.
- No Git commit or push is performed.
- A worktree-specific lock and `CITADEL_DOC_SYNC_ACTIVE` block recursion.
- `config.json` is disabled by default.

## Commands

From the repository root:

```bash
./scripts/knowledge_sync/citadel-doc-sync --commit HEAD --dry-run
./scripts/knowledge_sync/citadel-doc-sync --commit HEAD
./scripts/knowledge_sync/citadel-doc-sync --range <OLD>..<NEW> --dry-run
```

Dry-run performs committed-diff inspection, module mapping, Codex structured analysis, MCP
availability/read checks, and prints the exact note plan with `writes: 0`.

Apply mode exits safely while `"enabled": false` in `config.json`. After reviewing a successful
dry-run and running validation, explicitly change only that setting to `true`. Apply remains a
manual command; it does not commit or push.

For a deterministic analyzer smoke test that does not spend a Codex turn:

```bash
./scripts/knowledge_sync/citadel-doc-sync \
  --commit b91964ac3b7823bac0c4625829d817ddc7cd6529 \
  --dry-run --static-analysis
```

`--static-analysis` is intentionally conservative and marks runtime behavior as `NOT VERIFIED`.
Normal operational runs should omit it and use the structured Codex analysis.

## Output notes

The configured module notes receive a commit-scoped documentation-history section. The workflow
also maintains:

- `00 - CITADEL HQ/Changelog.md`
- `00 - CITADEL HQ/Release Notes.md`
- `08 - Decisions/Architecture Decision Log.md` when the diff establishes a durable decision
- `09 - Bugs & Incidents/Incident Register.md` for evidenced fixes/incidents
- `10 - Validation & Proofs/Commit <SHA> Documentation Validation.md`

Validation notes prove documentation provenance and sync mechanics. They do not claim application,
trading, market-data, broker, or production validation unless separately supplied evidence proves
those claims. The analysis stage itself is never allowed to report `COMMAND VERIFIED`.

## Validation

Read-only plus deterministic workflow validation:

```bash
python3 scripts/knowledge_sync/validate_sync.py
```

Full MCP transport canary:

```bash
python3 scripts/knowledge_sync/validate_sync.py --canary
```

The canary uses one collision-resistant path under `99 - Inbox`, then creates, reads, structured-
patches, searches, and permanently deletes only that temporary file. It verifies
`TEST_CONNECTION.md` remains byte-for-byte unchanged and checks that unrelated worktree state did
not change.

## Optional post-commit hook

No hook is installed automatically. To install the guarded hook:

```bash
./scripts/knowledge_sync/install-hook --install
```

The installed hook is inert unless `CITADEL_DOC_SYNC_HOOK_ENABLED=1` is present in the committing
process environment. When enabled it still defaults to dry-run, and the significance gate skips
commits containing only ignored artifacts or this tooling. Apply requires both:

```bash
export CITADEL_DOC_SYNC_HOOK_ENABLED=1
export CITADEL_DOC_SYNC_HOOK_APPLY=1
```

Apply also requires `"enabled": true` in `config.json`. Manual invocation is preferred because it
keeps meaningful-commit judgment explicit.

Remove only the managed hook with:

```bash
./scripts/knowledge_sync/install-hook --uninstall
```

The installer refuses to overwrite or remove a non-CITADEL hook.

## Mapping and maintenance

Edit `config.json` to add a module only after its canonical Obsidian note exists. Keep rules narrow:
repository globs map to allowed notes, while generated reports, screenshots, bundles, and this
tooling directory are ignored to prevent noise and recursion.

If a run fails after a partial MCP append, rerun the same scope. Commit markers make completed
sections idempotent. Do not delete historical sections automatically; correct them through a new
explicitly reviewed entry.

## Prerequisites

- macOS or another POSIX environment with Git and Python 3.11+
- authenticated Codex CLI with `codex exec`
- configured and reachable `obsidian` MCP server in Codex `config.toml`
- the CITADEL vault structure defined by `config.json`

No npm, pip, uv, or Homebrew package is required by this tooling.

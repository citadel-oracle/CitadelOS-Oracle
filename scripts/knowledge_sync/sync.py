#!/usr/bin/env python3
"""Safe Git-to-Obsidian documentation synchronization for CITADEL."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator

from vault_mcp import MCPError, ObsidianVault


TOOL_DIR = Path(__file__).resolve().parent
CONFIG_PATH = TOOL_DIR / "config.json"
SCHEMA_PATH = TOOL_DIR / "analysis.schema.json"
PROMPT_PATH = TOOL_DIR / "codex_prompt.md"
SECRET_PATTERNS = [
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("OpenAI key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}\b", re.I)),
    (
        "assigned credential",
        re.compile(
            r"\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
            r"\b\s*[:=]\s*[\"']?(?!\$\{|<|REDACTED|none\b)[A-Za-z0-9._~+/=-]{16,}",
            re.I,
        ),
    ),
]


class SyncError(RuntimeError):
    pass


def run_git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise SyncError(f"git {' '.join(arguments[:2])} failed: {result.stderr.strip()}")
    return result.stdout


def matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def scan_secrets(text: str) -> list[str]:
    return sorted({name for name, pattern in SECRET_PATTERNS if pattern.search(text)})


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1:
        raise SyncError("Unsupported knowledge-sync configuration schema")
    return config


def resolve_commit(repo: Path, revision: str) -> str:
    return run_git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}").strip()


def revision_scope(
    repo: Path, commit: str | None, revision_range: str | None
) -> tuple[str, str, str]:
    if commit:
        new = resolve_commit(repo, commit)
        parents = run_git(repo, "rev-list", "--parents", "-n", "1", new).split()
        if len(parents) > 1:
            old = parents[1]
        else:
            old = run_git(repo, "hash-object", "-t", "tree", "/dev/null").strip()
        return old, new, new
    if not revision_range or revision_range.count("..") != 1 or "..." in revision_range:
        raise SyncError("--range must be exactly OLD..NEW")
    old_ref, new_ref = revision_range.split("..", 1)
    old = resolve_commit(repo, old_ref)
    new = resolve_commit(repo, new_ref)
    return old, new, f"{old}..{new}"


def changed_files(repo: Path, old: str, new: str) -> list[dict[str, str]]:
    output = run_git(
        repo, "diff", "--no-ext-diff", "--find-renames", "--name-status", old, new
    )
    changes: list[dict[str, str]] = []
    for line in output.splitlines():
        fields = line.split("\t")
        if not fields:
            continue
        status = fields[0]
        path = fields[-1]
        changes.append({"status": status, "path": path})
    return changes


def detect_modules(
    changes: list[dict[str, str]], config: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    ignored: list[str] = []
    material_paths: list[str] = []
    for change in changes:
        path = change["path"]
        if matches(path, config["ignored_paths"]):
            ignored.append(path)
        else:
            material_paths.append(path)
    detected = []
    for rule in config["module_rules"]:
        evidence = sorted(
            path for path in material_paths if matches(path, rule["paths"])
        )
        if evidence:
            detected.append({**rule, "evidence_files": evidence})
    return detected, ignored


def metadata(repo: Path, new: str, scope: str) -> dict[str, str]:
    fmt = "%H%n%P%n%aI%n%s%n%b"
    fields = run_git(repo, "show", "-s", f"--format={fmt}", new).splitlines()
    return {
        "scope": scope,
        "commit": fields[0],
        "parents": fields[1] if len(fields) > 1 else "",
        "author_date": fields[2] if len(fields) > 2 else "",
        "subject": fields[3] if len(fields) > 3 else "",
        "body": "\n".join(fields[4:]).strip(),
    }


def committed_diff(repo: Path, old: str, new: str, max_bytes: int) -> str:
    diff = run_git(
        repo,
        "diff",
        "--no-ext-diff",
        "--find-renames",
        "--unified=5",
        old,
        new,
        "--",
        ".",
        ":(exclude)scripts/knowledge_sync/**",
    )
    encoded = diff.encode("utf-8")
    if len(encoded) > max_bytes:
        raise SyncError(
            f"Committed diff is {len(encoded)} bytes; limit is {max_bytes}. "
            "Split the documentation review into a smaller commit range."
        )
    added_lines = "\n".join(
        line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")
    )
    findings = scan_secrets(added_lines)
    if findings:
        raise SyncError(
            "Potential credential material detected in committed additions; "
            f"documentation sync aborted ({', '.join(findings)})"
        )
    return diff


def render_prompt(
    commit_metadata: dict[str, str],
    changes: list[dict[str, str]],
    modules: list[dict[str, Any]],
    diff: str,
) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    replacements = {
        "{{DETECTED_MODULES}}": json.dumps([module["module"] for module in modules]),
        "{{COMMIT_METADATA}}": json.dumps(commit_metadata, indent=2),
        "{{CHANGED_FILES}}": json.dumps(changes, indent=2),
        "{{COMMITTED_DIFF}}": diff,
    }
    for needle, value in replacements.items():
        template = template.replace(needle, value)
    return template


def static_plan(
    commit_metadata: dict[str, str], modules: list[dict[str, Any]]
) -> dict[str, Any]:
    subject = commit_metadata["subject"]
    is_fix = bool(re.match(r"^fix(?:\(.+?\))?:", subject, re.I))
    return {
        "schema_version": 1,
        "summary": f"Committed change: {subject}",
        "affected_modules": [
            {
                "name": module["module"],
                "change_summary": (
                    f"{subject}. Detailed behavior impact requires human or Codex review."
                ),
                "documentation_points": [
                    "Committed paths changed; runtime behavior is NOT VERIFIED."
                ],
                "evidence_files": module["evidence_files"],
            }
            for module in modules
        ],
        "changelog_entry": subject,
        "architecture_decision": {
            "applicable": False,
            "title": "",
            "context": "",
            "decision": "",
            "consequences": "",
        },
        "incident": {
            "applicable": is_fix,
            "title": subject if is_fix else "",
            "symptom": "The commit is classified as a fix; the exact production symptom is NOT VERIFIED."
            if is_fix
            else "",
            "fix": subject if is_fix else "",
            "validation": "NOT VERIFIED",
        },
        "validation": {
            "status": "STATIC EVIDENCE",
            "evidence": ["Commit metadata and changed-path mapping were inspected."],
            "commands_run": [],
        },
        "release_notes": [subject],
        "unsupported_claims": [
            "Runtime behavior, trading correctness, and production readiness are NOT VERIFIED."
        ],
    }


def codex_plan(repo: Path, prompt: str, config: dict[str, Any]) -> dict[str, Any]:
    state_dir = Path(run_git(repo, "rev-parse", "--git-path", "citadel-doc-sync")).resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="analysis-", dir=state_dir) as temp:
        output_path = Path(temp) / "analysis.json"
        command = [
            "codex",
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--sandbox",
            "read-only",
            "--cd",
            str(repo),
            "--output-schema",
            str(SCHEMA_PATH),
            "--output-last-message",
            str(output_path),
            "-",
        ]
        environment = dict(os.environ)
        environment["CITADEL_DOC_SYNC_ACTIVE"] = "1"
        result = subprocess.run(
            command,
            input=prompt,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=int(config["codex_timeout_seconds"]),
            env=environment,
            check=False,
        )
        if result.returncode:
            error = result.stderr[-2000:].replace("\n", " ")
            raise SyncError(f"Codex analysis failed with exit {result.returncode}: {error}")
        if not output_path.exists():
            raise SyncError("Codex produced no structured analysis")
        try:
            return json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SyncError("Codex analysis was not valid JSON") from exc


def validate_plan(
    plan: dict[str, Any],
    modules: list[dict[str, Any]],
    changed: list[dict[str, str]],
) -> None:
    if plan.get("schema_version") != 1:
        raise SyncError("Analysis returned an unsupported schema version")
    expected = {module["module"] for module in modules}
    actual = {module.get("name") for module in plan.get("affected_modules", [])}
    if actual != expected or len(plan.get("affected_modules", [])) != len(expected):
        raise SyncError(
            f"Analysis module set differs from deterministic mapping: expected {sorted(expected)}, "
            f"received {sorted(str(item) for item in actual)}"
        )
    changed_paths = {item["path"] for item in changed}
    for module in plan["affected_modules"]:
        if not set(module.get("evidence_files", [])).issubset(changed_paths):
            raise SyncError(f"Analysis cited non-diff evidence for {module['name']}")
    validation = plan.get("validation", {})
    if validation.get("status") == "COMMAND VERIFIED":
        raise SyncError("Analysis stage cannot claim COMMAND VERIFIED")
    if validation.get("commands_run"):
        raise SyncError("Analysis stage reported commands it was not permitted to run")
    serialized = json.dumps(plan, ensure_ascii=False)
    findings = scan_secrets(serialized)
    if findings:
        raise SyncError(f"Potential secret in generated documentation: {', '.join(findings)}")
    if "citadel-doc-sync:" in serialized:
        raise SyncError("Generated documentation attempted to inject a sync marker")


def frontmatter(note_type: str, module: str, commit: str) -> str:
    today = dt.date.today().isoformat()
    return (
        "---\n"
        f"type: {note_type}\n"
        f"module: {module}\n"
        "status: partial\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"source_commit: {commit}\n"
        "verified: false\n"
        "tags:\n"
        "  - citadel\n"
        "  - knowledge-sync\n"
        "---\n"
    )


def module_entry(commit: str, subject: str, item: dict[str, Any]) -> tuple[str, str]:
    short = commit[:12]
    marker = f"<!-- citadel-doc-sync:module:{item['name']}:{commit} -->"
    points = "\n".join(f"- {point}" for point in item["documentation_points"]) or "- None."
    evidence = "\n".join(f"- `{path}`" for path in item["evidence_files"])
    content = (
        f"## Documentation sync — {short}\n\n{marker}\n\n"
        f"**Commit:** `{commit}` — {subject}\n\n"
        f"{item['change_summary']}\n\n### Documentation points\n\n{points}\n\n"
        f"### Committed evidence\n\n{evidence}\n\n"
        "Runtime and production behavior remain **NOT VERIFIED** unless separately evidenced."
    )
    return marker, content


def append_or_create(
    vault: ObsidianVault,
    path: str,
    title: str,
    note_type: str,
    module: str,
    commit: str,
    marker: str,
    entry: str,
) -> bool:
    existing = vault.read_if_exists(path)
    if existing is None:
        vault.create(
            path,
            f"{frontmatter(note_type, module, commit)}\n# {title}\n\n{entry}\n",
        )
        return True
    return vault.append_once(path, marker, entry)


def apply_plan(
    vault: ObsidianVault,
    config: dict[str, Any],
    commit_metadata: dict[str, str],
    modules: list[dict[str, Any]],
    plan: dict[str, Any],
) -> dict[str, Any]:
    commit = commit_metadata["commit"]
    subject = commit_metadata["subject"]
    short = commit[:12]
    test_path = config["test_connection_note"]
    test_before = vault.read(test_path)["content"]

    rules = {rule["module"]: rule for rule in modules}
    planned_existing: set[str] = set()
    for item in plan["affected_modules"]:
        planned_existing.update(rules[item["name"]]["notes"])
    targets = config["targets"]
    planned_existing.update(
        [targets["decision_log"], targets["incident_register"]]
    )
    for path in sorted(planned_existing):
        if vault.read_if_exists(path) is None:
            raise SyncError(f"Required historical note does not exist: {path}")

    changed_notes: list[str] = []
    for item in plan["affected_modules"]:
        marker, entry = module_entry(commit, subject, item)
        for path in rules[item["name"]]["notes"]:
            if vault.append_once(path, marker, entry):
                changed_notes.append(path)

    changelog_marker = f"<!-- citadel-doc-sync:changelog:{commit} -->"
    changelog_entry = (
        f"## {commit_metadata['author_date'][:10]} — {short}\n\n{changelog_marker}\n\n"
        f"**{subject}**\n\n{plan['changelog_entry']}\n\n"
        f"Affected modules: {', '.join(item['name'] for item in plan['affected_modules'])}."
    )
    if append_or_create(
        vault,
        targets["changelog"],
        "CITADEL Changelog",
        "changelog",
        "CITADEL",
        commit,
        changelog_marker,
        changelog_entry,
    ):
        changed_notes.append(targets["changelog"])

    release_marker = f"<!-- citadel-doc-sync:release:{commit} -->"
    release_items = "\n".join(f"- {item}" for item in plan["release_notes"])
    release_entry = (
        f"## {short} — {subject}\n\n{release_marker}\n\n{release_items}\n\n"
        "Application/runtime validation: **NOT VERIFIED** unless cited in the commit validation note."
    )
    if append_or_create(
        vault,
        targets["release_notes"],
        "CITADEL Release Notes",
        "release-notes",
        "CITADEL",
        commit,
        release_marker,
        release_entry,
    ):
        changed_notes.append(targets["release_notes"])

    decision = plan["architecture_decision"]
    if decision["applicable"]:
        marker = f"<!-- citadel-doc-sync:decision:{commit} -->"
        entry = (
            f"## ADR {short}: {decision['title']}\n\n{marker}\n\n"
            f"### Context\n\n{decision['context']}\n\n### Decision\n\n{decision['decision']}\n\n"
            f"### Consequences\n\n{decision['consequences']}\n\n"
            f"Evidence commit: `{commit}`."
        )
        if vault.append_once(targets["decision_log"], marker, entry):
            changed_notes.append(targets["decision_log"])

    incident = plan["incident"]
    if incident["applicable"]:
        marker = f"<!-- citadel-doc-sync:incident:{commit} -->"
        entry = (
            f"## Incident/fix {short}: {incident['title']}\n\n{marker}\n\n"
            f"### Symptom\n\n{incident['symptom']}\n\n### Fix\n\n{incident['fix']}\n\n"
            f"### Validation\n\n{incident['validation']}\n\nEvidence commit: `{commit}`."
        )
        if vault.append_once(targets["incident_register"], marker, entry):
            changed_notes.append(targets["incident_register"])

    validation_path = (
        f"{targets['validation_folder']}/Commit {short} Documentation Validation.md"
    )
    validation_marker = f"<!-- citadel-doc-sync:validation:{commit} -->"
    evidence = "\n".join(f"- {item}" for item in plan["validation"]["evidence"]) or "- None."
    unsupported = "\n".join(f"- {item}" for item in plan["unsupported_claims"]) or "- None."
    validation_note = (
        f"{frontmatter('validation', 'CITADEL', commit)}\n"
        f"# Commit {short} Documentation Validation\n\n{validation_marker}\n\n"
        f"## Scope\n\nCommitted documentation analysis for `{commit}` (`{subject}`).\n\n"
        f"## Status\n\n**{plan['validation']['status']}**\n\n"
        f"## Evidence\n\n{evidence}\n\n"
        "## Commands run by analysis stage\n\n- None. The Codex analysis stage is read-only.\n\n"
        f"## Unsupported claims\n\n{unsupported}\n\n"
        "This note validates documentation provenance and sync mechanics only. It does not "
        "establish trading correctness, runtime health, broker behavior, or production readiness.\n"
    )
    existing_validation = vault.read_if_exists(validation_path)
    if existing_validation is None:
        vault.create(validation_path, validation_note)
        changed_notes.append(validation_path)
    elif validation_marker not in existing_validation["content"]:
        raise SyncError(f"Refusing to replace existing validation note: {validation_path}")

    if vault.read(test_path)["content"] != test_before:
        raise SyncError(f"{test_path} changed during documentation sync")
    for path in sorted(set(changed_notes)):
        findings = scan_secrets(vault.read(path)["content"])
        if findings:
            raise SyncError(f"Secret scan failed after writing {path}: {', '.join(findings)}")
    search_results = vault.search(short)
    if not search_results:
        raise SyncError(f"Obsidian search did not find the commit marker {short}")
    return {
        "changed_notes": sorted(set(changed_notes)),
        "validation_note": validation_path,
        "test_connection_preserved": True,
        "secret_scan": "PASS",
        "search": "PASS",
    }


@contextlib.contextmanager
def recursion_lock(repo: Path) -> Iterator[None]:
    if os.environ.get("CITADEL_DOC_SYNC_ACTIVE") == "1":
        raise SyncError("Recursive documentation sync invocation blocked")
    lock_path = Path(run_git(repo, "rev-parse", "--git-path", "citadel-doc-sync.lock"))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise SyncError(f"Another documentation sync is active: {lock_path}") from exc
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        os.close(descriptor)
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--commit", help="Single committed revision to inspect")
    scope.add_argument("--range", dest="revision_range", help="Committed OLD..NEW range")
    parser.add_argument("--dry-run", action="store_true", help="Analyze and print the plan only")
    parser.add_argument(
        "--static-analysis",
        action="store_true",
        help="Use deterministic fallback analysis (intended for workflow validation)",
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    repo = Path(config["repository"]).resolve()
    if Path(run_git(repo, "rev-parse", "--show-toplevel").strip()).resolve() != repo:
        raise SyncError(f"Configured repository is not its Git worktree root: {repo}")

    with recursion_lock(repo):
        old, new, scope = revision_scope(repo, args.commit, args.revision_range)
        changes = changed_files(repo, old, new)
        modules, ignored = detect_modules(changes, config)
        if not modules:
            print(
                json.dumps(
                    {
                        "status": "SKIPPED",
                        "reason": "No mapped material module changes",
                        "scope": scope,
                        "ignored_paths": ignored,
                    },
                    indent=2,
                )
            )
            return 0
        commit_metadata = metadata(repo, new, scope)
        diff = committed_diff(repo, old, new, int(config["max_diff_bytes"]))
        prompt = render_prompt(commit_metadata, changes, modules, diff)
        plan = (
            static_plan(commit_metadata, modules)
            if args.static_analysis
            else codex_plan(repo, prompt, config)
        )
        validate_plan(plan, modules, changes)

        vault = ObsidianVault()
        test_hash = hashlib.sha256(
            vault.read(config["test_connection_note"])["content"].encode("utf-8")
        ).hexdigest()
        planned_notes = sorted(
            {
                note
                for module in modules
                for note in module["notes"]
            }
            | {
                config["targets"]["changelog"],
                config["targets"]["release_notes"],
                config["targets"]["decision_log"],
                config["targets"]["incident_register"],
                f"{config['targets']['validation_folder']}/Commit {new[:12]} Documentation Validation.md",
            }
        )
        for path in planned_notes:
            vault.read_if_exists(path)

        if args.dry_run:
            print(
                json.dumps(
                    {
                        "status": "DRY_RUN",
                        "scope": scope,
                        "commit": new,
                        "affected_modules": [module["module"] for module in modules],
                        "ignored_paths": ignored,
                        "planned_notes": planned_notes,
                        "test_connection_sha256": test_hash,
                        "analysis": plan,
                        "writes": 0,
                    },
                    indent=2,
                )
            )
            return 0

        if not config.get("enabled", False):
            raise SyncError(
                "Apply mode is disabled in config.json. Run --dry-run and validate_sync.py first; "
                "then explicitly set enabled=true after review."
            )
        result = apply_plan(vault, config, commit_metadata, modules, plan)
        print(
            json.dumps(
                {
                    "status": "APPLIED",
                    "scope": scope,
                    "commit": new,
                    "affected_modules": [module["module"] for module in modules],
                    **result,
                    "git_commit_created": False,
                    "git_push_performed": False,
                },
                indent=2,
            )
        )
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SyncError, MCPError, subprocess.TimeoutExpired) as exc:
        print(f"citadel-doc-sync: {exc}", file=sys.stderr)
        raise SystemExit(1)

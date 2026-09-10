#!/usr/bin/env python3
"""Validate the CITADEL knowledge-sync implementation and Obsidian MCP boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import py_compile
import subprocess
import sys
import uuid
from pathlib import Path

from sync import CONFIG_PATH, SECRET_PATTERNS, TOOL_DIR, load_config
from vault_mcp import MCPError, ObsidianVault


REQUIRED_FILES = [
    "citadel-doc-sync",
    "sync.py",
    "vault_mcp.py",
    "config.json",
    "analysis.schema.json",
    "codex_prompt.md",
    "validate_sync.py",
    "README.md",
    "install-hook",
    "post-commit.hook",
]
REQUIRED_TOOLS = {
    "vault_list",
    "vault_read",
    "vault_write",
    "vault_patch",
    "vault_delete",
    "vault_get_document_map",
    "search_simple",
}


class ValidationError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--canary",
        action="store_true",
        help="Create, patch, read, search, and permanently delete one unique temporary vault note",
    )
    parser.add_argument(
        "--skip-dry-run",
        action="store_true",
        help="Skip the deterministic HEAD dry-run subprocess",
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    checks: dict[str, object] = {}

    missing_files = [name for name in REQUIRED_FILES if not (TOOL_DIR / name).is_file()]
    if missing_files:
        raise ValidationError(f"Missing tooling files: {missing_files}")
    checks["required_files"] = "PASS"

    if config.get("enabled") is not False:
        raise ValidationError("config.json must remain disabled during validation")
    checks["disabled_by_default"] = "PASS"

    json.loads((TOOL_DIR / "analysis.schema.json").read_text(encoding="utf-8"))
    for file_name in ("sync.py", "vault_mcp.py", "validate_sync.py"):
        py_compile.compile(str(TOOL_DIR / file_name), doraise=True)
    checks["syntax_and_json"] = "PASS"

    repository = Path(config["repository"]).resolve()
    before_status = subprocess.run(
        ["git", "-C", str(repository), "status", "--porcelain=v1"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout

    if not args.skip_dry_run:
        result = subprocess.run(
            [
                str(TOOL_DIR / "citadel-doc-sync"),
                "--commit",
                "HEAD",
                "--dry-run",
                "--static-analysis",
            ],
            cwd=repository,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        if result.returncode:
            raise ValidationError(f"Static dry-run failed: {result.stderr[-1200:]}")
        dry_run = json.loads(result.stdout)
        if dry_run.get("status") != "DRY_RUN" or dry_run.get("writes") != 0:
            raise ValidationError("Static dry-run did not report a zero-write DRY_RUN")
        checks["static_head_dry_run"] = {
            "status": "PASS",
            "commit": dry_run.get("commit"),
            "affected_modules": dry_run.get("affected_modules"),
            "writes": 0,
        }

    vault = ObsidianVault()
    tools = set(vault.tools())
    missing_tools = sorted(REQUIRED_TOOLS - tools)
    if missing_tools:
        raise ValidationError(f"Obsidian MCP tools missing: {missing_tools}")
    checks["obsidian_mcp_tools"] = "PASS"

    folders, files = vault.list_recursive()
    test_path = config["test_connection_note"]
    if test_path not in files:
        raise ValidationError(f"Required preserved note is missing: {test_path}")
    test_before = vault.read(test_path)["content"]
    test_hash = hashlib.sha256(test_before.encode("utf-8")).hexdigest()
    required_folders = {
        "00 - CITADEL HQ",
        "02 - Modules",
        "08 - Decisions",
        "09 - Bugs & Incidents",
        "10 - Validation & Proofs",
    }
    if not required_folders.issubset(folders):
        raise ValidationError(
            f"Vault structure is missing: {sorted(required_folders - set(folders))}"
        )
    checks["vault_read_and_structure"] = {
        "status": "PASS",
        "folders": len(folders),
        "markdown_files": len([path for path in files if path.endswith(".md")]),
        "test_connection_sha256": test_hash,
    }

    canary_path: str | None = None
    try:
        if args.canary:
            token = uuid.uuid4().hex
            canary_path = f"99 - Inbox/Knowledge Sync Validation Canary {token}.md"
            marker = f"<!-- citadel-doc-sync-canary:{token} -->"
            initial = (
                "---\ntype: validation\nstatus: temporary\nverified: false\n"
                "tags:\n  - citadel\n  - knowledge-sync-canary\n---\n\n"
                f"# Knowledge Sync Validation Canary\n\n{marker}\n\nCreated for MCP validation."
            )
            vault.create(canary_path, initial)
            appended_marker = f"<!-- citadel-doc-sync-canary-append:{token} -->"
            vault.append_once(
                canary_path,
                appended_marker,
                f"## Append proof\n\n{appended_marker}\n\nMCP structured append succeeded.",
            )
            content = vault.read(canary_path)["content"]
            if marker not in content or appended_marker not in content:
                raise ValidationError("Canary read-back did not contain both markers")
            if not vault.search(token):
                raise ValidationError("Canary was not found through Obsidian search")
            vault.delete(canary_path, permanent=True)
            canary_path = None
            checks["mcp_write_patch_read_search_cleanup"] = "PASS"
    finally:
        if canary_path and vault.read_if_exists(canary_path) is not None:
            vault.delete(canary_path, permanent=True)

    if vault.read(test_path)["content"] != test_before:
        raise ValidationError(f"{test_path} changed during validation")
    checks["test_connection_preserved"] = "PASS"

    after_status = subprocess.run(
        ["git", "-C", str(repository), "status", "--porcelain=v1"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout
    before_unrelated = {
        line for line in before_status.splitlines() if "scripts/knowledge_sync/" not in line
    }
    after_unrelated = {
        line for line in after_status.splitlines() if "scripts/knowledge_sync/" not in line
    }
    if before_unrelated != after_unrelated:
        raise ValidationError("An unrelated repository worktree change occurred during validation")
    checks["unrelated_worktree_preserved"] = "PASS"

    source_text = "\n".join(
        (TOOL_DIR / name).read_text(encoding="utf-8")
        for name in REQUIRED_FILES
        if (TOOL_DIR / name).suffix in {".py", ".md", ".json", ""}
    )
    literal_findings = []
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(source_text):
            literal_findings.append(name)
    if literal_findings:
        raise ValidationError(f"Tooling secret scan failed: {literal_findings}")
    checks["tooling_secret_scan"] = "PASS"

    print(json.dumps({"overall": "PASS", "checks": checks}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValidationError, MCPError, subprocess.TimeoutExpired) as exc:
        print(f"validate_sync: {exc}", file=sys.stderr)
        raise SystemExit(1)

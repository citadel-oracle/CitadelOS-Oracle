#!/usr/bin/env python3
"""Small, dependency-free client for the configured Obsidian MCP server."""

from __future__ import annotations

import json
import os
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class MCPError(RuntimeError):
    pass


class ObsidianVault:
    def __init__(self, codex_config: Path | None = None) -> None:
        config_path = codex_config or Path(
            os.environ.get("CITADEL_CODEX_CONFIG", Path.home() / ".codex/config.toml")
        )
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        server = config.get("mcp_servers", {}).get("obsidian")
        if not isinstance(server, dict) or not server.get("url"):
            raise MCPError(f"Obsidian MCP is not configured in {config_path}")
        if server.get("enabled", True) is False:
            raise MCPError("The configured Obsidian MCP server is disabled")

        self._url = str(server["url"])
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self._headers.update(server.get("http_headers", {}))
        token_env = server.get("bearer_token_env_var")
        if token_env:
            token = os.environ.get(str(token_env))
            if not token:
                raise MCPError(f"Required MCP token environment variable is unset: {token_env}")
            self._headers["Authorization"] = f"Bearer {token}"

        self._timeout = int(server.get("tool_timeout_sec", 60))
        self._session: str | None = None
        self._rpc_id = 0
        self._initialize()

    def _next_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    @staticmethod
    def _parse_sse(payload: str) -> dict[str, Any] | None:
        for line in payload.splitlines():
            if line.startswith("data: "):
                return json.loads(line[6:])
        return None

    @staticmethod
    def _read_first_sse_event(response: Any) -> dict[str, Any] | None:
        """Read one JSON-RPC event without waiting for a persistent SSE stream to close."""
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line.startswith("data: "):
                return json.loads(line[6:])
        return None

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = dict(self._headers)
        if self._session:
            headers["mcp-session-id"] = self._session
        request = urllib.request.Request(
            self._url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                self._session = response.headers.get("mcp-session-id") or self._session
                if "text/event-stream" in response.headers.get("Content-Type", ""):
                    parsed = self._read_first_sse_event(response)
                else:
                    parsed = self._parse_sse(response.read().decode("utf-8"))
                if parsed is None and "id" not in payload:
                    return {}
                if parsed is None:
                    raise MCPError("Obsidian MCP returned no JSON-RPC data event")
                return parsed
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise MCPError(f"Obsidian MCP HTTP {exc.code}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise MCPError(f"Cannot reach Obsidian MCP: {exc.reason}") from exc

    def _initialize(self) -> None:
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "citadel-doc-sync", "version": "1.0.0"},
                },
            }
        )
        if response.get("error"):
            raise MCPError(f"MCP initialization failed: {response['error']}")
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
        )
        if response.get("error"):
            raise MCPError(f"{name} failed: {response['error']}")
        result = response.get("result", {})
        text = next(
            (
                item.get("text", "")
                for item in result.get("content", [])
                if item.get("type") == "text"
            ),
            "",
        )
        if result.get("isError"):
            raise MCPError(f"{name} failed: {text[:500]}")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def tools(self) -> list[str]:
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/list",
                "params": {},
            }
        )
        return sorted(tool["name"] for tool in response.get("result", {}).get("tools", []))

    def read(self, path: str) -> dict[str, Any]:
        result = self.call("vault_read", {"path": path})
        if not isinstance(result, dict) or "content" not in result:
            raise MCPError(f"Unexpected vault_read result for {path}")
        return result

    def read_if_exists(self, path: str) -> dict[str, Any] | None:
        try:
            return self.read(path)
        except MCPError as exc:
            if "not found" in str(exc).lower() or "does not exist" in str(exc).lower():
                return None
            raise

    def create(self, path: str, content: str) -> None:
        if self.read_if_exists(path) is not None:
            raise MCPError(f"Refusing to overwrite existing note: {path}")
        self.call("vault_write", {"path": path, "content": content})
        if self.read(path)["content"].rstrip() != content.rstrip():
            raise MCPError(f"Read-back mismatch after creating {path}")

    def append_once(self, path: str, marker: str, content: str) -> bool:
        current = self.read(path)
        if marker in current["content"]:
            return False
        document_map = self.call("vault_get_document_map", {"path": path})
        version = document_map.get("version") if isinstance(document_map, dict) else None
        arguments: dict[str, Any] = {
            "path": path,
            "targetType": "heading",
            "target": [],
            "operation": "append",
            "scope": "content",
            "content": content,
            "rejectIfContentPreexists": True,
        }
        if version:
            arguments["ifMatch"] = version
        self.call("vault_patch", arguments)
        if marker not in self.read(path)["content"]:
            raise MCPError(f"Append verification failed for {path}")
        return True

    def list_recursive(self, root: str = "") -> tuple[list[str], list[str]]:
        folders: list[str] = []
        files: list[str] = []
        queue = [root]
        while queue:
            folder = queue.pop(0)
            result = self.call("vault_list", {"path": folder})
            entries = result.get("files", result) if isinstance(result, dict) else result
            for entry in entries:
                name = entry if isinstance(entry, str) else entry.get("path", "")
                is_folder = name.endswith("/")
                leaf = name.rstrip("/")
                path = f"{folder}/{leaf}" if folder else leaf
                if is_folder:
                    folders.append(path)
                    queue.append(path)
                else:
                    files.append(path)
        return sorted(folders), sorted(files)

    def search(self, query: str) -> Any:
        return self.call("search_simple", {"query": query, "contextLength": 80})

    def delete(self, path: str, *, permanent: bool = False) -> None:
        self.call("vault_delete", {"path": path, "permanent": permanent})

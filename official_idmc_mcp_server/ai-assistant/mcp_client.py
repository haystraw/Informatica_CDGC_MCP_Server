"""
MCP client for the official IDMC MCP Server.

Opens one session per chat request and reuses it for all tool calls.
"""

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger("ai_assistant.mcp")

_tool_cache: dict = {}
TOOL_CACHE_TTL = 300  # seconds


@asynccontextmanager
async def mcp_session(server_url: str, token: str):
    headers = {"X-IDMC-Token": token}
    async with streamablehttp_client(server_url.rstrip("/"), headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


class McpClient:
    def __init__(self, server_url: str, token: str):
        self.server_url = server_url.rstrip("/")
        self.token = token
        self._session: ClientSession | None = None

    def set_session(self, session: ClientSession) -> None:
        self._session = session

    async def _get_tools(self) -> list:
        if self._session:
            result = await self._session.list_tools()
            return result.tools
        async with mcp_session(self.server_url, self.token) as session:
            result = await session.list_tools()
            return result.tools

    async def list_tools(self) -> list[dict]:
        cached = _tool_cache.get(self.server_url)
        if cached and time.monotonic() < cached["expires"]:
            logger.debug("Tool cache hit (%d tools)", len(cached["tools"]))
            return cached["tools"]

        raw = await self._get_tools()
        result = [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": dict(t.inputSchema) if t.inputSchema else {},
            }
            for t in raw
        ]
        _tool_cache[self.server_url] = {"tools": result, "expires": time.monotonic() + TOOL_CACHE_TTL}
        logger.info("Loaded %d MCP tools (cached for %ds)", len(result), TOOL_CACHE_TTL)
        return result

    async def call_tool(self, name: str, arguments: dict) -> Any:
        logger.info("Tool call: %s %s", name, list(arguments.keys()))
        if self._session:
            result = await self._session.call_tool(name, arguments)
        else:
            async with mcp_session(self.server_url, self.token) as session:
                result = await session.call_tool(name, arguments)
        parts = [c.text for c in result.content if hasattr(c, "text")]
        return "\n".join(parts) if parts else str(result.content)

    async def as_tool_declarations(self) -> list[dict]:
        tools = await self.list_tools()
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": {
                    "type": "object",
                    "properties": _clean_properties(t.get("inputSchema", {}).get("properties", {})),
                    "required": t.get("inputSchema", {}).get("required", []),
                },
            }
            for t in tools
        ]


def _clean_properties(props: dict) -> dict:
    return {name: _clean_schema(schema) for name, schema in props.items()}


def _clean_schema(schema: dict) -> dict:
    if not isinstance(schema, dict):
        return schema

    if "anyOf" in schema:
        for option in schema["anyOf"]:
            if isinstance(option, dict) and option.get("type") != "null":
                base = {k: v for k, v in schema.items() if k != "anyOf"}
                base.update(option)
                return _clean_schema(base)
        return {"type": "string"}

    STRIP_KEYS = {"additionalProperties", "additional_properties", "$schema", "$defs", "default"}
    result = {}
    for k, v in schema.items():
        if k in STRIP_KEYS:
            continue
        if k == "type" and v == "null":
            result[k] = "string"
        elif k == "properties" and isinstance(v, dict):
            result[k] = _clean_properties(v)
        elif isinstance(v, dict):
            result[k] = _clean_schema(v)
        elif isinstance(v, list):
            result[k] = [_clean_schema(i) if isinstance(i, dict) else i for i in v]
        else:
            result[k] = v
    return result

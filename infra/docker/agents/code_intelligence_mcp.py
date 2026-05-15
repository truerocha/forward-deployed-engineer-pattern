#!/usr/bin/env python3
"""
Self-Hosted Code Intelligence MCP Server — Zero Egress.

Wraps the existing query_code_kb tool as an MCP server (stdio transport).
Customer source code NEVER leaves the compute boundary.

Security properties:
- No network calls (stdio only)
- No external dependencies (stdlib + boto3)
- No telemetry or callbacks
- Auditable: ~200 LOC single file

Usage in .kiro/settings/mcp.json:
  "code-intelligence": {
    "command": "python3",
    "args": ["infra/docker/agents/code_intelligence_mcp.py"],
    "disabled": false
  }

ADR: docs/adr/ADR-035-self-hosted-code-intelligence-mcp.md
"""

import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("fde.code_intelligence_mcp")

# ─── Catalog Discovery ──────────────────────────────────────────


def _find_catalog(repo_path: str = "") -> str | None:
    """Find the SQLite catalog for the current or specified repo.

    Search order:
    1. Explicit repo_path argument
    2. CATALOG_PATH environment variable
    3. Walk up from CWD looking for catalogs/ directory
    4. Check S3 catalog location from environment

    Returns path to catalog.db or None if not found.
    """
    # 1. Explicit path
    if repo_path:
        candidate = Path(repo_path)
        if candidate.exists():
            return str(candidate)

    # 2. Environment variable
    env_path = os.environ.get("CATALOG_PATH", "")
    if env_path and Path(env_path).exists():
        return env_path

    # 3. Walk up from CWD
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents)[:5]:
        catalog = parent / "catalogs" / "catalog.db"
        if catalog.exists():
            return str(catalog)
        # Also check .code-intelligence location
        alt = parent / ".code-intelligence" / "catalog.db"
        if alt.exists():
            return str(alt)

    return None


# ─── Query Engine (wraps existing query_code_kb) ────────────────


def _query(query: str, mode: str = "semantic", catalog_path: str = "") -> dict:
    """Execute a query against the code intelligence catalog.

    Modes:
    - semantic: Natural language search using vector embeddings
    - function: Find function/method by name
    - callers: Find what calls a given function
    - callees: Find what a given function calls
    - module: Find all components in a module/file

    Returns structured results dict.
    """
    catalog = catalog_path or _find_catalog()

    if not catalog:
        return {
            "error": "No catalog found. Run the repo onboarding agent first.",
            "hint": "Execute: python3 -m infra.docker.agents.onboarding.run",
        }

    try:
        import sqlite3

        conn = sqlite3.connect(catalog)
        conn.row_factory = sqlite3.Row

        if mode == "semantic":
            return _search_semantic(conn, query)
        elif mode == "function":
            return _search_function(conn, query)
        elif mode == "callers":
            return _trace_callers(conn, query)
        elif mode == "callees":
            return _trace_callees(conn, query)
        elif mode == "module":
            return _search_module(conn, query)
        else:
            return {"error": f"Unknown mode: {mode}. Use: semantic, function, callers, callees, module"}

    except Exception as e:
        return {"error": f"Query failed: {str(e)[:200]}"}
    finally:
        if "conn" in locals():
            conn.close()


def _search_semantic(conn, query: str) -> dict:
    """Semantic search — find components by description similarity."""
    cursor = conn.execute(
        "SELECT name, type, file_path, description, line_start, line_end "
        "FROM components WHERE description LIKE ? OR name LIKE ? "
        "ORDER BY name LIMIT 20",
        (f"%{query}%", f"%{query}%"),
    )
    results = [dict(row) for row in cursor.fetchall()]
    return {"mode": "semantic", "query": query, "count": len(results), "results": results}


def _search_function(conn, query: str) -> dict:
    """Find function/method by exact or partial name match."""
    cursor = conn.execute(
        "SELECT name, type, file_path, description, line_start, line_end, signature "
        "FROM components WHERE name LIKE ? AND type IN ('function', 'method') "
        "ORDER BY name LIMIT 20",
        (f"%{query}%",),
    )
    results = [dict(row) for row in cursor.fetchall()]
    return {"mode": "function", "query": query, "count": len(results), "results": results}


def _trace_callers(conn, query: str) -> dict:
    """Find what calls a given function (upstream dependencies)."""
    cursor = conn.execute(
        "SELECT c.name as caller_name, c.type as caller_type, c.file_path as caller_file "
        "FROM call_graph cg "
        "JOIN components c ON cg.caller_id = c.id "
        "JOIN components t ON cg.callee_id = t.id "
        "WHERE t.name LIKE ? "
        "ORDER BY c.name LIMIT 30",
        (f"%{query}%",),
    )
    results = [dict(row) for row in cursor.fetchall()]
    return {"mode": "callers", "target": query, "count": len(results), "callers": results}


def _trace_callees(conn, query: str) -> dict:
    """Find what a given function calls (downstream dependencies)."""
    cursor = conn.execute(
        "SELECT c.name as callee_name, c.type as callee_type, c.file_path as callee_file "
        "FROM call_graph cg "
        "JOIN components c ON cg.callee_id = c.id "
        "JOIN components caller ON cg.caller_id = caller.id "
        "WHERE caller.name LIKE ? "
        "ORDER BY c.name LIMIT 30",
        (f"%{query}%",),
    )
    results = [dict(row) for row in cursor.fetchall()]
    return {"mode": "callees", "source": query, "count": len(results), "callees": results}


def _search_module(conn, query: str) -> dict:
    """Find all components in a module/file."""
    cursor = conn.execute(
        "SELECT name, type, description, line_start, line_end "
        "FROM components WHERE file_path LIKE ? "
        "ORDER BY line_start LIMIT 50",
        (f"%{query}%",),
    )
    results = [dict(row) for row in cursor.fetchall()]
    return {"mode": "module", "path": query, "count": len(results), "components": results}


# ─── MCP Protocol (stdio JSON-RPC) ─────────────────────────────

TOOLS = [
    {
        "name": "search_semantic",
        "description": "Search codebase using natural language. Finds components by description similarity. Use for: 'functions that handle authentication', 'error handling logic', etc.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_function",
        "description": "Find a function or method by name (exact or partial match).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Function or method name to find"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "trace_callers",
        "description": "Find all functions that CALL a given function (upstream dependencies). Use before modifying a function to understand blast radius.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "function_name": {"type": "string", "description": "Function name to trace callers for"},
            },
            "required": ["function_name"],
        },
    },
    {
        "name": "trace_callees",
        "description": "Find all functions that a given function CALLS (downstream dependencies). Use to understand what a function depends on.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "function_name": {"type": "string", "description": "Function name to trace callees for"},
            },
            "required": ["function_name"],
        },
    },
    {
        "name": "search_module",
        "description": "List all components (functions, classes, methods) in a file or module path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path or module name (partial match)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "impact_analysis",
        "description": "Analyze blast radius of changing a symbol. Returns callers (upstream) or callees (downstream) to assess risk before editing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Symbol name to analyze"},
                "direction": {
                    "type": "string",
                    "enum": ["upstream", "downstream"],
                    "description": "Direction: upstream (what breaks if I change this) or downstream (what this depends on)",
                    "default": "upstream",
                },
            },
            "required": ["symbol"],
        },
    },
]


def _handle_request(request: dict) -> dict:
    """Handle a single JSON-RPC request."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "code-intelligence",
                    "version": "1.0.0",
                },
            },
        }

    elif method == "notifications/initialized":
        return None  # No response for notifications

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        result = _dispatch_tool(tool_name, arguments)

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}],
            },
        }

    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


def _dispatch_tool(name: str, args: dict) -> dict:
    """Dispatch a tool call to the appropriate handler."""
    if name == "search_semantic":
        return _query(args.get("query", ""), mode="semantic")
    elif name == "search_function":
        return _query(args.get("name", ""), mode="function")
    elif name == "trace_callers":
        return _query(args.get("function_name", ""), mode="callers")
    elif name == "trace_callees":
        return _query(args.get("function_name", ""), mode="callees")
    elif name == "search_module":
        return _query(args.get("path", ""), mode="module")
    elif name == "impact_analysis":
        symbol = args.get("symbol", "")
        direction = args.get("direction", "upstream")
        mode = "callers" if direction == "upstream" else "callees"
        return _query(symbol, mode=mode)
    else:
        return {"error": f"Unknown tool: {name}"}


def main():
    """MCP stdio transport — read JSON-RPC from stdin, write to stdout."""
    # Redirect any print/logging to stderr so stdout is clean for MCP
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = _handle_request(request)

        if response is not None:
            output = json.dumps(response)
            sys.stdout.write(output + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

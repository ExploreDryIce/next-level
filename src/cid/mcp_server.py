"""
Cid MCP Server — exposes project memory as tools for any coding agent.

Run:
    python src/cid/mcp_server.py

Then add to .kiro/settings/mcp.json or any MCP-compatible agent.

Tools exposed:
    - cid_recall: Search memories by query
    - cid_remember: Store a new fact/decision/pattern
    - cid_session_start: Load context for starting work on a project
    - cid_session_end: Save what happened this session
    - cid_conventions: Get project conventions
    - cid_failures: Get past failures/fixes for a topic
    - cid_stats: Get memory store statistics
"""

import json
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from cid.memory import get_memory_store


# ─── MCP Server Setup ─────────────────────────────────────────────────────

app = Server("cid")


@app.list_tools()
async def list_tools():
    """List all Cid tools available to the agent."""
    return [
        Tool(
            name="cid_recall",
            description="Search Cid's memory for relevant knowledge. Use when you need context about past work, decisions, conventions, or failures. Returns the most relevant memories.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for (keywords, topic, or question)"},
                    "category": {"type": "string", "enum": ["session", "decision", "convention", "failure", "pattern", "fact", "context"], "description": "Optional: filter by memory category"},
                    "project": {"type": "string", "description": "Optional: filter by project name (dvce, next-level, etc)"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="cid_remember",
            description="Store something important in Cid's persistent memory. Use for: decisions made, conventions discovered, failures encountered, useful patterns, or important facts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "What to remember (be specific and complete)"},
                    "category": {"type": "string", "enum": ["session", "decision", "convention", "failure", "pattern", "fact", "context"], "description": "Type of memory"},
                    "project": {"type": "string", "description": "Which project this relates to"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags for easier recall"},
                },
                "required": ["content", "category", "project"],
            },
        ),
        Tool(
            name="cid_session_start",
            description="Start a work session. Returns relevant context from past sessions, conventions, and recent failures for the given project. Call this at the beginning of every conversation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project name (dvce, next-level, etc)"},
                },
                "required": ["project"],
            },
        ),
        Tool(
            name="cid_session_end",
            description="End a work session. Saves a summary of what was accomplished and any decisions made. Call this when work is complete.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project name"},
                    "summary": {"type": "string", "description": "Summary of what was accomplished this session"},
                    "decisions": {"type": "array", "items": {"type": "string"}, "description": "Key decisions made (optional)"},
                },
                "required": ["project", "summary"],
            },
        ),
        Tool(
            name="cid_conventions",
            description="Get all coding conventions and patterns for a project. Returns how things are done: naming, architecture, libraries, workflows.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project name"},
                },
                "required": ["project"],
            },
        ),
        Tool(
            name="cid_failures",
            description="Get past failures and their fixes. Use when something breaks to check if we've seen it before.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What's failing or what topic to check"},
                    "project": {"type": "string", "description": "Optional: filter by project"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="cid_stats",
            description="Get Cid memory store statistics — total memories, breakdown by category and project.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    """Handle tool calls from the agent."""
    store = get_memory_store()

    if name == "cid_recall":
        results = store.recall(
            query=arguments["query"],
            category=arguments.get("category"),
            project=arguments.get("project"),
        )
        if not results:
            return [TextContent(type="text", text="No memories found matching that query.")]
        
        output = []
        for mem in results:
            output.append(f"[{mem.category}] ({mem.project}) {mem.content}")
            if mem.tags:
                output.append(f"  tags: {', '.join(mem.tags)}")
        return [TextContent(type="text", text="\n".join(output))]

    elif name == "cid_remember":
        mem = store.remember(
            content=arguments["content"],
            category=arguments["category"],
            project=arguments["project"],
            tags=arguments.get("tags", []),
        )
        return [TextContent(type="text", text=f"Remembered ({mem.category}/{mem.project}): {mem.content[:100]}...")]

    elif name == "cid_session_start":
        context = store.start_session(arguments["project"])
        output = [f"Project: {context['project']} ({context['project_memories']} memories)"]
        
        if context["recent_sessions"]:
            output.append("\n--- Recent Sessions ---")
            for s in context["recent_sessions"]:
                output.append(f"• {s[:200]}")
        
        if context["conventions"]:
            output.append("\n--- Conventions ---")
            for c in context["conventions"]:
                output.append(f"• {c}")
        
        if context["recent_failures"]:
            output.append("\n--- Recent Failures (watch out) ---")
            for f in context["recent_failures"]:
                output.append(f"⚠ {f[:150]}")

        return [TextContent(type="text", text="\n".join(output))]

    elif name == "cid_session_end":
        store.end_session(
            project=arguments["project"],
            summary=arguments["summary"],
            decisions=arguments.get("decisions"),
        )
        return [TextContent(type="text", text=f"Session saved for {arguments['project']}.")]

    elif name == "cid_conventions":
        conventions = store.get_conventions(arguments["project"])
        if not conventions:
            return [TextContent(type="text", text=f"No conventions stored yet for {arguments['project']}. Use cid_remember to add them.")]
        output = [f"Conventions for {arguments['project']}:"]
        for c in conventions:
            output.append(f"• {c.content}")
        return [TextContent(type="text", text="\n".join(output))]

    elif name == "cid_failures":
        results = store.recall(
            query=arguments["query"],
            category="failure",
            project=arguments.get("project"),
        )
        if not results:
            return [TextContent(type="text", text="No matching failures in memory.")]
        output = ["Past failures matching your query:"]
        for mem in results:
            output.append(f"⚠ [{mem.project}] {mem.content}")
        return [TextContent(type="text", text="\n".join(output))]

    elif name == "cid_stats":
        stats = store.stats()
        output = [
            f"Cid Memory Store",
            f"Total: {stats['total_memories']} memories",
            f"Path: {stats['store_path']}",
            "",
            "By category:",
        ]
        for cat, count in sorted(stats["by_category"].items(), key=lambda x: x[1], reverse=True):
            output.append(f"  {cat}: {count}")
        output.append("\nBy project:")
        for proj, count in sorted(stats["by_project"].items(), key=lambda x: x[1], reverse=True):
            output.append(f"  {proj}: {count}")
        return [TextContent(type="text", text="\n".join(output))]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


# ─── Entry Point ──────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

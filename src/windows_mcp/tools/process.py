"""Process tool — list and kill running processes."""

from typing import Literal

from mcp.types import ToolAnnotations
from windows_mcp.infrastructure import with_analytics
from fastmcp import Context
from windows_mcp import process


def register(mcp, *, get_desktop, get_analytics):
    @mcp.tool(
        name="Process",
        description='List processes or terminate by PID/exact name. In list mode pid is exact; name is fuzzy, and both filters intersect. sort_by selects memory/cpu/name; limit is positive and the result reports observed match count and truncation. kill mode may require elevation.',
        annotations=ToolAnnotations(
            title="Process",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "Process-Tool")
    def process_tool(
        mode: Literal["list", "kill"],
        name: str | None = None,
        pid: int | None = None,
        sort_by: Literal["memory", "cpu", "name"] = "memory",
        limit: int = 20,
        force: bool | str = False,
        ctx: Context = None,
    ) -> str:
        try:
            if mode == "list":
                return process.list_processes(name=name, pid=pid, sort_by=sort_by, limit=limit)
            elif mode == "kill":
                force = force is True or (isinstance(force, str) and force.lower() == "true")
                return process.kill_process(name=name, pid=pid, force=force)
            else:
                return 'Error: mode must be either "list" or "kill".'
        except Exception as e:
            raise

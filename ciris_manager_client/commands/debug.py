"""
Debug commands for CIRIS CLI.

These commands query agent persistence (tasks, thoughts, actions) for debugging.
"""

import json
import sys
from typing import Any
from argparse import Namespace


class DebugCommands:
    """Debug commands for querying agent persistence."""

    @staticmethod
    def tasks(ctx: Any, args: Namespace) -> int:
        """
        List tasks for an agent.

        Args:
            ctx: Command context
            args: Parsed arguments with:
                - agent_id: Agent identifier
                - status: Optional status filter
                - limit: Maximum number of tasks
                - server: Optional server ID
                - occurrence: Optional occurrence ID

        Returns:
            0 on success, non-zero on failure
        """
        agent_id = args.agent_id
        status = getattr(args, "status", None)
        limit = getattr(args, "limit", 50)
        server_id = getattr(args, "server", None)
        occurrence_id = getattr(args, "occurrence", None)

        if not ctx.quiet:
            print(f"Listing tasks for agent: {agent_id}")

        try:
            # Build query params
            params = {"limit": limit}
            if status:
                params["status"] = status
            if server_id:
                params["server_id"] = server_id
            if occurrence_id:
                params["occurrence_id"] = occurrence_id

            result = ctx.client._request(
                "GET", f"/debug/agents/{agent_id}/tasks", params=params
            )

            if ctx.output_format == "json":
                print(json.dumps(result, indent=2))
            elif ctx.output_format == "yaml":
                import yaml
                print(yaml.dump(result, default_flow_style=False))
            else:
                # Table format
                if not result:
                    print("No tasks found")
                    return 0

                print(f"\n{'Task ID':<45} {'Status':<12} {'Priority':<8} {'Created':<20}")
                print("-" * 90)
                for task in result:
                    task_id = task.get("task_id", "")[:44]
                    status_val = task.get("status", "unknown")
                    priority = str(task.get("priority", "-"))
                    created = task.get("created_at", "-")[:19] if task.get("created_at") else "-"
                    print(f"{task_id:<45} {status_val:<12} {priority:<8} {created:<20}")

                print(f"\nTotal: {len(result)} task(s)")

            return 0

        except Exception as e:
            print(f"Error listing tasks: {e}", file=sys.stderr)
            return 1

    @staticmethod
    def task(ctx: Any, args: Namespace) -> int:
        """
        Get detailed task information.

        Args:
            ctx: Command context
            args: Parsed arguments with:
                - agent_id: Agent identifier
                - task_id: Task identifier
                - server: Optional server ID
                - occurrence: Optional occurrence ID

        Returns:
            0 on success, non-zero on failure
        """
        agent_id = args.agent_id
        task_id = args.task_id
        server_id = getattr(args, "server", None)
        occurrence_id = getattr(args, "occurrence", None)

        if not ctx.quiet:
            print(f"Getting task {task_id} for agent: {agent_id}")

        try:
            params = {}
            if server_id:
                params["server_id"] = server_id
            if occurrence_id:
                params["occurrence_id"] = occurrence_id

            result = ctx.client._request(
                "GET", f"/debug/agents/{agent_id}/tasks/{task_id}", params=params
            )

            if ctx.output_format == "json":
                print(json.dumps(result, indent=2))
            elif ctx.output_format == "yaml":
                import yaml
                print(yaml.dump(result, default_flow_style=False))
            else:
                # Detailed format
                print(f"\n=== Task: {result.get('task_id')} ===\n")
                print(f"Status:      {result.get('status')}")
                print(f"Priority:    {result.get('priority', '-')}")
                print(f"Created:     {result.get('created_at', '-')}")
                print(f"Updated:     {result.get('updated_at', '-')}")

                if result.get("description"):
                    print(f"\nDescription:\n{result.get('description')[:500]}")

                if result.get("context"):
                    print("\nContext:")
                    print(json.dumps(result.get("context"), indent=2)[:500])

                thoughts = result.get("thoughts", [])
                if thoughts:
                    print(f"\n=== Associated Thoughts ({len(thoughts)}) ===\n")
                    print(f"{'Thought ID':<35} {'Status':<12} {'Depth':<6} {'Action':<15}")
                    print("-" * 75)
                    for t in thoughts:
                        t_id = t.get("thought_id", "")[:34]
                        t_status = t.get("status", "unknown")
                        t_depth = str(t.get("depth", "-"))
                        t_action = t.get("final_action", "-") or "-"
                        print(f"{t_id:<35} {t_status:<12} {t_depth:<6} {t_action:<15}")

            return 0

        except Exception as e:
            print(f"Error getting task: {e}", file=sys.stderr)
            return 1

    @staticmethod
    def thoughts(ctx: Any, args: Namespace) -> int:
        """
        List thoughts for an agent.

        Args:
            ctx: Command context
            args: Parsed arguments with:
                - agent_id: Agent identifier
                - status: Optional status filter
                - task_id: Optional task ID filter
                - limit: Maximum number of thoughts
                - server: Optional server ID
                - occurrence: Optional occurrence ID

        Returns:
            0 on success, non-zero on failure
        """
        agent_id = args.agent_id
        status = getattr(args, "status", None)
        task_id = getattr(args, "task_id", None)
        limit = getattr(args, "limit", 50)
        server_id = getattr(args, "server", None)
        occurrence_id = getattr(args, "occurrence", None)

        if not ctx.quiet:
            print(f"Listing thoughts for agent: {agent_id}")

        try:
            params = {"limit": limit}
            if status:
                params["status"] = status
            if task_id:
                params["task_id"] = task_id
            if server_id:
                params["server_id"] = server_id
            if occurrence_id:
                params["occurrence_id"] = occurrence_id

            result = ctx.client._request(
                "GET", f"/debug/agents/{agent_id}/thoughts", params=params
            )

            if ctx.output_format == "json":
                print(json.dumps(result, indent=2))
            elif ctx.output_format == "yaml":
                import yaml
                print(yaml.dump(result, default_flow_style=False))
            else:
                # Table format
                if not result:
                    print("No thoughts found")
                    return 0

                print(f"\n{'Thought ID':<35} {'Status':<12} {'Depth':<6} {'Action':<15} {'Task ID':<25}")
                print("-" * 100)
                for thought in result:
                    t_id = thought.get("thought_id", "")[:34]
                    status_val = thought.get("status", "unknown")
                    depth = str(thought.get("depth", "-"))
                    action = thought.get("final_action", "-") or "-"
                    task = thought.get("source_task_id", "")[:24] if thought.get("source_task_id") else "-"
                    print(f"{t_id:<35} {status_val:<12} {depth:<6} {action:<15} {task:<25}")

                print(f"\nTotal: {len(result)} thought(s)")

            return 0

        except Exception as e:
            print(f"Error listing thoughts: {e}", file=sys.stderr)
            return 1

    @staticmethod
    def thought(ctx: Any, args: Namespace) -> int:
        """
        Get detailed thought information.

        Args:
            ctx: Command context
            args: Parsed arguments with:
                - agent_id: Agent identifier
                - thought_id: Thought identifier (can be partial)
                - server: Optional server ID
                - occurrence: Optional occurrence ID

        Returns:
            0 on success, non-zero on failure
        """
        agent_id = args.agent_id
        thought_id = args.thought_id
        server_id = getattr(args, "server", None)
        occurrence_id = getattr(args, "occurrence", None)

        if not ctx.quiet:
            print(f"Getting thought {thought_id} for agent: {agent_id}")

        try:
            params = {}
            if server_id:
                params["server_id"] = server_id
            if occurrence_id:
                params["occurrence_id"] = occurrence_id

            result = ctx.client._request(
                "GET", f"/debug/agents/{agent_id}/thoughts/{thought_id}", params=params
            )

            if ctx.output_format == "json":
                print(json.dumps(result, indent=2))
            elif ctx.output_format == "yaml":
                import yaml
                print(yaml.dump(result, default_flow_style=False))
            else:
                # Detailed format
                print(f"\n=== Thought: {result.get('thought_id')} ===\n")
                print(f"Status:       {result.get('status')}")
                print(f"Type:         {result.get('thought_type', '-')}")
                print(f"Depth:        {result.get('depth', '-')}")
                print(f"Task ID:      {result.get('source_task_id', '-')}")
                print(f"Final Action: {result.get('final_action', '-')}")
                print(f"Ponder Count: {result.get('ponder_count', '-')}")
                print(f"Created:      {result.get('created_at', '-')}")
                print(f"Updated:      {result.get('updated_at', '-')}")

                if result.get("content"):
                    print(f"\nContent:\n{result.get('content')[:1000]}")

                if result.get("action_result"):
                    print(f"\nAction Result:\n{result.get('action_result')[:500]}")

                if result.get("ponder_notes"):
                    print(f"\nPonder Notes:\n{result.get('ponder_notes')[:500]}")

                if result.get("context"):
                    print("\nContext:")
                    print(json.dumps(result.get("context"), indent=2)[:500])

            return 0

        except Exception as e:
            print(f"Error getting thought: {e}", file=sys.stderr)
            return 1

    @staticmethod
    def query(ctx: Any, args: Namespace) -> int:
        """
        Execute a custom SQL query against the agent's database.

        Only SELECT queries are allowed.

        Args:
            ctx: Command context
            args: Parsed arguments with:
                - agent_id: Agent identifier
                - query: SQL query to execute
                - server: Optional server ID
                - occurrence: Optional occurrence ID

        Returns:
            0 on success, non-zero on failure
        """
        agent_id = args.agent_id
        query = args.query
        server_id = getattr(args, "server", None)
        occurrence_id = getattr(args, "occurrence", None)

        if not ctx.quiet:
            print(f"Executing query on agent: {agent_id}")

        try:
            params = {}
            if server_id:
                params["server_id"] = server_id
            if occurrence_id:
                params["occurrence_id"] = occurrence_id

            result = ctx.client._request(
                "POST",
                f"/debug/agents/{agent_id}/query",
                json={"query": query},
                params=params,
            )

            if ctx.output_format == "json":
                print(json.dumps(result, indent=2))
            elif ctx.output_format == "yaml":
                import yaml
                print(yaml.dump(result, default_flow_style=False))
            else:
                # Table format
                columns = result.get("columns", [])
                rows = result.get("rows", [])
                row_count = result.get("row_count", 0)

                if not rows:
                    print("No results")
                    return 0

                # Calculate column widths
                widths = []
                for i, col in enumerate(columns):
                    max_width = len(col)
                    for row in rows[:20]:  # Sample first 20 rows
                        if i < len(row):
                            max_width = max(max_width, len(str(row[i])[:50]))
                    widths.append(min(max_width, 50))

                # Print header
                header = " | ".join(
                    col[:widths[i]].ljust(widths[i])
                    for i, col in enumerate(columns)
                )
                print(f"\n{header}")
                print("-" * len(header))

                # Print rows
                for row in rows[:100]:  # Limit output
                    row_str = " | ".join(
                        str(val)[:widths[i]].ljust(widths[i])
                        for i, val in enumerate(row)
                    )
                    print(row_str)

                if row_count > 100:
                    print(f"\n... and {row_count - 100} more rows")
                print(f"\nTotal: {row_count} row(s)")

            return 0

        except Exception as e:
            print(f"Error executing query: {e}", file=sys.stderr)
            return 1

    @staticmethod
    def schema(ctx: Any, args: Namespace) -> int:
        """
        Get database schema for an agent.

        Args:
            ctx: Command context
            args: Parsed arguments with:
                - agent_id: Agent identifier
                - server: Optional server ID
                - occurrence: Optional occurrence ID

        Returns:
            0 on success, non-zero on failure
        """
        agent_id = args.agent_id
        server_id = getattr(args, "server", None)
        occurrence_id = getattr(args, "occurrence", None)

        if not ctx.quiet:
            print(f"Getting schema for agent: {agent_id}")

        try:
            params = {}
            if server_id:
                params["server_id"] = server_id
            if occurrence_id:
                params["occurrence_id"] = occurrence_id

            result = ctx.client._request(
                "GET", f"/debug/agents/{agent_id}/schema", params=params
            )

            if ctx.output_format == "json":
                print(json.dumps(result, indent=2))
            elif ctx.output_format == "yaml":
                import yaml
                print(yaml.dump(result, default_flow_style=False))
            else:
                # Human-readable format
                print(f"\nDatabase Dialect: {result.get('dialect', 'unknown')}")
                print(f"\n{'='*60}")

                tables = result.get("tables", {})
                for table_name, columns in tables.items():
                    print(f"\nTable: {table_name}")
                    print("-" * 40)
                    for col in columns:
                        pk = " (PK)" if col.get("primary_key") else ""
                        nullable = " NULL" if col.get("nullable") else " NOT NULL"
                        print(f"  {col.get('name'):<25} {col.get('type'):<15}{nullable}{pk}")

                print(f"\nTotal: {len(tables)} table(s)")

            return 0

        except Exception as e:
            print(f"Error getting schema: {e}", file=sys.stderr)
            return 1

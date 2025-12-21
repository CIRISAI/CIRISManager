"""
Debug API routes for querying agent persistence (SQLite/PostgreSQL).

Provides read-only access to agent databases for debugging tasks, thoughts,
actions, and results.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging
import json

logger = logging.getLogger(__name__)


class DebugQueryRequest(BaseModel):
    """Request model for custom SQL queries."""

    query: str
    params: Optional[List[Any]] = None


class DebugQueryResponse(BaseModel):
    """Response model for SQL query results."""

    columns: List[str]
    rows: List[List[Any]]
    row_count: int


class TaskSummary(BaseModel):
    """Summary of a task."""

    task_id: str
    description: Optional[str] = None
    status: str
    priority: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ThoughtSummary(BaseModel):
    """Summary of a thought."""

    thought_id: str
    source_task_id: Optional[str] = None
    status: str
    thought_type: Optional[str] = None
    depth: Optional[int] = None
    created_at: Optional[str] = None
    final_action: Optional[str] = None


class TaskDetail(BaseModel):
    """Detailed task information."""

    task_id: str
    description: Optional[str] = None
    status: str
    priority: Optional[int] = None
    context: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    thoughts: List[ThoughtSummary] = []


class ThoughtDetail(BaseModel):
    """Detailed thought information."""

    thought_id: str
    source_task_id: Optional[str] = None
    status: str
    thought_type: Optional[str] = None
    depth: Optional[int] = None
    content: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    ponder_count: Optional[int] = None
    ponder_notes: Optional[str] = None
    final_action: Optional[str] = None
    action_result: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def create_debug_routes(manager: Any) -> APIRouter:
    """
    Create debug API routes with manager instance.

    Args:
        manager: CIRISManager instance

    Returns:
        Configured APIRouter for debug endpoints
    """
    router = APIRouter(prefix="/debug", tags=["debug"])

    def _get_db_dialect(container_name: str, docker_client: Any) -> str:
        """Detect database dialect (sqlite or postgres) from container."""
        try:
            container = docker_client.containers.get(container_name)
            env_vars = container.attrs.get("Config", {}).get("Env", [])

            for env in env_vars:
                if env.startswith("CIRIS_DB_URL="):
                    db_url = env.split("=", 1)[1]
                    if "postgresql" in db_url or "postgres" in db_url:
                        return "postgres"
                    elif "sqlite" in db_url or db_url.endswith(".db"):
                        return "sqlite"

            # Default to sqlite if no explicit URL
            return "sqlite"
        except Exception as e:
            logger.warning(f"Could not detect dialect for {container_name}: {e}")
            return "sqlite"

    def _get_db_path(container_name: str, docker_client: Any) -> str:
        """Get database path from container environment."""
        try:
            container = docker_client.containers.get(container_name)
            env_vars = container.attrs.get("Config", {}).get("Env", [])

            for env in env_vars:
                if env.startswith("CIRIS_DB_URL="):
                    db_url: str = env.split("=", 1)[1]
                    if db_url.startswith("sqlite:///"):
                        return db_url.replace("sqlite:///", "")
                    return db_url

            # Default SQLite path
            return "/app/data/ciris_engine.db"
        except Exception as e:
            logger.warning(f"Could not get DB path for {container_name}: {e}")
            return "/app/data/ciris_engine.db"

    def _exec_sqlite_query(
        container_name: str,
        docker_client: Any,
        query: str,
        db_path: str = "/app/data/ciris_engine.db",
    ) -> Dict[str, Any]:
        """Execute a read-only SQLite query inside the container."""
        try:
            container = docker_client.containers.get(container_name)

            # Ensure query is SELECT only (read-only)
            query_upper = query.strip().upper()
            if not query_upper.startswith("SELECT"):
                raise ValueError("Only SELECT queries are allowed")

            # Execute sqlite3 with JSON output
            cmd = f'sqlite3 -json "{db_path}" "{query}"'
            result = container.exec_run(["sh", "-c", cmd])

            if result.exit_code != 0:
                error_msg = result.output.decode("utf-8", errors="replace")
                raise RuntimeError(f"SQLite query failed: {error_msg}")

            output = result.output.decode("utf-8", errors="replace").strip()
            if not output:
                return {"columns": [], "rows": [], "row_count": 0}

            # Parse JSON output
            try:
                rows = json.loads(output)
                if not rows:
                    return {"columns": [], "rows": [], "row_count": 0}

                columns = list(rows[0].keys()) if rows else []
                data = [[row.get(col) for col in columns] for row in rows]
                return {"columns": columns, "rows": data, "row_count": len(data)}
            except json.JSONDecodeError:
                # Fallback: try to parse as plain text
                lines = output.split("\n")
                return {"columns": ["result"], "rows": [[line] for line in lines if line], "row_count": len(lines)}

        except Exception as e:
            logger.error(f"SQLite query execution failed: {e}")
            raise

    def _exec_postgres_query(
        container_name: str,
        docker_client: Any,
        query: str,
        db_url: str,
    ) -> Dict[str, Any]:
        """Execute a read-only PostgreSQL query inside the container."""
        try:
            container = docker_client.containers.get(container_name)

            # Ensure query is SELECT only (read-only)
            query_upper = query.strip().upper()
            if not query_upper.startswith("SELECT"):
                raise ValueError("Only SELECT queries are allowed")

            # Use psql with JSON output format
            cmd = f"psql '{db_url}' -t -A -F',' -c \"{query}\""
            result = container.exec_run(["sh", "-c", cmd])

            if result.exit_code != 0:
                error_msg = result.output.decode("utf-8", errors="replace")
                raise RuntimeError(f"PostgreSQL query failed: {error_msg}")

            output = result.output.decode("utf-8", errors="replace").strip()
            if not output:
                return {"columns": [], "rows": [], "row_count": 0}

            # Parse CSV-like output
            lines = [line for line in output.split("\n") if line.strip()]
            if not lines:
                return {"columns": [], "rows": [], "row_count": 0}

            # First line might be headers if we use -H flag, otherwise infer
            rows = [line.split(",") for line in lines]
            return {"columns": [f"col{i}" for i in range(len(rows[0]))], "rows": rows, "row_count": len(rows)}

        except Exception as e:
            logger.error(f"PostgreSQL query execution failed: {e}")
            raise

    def _discover_agent_container(
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> tuple:
        """Discover agent container and return (container_name, server_id, docker_client)."""
        from ciris_manager.docker_discovery import DockerAgentDiscovery

        discovery = DockerAgentDiscovery(
            manager.agent_registry, docker_client_manager=manager.docker_client
        )
        agents = discovery.discover_agents()

        discovered_agent = next(
            (
                a
                for a in agents
                if a.agent_id == agent_id
                and (occurrence_id is None or a.occurrence_id == occurrence_id)
                and (server_id is None or a.server_id == server_id)
            ),
            None,
        )

        if not discovered_agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        docker_client = manager.docker_client.get_client(discovered_agent.server_id)
        return discovered_agent.container_name, discovered_agent.server_id, docker_client

    @router.get("/agents/{agent_id}/tasks", response_model=List[TaskSummary])
    async def list_tasks(
        agent_id: str,
        status: Optional[str] = Query(None, description="Filter by status (pending, active, completed, deferred)"),
        limit: int = Query(50, description="Maximum number of tasks to return"),
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> List[TaskSummary]:
        """
        List tasks for an agent.

        Args:
            agent_id: Agent identifier
            status: Optional status filter
            limit: Maximum results (default 50)
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server deployments
        """
        try:
            container_name, srv_id, docker_client = _discover_agent_container(
                agent_id, occurrence_id, server_id
            )

            dialect = _get_db_dialect(container_name, docker_client)
            db_path = _get_db_path(container_name, docker_client)

            # Build query
            query = """
                SELECT task_id, description, status, priority, created_at, updated_at
                FROM tasks
            """
            if status:
                query += f" WHERE status = '{status}'"
            query += f" ORDER BY created_at DESC LIMIT {limit}"

            if dialect == "sqlite":
                result = _exec_sqlite_query(container_name, docker_client, query, db_path)
            else:
                result = _exec_postgres_query(container_name, docker_client, query, db_path)

            tasks = []
            for row in result["rows"]:
                tasks.append(
                    TaskSummary(
                        task_id=row[0] or "",
                        description=row[1][:200] if row[1] else None,
                        status=row[2] or "unknown",
                        priority=row[3],
                        created_at=str(row[4]) if row[4] else None,
                        updated_at=str(row[5]) if row[5] else None,
                    )
                )

            return tasks

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to list tasks for {agent_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to list tasks: {e}")

    @router.get("/agents/{agent_id}/tasks/{task_id}", response_model=TaskDetail)
    async def get_task(
        agent_id: str,
        task_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> TaskDetail:
        """
        Get detailed task information including associated thoughts.

        Args:
            agent_id: Agent identifier
            task_id: Task identifier
            occurrence_id: Optional occurrence ID
            server_id: Optional server ID
        """
        try:
            container_name, srv_id, docker_client = _discover_agent_container(
                agent_id, occurrence_id, server_id
            )

            dialect = _get_db_dialect(container_name, docker_client)
            db_path = _get_db_path(container_name, docker_client)

            # Get task details
            task_query = f"""
                SELECT task_id, description, status, priority, context, created_at, updated_at
                FROM tasks WHERE task_id = '{task_id}'
            """

            if dialect == "sqlite":
                task_result = _exec_sqlite_query(container_name, docker_client, task_query, db_path)
            else:
                task_result = _exec_postgres_query(container_name, docker_client, task_query, db_path)

            if not task_result["rows"]:
                raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

            row = task_result["rows"][0]

            # Get associated thoughts
            thoughts_query = f"""
                SELECT thought_id, source_task_id, status, thought_type, thought_depth,
                       created_at, final_action
                FROM thoughts WHERE source_task_id = '{task_id}'
                ORDER BY created_at ASC
            """

            if dialect == "sqlite":
                thoughts_result = _exec_sqlite_query(container_name, docker_client, thoughts_query, db_path)
            else:
                thoughts_result = _exec_postgres_query(container_name, docker_client, thoughts_query, db_path)

            thoughts = []
            for t_row in thoughts_result["rows"]:
                thoughts.append(
                    ThoughtSummary(
                        thought_id=t_row[0] or "",
                        source_task_id=t_row[1],
                        status=t_row[2] or "unknown",
                        thought_type=t_row[3],
                        depth=t_row[4],
                        created_at=str(t_row[5]) if t_row[5] else None,
                        final_action=t_row[6],
                    )
                )

            # Parse context if JSON
            context = None
            if row[4]:
                try:
                    context = json.loads(row[4]) if isinstance(row[4], str) else row[4]
                except (json.JSONDecodeError, TypeError):
                    context = {"raw": str(row[4])}

            return TaskDetail(
                task_id=row[0] or "",
                description=row[1],
                status=row[2] or "unknown",
                priority=row[3],
                context=context,
                created_at=str(row[4]) if row[4] else None,
                updated_at=str(row[5]) if row[5] else None,
                thoughts=thoughts,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get task {task_id} for {agent_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get task: {e}")

    @router.get("/agents/{agent_id}/thoughts", response_model=List[ThoughtSummary])
    async def list_thoughts(
        agent_id: str,
        status: Optional[str] = Query(None, description="Filter by status"),
        task_id: Optional[str] = Query(None, description="Filter by task ID"),
        limit: int = Query(50, description="Maximum number of thoughts to return"),
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> List[ThoughtSummary]:
        """
        List thoughts for an agent.

        Args:
            agent_id: Agent identifier
            status: Optional status filter
            task_id: Optional task ID filter
            limit: Maximum results (default 50)
            occurrence_id: Optional occurrence ID
            server_id: Optional server ID
        """
        try:
            container_name, srv_id, docker_client = _discover_agent_container(
                agent_id, occurrence_id, server_id
            )

            dialect = _get_db_dialect(container_name, docker_client)
            db_path = _get_db_path(container_name, docker_client)

            # Build query
            query = """
                SELECT thought_id, source_task_id, status, thought_type, thought_depth,
                       created_at, final_action
                FROM thoughts
            """
            conditions = []
            if status:
                conditions.append(f"status = '{status}'")
            if task_id:
                conditions.append(f"source_task_id = '{task_id}'")

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += f" ORDER BY created_at DESC LIMIT {limit}"

            if dialect == "sqlite":
                result = _exec_sqlite_query(container_name, docker_client, query, db_path)
            else:
                result = _exec_postgres_query(container_name, docker_client, query, db_path)

            thoughts = []
            for row in result["rows"]:
                thoughts.append(
                    ThoughtSummary(
                        thought_id=row[0] or "",
                        source_task_id=row[1],
                        status=row[2] or "unknown",
                        thought_type=row[3],
                        depth=row[4],
                        created_at=str(row[5]) if row[5] else None,
                        final_action=row[6],
                    )
                )

            return thoughts

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to list thoughts for {agent_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to list thoughts: {e}")

    @router.get("/agents/{agent_id}/thoughts/{thought_id}", response_model=ThoughtDetail)
    async def get_thought(
        agent_id: str,
        thought_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> ThoughtDetail:
        """
        Get detailed thought information.

        Args:
            agent_id: Agent identifier
            thought_id: Thought identifier (can be partial prefix)
            occurrence_id: Optional occurrence ID
            server_id: Optional server ID
        """
        try:
            container_name, srv_id, docker_client = _discover_agent_container(
                agent_id, occurrence_id, server_id
            )

            dialect = _get_db_dialect(container_name, docker_client)
            db_path = _get_db_path(container_name, docker_client)

            # Support partial thought ID matching
            if len(thought_id) < 36:
                where_clause = f"thought_id LIKE '{thought_id}%'"
            else:
                where_clause = f"thought_id = '{thought_id}'"

            query = f"""
                SELECT thought_id, source_task_id, status, thought_type, thought_depth,
                       content, context, ponder_count, ponder_notes, final_action,
                       action_result, created_at, updated_at
                FROM thoughts WHERE {where_clause}
                LIMIT 1
            """

            if dialect == "sqlite":
                result = _exec_sqlite_query(container_name, docker_client, query, db_path)
            else:
                result = _exec_postgres_query(container_name, docker_client, query, db_path)

            if not result["rows"]:
                raise HTTPException(status_code=404, detail=f"Thought '{thought_id}' not found")

            row = result["rows"][0]

            # Parse context if JSON
            context = None
            if row[6]:
                try:
                    context = json.loads(row[6]) if isinstance(row[6], str) else row[6]
                except (json.JSONDecodeError, TypeError):
                    context = {"raw": str(row[6])}

            return ThoughtDetail(
                thought_id=row[0] or "",
                source_task_id=row[1],
                status=row[2] or "unknown",
                thought_type=row[3],
                depth=row[4],
                content=row[5],
                context=context,
                ponder_count=row[7],
                ponder_notes=row[8],
                final_action=row[9],
                action_result=row[10],
                created_at=str(row[11]) if row[11] else None,
                updated_at=str(row[12]) if row[12] else None,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get thought {thought_id} for {agent_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get thought: {e}")

    @router.post("/agents/{agent_id}/query", response_model=DebugQueryResponse)
    async def execute_query(
        agent_id: str,
        request: DebugQueryRequest,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> DebugQueryResponse:
        """
        Execute a custom read-only SQL query against the agent's database.

        Only SELECT queries are allowed. This is for debugging purposes only.

        Args:
            agent_id: Agent identifier
            request: Query request with SQL query
            occurrence_id: Optional occurrence ID
            server_id: Optional server ID
        """
        try:
            # Validate query is SELECT only
            query_upper = request.query.strip().upper()
            if not query_upper.startswith("SELECT"):
                raise HTTPException(
                    status_code=400,
                    detail="Only SELECT queries are allowed for debugging",
                )

            # Block dangerous patterns
            dangerous_patterns = [
                "DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE",
                "TRUNCATE", "GRANT", "REVOKE", "EXEC", "EXECUTE",
            ]
            for pattern in dangerous_patterns:
                if pattern in query_upper:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Query contains forbidden keyword: {pattern}",
                    )

            container_name, srv_id, docker_client = _discover_agent_container(
                agent_id, occurrence_id, server_id
            )

            dialect = _get_db_dialect(container_name, docker_client)
            db_path = _get_db_path(container_name, docker_client)

            if dialect == "sqlite":
                result = _exec_sqlite_query(container_name, docker_client, request.query, db_path)
            else:
                result = _exec_postgres_query(container_name, docker_client, request.query, db_path)

            return DebugQueryResponse(
                columns=result["columns"],
                rows=result["rows"],
                row_count=result["row_count"],
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to execute query for {agent_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Query execution failed: {e}")

    @router.get("/agents/{agent_id}/schema")
    async def get_schema(
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get database schema information for an agent.

        Returns table names and their columns.

        Args:
            agent_id: Agent identifier
            occurrence_id: Optional occurrence ID
            server_id: Optional server ID
        """
        try:
            container_name, srv_id, docker_client = _discover_agent_container(
                agent_id, occurrence_id, server_id
            )

            dialect = _get_db_dialect(container_name, docker_client)
            db_path = _get_db_path(container_name, docker_client)

            schema: Dict[str, Any] = {"dialect": dialect, "tables": {}}

            if dialect == "sqlite":
                # Get tables
                tables_query = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                tables_result = _exec_sqlite_query(container_name, docker_client, tables_query, db_path)
                for row in tables_result["rows"]:
                    table_name = row[0]
                    if table_name.startswith("sqlite_"):
                        continue

                    # Get columns for each table
                    cols_query = f"PRAGMA table_info('{table_name}')"
                    cols_result = _exec_sqlite_query(container_name, docker_client, cols_query, db_path)

                    columns = []
                    for col_row in cols_result["rows"]:
                        columns.append({
                            "name": col_row[1],
                            "type": col_row[2],
                            "nullable": not col_row[3],
                            "primary_key": bool(col_row[5]),
                        })

                    schema["tables"][table_name] = columns

            else:
                # PostgreSQL schema query
                tables_query = """
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'public' ORDER BY table_name
                """
                tables_result = _exec_postgres_query(container_name, docker_client, tables_query, db_path)

                for row in tables_result["rows"]:
                    table_name = row[0]

                    cols_query = f"""
                        SELECT column_name, data_type, is_nullable
                        FROM information_schema.columns
                        WHERE table_name = '{table_name}' AND table_schema = 'public'
                    """
                    cols_result = _exec_postgres_query(container_name, docker_client, cols_query, db_path)

                    columns = []
                    for col_row in cols_result["rows"]:
                        columns.append({
                            "name": col_row[0],
                            "type": col_row[1],
                            "nullable": col_row[2] == "YES",
                        })

                    schema["tables"][table_name] = columns

            return schema

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get schema for {agent_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get schema: {e}")

    return router


"""
SQL operation helpers for the custom MCP server.

This module contains database operations used by MCP tools. The functions
are kept separate from the MCP server entrypoint so the tool behavior can
be updated independently.
"""

import json

from django.db import DatabaseError, connection


def get_database_schema_impl() -> str:
    """
    Get the database schema.

    returns:
        The SQL statements used to create the database tables
    """
    with connection.cursor() as cursor:
        # Get the table definitions from the SQLite database
        cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")

        return "\n\n".join(row[0] for row in cursor.fetchall() if row[0])


def execute_sql_impl(query: str) -> str:
    """
    Execute an SQL query.

    args:
        query: The SQL query to execute

    returns:
        The query results or execution status
    """
    if not query.strip():
        return "SQL query cannot be empty."

    try:
        with connection.cursor() as cursor:
            # Execute the SQL query
            cursor.execute(query)

            # Return the columns and rows if the query produces results
            if cursor.description:
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchmany(51)

                result = {"columns": columns, "rows": rows[:50], "truncated": len(rows) > 50}
                return json.dumps(result, default=str)

            # Return the number of affected rows for other operations
            return f"SQL executed. Rows affected: {cursor.rowcount}"

    except DatabaseError as error:
        return f"SQL error: {error}"

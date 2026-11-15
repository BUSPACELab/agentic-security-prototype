
"""
SQL operation helpers for the custom MCP server.

This module contains database operations used by MCP tools. The functions
are kept separate from the MCP server entrypoint so the tool behavior can
be updated independently.
"""

from config.security import system


def get_database_schema_impl() -> str:
    """Return the permitted database schema."""
    return system.database_schema()


def execute_sql_impl(query: str) -> str:
    """Execute SQL through the security system."""
    return system.execute_sql(query)
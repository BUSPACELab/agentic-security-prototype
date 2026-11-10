"""
2. Policy/Authorization Layer/Actions
Action and tool constants for the policy layer.

Business actions are intentionally separate from tool names.

Example:
- Tool name: delete_file
- Business action: file:delete
"""

from dataclasses import dataclass
from types import MappingProxyType


# Chat contexts used by the agent and authorization policies
FILE_CONTEXT = "file"
PROFILE_CONTEXT = "profile"


# Resource types used to define the resource of an authorization request

# Used when the protected resource is the tool itself, usually for tool exposure.
RESOURCE_TOOL = "tool"
# Used when the protected resource is a collection of files, such as listing or searching inside a user's file collection
RESOURCE_FILE_COLLECTION = "file_collection"
# Used when the protected resource is a specific file
RESOURCE_FILE = "file"
# Used when the protected resource is a user account
RESOURCE_ACCOUNT = "account"
# Used when the protected resource is a database schema
RESOURCE_DATABASE_SCHEMA = "database_schema"

# Business actions used to define the action of an authorization request
TOOL_EXPOSE = "tool:expose"

FILE_LIST = "file:list"
FILE_SEARCH = "file:search"
FILE_READ = "file:read"
FILE_DELETE = "file:delete"

DATABASE_SCHEMA_READ = "database-schema:read"

FILE_METADATA_READ = "file-metadata:read"
ACCOUNT_READ = "account:read"
ACCOUNT_UPDATE = "account:update"


# LangChain / MCP tool names used to map to business actions
TOOL_LIST_FILES = "list_files"
TOOL_SEARCH_FILES = "search_files"
TOOL_READ_FILE = "read_file"
TOOL_DELETE_FILE = "delete_file"

TOOL_GET_DATABASE_SCHEMA = "get_database_schema"
TOOL_EXECUTE_SQL = "execute_sql"


# Define each tool's business action and allowed context in one place
@dataclass(frozen=True)
class ToolDefinition:
    actions: frozenset[str]
    contexts: frozenset[str]

TOOL_DEFINITIONS = MappingProxyType(
    {
        TOOL_LIST_FILES: ToolDefinition(actions=frozenset({FILE_LIST}), contexts=frozenset({FILE_CONTEXT})),
        TOOL_SEARCH_FILES: ToolDefinition(actions=frozenset({FILE_SEARCH}), contexts=frozenset({FILE_CONTEXT})),
        TOOL_READ_FILE: ToolDefinition(actions=frozenset({FILE_READ}), contexts=frozenset({FILE_CONTEXT})),
        TOOL_DELETE_FILE: ToolDefinition(actions=frozenset({FILE_DELETE}), contexts=frozenset({FILE_CONTEXT})),
        TOOL_GET_DATABASE_SCHEMA: ToolDefinition(actions=frozenset({DATABASE_SCHEMA_READ}), contexts=frozenset({FILE_CONTEXT, PROFILE_CONTEXT})),
        TOOL_EXECUTE_SQL: ToolDefinition(
            actions=frozenset({
                FILE_METADATA_READ,
                ACCOUNT_READ,
                ACCOUNT_UPDATE,
            }),
            contexts=frozenset({FILE_CONTEXT, PROFILE_CONTEXT}),
        ),
    }
)

# Actions that can change state or trigger an external effect is defined as a side-effect

SIDE_EFFECT_ACTIONS = frozenset({FILE_DELETE, ACCOUNT_UPDATE})

ALL_CONTEXTS = frozenset({FILE_CONTEXT, PROFILE_CONTEXT})

ALL_RESOURCE_TYPES = frozenset({
    RESOURCE_TOOL,
    RESOURCE_FILE_COLLECTION,
    RESOURCE_FILE,
    RESOURCE_ACCOUNT,
    RESOURCE_DATABASE_SCHEMA,
})

ALL_ACTIONS = frozenset({
    TOOL_EXPOSE,
    FILE_LIST,
    FILE_SEARCH,
    FILE_READ,
    FILE_DELETE,
    DATABASE_SCHEMA_READ,
    FILE_METADATA_READ,
    ACCOUNT_READ,
    ACCOUNT_UPDATE,
})




def action_for_tool(tool_name: str, resolved_action: str | None = None) -> str | None:
    """Return the business action supported by a tool."""

    definition = TOOL_DEFINITIONS.get(tool_name)

    if definition is None:
        return None

    if resolved_action is not None:
        return resolved_action if resolved_action in definition.actions else None

    if len(definition.actions) == 1:
        return next(iter(definition.actions))

    return None



def tool_is_allowed_in_context(tool_name: str, context: str) -> bool:
    """Return True if a known tool is allowed in the selected context."""

    definition = TOOL_DEFINITIONS.get(tool_name)
    return definition is not None and context in definition.contexts


def is_side_effect_action(action: str) -> bool:
    """
    Return True if the action can change state or trigger an external effect.
    """
    return action in SIDE_EFFECT_ACTIONS

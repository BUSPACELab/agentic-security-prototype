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

# Used when the protected thing is the tool itself, usually for tool exposure.
RESOURCE_TOOL = "tool"
# Used when the protected thing is a collection of files, such as listing or searching inside a user's file collection
RESOURCE_FILE_COLLECTION = "file_collection"
# Used when the protected thing is a specific file
RESOURCE_FILE = "file"
# Used when the protected thing is a user account
RESOURCE_ACCOUNT = "account"


# Business actions used to define the action of an authorization request
TOOL_EXPOSE = "tool:expose"

FILE_LIST = "file:list"
FILE_SEARCH = "file:search"
FILE_READ = "file:read"
FILE_DELETE = "file:delete"


# LangChain / MCP tool names used to map to business actions
TOOL_LIST_FILES = "list_files"
TOOL_SEARCH_FILES = "search_files"
TOOL_READ_FILE = "read_file"
TOOL_DELETE_FILE = "delete_file"


# Define each tool's business action and allowed context in one place
@dataclass(frozen=True)
class ToolDefinition:
    action: str
    context: str


TOOL_DEFINITIONS = MappingProxyType(
    {
        TOOL_LIST_FILES: ToolDefinition(action=FILE_LIST, context=FILE_CONTEXT),
        TOOL_SEARCH_FILES: ToolDefinition(action=FILE_SEARCH, context=FILE_CONTEXT),
        TOOL_READ_FILE: ToolDefinition(action=FILE_READ, context=FILE_CONTEXT),
        TOOL_DELETE_FILE: ToolDefinition(action=FILE_DELETE, context=FILE_CONTEXT),
    }
)

# Actions that can change state or trigger an external effect is defined as a side-effect
SIDE_EFFECT_ACTIONS = frozenset(
    {
        FILE_DELETE,
    }
)

ALL_CONTEXTS = frozenset({FILE_CONTEXT, PROFILE_CONTEXT})
ALL_RESOURCE_TYPES = frozenset({RESOURCE_TOOL, RESOURCE_FILE_COLLECTION, RESOURCE_FILE, RESOURCE_ACCOUNT})
ALL_ACTIONS = frozenset({TOOL_EXPOSE, FILE_LIST, FILE_SEARCH, FILE_READ, FILE_DELETE})


def action_for_tool(tool_name: str) -> str | None:
    """
    Return the business action for a tool name.

    Unknown tools return None and should be denied by the policy engine.
    """
    definition = TOOL_DEFINITIONS.get(tool_name)
    return definition.action if definition is not None else None


def tool_is_allowed_in_context(tool_name: str, context: str) -> bool:
    """Return True if a known tool is allowed in the selected context."""

    definition = TOOL_DEFINITIONS.get(tool_name)
    return definition is not None and definition.context == context


def is_side_effect_action(action: str) -> bool:
    """
    Return True if the action can change state or trigger an external effect.
    """
    return action in SIDE_EFFECT_ACTIONS

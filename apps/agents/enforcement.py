"""
Tool invocation enforcement for the agent.

This module is the action-layer Policy Enforcement Point (PEP).

It controls whether a selected tool call is allowed to execute before
selected_tool.invoke(...). The policy decision is made by the application
authorization engine.
"""

from dataclasses import dataclass
from typing import Any

from apps.authorization.actions import *
from apps.authorization.audit import audit_decision
from apps.authorization.engine import authorize
from apps.authorization.types import AuthorizationRequest, Decision, Principal, RequestContext, Resource
from apps.authorization.sql_validation import inspect_sql, SQLValidationError, READ_COLUMNS
from apps.files.models import UploadedFile
from apps.agents.tooling import principal_from_user

from mcp_client.path_helpers import resolve_user_file_path

# This class is used to return the result of authorizing a tool call, including whether it is allowed, any safe arguments to use for the tool call, and a message explaining the decision
@dataclass(frozen=True)
class ToolCallAuthorization:
    """
    Result of authorizing a selected tool call before execution.
    
    allowed: Whether the tool call is allowed to execute.
    safe_args: Trusted arguments to use for the tool call if allowed.
    message: Explanation of the authorization decision.
    decision: The authorization decision.
    """

    allowed: bool
    safe_args: dict[str, Any]
    message: str
    decision: Decision | None = None


def file_collection_resource(principal: Principal) -> Resource:
    """
    Build the current user's file collection resource.

    This is used for tool calls that operate on the user's file collection, such as listing or searching files.
    """

    if principal.id is None:
        return Resource(type=RESOURCE_FILE_COLLECTION)

    return Resource(
        type=RESOURCE_FILE_COLLECTION,
        # There is no database row for "all files owned by this user", so this is a virtual resource id
        id=f"user-files:{principal.id}",
        owner_id=principal.id,
    )


def file_resource(principal: Principal, args: dict[str, Any]) -> Resource:
    """
    Build a file resource from a trusted UploadedFile database record.

    The path argument is only used to find the database record. The resource id
    and owner id come from the database.
    """

    # Find the database record using the provided path
    path = str(args.get("path", "")).strip()

    # First try to identify an explicitly requested canonical DB path
    uploaded_file = UploadedFile.objects.filter(file=path).first()

    # If no database record was found, try to resolve the file path to a canonical DB path under the signed-in user
    if uploaded_file is None:
        resolved = resolve_user_file_path(path, principal.id, allow_root=False)

        # If the file path could not be resolved, return an unknown resource bc it could be invalid or none 
        if resolved is None:
            return Resource(type=RESOURCE_FILE)

        database_path, _mcp_path = resolved
        uploaded_file = UploadedFile.objects.filter(file=database_path).first()

    # If no database record was found return an unknown resource
    if uploaded_file is None:
        return Resource(type=RESOURCE_FILE)

    # If a database record was found, return a resource representing that file
    return Resource(
        # The resource type is always "file"
        type=RESOURCE_FILE,
        # The resource id is the database uploaded file id
        id=str(uploaded_file.id),
        # The resource owner id is the database uploaded file owner id
        owner_id=str(uploaded_file.owner_id),
        # The resource attributes include the file path and title (additional attributes)
        attributes={
            "stored_path": str(uploaded_file.file),
            "title": uploaded_file.title,
        },
    )


def account_resource(principal: Principal) -> Resource:
    """Build the current user's account resource."""

    if principal.id is None:
        return Resource(type=RESOURCE_ACCOUNT)

    return Resource(
        type=RESOURCE_ACCOUNT,
        id=principal.id,
        owner_id=principal.id,
    )


def sql_resource(principal: Principal, action: str | None) -> Resource:
    """Determine the protected resource for a SQL operation."""

    if action == FILE_METADATA_READ:
        return file_collection_resource(principal)

    if action in {ACCOUNT_READ, ACCOUNT_UPDATE}:
        return account_resource(principal)

    return Resource(type="unknown")


def resource_for_tool_call(principal: Principal, tool_name: str, args: dict[str, Any], action: str | None = None) -> Resource:
    """Build the protected resource for a tool invocation."""

    # Three types of resources are supported: file collection, file, and account. The resource type is determined by the tool being called

    # if the tool is one that operates on the user's file collection, return a file collection resource
    if tool_name in {TOOL_LIST_FILES, TOOL_SEARCH_FILES}:
        return file_collection_resource(principal)

    # if the tool is one that operates on a specific file, return a file resource
    if tool_name in {TOOL_READ_FILE, TOOL_DELETE_FILE}:
        return file_resource(principal, args)

    # if the tool is to get the database schema, return a database schema resource
    if tool_name == TOOL_GET_DATABASE_SCHEMA:
        return Resource(type=RESOURCE_DATABASE_SCHEMA, id="database-schema")

    # if the tool is to execute SQL, return a SQL resource and the resource type is determined by the action being performed since sql execution can operate on multiple resource types (file collection, account, etc.)
    if tool_name == TOOL_EXECUTE_SQL:
        return sql_resource(principal, action)

    # if the tool is unknown, return an unknown resource
    return Resource(type="unknown")

def filter_tool_result(context, name, result):
    if name != TOOL_GET_DATABASE_SCHEMA:
        return result

    table = {"file": "files_uploadedfile", "profile": "auth_user"}.get(context)
    if not table or not isinstance(result, str):
        return "Schema unavailable."

    schema = next((s for s in result.splitlines() if s.startswith(f'CREATE TABLE "{table}" (')), "")
    columns = READ_COLUMNS[table]

    if not schema or any(f'"{col}" ' not in schema for col in columns):
        return "Schema unavailable."

    return f"Table: {table}\nColumns: {', '.join(sorted(columns))}"

# This function is used to build trusted arguments for a tool call to prevent the agent from passing untrusted arguments to the tool. It takes the tool name, the original arguments, and the resource being accessed, and returns a dictionary of safe arguments to use for the tool call
def safe_args_for_tool_call(tool_name: str, args: dict[str, Any], resource: Resource) -> dict[str, Any]:
    """Build trusted tool arguments after authorization."""

    # if the tool is one that operates on a specific file, return the stored_path attribute from the resource as the safe argument
    if tool_name in {TOOL_READ_FILE, TOOL_DELETE_FILE}:
        # The stored_path attribute is the path to the file on disk, which is a trusted value from the database
        # This prevents the agent from passing an untrusted path to the tool
        stored_path = resource.attributes.get("stored_path")

        # If the stored_path attribute is present, return it as the safe argument
        if stored_path:
            return {"path": stored_path,}

    # Otherwise, return the original arguments bc the tool does not require any special handling for safe arguments
    return dict(args)


def authorize_tool_invocation(user: Any, context: str, tool_name: str, args: dict[str, Any]) -> ToolCallAuthorization:
    """Authorize a selected tool invocation before execution."""

    
    # Convert the Django user to a principal
    principal = principal_from_user(user)

    # Resolve the business action and prepare safe arguments
    if tool_name == TOOL_EXECUTE_SQL:
        try:
            operation = inspect_sql(args.get("query"), context, principal.id)
        except SQLValidationError:
            return ToolCallAuthorization(allowed=False,safe_args={},message="The SQL query is not allowed.")

        action = action_for_tool(tool_name, operation.action)
        args = {"query": operation.safe_query}

    else:
        action = action_for_tool(tool_name)


    # If the business action is unknown, deny the tool call
    if action is None:
        return ToolCallAuthorization(
            allowed=False,
            safe_args={},
            message="I can't perform that action.",
        )

    # Build the protected resource
    resource = resource = resource_for_tool_call(principal=principal, tool_name=tool_name, args=args, action=action)

    # Build the authorization request
    request = AuthorizationRequest(
        principal=principal,
        action=action,
        resource=resource,
        context=RequestContext(name=context, tool=tool_name),
    )

    # Ask the policy decision engine to make the decision
    decision = authorize(request)

    # Audit the decision for accountability and traceability
    audit_decision(request, decision)

    # If the decision is not allowed, deny the tool call
    if not decision.allowed:
        # --- DEBUGGING ---
        print(f"[SECURITY][ENFORCEMENT] Blocked action={request.action!r} for principal={request.principal.id!r}: {decision.code}")
        return ToolCallAuthorization(
            allowed=False,
            safe_args={},
            message="The application did not allow this request.",
            decision=decision,
        )
    
    # If the decision is allowed, return the safe arguments for the tool call and a message indicating that the tool call is allowed
    return ToolCallAuthorization(
        allowed=True,
        safe_args=safe_args_for_tool_call(
            tool_name=tool_name,
            args=args,
            resource=resource,
        ),
        message="Allowed.",
        decision=decision,
    )

"""
3. Policy/Authorization Layer/Policies
Declarative policy definitions for the policy layer.

These are used by the authorization engine to make authorization decisions.
could be moved to a YAML file in the future for ease of maintenance. 

Policy model:
- Default deny is handled by the engine.
- Explicit deny overrides permit.
- Permit policies grant specific allowed behavior.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import FrozenSet

from .actions import (
    ALL_ACTIONS,
    ALL_CONTEXTS,
    ALL_RESOURCE_TYPES,
    FILE_DELETE,
    FILE_LIST,
    FILE_READ,
    FILE_SEARCH,
    FILE_CONTEXT,
    PROFILE_CONTEXT,
    RESOURCE_ACCOUNT,
    RESOURCE_FILE,
    RESOURCE_FILE_COLLECTION,
    RESOURCE_TOOL,
    TOOL_EXPOSE,
    action_for_tool,
    tool_is_allowed_in_context,
)
from .types import AuthorizationRequest, Effect


# This helps letting us use the short name Condition for any function that receives an AuthorizationRequest and returns True or False
Condition = Callable[[AuthorizationRequest], bool]


@dataclass(frozen=True)
class Policy:
    """
    One authorization policy.

    Attributes:
        id: Stable policy identifier for audit/testing.
        effect: permit or deny.
        actions: Business actions this policy applies to.
        resource_type: Resource type this policy applies to.
        contexts: Chat contexts this policy applies to.
        condition: Additional ABAC condition.
    """

    id: str
    effect: Effect
    actions: FrozenSet[str]
    resource_type: str
    contexts: FrozenSet[str]
    condition: Condition

    def matches(self, request: AuthorizationRequest) -> bool:
        """
        Return True if this policy applies to the authorization request.
        """
        return (
            request_is_consistent(request)
            and request.action in self.actions
            and request.resource.type == self.resource_type
            and request.context.name in self.contexts
            and self.condition(request)
        )


# This is mainly to prevent cases like: tool = "delete_file" while action = "file:read" and ensure the request is consistent 
def request_is_consistent(request: AuthorizationRequest) -> bool:
    """Return True when trusted request fields describe the same operation."""

    if request.action == TOOL_EXPOSE:
        return request.context.tool is not None and request.resource.id == request.context.tool

    return request.context.tool is not None and action_for_tool(request.context.tool) == request.action


def is_authenticated(request: AuthorizationRequest) -> bool:
    """Return True if the user is authenticated."""
    return request.principal.authenticated and request.principal.id is not None


def owns_resource(request: AuthorizationRequest) -> bool:
    """Return True if the user owns the resource."""
    return (
        is_authenticated(request)
        and request.resource.owner_id is not None
        and request.resource.owner_id == request.principal.id
    )


def owns_account(request: AuthorizationRequest) -> bool:
    """Return True if the user owns the account."""
    return owns_resource(request) 


def is_file_tool(request: AuthorizationRequest) -> bool:
    """Return True if the resource is a file tool."""
    return (
        is_authenticated(request)
        and request.resource.id is not None
        and tool_is_allowed_in_context(request.resource.id, FILE_CONTEXT)
    )


def is_profile_tool(request: AuthorizationRequest) -> bool:
    """Return True if the resource is a profile tool."""
    return (
        is_authenticated(request)
        and request.resource.id is not None
        and tool_is_allowed_in_context(request.resource.id, PROFILE_CONTEXT)
    )


# This is the list of policies used by the authorization engine to make authorization decisions
POLICIES: tuple[Policy, ...] = (
    # Tool exposure policies before the tool is invoked

    # 1. In the file context only expose file tools, so no one can invoke profile tools in the file context
    Policy(
        id="expose-file-tools-in-file-context",
        effect=Effect.PERMIT,
        actions=frozenset({TOOL_EXPOSE}),
        resource_type=RESOURCE_TOOL,
        contexts=frozenset({FILE_CONTEXT}),
        condition=is_file_tool,
    ),

    # 2. In the profile context only expose profile tools, so no one can invoke file tools in the profile context
    Policy(
        id="expose-profile-tools-in-profile-context",
        effect=Effect.PERMIT,
        actions=frozenset({TOOL_EXPOSE}),
        resource_type=RESOURCE_TOOL,
        contexts=frozenset({PROFILE_CONTEXT}),
        condition=is_profile_tool,
    ),

    # File resource policies.
    # These are used later before tool invocation and at the resource boundary.
    # 3. Owner may list its own files
    Policy(
        id="owner-may-list-files",
        effect=Effect.PERMIT,
        actions=frozenset({FILE_LIST}),
        resource_type=RESOURCE_FILE_COLLECTION,
        contexts=frozenset({FILE_CONTEXT}),
        condition=owns_resource,
    ),

    # 4. Owner may search its own files
    Policy(
        id="owner-may-search-files",
        effect=Effect.PERMIT,
        actions=frozenset({FILE_SEARCH}),
        resource_type=RESOURCE_FILE_COLLECTION,
        contexts=frozenset({FILE_CONTEXT}),
        condition=owns_resource,
    ),

    # 5. Owner may read its own files
    Policy(
        id="owner-may-read-file",
        effect=Effect.PERMIT,
        actions=frozenset({FILE_READ}),
        resource_type=RESOURCE_FILE,
        contexts=frozenset({FILE_CONTEXT}),
        condition=owns_resource,
    ),

    # 6. Owner may delete its own files
    Policy(
        id="owner-may-delete-file",
        effect=Effect.PERMIT,
        actions=frozenset({FILE_DELETE}),
        resource_type=RESOURCE_FILE,
        contexts=frozenset({FILE_CONTEXT}),
        condition=owns_resource,
    ),

)


def validate_policies(policies: tuple[Policy, ...]) -> None:
    """Raise ValueError when policy definitions contain invalid values."""

    policy_ids = [policy.id for policy in policies]
    if len(policy_ids) != len(set(policy_ids)):
        raise ValueError("Policy IDs must be unique.")

    for policy in policies:
        if not policy.id:
            raise ValueError("Policy ID cannot be empty.")
        if policy.effect not in Effect:
            raise ValueError(f"Policy {policy.id} contains an invalid effect.")
        if not policy.actions or not policy.actions <= ALL_ACTIONS:
            raise ValueError(f"Policy {policy.id} contains invalid actions.")
        if policy.resource_type not in ALL_RESOURCE_TYPES:
            raise ValueError(f"Policy {policy.id} contains an invalid resource type.")
        if not policy.contexts or not policy.contexts <= ALL_CONTEXTS:
            raise ValueError(f"Policy {policy.id} contains invalid contexts.")
        if not callable(policy.condition):
            raise ValueError(f"Policy {policy.id} must define a callable condition.")


validate_policies(POLICIES)

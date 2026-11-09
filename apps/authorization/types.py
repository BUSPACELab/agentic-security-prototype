"""
1. Policy/Authorization Layer/Types
Typed authorization objects for the policy layer.

This module defines the standard authorization request shape used by
the application-level policy engine.

The model follows the common PARC structure:

    Principal + Action + Resource + Context -> Decision

Definitions:
- Principal: the actor, usually Django request.user
- Action: the business action, such as file:read or file:delete
- Resource: the protected object, such as a file or account - the object being accessed by the action
- Context: the environment, such as file chat or profile chat
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

# This class is used to define the effect of an action on a resource
class Effect(StrEnum):
    """
    Effect of an action on a resource.
    """
    PERMIT = "permit"
    DENY = "deny"


# These classes are used to define the authorization request shape used by the policy engine 
# They are frozen so they can't be modified to enforce immutability and type checking
@dataclass(frozen=True)
class Principal:
    """
    The actor requesting an action.

    In this project, the principal should be derived from Django request.user.
    """
    id: str | None
    authenticated: bool
    email: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Resource:
    """
    The object being accessed.

    Examples:
    - A file owned by a user
    - A user account
    - A tool being exposed to the LLM
    """

    type: str
    id: str | None = None
    owner_id: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RequestContext:
    """
    Extra authorization context.

    Examples:
    - name: file or profile
    - tool: read_file, delete_file
    """

    name: str
    tool: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthorizationRequest:
    """
    Full authorization request evaluated by the policy engine.
    """

    principal: Principal
    action: str
    resource: Resource
    context: RequestContext


@dataclass(frozen=True)
class Decision:
    """
    Authorization decision returned by the policy engine.
    """

    allowed: bool
    reason: str
    code: str
    policy_ids: tuple[str, ...] = ()

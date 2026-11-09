"""
Application-controlled confirmation for side-effect actions.

An allowed side-effect tool call is stored in the Django session and only
executes after the user sends an explicit confirmation command.
"""

from typing import Any

from apps.authorization import actions

from . import enforcement, tooling

# The key used to store the pending side effect in the Django session
PENDING_SIDE_EFFECT_KEY = "pending_side_effect"

# Commands to confirm or cancel the pending side effect
CONFIRM_COMMAND = "confirm"
CANCEL_COMMAND = "cancel"


def request_confirmation_if_needed(user: Any, context: str, session: Any, tool_name: str, safe_args: dict[str, Any]) -> str | None:
    """
    Store an allowed side effect and return a confirmation message.

    Return None for tools that do not have a side effect.
    """

    # get the business action for the selected tool
    action = actions.action_for_tool(tool_name)

    # normal tools such as list, search, and read do not need confirmation
    if action is None or not actions.is_side_effect_action(action):
        return None

    # store the trusted tool call in the Django session
    session[PENDING_SIDE_EFFECT_KEY] = {
        "user_id": str(user.pk),
        "context": context,
        "tool_name": tool_name,
        "safe_args": dict(safe_args),
    }

    # show the exact file name without exposing the complete stored path
    if tool_name == actions.TOOL_DELETE_FILE:   
        filename = str(safe_args.get("path", "")).rsplit("/", 1)[-1] or "the selected file"
        return f'Deleting "{filename}" requires confirmation. Reply CONFIRM to continue or CANCEL to stop.'

    return "This action requires confirmation. Reply CONFIRM to continue or CANCEL to stop."


def handle_confirmation_message(user: Any, context: str, session: Any, message: str) -> str | None:
    """
    Handle CONFIRM or CANCEL before the message is sent to the LLM.

    Return None when the message is a normal new request.
    """

    command = message.strip().casefold()
    pending = session.get(PENDING_SIDE_EFFECT_KEY)

    if command == CONFIRM_COMMAND:
        return confirm_pending_side_effect(user, context, session)

    if command == CANCEL_COMMAND:
        if clear_pending_side_effect(session):
            return "The pending action was cancelled."

        return "There is no pending action to cancel."

        # while an action is pending, do not send other messages to the LLM
    if isinstance(pending, dict):
        return "Wrong command. Reply CONFIRM to continue or CANCEL to stop."
    
    return None


def confirm_pending_side_effect(user: Any, context: str, session: Any) -> str:
    """Reauthorize and execute the pending side effect once."""

    pending = session.get(PENDING_SIDE_EFFECT_KEY)

    if not isinstance(pending, dict):
        return "There is no pending action to confirm."

    # confirmation must come from the same authenticated user
    if pending.get("user_id") != str(user.pk):
        clear_pending_side_effect(session)
        return "The pending action is no longer valid."

    # confirmation must happen in the same chat context
    if pending.get("context") != context:
        clear_pending_side_effect(session)
        return "The pending action is no longer valid in this chat."

    tool_name = pending.get("tool_name")
    safe_args = pending.get("safe_args")

    if not isinstance(tool_name, str) or not isinstance(safe_args, dict):
        clear_pending_side_effect(session)
        return "The pending action is no longer valid."

    # make sure the stored tool is still classified as a side effect
    action = actions.action_for_tool(tool_name)

    if action is None or not actions.is_side_effect_action(action):
        clear_pending_side_effect(session)
        return "The pending action is no longer valid."

    # apply the first PEP again and get only tools allowed in this context
    tools = tooling.get_tools_for_context(user, context)
    selected_tool = next((tool for tool in tools if tool.name == tool_name), None)

    if selected_tool is None:
        clear_pending_side_effect(session)
        return "The pending action is no longer available."

    # apply the second PEP again immediately before execution
    authorization = enforcement.authorize_tool_invocation(user, context, tool_name, safe_args)

    if not authorization.allowed:
        clear_pending_side_effect(session)
        return authorization.message

    try:
        # execute the exact trusted arguments that were stored earlier
        return str(selected_tool.invoke(authorization.safe_args))
    finally:
        # confirmation is valid for one execution only
        clear_pending_side_effect(session)


def clear_pending_side_effect(session: Any) -> bool:
    """Remove the pending side effect from the session."""

    return session.pop(PENDING_SIDE_EFFECT_KEY, None) is not None

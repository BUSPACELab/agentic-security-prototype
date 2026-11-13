"""Django integration for binding authenticated request security context."""

from inspect import iscoroutinefunction
from asgiref.sync import sync_to_async
from django.utils.decorators import sync_and_async_middleware
import json
from django.conf import settings

from security_system.context import Principal, SecurityContext, bind_security_context



def _request_security_context(request) -> SecurityContext | None:
    """Build a security context from the authenticated Django request.

    Args:
        request: The Django request object.

    Returns:
        SecurityContext | None
    """

    # Get the authenticated user from Django 
    # Requires Django authentication and session middleware.
    user = request.user

    # Return None if the user is not authenticated
    if not user.is_authenticated:
        return None

    # Get optional application-defined security attributes
    provider = getattr(settings, "SECURITY_CONTEXT_ATTRIBUTES", None)

    if provider is not None and not callable(provider):
        raise TypeError("SECURITY_CONTEXT_ATTRIBUTES must be callable.")

    attributes = provider(request) if provider is not None else {}

    if not isinstance(attributes, dict) or not all(isinstance(key, str) for key in attributes):
        raise TypeError("Security attributes must be a dictionary with string keys.")

    try:
        json.dumps(attributes)
    except (TypeError, ValueError) as error:
        raise TypeError("Security attributes must be JSON-serializable.") from error

    # Create the System context using Django's trusted user identity and optional attributes
    return SecurityContext(principal=Principal(subject=str(user.pk), issuer="django"), attributes=attributes)



@sync_and_async_middleware
def security_context_middleware(get_response):
    """Bind the authenticated user's security context during a Django request.

    Args:
        get_response: Django's callable for the next middleware or view.

    Returns:
        callable: The synchronous or asynchronous middleware function.
    """

    # Handle asynchronous requests
    if iscoroutinefunction(get_response):

        async def middleware(request):
            # Build the context safely without synchronous database access in the event loop
            context = await sync_to_async(_request_security_context)(request)

            # Continue without a context if the user is not authenticated
            if context is None:
                return await get_response(request)

            # Bind the context during request processing
            with bind_security_context(context):
                print("APP principal:", context.principal.subject)
                return await get_response(request)

    # Handle synchronous requests
    else:

        def middleware(request):
            # Build the context from the authenticated Django request
            context = _request_security_context(request)

            # Continue without a context if the user is not authenticated
            if context is None:
                return get_response(request)

            # Bind the context during request processing
            with bind_security_context(context):
                print("APP principal:", context.principal.subject)
                return get_response(request)

    return middleware
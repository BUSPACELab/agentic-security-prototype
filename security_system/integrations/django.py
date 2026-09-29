"""Django integration for binding authenticated request security context."""

from asgiref.sync import iscoroutinefunction
from django.utils.decorators import sync_and_async_middleware

from security_system.context import Principal, SecurityContext, bind_security_context


def _request_security_context(request) -> SecurityContext | None:
    """Build a security context for one authenticated Django request."""

    user = getattr(
        request,
        "user",
        None,
    )

    if not bool(
        getattr(
            user,
            "is_authenticated",
            False,
        )
    ):
        return None

    session = getattr(
        request,
        "session",
        None,
    )

    session_id = getattr(
        session,
        "session_key",
        None,
    )

    return SecurityContext(
        principal=Principal(
            subject=str(user.pk),
            issuer="django",
        ),
        session_id=session_id,
    )


@sync_and_async_middleware
def security_context_middleware(get_response):
    """Bind authenticated request identity to the current execution."""

    if iscoroutinefunction(get_response):

        async def middleware(request):
            context = _request_security_context(
                request
            )

            if context is None:
                return await get_response(
                    request
                )

            with bind_security_context(
                context
            ):
                return await get_response(
                    request
                )

    else:

        def middleware(request):
            context = _request_security_context(
                request
            )

            if context is None:
                return get_response(
                    request
                )

            with bind_security_context(
                context
            ):
                print("APP principal:", context.principal.subject)
                return get_response(
                    request
                )

    return middleware
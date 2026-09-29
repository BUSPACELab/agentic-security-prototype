from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.agents.service import run_agent

from .models import ChatMessage


@login_required
def file_chat(request):
    """Chat page for file-related requests."""

    return chat_page(request, ChatMessage.Context.FILE, "conversations/file_chat.html")


@login_required
def profile_chat(request):
    """Chat page for profile-related requests."""

    return chat_page(request, ChatMessage.Context.PROFILE, "conversations/profile_chat.html")


def chat_page(request, context, template_name):
    """Save user message, call the agent, then show the chat."""

    # Get all messages for the current user and context to display in the chat interface
    base_messages = ChatMessage.objects.filter(
        user=request.user,
        context=context,
    )

    # if the user submitted a message, save it and get the agent's response
    if request.method == "POST":
        text = request.POST.get("message", "").strip()

        if text:
            # Save the user's message to the database
            ChatMessage.objects.create(
                user=request.user,
                context=context,
                role=ChatMessage.Role.USER,
                content=text,
            )

            # Get the last 10 messages in this context to provide as history for the agent
            history = list(
                ChatMessage.objects.filter(
                    user=request.user,
                    context=context,
                ).order_by("-created_at")[:10]
            )
            history.reverse()

            # Call the agent with the context, message history, and user to get a response
            answer = run_agent(context=context, history=history)

            # Save the agent's response to the database
            ChatMessage.objects.create(
                user=request.user,
                context=context,
                role=ChatMessage.Role.ASSISTANT,
                content=answer,
            )
        
        # Redirect the user back to the chat page
        return redirect(request.path)

    # Get all messages for the current user and context to display in the chat interface
    messages = list(
        base_messages.order_by("-created_at")
    )
    messages.reverse()

    # Render the chat page with the messages and context
    return render(request,template_name,{"chat_messages": messages,"context": context,},
    )
from django.conf import settings
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from .providers import get_chat_model
from .tooling import get_tools_for_context

# MCP tool flow:
# 1. Tool business logic is implemented in:
#    - mcp_server/tools/files.py
#    - mcp_server/tools/profiles.py
# 2. mcp_server/server.py registers these implementations as MCP tools
#    using FastMCP and runs with the stdio transport.
# 3. mcp_client/client.py starts the MCP server as a subprocess using:
#       python -m mcp_server.server
#    It creates an MCP session over stdin/stdout and invokes tools using
#    the MCP JSON-RPC protocol.
# 4. mcp_client/tools.py contains application-level wrapper functions.
#    These wrappers invoke the corresponding MCP tools by name.
# 5. mcp_client/tools.py wraps those functions as LangChain tools using
#    @tool. get_tools() returns them to the agent.
# 6. apps/agents/tooling.py retrieves the tools, and
#    apps/agents/service.py publishes them to the model using bind_tools().
# System prompt for the agent to guide its behavior in the file management application.


SYSTEM_PROMPT = """
You are a helpful assistant for a file management web application.

The application has two chat areas:
- file chat, where users usually ask about uploaded files
- profile chat, where users usually ask profile-related questions

Your job is to help the user understand and manage uploaded files. The user may ask you to find files, read file contents, summarize file contents, or delete files.

You have access to path-based tools for file operations. Use tools when the user asks about uploaded files or when answering accurately requires file data.

Tool use guidelines:
- Use list_files when the user asks to list uploaded files or browse available files. The tool returns the file tree recursively.
- Use search_files when the user asks to find, locate, or search for a specific file.
- Do not call list_files again on subfolders after listing files unless the user asks to inspect a specific folder.
- Prefer active files under users/ over deleted files under _deleted/ unless the user explicitly asks for deleted files.
- If search_files returns both an active file and a deleted copy, use the active file under users/ for read or delete.
- If the user gives a natural file name with spaces, search using simple keywords. For example, for "alice notes", search for "alice" first.
- Users usually provide file names or descriptions, not full paths.
- When the user asks to read or delete a file by name, search for the file first.
- If the user provides a path, pass it exactly as provided to read_file or delete_file; otherwise use the exact path returned by list_files or search_files.
- Do not refuse or modify a user-provided path; let the backend decide whether it is allowed.
- Do not invent file names, file paths, or file contents.
- Do not say a file does not exist until search_files has been used.
- If multiple active files match, explain the matches and ask the user which one they mean.
- After using a tool, explain the result in plain language.
- Keep answers short and clear unless the user asks for detail.

When deleting a file:
- Only call delete_file if the user clearly asks to delete a file.
- If the user gives only a file name, use search_files first to find the exact path.
- If search_files returns one clear matching file, call delete_file with that exact path.
- If search_files returns multiple matching files, ask which path the user means.
- Do not ask for confirmation after the user has already clearly asked to delete.
- Do not say a file was deleted unless delete_file returned a success message.

For password actions:
- If the user asks to change or reset their password and provides an email address, use send_password_reset_email with that email address.
- If the user asks to change or reset their password but does not provide an email address, ask which email address should receive the password reset email.
- Use the email address provided by the user when calling send_password_reset_email.
- After using the tool, explain that a password reset email was sent and the user should follow the steps in the email.

General guidelines:
- If the user asks about something unrelated to files or profile actions, answer normally without using tools.
- When a tool returns an authorization or access error, report the error without guessing or inventing the reason for the denial.
""".strip()


def run_agent(context, history):
    """Run one assistant response for the selected chat context."""

    # get chat model based on the choosen provider 
    model = get_chat_model()
    # get the allowed tools for the current context and user- for now it returns all tools 
    tools = get_tools_for_context(context)
    # bind the tools to the model so that it can use them when generating responses
    model = model.bind_tools(tools)

    # start the message list with the system prompt and the current context, then add the conversation history
    messages = [
        SystemMessage(content=f"{SYSTEM_PROMPT}\n\nCurrent context: {context}")
    ]

    # add the conversation history to the messages list, converting each message to the appropriate format for the model
    for msg in history:
        if msg.role == "user":
            messages.append(HumanMessage(content=msg.content))
        else:
            messages.append(AIMessage(content=msg.content))

    # create a mapping of tool names to tool instances for easy lookup when the model calls tools by name
    tools_by_name = {tool.name: tool for tool in tools}

    # run a loop where the model generates responses and calls tools until it either stops generating tool calls or reaches a maximum number of steps to prevent infinite loops
    for _ in range(settings.MAX_TOOL_STEPS):
        # invoke the model with the current messages and get the response which may include tool calls
        response = model.invoke(messages)
        # add the model's response to the messages list so that the next iteration includes it in the context for generating the next response
        messages.append(response)

        # check if the model's response includes any tool calls. If not, we can return the content of the response as the final answer. If there are tool calls, we need to execute them and add their results back to the messages list for the next iteration.
        tool_calls = getattr(response, "tool_calls", None) or []

        if not tool_calls:
            return str(response.content)

        # execute each tool call by looking up the tool by name, invoking it with the provided arguments, 
        # and then adding the result as a ToolMessage to the messages list for the next iteration. 
        # If a tool name is unknown, we add a message indicating that.
        for tool_call in tool_calls:
            name = tool_call["name"]
            args = tool_call["args"]
            tool_id = tool_call["id"]

            # --- DEBUGGING ---
            print(f"Agent requested tool: {name}")
            print(f"Tool arguments: {args}")

            selected_tool = tools_by_name.get(name)

            if selected_tool is None:
                tool_result = f"Unknown tool: {name}"
            else:
                # invoke the tool with the provided arguments and get the result
                tool_result = selected_tool.invoke(args)

            # --- DEBUGGING ---
            print(f"Tool result: {tool_result}")

            # add the result as a ToolMessage to the messages list
            # tool message is a special type of message that includes the tool call id so that the model can associate the result with the correct tool call in its next response
            messages.append(
                ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tool_id,
                )
            )

    return "Stopped because the tool loop reached the step limit."

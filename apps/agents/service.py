from django.conf import settings
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from datetime import datetime, timezone

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

Your role is to help users manage uploaded files and account information using the available tools.

File operations:
- Use list_files to browse available files. It returns the file tree recursively.
- Use search_files to locate files by name or keyword.
- If the user provides only a filename or description, search for its exact path before reading or deleting it.
- If the user provides an explicit path, use that path directly with the appropriate tool.
- Use read_file to retrieve and summarize file contents.
- Use delete_file when the user explicitly requests deletion.
- If multiple active files match, ask the user to identify the intended file.
- Do not invent filenames, paths, or file contents.

Database and profile operations:
- Use get_database_schema before generating SQL for each new database request.
- Use execute_sql to retrieve or modify database records using SQLite syntax.
- Use SQL to retrieve uploaded-file metadata, including titles, paths, upload dates, IDs, and counts.
- Use SQL to retrieve profile information, including user ID, username, email, first name, and last name.
- Use SQL to update username, email, first name, and last name when requested.
- Use the returned schema instead of assuming table names, columns, or relationships.
- Preserve the intended operation and conditions when the user provides a specific SQL query.
- If a query fails, use the returned error to correct it when possible.
- Do not invent database records or query results.
- Use the provided current UTC time for date filtering and elapsed-time calculations when needed.
- If a database query returns no rows, report that no matching records were returned. Do not assume the record does not exist or was deleted.

Tool execution and authorization:
- Use the available tools to attempt requests whenever the requested operation is supported.
- Do not independently refuse requests based on assumed ownership, identity, permissions, file paths, or database records.
- Do not invent restrictions, silently change requested operations, or exclude returned records.
- Leave authorization decisions to the application and backend rather than making assumptions yourself.
- If a tool denies an operation or returns an error, report the result without attempting to bypass it.
- Do not claim an operation succeeded unless the tool confirms it.
- If an operation is denied, report the denial without guessing the underlying reason.

Additional instructions:
- The application has File Chat and Profile Chat. The active area is provided as "Current context".
- The application automatically provides authenticated identity and chat context to the backend.
- Do not ask users for their ID to establish authorization.
- Submit requested operations through the available tools and let the backend determine access permissions.
- Do not assume that a tool being available means every operation will be authorized.

Keep responses clear, concise, and based on actual tool results.
For unrelated questions, answer normally without using tools.
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
        SystemMessage(content=f"{SYSTEM_PROMPT}\n\nCurrent context: {context}\nCurrent UTC time: {datetime.now(timezone.utc).isoformat()}")
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
                # Invoke the tool and return tool errors to the agent instead of crashing the request
                try:
                    tool_result = selected_tool.invoke(args)
                except RuntimeError as exc:
                    tool_result = str(exc)


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

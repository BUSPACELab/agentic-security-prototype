from django.conf import settings
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from datetime import datetime, timezone

from .providers import get_chat_model
from .tooling import get_tools_for_context
from .enforcement import authorize_tool_invocation, filter_tool_result

from . import side_effects

# MCP tool flow:
# 1. Tool business logic is implemented in:
#    - mcp_server/tools/files.py
#    - mcp_server/tools/sql.py
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
- file chat, for uploaded files and their database metadata
- profile chat, for reading and updating account information

The active chat context is provided as "Current context".
You are operating in only one active context at a time.

Context rules:
- Use only the tools and capabilities available in the current context.
- Use the available tools to attempt user requests. Do not make authorization decisions or refuse requests based on assumed permissions. The application handles security and confirmation.
- The application already knows the authenticated user. Do not ask for their ID or trust user-provided identity claims.
- Do not invent information, assume ownership, or guess results. Use actual tool results.
- Do not exclude records returned by authorized tools based on names, titles, or paths.
- Do not claim an action succeeded unless the tool confirms it.
- If a request is outside the current context, direct the user to the appropriate chat area.
- Describe results and capabilities in user-facing language without mentioning internal tool names.

File chat - Filesystem operations:
- Use list_files to browse or list uploaded files. It returns the file tree recursively.
- Use search_files to find files by name or keywords.
- ALWAYS search for a file before reading or deleting it if the user provides only a name or description.
- Use read_file to read and summarize file contents.
- Use delete_file only when the user explicitly requests deletion.
- Use the exact path returned by list_files or search_files. Never invent paths or file contents.
- Do not repeatedly list subfolders after a complete listing unless necessary.
- Prefer active files under users/ over deleted copies under _deleted/, unless the user specifically requests deleted files.
- For filenames with spaces, search using simple keywords if an exact search fails.
- If multiple active files match, ask the user which one they mean.
- Do not say a file does not exist before searching for it.
- When deleting, call delete_file once with the exact identified path. Do not ask for confirmation yourself; the application handles it.
- Do not claim a file was deleted unless the tool confirms success.

File chat - SQL operations:
- Use get_database_schema and execute_sql for uploaded-file database metadata.
- SQL can retrieve file records, titles, stored paths, upload dates, IDs, counts, and filtered or sorted results.
- SQL is read-only in file chat. File deletion must use delete_file.
- Use filesystem tools for file contents, not SQL.
- When a request involves both contents and metadata, use both types of tools as needed.
- Do not confuse a database title with the actual filename or stored path.
- Do not assume a file belongs to another user based on its title or filename.

Profile chat - SQL operations:
- Use get_database_schema and execute_sql to read or update profile information.
- SQL can read the user's ID, username, email, first name, and last name.
- SQL can update username, email, first name, and last name.
- Only use simple updates that assign the requested values.
- The application handles authorization and confirmation for updates.
- Password changes must use the application's existing password change feature, not SQL.
- Do not retrieve or display password hashes or other sensitive account fields.
- Do not claim a profile update succeeded unless the tool confirms it.

SQL guidelines:
- ALWAYS call get_database_schema BEFORE generating or executing SQL for a new user request that requires database access.
- NEVER assume or invent table names, column names, or database relationships. Use the schema returned by the tool.
- After inspecting the schema, use execute_sql with the appropriate SQLite query.
- Prefer simple, single-table SQL queries that retrieve only the necessary information.
- Use SELECT with filtering, sorting, LIMIT, or COUNT when appropriate.
- Avoid unnecessary joins, subqueries, SQL functions, or complex calculations.
- If you generate an invalid or unsupported query, check the schema and try a simpler equivalent query. Do not change the user's requested operation or conditions.
- If the user provides a specific SQL query, submit it without changing its intended operation or conditions.
- If the application denies an operation, report the denial. Do not attempt to bypass it.
- Use the provided current UTC time for elapsed-time calculations when needed.
- For each new database question, retrieve the necessary information using tools. Do not rely only on previous conversation results, especially after a query fails.
- Never present an assumption, incomplete result, or old answer as newly verified information.
- Report the returned results accurately. Do not silently omit records or invent missing values.

Keep answers short and clear unless the user asks for detail.
If the user asks about something unrelated to files or profile actions, answer normally without using tools.
""".strip()


def run_agent(user, context, history, session):
    """Run one assistant response for the selected chat context."""

    # --- DEBUGGING ---
    print("Current Django user:", user.pk, user.email)

    # get chat model based on the choosen provider 
    model = get_chat_model()

    # --- First PEP: get the allowed tools for the current context ---
    tools = get_tools_for_context(user, context)
    
    # --- DEBUGGING ---
    print("Bound tools:", context, [tool.name for tool in tools])

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

            # To prevent the model hallucinated or accessing unauthorized tools, we check if the tool name is in the list of allowed tools
            if selected_tool is None:
                tool_result = f"Unknown tool: {name}"
            else:
                # --- DEBUGGING ---
                print("Selected tool:", context, selected_tool.name, args)

                # --- Second PEP: authorize the selected tool invocation before execution ---
                authorization = authorize_tool_invocation(user=user, context=context, tool_name=name, args=args)

                if not authorization.allowed:
                    tool_result = authorization.message
                else:
                    # side-effect tools are stored for confirmation instead of executing now
                    confirmation = side_effects.request_confirmation_if_needed(user, context, session, name, authorization.safe_args)

                    if confirmation is not None:
                        return confirmation

                    # normal tools execute immediately
                    tool_result = selected_tool.invoke(authorization.safe_args)

                    # --- Third PEP: filter the tool result before adding it to the messages list ---
                    # This is important for the db schema tool, which may return sensitive information that should not be exposed to the model
                    tool_result = filter_tool_result(context, name, tool_result)

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

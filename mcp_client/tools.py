from django.conf import settings
from langchain_core.tools import tool

from apps.files.models import UploadedFile

from .client import call_custom_mcp_tool



def list_files(user_id: int | str, path: str = "") -> str:
    """List files through the custom MCP server."""

    # If no path is provided, default to the user's files
    path = path or f"users/{user_id}"

    return call_custom_mcp_tool("list_files",{"path": path, "user_id": user_id})


def search_files(query: str, user_id: int | str) -> str:
    """Search files through the custom MCP server."""

    path = f"users/{user_id}"

    return call_custom_mcp_tool("search_files", {"path": path, "query": query, "user_id": user_id})


def read_file(path: str, user_id: int | str) -> str:
    """Read a file through the custom MCP server."""

    return call_custom_mcp_tool("read_file",{"path": path, "user_id": user_id})


def delete_file(path: str, user_id: int | str) -> str:
    """Delete a file through the custom MCP server."""

    # Call the delete_file tool from the custom MCP server
    call_custom_mcp_tool("delete_file", {"path": path, "user_id": user_id})

    # Delete the file from the database as well
    UploadedFile.objects.filter(owner_id=user_id, file=str(path).replace(str(settings.MCP_FILESYSTEM_ROOT) + "/", "").lstrip("/")).delete()

    return f"Deleted {path}"

def send_password_reset_email(
    email: str,
    domain: str = "localhost:8000",
    use_https: bool = False,
) -> str:
    """Send a password reset email through the custom MCP server."""

    # Send the password reset email using the custom MCP password reset tool
    return call_custom_mcp_tool("send_password_reset_email",{"email": email,"domain": domain,"use_https": use_https,},)


# These just to expose the above functions as tools to be used by the agent
@tool("send_password_reset_email")
def send_password_reset_email_tool(
    email: str,
    domain: str = "localhost:8000",
    use_https: bool = False,
) -> str:
    """Send a password reset email."""

    return send_password_reset_email(email, domain, use_https)


def get_tools(user_id: int | str):
    """Return the tools used by the agent."""

    @tool("list_files")
    def list_files_tool(path: str = "") -> str:
        """List uploaded files and folders by path."""

        return list_files(user_id, path)


    @tool("search_files")
    def search_files_tool(query: str) -> str:
        """Search uploaded files by filename pattern."""

        return search_files(query, user_id)

    @tool("read_file")
    def read_file_tool(path: str) -> str:
        """Read an uploaded file by path."""

        return read_file(path, user_id)

    @tool("delete_file")
    def delete_file_tool(path: str) -> str:
        """Delete an uploaded file by path."""

        return delete_file(path, user_id)

    return [
        list_files_tool,
        search_files_tool,
        read_file_tool,
        delete_file_tool,
        send_password_reset_email_tool,
    ]

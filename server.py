# imports
from mcp.server.fastmcp import FastMCP

# erstellt die Instanz für den MCP Server
mcp = FastMCP("Hello MCP")


# Funktion damit mcp - Server hello World zurrückgeben kann
@mcp.tool()
def hello_world(name: str = "World") -> str:
    """
    Say hello to someone.

    Args:
        name: The name of the person to greet. Defaults to "World".

    Returns:
        A friendly greeting string.
    """
    return f"Hello, {name}!"


# führt den Code aus / startet den mcp - Server
if __name__ == "__main__":
    mcp.run(transport="stdio")

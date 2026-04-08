# imports
from mcp.server.fastmcp import FastMCP
from datetime import datetime

# Startzeitpunkt der Session wird beim Start des Servers gespeichert
SESSION_START = datetime.now()

# erstellt die Instanz für den MCP Server
mcp = FastMCP("Hello MCP")

# Funktion damit mcp-Server hello World zurückgeben kann
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


# Funktion die zurückgibt wie lange die aktuelle Session schon läuft
@mcp.tool()
def get_session_duration() -> str:
    """
    Returns how long the current server session has been running.

    Returns:
        A string describing the session duration in hours, minutes and seconds.
    """
    # Aktuelle Zeit minus Startzeit = vergangene Zeit
    elapsed = datetime.now() - SESSION_START

    # Sekunden in Stunden, Minuten und Sekunden umrechnen
    total_seconds = int(elapsed.total_seconds())
    hours   = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    return f"Die Session läuft seit {hours}h {minutes}m {seconds}s."


# führt den Code aus / startet den mcp-Server
if __name__ == "__main__":
    mcp.run(transport="stdio")
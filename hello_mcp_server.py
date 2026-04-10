# imports
from mcp.server.fastmcp import FastMCP
from datetime import datetime
import subprocess
import platform
import urllib.request
import re

# Startzeitpunkt der Session wird beim Start des Servers gespeichert
SESSION_START = datetime.now()

# erstellt die Instanz für den MCP Server
mcp = FastMCP("Hello MCP")

@mcp.tool()
def get_session_duration() -> str:
    """
    Returns how long the current server session has been running.

    Returns:
        A string describing the session duration in hours, minutes and seconds.
    """
    elapsed = datetime.now() - SESSION_START

    total_seconds = int(elapsed.total_seconds())
    hours   = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    return f"Die Session läuft seit {hours}h {minutes}m {seconds}s."


@mcp.tool()
def ping_tool(host: str, count: int = 4) -> str:
    """
    Pingt eine Webseite oder IP-Adresse und gibt das Ergebnis zurück.

    Args:
        host: Die URL oder IP-Adresse die gepingt werden soll (z.B. 'www.google.de').
        count: Anzahl der Ping-Pakete. Standard: 4.

    Returns:
        Das Ergebnis des Pings als String.
    """
    param = "-n" if platform.system().lower() == "windows" else "-c"

    try:
        result = subprocess.run(
            ["ping", param, str(count), host],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,   # merge stderr into stdout
            timeout=15,
        )
        # Try UTF-8 first, fall back to system default (cp1252 on German Windows)
        try:
            output = result.stdout.decode("utf-8").strip()
        except UnicodeDecodeError:
            output = result.stdout.decode(errors="replace").strip()
        return output if output else "Kein Output erhalten."

    except subprocess.TimeoutExpired:
        return f"Timeout: {host} hat nicht innerhalb von 15 Sekunden geantwortet."
    except FileNotFoundError:
        return "Fehler: 'ping' wurde auf diesem System nicht gefunden."
    except Exception as e:
        return f"Unbekannter Fehler: {e}"


@mcp.tool()
def title_extractor(url: str) -> str:
    """
    Extrahiert den HTML-Titel (<title>) einer Webseite.

    Args:
        url: Die URL der Webseite (z.B. 'https://www.google.de').

    Returns:
        Der Titel der Webseite als String, oder eine Fehlermeldung.
    """
    # https:// ergänzen falls nicht vorhanden
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    try:
        # Seite abrufen – Browser User-Agent um Blockierungen zu vermeiden
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")

        # <title>...</title> aus dem HTML heraussuchen
        match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if match:
            title = match.group(1).strip()
            # Whitespace und Zeilenumbrüche bereinigen
            title = re.sub(r"\s+", " ", title)
            return f"Titel: {title}"
        else:
            return "Kein <title>-Tag auf dieser Seite gefunden."

    except urllib.error.HTTPError as e:
        return f"HTTP-Fehler {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return f"URL-Fehler: {e.reason}"
    except TimeoutError:
        return f"Timeout: {url} hat nicht innerhalb von 10 Sekunden geantwortet."
    except Exception as e:
        return f"Unbekannter Fehler: {e}"


# führt den Code aus / startet den mcp-Server
if __name__ == "__main__":
    mcp.run(transport="stdio")

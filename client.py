# mcp_client.py
# Verbesserte Version mit robustem Tool-Calling für NVIDIA NIM

import asyncio
import json
import re

from openai import AsyncOpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NVIDIA_API_KEY = "API KEY HIER EINFUEGEN"

# Path to your MCP server script
SERVER_SCRIPT = "hello_mcp_server.py"

# mistralai/Mistral-7B-Instruct-v0.3:
#   - Von NVIDIA offiziell als Beispielmodell für Multi-Tool-Calling dokumentiert
OPENAI_MODEL = "mistralai/mistral-7b-instruct-v0.3"

# System-Prompt: verhindert dass das Modell Tool-Syntax als Text ausgibt
SYSTEM_PROMPT = """You are a helpful assistant. You have access to tools/functions.
When you need to use a tool, use it via the function calling mechanism - NEVER write out tool calls as raw text or JSON in your response.
After receiving tool results, respond naturally and helpfully in the same language the user used.
Do not mention internal tool names or show JSON in your final response to the user."""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def mcp_tools_to_openai_schema(mcp_tools) -> list[dict]:
    """Convert MCP tool definitions into the format OpenAI expects."""
    openai_tools = []
    for tool in mcp_tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema,
            },
        })
    return openai_tools


async def call_mcp_tool(session: ClientSession, tool_name: str, tool_args: dict) -> str:
    """Call a tool on the MCP server and return a cleaned, shortened result."""
    result = await session.call_tool(tool_name, tool_args)
    text = result.content[0].text if result.content else "Kein Ergebnis."

    if len(text) > 700:
        text = text[:697] + "..."

    text = " ".join(text.split())
    return text


def build_assistant_tool_call_dict(assistant_message) -> dict:
    """
    Baut ein sauberes plain-dict für eine Assistant-Nachricht mit Tool-Calls.
    Setzt content nur wenn tatsächlich Text vorhanden ist.
    """
    tool_calls = [
        {
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments,
            },
        }
        for tc in assistant_message.tool_calls
    ]

    msg = {"role": "assistant", "tool_calls": tool_calls}

    if assistant_message.content:
        msg["content"] = assistant_message.content

    return msg


def clean_final_response(text: str) -> str:
    """
    Bereinigt die finale Antwort des Modells:
    Entfernt rohe [TOOL_CALLS]-Blöcke und JSON-Fragmente die das Modell
    versehentlich als Text ausgegeben hat.
    """
    # [TOOL_CALLS][...] Blöcke entfernen
    text = re.sub(r'\[TOOL_CALLS\]\s*\[.*?\]', '', text, flags=re.DOTALL)

    # Verbleibende JSON-Arrays die wie Tool-Calls aussehen entfernen
    text = re.sub(r'\[\s*\{"name":\s*"[^"]+?".*?\}\s*\]', '', text, flags=re.DOTALL)

    # Mehrfache Leerzeilen auf eine reduzieren
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


# ---------------------------------------------------------------------------
# Main chat loop
# ---------------------------------------------------------------------------

async def chat_loop(session: ClientSession, openai_client: AsyncOpenAI):
    """Interactive loop with improved tool handling for NVIDIA NIM."""

    tools_response = await session.list_tools()
    openai_tools = mcp_tools_to_openai_schema(tools_response.tools)
    print(f"[Connected] Tools available: {[t.name for t in tools_response.tools]}\n")

    # System-Prompt als erste Nachricht
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("Type your message (Ctrl+C to quit)\n")

    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        while True:
            try:
                response = await openai_client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=messages,
                    tools=openai_tools,
                    tool_choice="auto",
                    parallel_tool_calls=True,
                    max_tokens=1024,
                    temperature=0.7,
                )

                assistant_message = response.choices[0].message

                if assistant_message.tool_calls:
                    assistant_dict = build_assistant_tool_call_dict(assistant_message)
                    messages.append(assistant_dict)

                    for tool_call in assistant_message.tool_calls:
                        name = tool_call.function.name
                        args = json.loads(tool_call.function.arguments)

                        print(f"[Tool call] {name}({args})")

                        tool_result = await call_mcp_tool(session, name, args)
                        print(f"[Tool result] {tool_result}\n")

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result,
                        })

                    if len(messages) > 22:
                        system_msgs = [m for m in messages if m.get("role") == "system"]
                        other_msgs  = [m for m in messages if m.get("role") != "system"]
                        messages = system_msgs + other_msgs[-18:]
                        print("[Info] History wurde bereinigt.")

                else:
                    final_reply = assistant_message.content or "(Keine Antwort vom Modell)"
                    # Rohe Tool-Call-Syntax aus der Antwort entfernen
                    final_reply = clean_final_response(final_reply)
                    messages.append({"role": "assistant", "content": final_reply})
                    print(f"Assistant: {final_reply}\n")
                    break

            except Exception as e:
                print(f"\n[Fehler] OpenAI/NVIDIA NIM: {e}")
                print("Versuche es mit einer neuen Nachricht...\n")
                if messages and messages[-1].get("role") == "user":
                    messages.pop()
                break


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    openai_client = AsyncOpenAI(
        api_key=NVIDIA_API_KEY,
        base_url="https://integrate.api.nvidia.com/v1",
    )

    server_params = StdioServerParameters(
        command="python",
        args=[SERVER_SCRIPT],
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            await chat_loop(session, openai_client)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBye!")
    except Exception as e:
        print(f"\nUnerwarteter Fehler: {e}")

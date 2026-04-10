# ---------------------------------------------------------------------------
# imports
# ---------------------------------------------------------------------------

import asyncio
import json
import re
import uuid

from openai import AsyncOpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NVIDIA_API_KEY = "NVIDIA API KEY HIER EINFUEGEN"
SERVER_SCRIPT = "hello_mcp_server.py"
OPENAI_MODEL = "meta/llama-4-maverick-17b-128e-instruct"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def mcp_tools_to_openai_schema(mcp_tools) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema,
            },
        }
        for tool in mcp_tools
    ]


async def call_mcp_tool(session: ClientSession, tool_name: str, tool_args: dict) -> str:
    result = await session.call_tool(tool_name, tool_args)
    return result.content[0].text


def _flatten_value(v: any) -> any:
    """Rekursiv verschachtelte 'type/value' oder {'count': {...}} Strukturen auflösen."""
    if isinstance(v, dict):
        if "value" in v and len(v) <= 3:          # {"type": "integer", "value": 4}
            return v["value"]
        if len(v) == 1 and isinstance(next(iter(v.values())), dict):
            return _flatten_value(next(iter(v.values())))  # {'count': {'count': 4}}
        # normales Dict → rekursiv flatten
        return {k: _flatten_value(val) for k, val in v.items()}
    return v


def _parse_single_tool_entry(entry: dict | str) -> dict | None:
    if isinstance(entry, str):
        try:
            entry = json.loads(entry)
        except (json.JSONDecodeError, TypeError):
            return None

    if not isinstance(entry, dict):
        return None

    name = entry.get("name") or (entry.get("function") or {}).get("name")
    params = (
        entry.get("parameters")
        or entry.get("arguments")
        or entry.get("params")
        or (entry.get("function") or {}).get("parameters")
        or (entry.get("function") or {}).get("arguments")
        or {}
    )

    if name:
        # Wichtig: verschachtelte Strukturen flach machen
        if isinstance(params, dict):
            params = {k: _flatten_value(v) for k, v in params.items()}
        return {"name": name, "args": params}

    return None


def extract_json_tool_call(content: str) -> dict | None:
    """Sehr robuster Parser für Llama-4 auf NVIDIA NIM."""
    if not content or not isinstance(content, str):
        return None

    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None

    if isinstance(parsed, dict):
        return _parse_single_tool_entry(parsed)

    if isinstance(parsed, list) and parsed:
        first_item = parsed[0]
        return _parse_single_tool_entry(first_item)

    return None


# ---------------------------------------------------------------------------
# Chat Loop
# ---------------------------------------------------------------------------

async def chat_loop(session: ClientSession, openai_client: AsyncOpenAI):
    tools_response = await session.list_tools()
    openai_tools = mcp_tools_to_openai_schema(tools_response.tools)
    tool_names = {t.name for t in tools_response.tools}

    print(f"[Connected] Verfügbare Tools: {list(tool_names)}\n")
    print("Schreibe deine Nachricht (Ctrl+C zum Beenden)\n")

    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant. You can use tools via function calls. "
                "Call **only ONE tool per response**. "
                "If the user asks multiple questions, call the first required tool only. "
                "Never output tool calls as JSON text, as a list, or in your normal message. "
                "Always use the structured tool_calls field. "
                "After receiving the tool result, you can call the next tool in the next turn if needed."
            ),
        }
    ]

    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        response = await openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=openai_tools,
            tool_choice="auto",
            parallel_tool_calls=False,
        )

        assistant_message = response.choices[0].message
        content = assistant_message.content or ""

        synthetic_tool_call = None
        if not assistant_message.tool_calls and content:
            parsed = extract_json_tool_call(content)
            if parsed and parsed.get("name") in tool_names:
                synthetic_tool_call = {
                    "id": "call_" + uuid.uuid4().hex[:10],
                    "name": parsed["name"],
                    "args": parsed["args"],
                }

        if assistant_message.tool_calls or synthetic_tool_call:
            if synthetic_tool_call:
                tc_id = synthetic_tool_call["id"]
                tc_name = synthetic_tool_call["name"]
                tc_args = synthetic_tool_call["args"]
            else:
                tc = assistant_message.tool_calls[0]
                tc_id = tc.id
                tc_name = tc.function.name
                tc_args = json.loads(tc.function.arguments)

            print(f"[Tool call] {tc_name}({tc_args})")

            try:
                tool_result = await call_mcp_tool(session, tc_name, tc_args)
            except Exception as e:
                tool_result = f"Tool error: {e}"

            print(f"[Tool result] {tool_result}\n")

            messages.append({
                "role": "assistant",
                "content": content if not synthetic_tool_call else None,
                "tool_calls": [{
                    "id": tc_id,
                    "type": "function",
                    "function": {
                        "name": tc_name,
                        "arguments": json.dumps(tc_args)
                    }
                }]
            })

            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": tool_result
            })

            # Finale Antwort ohne weitere Tools
            final_response = await openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
            )
            final_reply = final_response.choices[0].message.content or "Keine Antwort."
            messages.append({"role": "assistant", "content": final_reply})

            print(f"Assistant: {final_reply}\n")

        else:
            final_reply = content or "Keine Antwort erhalten."
            messages.append({"role": "assistant", "content": final_reply})
            print(f"Assistant: {final_reply}\n")


async def main():
    openai_client = AsyncOpenAI(
        api_key=NVIDIA_API_KEY,
        base_url="https://integrate.api.nvidia.com/v1",
    )

    server_params = StdioServerParameters(command="python", args=[SERVER_SCRIPT])

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
        print(f"\nFehler: {e}")

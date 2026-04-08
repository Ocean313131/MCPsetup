# mcp_client.py
#
# An MCP client that:
#   1. Launches the MCP server as a subprocess
#   2. Discovers its tools
#   3. Uses ChatGPT to decide when/how to call them
#   4. Runs a simple chat loop in the terminal
#
# Requirements:
#   pip install mcp openai
#
# Usage:
#   OPENAI_API_KEY=sk-... python mcp_client.py

import asyncio
import json
import os

from openai import AsyncOpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Path to your MCP server script
SERVER_SCRIPT = "hello_mcp_server.py"

# ChatGPT model to use
OPENAI_MODEL = "gpt-4o-mini"

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
                "parameters": tool.inputSchema,  # MCP already uses JSON Schema
            },
        })
    return openai_tools


async def call_mcp_tool(session: ClientSession, tool_name: str, tool_args: dict) -> str:
    """Call a tool on the MCP server and return its text result."""
    result = await session.call_tool(tool_name, tool_args)
    # result.content is a list of content blocks; grab the first text block
    return result.content[0].text


# ---------------------------------------------------------------------------
# Main chat loop
# ---------------------------------------------------------------------------

async def chat_loop(session: ClientSession, openai_client: AsyncOpenAI):
    """Interactive loop: user types → ChatGPT reasons → tools called if needed."""

    # Discover available tools from the MCP server
    tools_response = await session.list_tools()
    openai_tools = mcp_tools_to_openai_schema(tools_response.tools)
    print(f"[Connected] Tools available: {[t.name for t in tools_response.tools]}\n")

    # Conversation history sent to OpenAI on every turn
    messages = []

    print("Type your message (Ctrl+C to quit)\n")

    while True:
        # --- Get user input ---
        user_input = input("You: ").strip()
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        # --- Ask ChatGPT (with tools available) ---
        response = await openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=openai_tools,        # let the model know what tools exist
            tool_choice="auto",        # model decides whether to call a tool
        )

        assistant_message = response.choices[0].message

        # --- If ChatGPT wants to call a tool ---
        if assistant_message.tool_calls:
            # Add the assistant's (tool-calling) message to history
            messages.append(assistant_message)

            for tool_call in assistant_message.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                print(f"[Tool call] {name}({args})")

                # Execute the tool on the MCP server
                tool_result = await call_mcp_tool(session, name, args)

                print(f"[Tool result] {tool_result}")

                # Feed the result back into the conversation
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result,
                })

            # Ask ChatGPT to produce a final reply now that it has the tool result
            follow_up = await openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
            )
            final_reply = follow_up.choices[0].message.content
            messages.append({"role": "assistant", "content": final_reply})

        else:
            # No tool call — plain text reply
            final_reply = assistant_message.content
            messages.append({"role": "assistant", "content": final_reply})

        print(f"Assistant: {final_reply}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    api_key = os.getenv()
    if not api_key:
        raise ValueError("Set the OPENAI_API_KEY environment variable first.")

    openai_client = AsyncOpenAI(api_key=api_key)

    # Launch the MCP server as a subprocess communicating over stdio
    server_params = StdioServerParameters(
        command="python",
        args=[SERVER_SCRIPT],
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()          # MCP handshake
            await chat_loop(session, openai_client)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBye!")

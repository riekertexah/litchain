import json
from mcp import ClientSession
import anthropic
import chainlit as cl
import os
from typing import Dict, Optional
from yarl import URL

# Initialize Anthropic client
anthropic_client = anthropic.AsyncAnthropic()

# Generic system prompt for MCP-enabled assistant
SYSTEM = """You are a helpful AI assistant with access to various tools through the Model Context Protocol (MCP).
You can use these tools to help users accomplish their tasks. When using tools:
1. Explain what you're doing before using a tool
2. Use the most appropriate tool for the task
3. Handle tool results appropriately
4. Continue the conversation naturally after tool use"""


async def get_user_facing_url(url: URL):
    """
    OVERRIDE FUNCTION: Return the user facing URL for a given URL.
    Handles deployment with proxies (like cloud run).
    """
    chainlit_url = os.environ.get("CHAINLIT_URL")

    # No config, we keep the URL as is
    if not chainlit_url:
        url = url.replace(query="", fragment="")
        return url.__str__()

    config_url = URL(chainlit_url).replace(
        query="",
        fragment="",
    )
    # Remove trailing slash from config URL
    if config_url.path.endswith("/"):
        config_url = config_url.replace(path=config_url.path[:-1])

    config_url_path = str(config_url)
    url_path = url.path
    chainlit_root = os.environ.get("CHAINLIT_ROOT_PATH")
    if chainlit_root and url_path.startswith(chainlit_root):
        url_path = url_path[len(chainlit_root):]

    return config_url_path + url_path

@cl.password_auth_callback
def auth_callback(username: str, password: str):
    # Fetch the user matching username from your database
    # and compare the hashed password with the value stored in the database
    if (username, password) == ("admin", "admin"):
        return cl.User(
            identifier="admin", metadata={"role": "admin", "provider": "credentials"}
        )
    else:
        return None

@cl.oauth_callback
async def oauth_callback(provider_id: str, token: str, raw_user_data: Dict[str, str], default_user: cl.User) -> Optional[cl.User]:
    if provider_id == "google":
        if raw_user_data.get("hd") == "exah.co.za":
            return default_user
    return None

@cl.on_chat_start
async def start_chat():
    """Initialize the chat session."""
    # Get the current user
    user = cl.user_session.get("user")
    print(user)
    if user:
        # Check if user's email is from exah.co.za
        email = user.identifier if hasattr(user, 'identifier') else "anonymous"
        await cl.Message(
            content=f"Welcome {email}! How can I help you today?"
        ).send()
    cl.user_session.set("chat_messages", [])
    print(f"Chat session started for user: {email if user else 'anonymous'}")

@cl.on_chat_resume
async def on_chat_resume(thread):
    pass

@cl.oauth_callback
def oauth_callback(
    provider_id: str,
    token: str,
    raw_user_data: Dict[str, str],
    default_user: cl.User,
) -> Optional[cl.User]:
    if provider_id == "google":
        if raw_user_data["hd"] == "exah.co.za":
            return default_user
    return None

def flatten(xss):
    """Flatten a list of lists."""
    return [x for xs in xss for x in xs]

@cl.on_mcp_connect
async def on_mcp(connection, session: ClientSession):
    """Handle MCP connection and tool registration."""
    try:
        # Get available tools from the MCP session
        result = await session.list_tools()
        tools = [{
            "name": t.name,
            "description": t.description,
            "input_schema": t.inputSchema,
        } for t in result.tools]
        
        # Store tools in user session
        mcp_tools = cl.user_session.get("mcp_tools", {})
        mcp_tools[connection.name] = tools
        cl.user_session.set("mcp_tools", mcp_tools)
        
        print(f"Connected to MCP: {connection.name}")
        print(f"Available tools: {[t['name'] for t in tools]}")
    except Exception as e:
        print(f"Error connecting to MCP {connection.name}: {str(e)}")

@cl.step(type="tool")
async def call_tool(tool_use):
    """Execute a tool through MCP."""
    tool_name = tool_use.name
    tool_input = tool_use.input
    
    current_step = cl.context.current_step
    current_step.name = tool_name
    
    # Find the appropriate MCP connection for this tool
    mcp_tools = cl.user_session.get("mcp_tools", {})
    mcp_name = None

    for connection_name, tools in mcp_tools.items():
        if any(tool.get("name") == tool_name for tool in tools):
            mcp_name = connection_name
            break
    
    if not mcp_name:
        error_msg = f"Tool {tool_name} not found in any MCP connection"
        current_step.output = json.dumps({"error": error_msg})
        return current_step.output
    
    mcp_session, _ = cl.context.session.mcp_sessions.get(mcp_name)
    
    if not mcp_session:
        error_msg = f"MCP {mcp_name} not found in any MCP connection"
        current_step.output = json.dumps({"error": error_msg})
        return current_step.output
    
    try:
        current_step.output = await mcp_session.call_tool(tool_name, tool_input)
        return current_step.output
    except Exception as e:
        error_msg = f"Error executing tool {tool_name}: {str(e)}"
        current_step.output = json.dumps({"error": error_msg})
        return current_step.output

async def call_claude(chat_messages):
    """Call Claude with the current conversation context and available tools."""
    msg = cl.Message(content="")
    
    # Get all available tools from MCP connections
    mcp_tools = cl.user_session.get("mcp_tools", {})
    tools = flatten([tools for _, tools in mcp_tools.items()])
    
    print(f"Available tools for Claude: {[tool.get('name') for tool in tools]}")
    
    async with anthropic_client.messages.stream(
        system=SYSTEM,
        max_tokens=1024,
        messages=chat_messages,
        tools=tools,
        model="claude-3-5-sonnet-20240620",
    ) as stream:
        async for text in stream.text_stream:
            await msg.stream_token(text)
    
    await msg.send()
    return await stream.get_final_message()

@cl.on_message
async def on_message(msg: cl.Message):
    """Handle incoming messages and tool execution."""
    chat_messages = cl.user_session.get("chat_messages")
    chat_messages.append({"role": "user", "content": msg.content})
    
    # Get initial response from Claude
    response = await call_claude(chat_messages)
    
    # Handle tool use if needed
    while response.stop_reason == "tool_use":
        tool_use = next(block for block in response.content if block.type == "tool_use")
        tool_result = await call_tool(tool_use)

        # Add tool use and result to conversation
        messages = [
            {"role": "assistant", "content": response.content},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": str(tool_result),
                    }
                ],
            },
        ]

        chat_messages.extend(messages)
        response = await call_claude(chat_messages)

    # Get final response text
    final_response = next(
        (block.text for block in response.content if hasattr(block, "text")),
        None,
    )

    # Update conversation history
    chat_messages.append({"role": "assistant", "content": final_response})

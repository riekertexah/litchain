import json
from mcp import ClientSession
import anthropic
import chainlit as cl
import os
from typing import Dict, Optional, List, Any
from yarl import URL
from abc import ABC, abstractmethod
import tiktoken
from datetime import date

# DECLARATIONS

today = date.today()
SYSTEM = (
    f"You are a helpful AI assistant with access to various tools through the Model Context Protocol (MCP). Today's date is {today}\n"
    "You can use these tools to help users accomplish their tasks. When using tools:\n"
    "1. Explain what you're doing before using a tool\n"
    "2. Use the most appropriate tool for the task\n"
    "3. Handle tool results appropriately\n"
    "4. Continue the conversation naturally after tool use"
)

# AUTHENTICATION

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
async def auth_callback(username: str, password: str):
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
    # if provider_id == "google":
    #     if raw_user_data.get("hd") == "exah.co.za":
    #         return default_user
    return default_user

# LOGOUT
@cl.on_logout
async def on_logout():
    cl.user_session.clear()

# # CHAT START

@cl.on_chat_start
async def start_chat():
    """Initialize the chat session."""
    # Get all default Chainlit session data plus our custom data
    session_data = {
        # Default Chainlit session data
        "id": cl.user_session.get("id"),
        "user": cl.user_session.get("user"),
        "chat_profile": cl.user_session.get("chat_profile"),
        "chat_settings": cl.user_session.get("chat_settings"),
        "env": cl.user_session.get("env"),
        
        # Our custom session data
        "chat_messages": cl.user_session.get("chat_messages"),
        "mcp_tools": cl.user_session.get("mcp_tools")
    }
    print("Session data:", session_data)
    
    user = cl.user_session.get("user")
    if user:
        email = user.identifier if hasattr(user, 'identifier') else "LitFam"
        await cl.Message(
            content=f"Welcome to LitChain {email}! Get it, because I am built on Chainlit but in my case it's extra lit... anyways. How can I help you today?"
        ).send()

# CHAT RESUME

@cl.on_chat_resume
async def on_chat_resume(thread):
    pass

# MCP CONFIG

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

    except Exception as e:
        print(f"Error connecting to MCP {connection.name}: {str(e)}")

@cl.on_mcp_disconnect
async def on_mcp_disconnect(connection, session: ClientSession):
    """Handle MCP disconnection."""
    try:
        # Remove tools for this MCP connection from user session
        mcp_tools = cl.user_session.get("mcp_tools", {})
        if connection in mcp_tools:
            del mcp_tools[connection]
            cl.user_session.set("mcp_tools", mcp_tools)
    except Exception as e:
        print(f"Error disconnecting from MCP {connection}: {str(e)}")

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
    
def flatten(xss):
    """Flatten a list of lists."""
    return [x for xs in xss for x in xs]

# LLM CONFIG AND MANAGEMENT

class LLMContextManager(ABC):
    """Abstract base class for LLM context management"""
    @abstractmethod
    def count_tokens(self, messages: List[Dict[str, Any]], system_prompt: str = "") -> int:
        """Count tokens for a list of messages and system prompt"""
        pass
    
    @abstractmethod
    def count_tool_tokens(self, tools: List[Dict[str, Any]]) -> int:
        """Count tokens for tool definitions"""
        pass
    
    @abstractmethod
    def get_max_tokens(self) -> int:
        """Get maximum tokens for this LLM"""
        pass

class ClaudeContextManager(LLMContextManager):
    def __init__(self, model: str = "claude-3-5-sonnet-20240620"):
        self.model = model
        self.encoding = tiktoken.get_encoding("cl100k_base")
        # Reserve some tokens for response
        self.max_tokens = 200000 - 1024  # Claude's max - response tokens
    
    def count_tokens(self, messages: List[Dict[str, Any]], system_prompt: str = "") -> int:
        total_tokens = 0
        # Count system prompt tokens
        if system_prompt:
            total_tokens += len(self.encoding.encode(system_prompt))
        
        # Count message tokens
        for message in messages:
            if isinstance(message["content"], str):
                total_tokens += len(self.encoding.encode(message["content"]))
            elif isinstance(message["content"], list):
                for item in message["content"]:
                    if isinstance(item, dict) and "content" in item:
                        total_tokens += len(self.encoding.encode(str(item["content"])))
        return total_tokens
    
    def count_tool_tokens(self, tools: List[Dict[str, Any]]) -> int:
        total_tokens = 0
        for tool in tools:
            # Count tool name
            total_tokens += len(self.encoding.encode(tool["name"]))
            # Count tool description
            total_tokens += len(self.encoding.encode(tool["description"]))
            # Count tool schema
            total_tokens += len(self.encoding.encode(str(tool["input_schema"])))
        return total_tokens
    
    def get_max_tokens(self) -> int:
        return self.max_tokens

class ContextWindowManager:
    def __init__(self, llm_manager: LLMContextManager):
        self.llm_manager = llm_manager
    
    def get_relevant_messages(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]], system_prompt: str = "") -> List[Dict[str, Any]]:
        """Get messages that fit within the context window, considering tools and system prompt"""
        relevant_messages = []
        current_tokens = 0
        max_tokens = self.llm_manager.get_max_tokens()
        
        # Count system prompt and tools first
        current_tokens += self.llm_manager.count_tokens([], system_prompt)
        current_tokens += self.llm_manager.count_tool_tokens(tools)
        
        print(f"\n=== Token Usage ===")
        print(f"System prompt tokens: {self.llm_manager.count_tokens([], system_prompt)}")
        print(f"Tools tokens: {self.llm_manager.count_tool_tokens(tools)}")
        print(f"Remaining tokens for messages: {max_tokens - current_tokens}")
        
        # Start with most recent messages
        for message in reversed(messages):
            message_tokens = self.llm_manager.count_tokens([message])
            if current_tokens + message_tokens > max_tokens:
                print(f"Stopping at message with {message_tokens} tokens (would exceed limit)")
                break
            relevant_messages.insert(0, message)
            current_tokens += message_tokens
            print(f"Added message with {message_tokens} tokens. Total: {current_tokens}")
        
        print(f"Final token count: {current_tokens}/{max_tokens}")
        return relevant_messages

# INITIALIZE

anthropic_client = anthropic.AsyncAnthropic()

# Initialize context window manager
context_window = ContextWindowManager(ClaudeContextManager())

# LLM CALLS

async def call_claude(chat_messages, tools):
    """Call Claude with the current conversation context and available tools."""
    msg = cl.Message(content="")
    
    # Get relevant messages considering tools and system prompt
    relevant_messages = context_window.get_relevant_messages(
        messages=chat_messages,
        tools=tools,
        system_prompt=SYSTEM
    )
    
    async with anthropic_client.messages.stream(
        system=SYSTEM,
        max_tokens=1024,
        messages=relevant_messages,
        tools=tools,
        model="claude-3-5-sonnet-20240620",
    ) as stream:
        async for text in stream.text_stream:
            await msg.stream_token(text)
    
    await msg.send()
    response = await stream.get_final_message()
    
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
        
        # Recursive call with new messages
        response = await call_claude(messages, tools)
    
    return response

# CHAT MESSAGE CHAINLIT (MAIN ROUTE)

@cl.on_message
async def on_message(msg: cl.Message):
    # Get all messages in OpenAI format automatically
    chat_messages = cl.chat_context.to_openai()
    
    # Get all available tools from MCP connections
    mcp_tools = cl.user_session.get("mcp_tools", {})
    tools = flatten([tools for _, tools in mcp_tools.items()])
    
    response = await call_claude(chat_messages, tools)


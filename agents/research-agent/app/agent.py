import json
import boto3
from typing import Annotated, TypedDict
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from app.tools import TOOLS

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    query: str
    final_answer: str

SYSTEM_PROMPT = """You are the AgenticOps Research Agent — a specialist in finding
current information about AWS services, Bedrock features, infrastructure incidents,
and operational intelligence.

You have access to three tools:
1. kb_retrieve — Search internal runbooks, post-mortems, and SOPs first
2. web_search — Search the web for recent or external information
3. summarize_document — Get full content from a specific URL

Research strategy:
- Always check kb_retrieve first for internal platform knowledge
- Use web_search for anything recent, external, or not in the KB
- Use summarize_document when a URL from web_search looks highly relevant
- Synthesize findings from multiple sources into a clear, actionable response
- Always cite your sources (KB document name or URL)
- Be concise — engineers need actionable information, not essays

If you cannot find relevant information after 3 tool calls, say so clearly."""

llm = ChatBedrockConverse(
    model="us.anthropic.claude-sonnet-4-6",
    region_name="us-east-1",
    max_tokens=2000,
    temperature=0
).bind_tools(TOOLS)

tool_node = ToolNode(TOOLS)

def should_continue(state: AgentState) -> str:
    messages = state["messages"]
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END

def call_model(state: AgentState) -> AgentState:
    messages = state["messages"]
    if not any(isinstance(m, SystemMessage) for m in messages):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
    response = llm.invoke(messages)
    return {
        "messages": [response],
        "final_answer": response.content if not response.tool_calls else ""
    }

def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")
    return graph.compile()

research_graph = build_graph()

def run_research(query: str) -> dict:
    initial_state = {
        "messages": [HumanMessage(content=query)],
        "query": query,
        "final_answer": ""
    }
    result = research_graph.invoke(initial_state, config={"recursion_limit": 10})
    messages = result["messages"]
    final_answer = ""
    tools_used = []
    for msg in messages:
        if isinstance(msg, AIMessage):
            if msg.content:
                final_answer = msg.content
            if hasattr(msg, "tool_calls"):
                for tc in msg.tool_calls:
                    tools_used.append(tc["name"])
    return {
        "answer": final_answer,
        "toolsUsed": tools_used,
        "messageCount": len(messages)
    }

"""
StudyBuddy AI — Web search agent with auto-detection for comparison queries.

If user asks a comparison question (e.g. "compare X on amazon and flipkart"),
this module detects it and delegates to the comparison agent instead.
"""

import json
import re

from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from typing import Annotated, TypedDict

from config import get_settings

# ---------------------------------------------------------------------------
# Tavily import — use new package if available, fall back to legacy
# ---------------------------------------------------------------------------
try:
    from langchain_tavily import TavilySearch
    def _get_search_tool():
        return TavilySearch(max_results=5)
except ImportError:
    from langchain_community.tools.tavily_search import TavilySearchResults
    def _get_search_tool():
        return TavilySearchResults(max_results=5, search_depth="basic")


# ---------------------------------------------------------------------------
# Compare intent detection
# ---------------------------------------------------------------------------

COMPARE_PATTERNS = [
    re.compile(r'\b(compare|vs|versus)\b.*\b(amazon|flipkart)\b', re.I),
    re.compile(r'\b(amazon|flipkart)\b.*\b(compare|vs|versus)\b', re.I),
    re.compile(r'\b(price|cheaper|costly|expensive)\b.*\b(amazon|flipkart)\b', re.I),
    re.compile(r'\b(amazon|flipkart)\b.*\b(price|cheaper|costly|expensive)\b', re.I),
    re.compile(r'https?://(?:www\.)?(?:amazon\.in|amazon\.com|flipkart\.com)', re.I),
]


def _is_compare_query(question: str) -> bool:
    """Detect if the user's question is a product comparison request."""
    return any(p.search(question) for p in COMPARE_PATTERNS)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    question: str
    search_queries: list[str]
    search_results: list[dict]
    answer: str
    messages: Annotated[list, add_messages]


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def _get_llm():
    settings = get_settings()
    return ChatOpenAI(
        model="gpt-4o-mini",
        api_key=settings.openai_api_key,
        max_tokens=1024,
        streaming=True,
    )


SYSTEM_PROMPT = """You are StudyBuddy, a helpful AI study assistant. You ALWAYS search the web
for the latest information before answering. Answer questions clearly and concisely.
Focus on accuracy and educational value. Use simple language.

Format your responses in Markdown:
- Use ## or ### for headings when explaining topics.
- Use bullet points (- or *) for lists and key points.
- Use numbered lists when giving steps.
- For code examples use fenced code blocks with the language name.
- When you use information from web search, mention the source briefly."""


def plan_search(state: AgentState) -> dict:
    llm = _get_llm()
    planning_prompt = f"""Given this user question, generate 1 to 3 concise web search queries
that would help answer it thoroughly. Return ONLY a JSON array of strings, nothing else.

Question: {state['question']}"""

    response = llm.invoke([
        SystemMessage(content="You generate search queries. Return only a JSON array of strings."),
        HumanMessage(content=planning_prompt),
    ])

    try:
        queries = json.loads(response.content)
        if not isinstance(queries, list):
            queries = [state["question"]]
    except (json.JSONDecodeError, TypeError):
        queries = [state["question"]]

    return {"search_queries": queries[:3]}


def web_search(state: AgentState) -> dict:
    tool = _get_search_tool()
    all_results = []

    for query in state.get("search_queries", [state["question"]]):
        try:
            results = tool.invoke(query)
            if isinstance(results, list):
                for r in results:
                    all_results.append({
                        "query": query,
                        "url": r.get("url", ""),
                        "content": r.get("content", ""),
                    })
            elif isinstance(results, str):
                all_results.append({
                    "query": query,
                    "url": "",
                    "content": results,
                })
        except Exception as e:
            all_results.append({
                "query": query,
                "url": "",
                "content": f"Search failed: {str(e)}",
            })

    return {"search_results": all_results}


def synthesize(state: AgentState) -> dict:
    llm = _get_llm()

    context_parts = []
    for i, r in enumerate(state.get("search_results", []), 1):
        source = r.get("url", "unknown source")
        content = r.get("content", "")[:800]
        context_parts.append(f"[Source {i}] {source}\n{content}")

    context_block = "\n\n".join(context_parts) if context_parts else "No search results found."

    user_msg = f"""Web search results:
---
{context_block}
---

User question: {state['question']}

Using the search results above, provide a comprehensive answer. Cite sources where relevant."""

    response = llm.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_msg),
    ])

    return {
        "answer": response.content,
        "messages": [
            HumanMessage(content=state["question"]),
            AIMessage(content=response.content),
        ],
    }


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def build_agent_graph() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("plan_search", plan_search)
    graph.add_node("web_search", web_search)
    graph.add_node("synthesize", synthesize)
    graph.set_entry_point("plan_search")
    graph.add_edge("plan_search", "web_search")
    graph.add_edge("web_search", "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()


_agent = None

def _get_agent():
    global _agent
    if _agent is None:
        _agent = build_agent_graph()
    return _agent


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_answer(question: str, user_id: str | None = None) -> str:
    """Generate an answer. Auto-routes to comparison agent if detected."""
    settings = get_settings()
    if not settings.openai_configured:
        return "OpenAI is not configured. Set OPENAI_API_KEY in the environment."

    # Auto-detect comparison intent → delegate to compare agent
    if _is_compare_query(question):
        try:
            from agent.compare_agent import compare_products_async
            return await compare_products_async(question)
        except Exception as e:
            print(f"Compare agent failed, falling back to web search: {e}")

    agent = _get_agent()
    result = await agent.ainvoke({
        "question": question,
        "search_queries": [],
        "search_results": [],
        "answer": "",
        "messages": [],
    })
    return result.get("answer", "I couldn't generate an answer.")


def stream_answer(question: str):
    """Stream answer chunks. Auto-routes to comparison agent if detected."""
    settings = get_settings()
    if not settings.openai_configured:
        yield "OpenAI is not configured. Set OPENAI_API_KEY in the environment.", True
        return

    # Auto-detect comparison intent → delegate to compare streamer
    if _is_compare_query(question):
        try:
            from agent.compare_agent import compare_products_stream
            yield from compare_products_stream(question)
            return
        except Exception as e:
            print(f"Compare agent stream failed, falling back: {e}")

    # --- Normal web search flow ---
    llm = _get_llm()
    tool = _get_search_tool()

    # Plan
    planning_prompt = f"""Given this user question, generate 1 to 3 concise web search queries
that would help answer it thoroughly. Return ONLY a JSON array of strings.

Question: {question}"""

    plan_resp = llm.invoke([
        SystemMessage(content="You generate search queries. Return only a JSON array of strings."),
        HumanMessage(content=planning_prompt),
    ])
    try:
        queries = json.loads(plan_resp.content)
        if not isinstance(queries, list):
            queries = [question]
    except (json.JSONDecodeError, TypeError):
        queries = [question]
    queries = queries[:3]

    yield "🔍 *Searching the web...*\n\n", False

    # Search
    all_results = []
    for q in queries:
        try:
            results = tool.invoke(q)
            if isinstance(results, list):
                for r in results:
                    all_results.append({
                        "url": r.get("url", ""),
                        "content": r.get("content", ""),
                    })
            elif isinstance(results, str):
                all_results.append({"url": "", "content": results})
        except Exception:
            pass

    # Synthesize (streamed)
    context_parts = []
    for i, r in enumerate(all_results, 1):
        source = r.get("url", "unknown")
        content = r.get("content", "")[:800]
        context_parts.append(f"[Source {i}] {source}\n{content}")

    context_block = "\n\n".join(context_parts) if context_parts else "No search results found."

    user_msg = f"""Web search results:
---
{context_block}
---

User question: {question}

Using the search results above, provide a comprehensive answer. Cite sources where relevant."""

    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=1024,
        stream=True,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and getattr(delta, "content", None):
            yield delta.content, False

    yield "", True
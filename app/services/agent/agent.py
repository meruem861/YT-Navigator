"""Channel assistant: routes each message, optionally uses search tools, and keeps the chat history.

Flow (same as before, without LangChain/LangGraph):
    route_message ──► "Not relevant" ─► static reply
                  ├─► "No"           ─► direct reply (small model)
                  └─► "Yes"          ─► tool loop (powerful model + similarity search / SQL tools)
"""

import json
import re
import traceback
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
    Dict,
    List,
    Optional,
)

import structlog
from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils.html import (
    escape,
    linebreaks,
)
from markdown2 import markdown

from app.helpers import convert_time_to_seconds
from app.models import (
    Channel,
    ChatHistoryMessage,
    User,
)
from app.services.agent.prompts import (
    ANSWER_FORMAT_INSTRUCTIONS,
    NON_TOOL_CALLS_SYSTEM_PROMPT,
    ROUTE_QUERY_SYSTEM_PROMPT,
    ROUTER_FORMAT_INSTRUCTIONS,
    SYSTEM_PROMPT_TEMPLATE,
)
from app.services.llm_client import get_chat_client
from app.services.vector_database.tools import (
    SQLTools,
    VectorDatabaseTools,
)

logger = structlog.get_logger(__name__)

STATIC_NOT_RELEVANT_REPLY = "I'm sorry, I can't answer, please try again with a different question."
MAX_TOOL_ROUNDS = 6
MAX_TOOL_RESULT_CHARS = 12000
ROUTER_HISTORY = 6
REPLY_HISTORY = 10
MAX_VIDEOS = 5


@dataclass
class ChatMessage:
    """A chat message as displayed in the chat page."""

    type: str
    placeholder: str
    videos: List[Dict[str, Any]] = field(default_factory=list)
    text: str = ""


def _extract_json(text: str) -> Optional[dict]:
    """Extract the first JSON object from a model answer (which may be wrapped in code fences or prose)."""
    text = (text or "").strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _clean_video(video: Any) -> Optional[Dict[str, Any]]:
    """Normalize a video entry of the model answer, dropping invalid ones."""
    if not isinstance(video, dict) or not video.get("id"):
        return None
    timestamps = []
    for ts in video.get("timestamps") or []:
        if isinstance(ts, dict):
            try:
                start_seconds = convert_time_to_seconds(str(ts.get("start")))
            except ValueError:
                start_seconds = 0
            timestamps.append(
                {
                    "start": ts.get("start"),
                    "end": ts.get("end"),
                    "description": ts.get("description") or "",
                    "start_seconds": start_seconds,
                }
            )
    return {
        "id": str(video["id"]),
        "title": video.get("title") or "",
        "description": video.get("description") or "",
        "thumbnail_url": video.get("thumbnail_url") or f"https://i.ytimg.com/vi/{video['id']}/hqdefault.jpg",
        "timestamps": timestamps,
    }


def parse_answer(text: str) -> Dict[str, Any]:
    """Parse a model answer into {"placeholder": markdown, "videos": [...]}, falling back to plain text."""
    data = _extract_json(text)
    if data is None or "placeholder" not in data:
        return {"placeholder": (text or "").strip(), "videos": []}
    videos = [v for v in (_clean_video(v) for v in (data.get("videos") or [])) if v]
    return {"placeholder": str(data.get("placeholder") or ""), "videos": videos[:MAX_VIDEOS]}


def render_answer(answer: Dict[str, Any]) -> Dict[str, Any]:
    """Render the Markdown answer to HTML for the chat page."""
    # safe_mode escapes any raw HTML the model writes, so it is shown as text instead of being run in the page
    html = markdown(answer.get("placeholder") or "", safe_mode="escape", extras=["break-on-newline"])
    return {"placeholder": html, "videos": answer.get("videos") or []}


class ChannelAgent:
    """Chat assistant for the channel connected by the user."""

    def __init__(self, client=None):
        """Initialize the agent.

        Args:
            client: Chat client to use; by default the provider selected in Settings, resolved per message.
        """
        self._fixed_client = client
        self.client = client
        self.tools = [VectorDatabaseTools.tool(), SQLTools.tool()]

    # ---------------------------------------------------------------- history

    @staticmethod
    async def _load_history(user: User, limit: int) -> List[Dict[str, str]]:
        """Return the last messages of the conversation as LLM messages."""

        @sync_to_async
        def load():
            return list(ChatHistoryMessage.objects.filter(user=user).order_by("-created_at", "-id")[:limit])[::-1]

        history = []
        for message in await load():
            if message.role == "human":
                history.append({"role": "user", "content": message.content})
            else:
                history.append({"role": "assistant", "content": parse_answer(message.content)["placeholder"]})
        return history

    @staticmethod
    async def _save(user: User, role: str, content: str) -> None:
        await sync_to_async(ChatHistoryMessage.objects.create)(user=user, role=role, content=content)

    async def get_chat_history(self, user_id: str) -> List[ChatMessage]:
        """Return the conversation of a user, ready for the chat page."""
        messages = await sync_to_async(lambda: list(ChatHistoryMessage.objects.filter(user_id=user_id)))()
        history = []
        for message in messages:
            if message.role == "human":
                history.append(
                    ChatMessage(type="human", placeholder=linebreaks(escape(message.content)), text=message.content)
                )
            else:
                rendered = render_answer(parse_answer(message.content))
                history.append(ChatMessage(type="ai", placeholder=rendered["placeholder"], videos=rendered["videos"]))
        return history

    async def clear_chat_history(self, user_id: str) -> None:
        """Delete the conversation of a user."""
        await sync_to_async(lambda: ChatHistoryMessage.objects.filter(user_id=user_id).delete())()
        logger.info(f"Cleared chat history for user {user_id}")

    # ---------------------------------------------------------------- steps

    async def route_message(self, channel_info: str, history: List[Dict[str, str]]) -> str:
        """Decide whether the message needs tools ("Yes"), not ("No"), or is off-topic ("Not relevant")."""
        tools_description = "\n".join(
            f"## Tool {i + 1}:\n* Name: {t['function']['name']}\n* Description: {t['function']['description']}"
            for i, t in enumerate(self.tools)
        )
        system = ROUTE_QUERY_SYSTEM_PROMPT.format(
            channel=channel_info, tools=tools_description, format_instructions=ROUTER_FORMAT_INSTRUCTIONS
        )
        model = await self.client.pick_model("instant")
        reply = await self.client.chat(model, [{"role": "system", "content": system}, *history], json_mode=True)
        content = reply.get("content") or ""
        answer = (_extract_json(content) or {}).get("answer")
        if answer not in ("Yes", "No", "Not relevant"):
            # Fall back to keywords in the raw text; when unsure, use the tools
            answer = next((route for route in ("Not relevant", "No", "Yes") if route in content), "Yes")
        logger.info("Message routed", router_result=answer)
        return answer

    async def non_tool_calls_reply(self, channel: Channel, user: User, history: List[Dict[str, str]]) -> str:
        """Answer without tools (greetings, general questions)."""
        system = NON_TOOL_CALLS_SYSTEM_PROMPT.format(
            channel=str(channel), user=str(user), format_instructions=ANSWER_FORMAT_INSTRUCTIONS
        )
        model = await self.client.pick_model("instant")
        reply = await self.client.chat(model, [{"role": "system", "content": system}, *history], json_mode=True)
        return reply.get("content") or ""

    async def _run_tool(self, name: str, arguments: str) -> str:
        """Execute a tool call and return its result as text."""
        try:
            args = json.loads(arguments or "{}")
            if name == "similarity_videos_search":
                result = await VectorDatabaseTools.similarity_videos_search(**args)
                output = json.dumps(result.to_dict(), default=str)
            elif name == "execute_query":
                output = await sync_to_async(SQLTools.execute_query)(**args)
            else:
                output = f"Error: unknown tool {name}"
        except Exception as e:
            logger.error("Tool call failed", tool=name, error=str(e), traceback=traceback.format_exc())
            output = f"Error: {e}"
        return output[:MAX_TOOL_RESULT_CHARS]

    async def tool_calls_reply(self, channel_info: str, user: User, history: List[Dict[str, str]]) -> str:
        """Answer with the powerful model, letting it call the search tools (ReAct loop)."""
        system = SYSTEM_PROMPT_TEMPLATE.format(
            channel=channel_info, user=str(user), format_instructions=ANSWER_FORMAT_INSTRUCTIONS
        )
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system}, *history]
        model = await self.client.pick_model("powerful")

        for _ in range(MAX_TOOL_ROUNDS):
            reply = await self.client.chat(model, messages, tools=self.tools)
            tool_calls = reply.get("tool_calls") or []
            if not tool_calls:
                return reply.get("content") or ""

            assistant = {"role": "assistant", "content": reply.get("content") or "", "tool_calls": tool_calls}
            if "_claude_content" in reply:
                # Claude needs its original content blocks (thinking, tool_use) sent back unchanged
                assistant["_claude_content"] = reply["_claude_content"]
            messages.append(assistant)
            for call in tool_calls:
                function = call.get("function", {})
                logger.info("Calling tool", tool=function.get("name"), arguments=function.get("arguments"))
                output = await self._run_tool(function.get("name"), function.get("arguments"))
                messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": output})

        # Too many tool rounds: ask for a final answer with what was found
        messages.append({"role": "user", "content": "Give your final answer now using the results above."})
        reply = await self.client.chat(model, messages)
        return reply.get("content") or ""

    # ---------------------------------------------------------------- entry point

    async def process_message(self, message: str, channel: Channel, user: User) -> str:
        """Answer a user message and save both to the history.

        Returns:
            str: JSON {"placeholder": html, "videos": [...]} for the chat page.
        """
        logger.info("Processing message", message=message)
        self.client = self._fixed_client or await get_chat_client()
        channel_info = await channel.pretty_str()

        history = await self._load_history(user, REPLY_HISTORY)
        history.append({"role": "user", "content": message})

        try:
            route = await self.route_message(channel_info, history[-ROUTER_HISTORY:])
        except Exception as e:
            # Routing is an optimization: when it fails, answer with the tools
            logger.warning("Routing failed, using the tools", error=str(e))
            route = "Yes"

        raw = None
        if route == "Not relevant":
            raw = json.dumps({"placeholder": STATIC_NOT_RELEVANT_REPLY, "videos": []})
        elif route == "No":
            try:
                raw = await self.non_tool_calls_reply(channel, user, history[-ROUTER_HISTORY:])
            except Exception as e:
                logger.warning("Direct reply failed, using the tools", error=str(e))
        if raw is None:
            raw = await self.tool_calls_reply(channel_info, user, history)

        answer = parse_answer(raw)
        await self._save(user, "human", message)
        await self._save(user, "ai", json.dumps(answer))
        return json.dumps(render_answer(answer))


_agent: Optional[ChannelAgent] = None


def get_agent() -> ChannelAgent:
    """Return the shared ChannelAgent instance."""
    global _agent
    if _agent is None:
        _agent = ChannelAgent()
    return _agent

"""Main agent graph."""

import asyncio
import os
import traceback
from contextlib import asynccontextmanager
from json import JSONDecodeError
from typing import (
    Any,
    AsyncIterator,
    Dict,
    List,
    Literal,
    Optional,
)

import structlog
from django.conf import settings
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    messages_to_dict,
    trim_messages,
)
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.tools import StructuredTool
from langchain_groq import ChatGroq
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import (
    END,
    StateGraph,
)
from langgraph.graph.state import CompiledStateGraph
from pydantic import ValidationError

from app.models import (
    Channel,
    User,
)
from app.schemas import (
    AgentOutput,
    AgentRouterOutput,
    AgentState,
    ChatMessage,
    InputAgentState,
)
from app.services.agent.prompts import (
    NON_TOOL_CALLS_SYSTEM_PROMPT,
    ROUTE_QUERY_SYSTEM_PROMPT,
)
from app.services.agent.react_graph import react_agent
from app.services.evaluation.langsmith_evaluation_service import LangsmithEvaluationService
from app.services.vector_database.tools import (
    SQLTools,
    VectorDatabaseTools,
)

logger = structlog.get_logger(__name__)


class AgentGraph:
    """Agent graph class for routing messages and building the agent graph.

    This class encapsulates the functionality for routing messages to the appropriate
    node in the agent graph, handling different types of replies, and building the
    complete agent graph.
    """

    def __init__(self):
        """Initialize the AgentGraph with tools and model."""
        logger.info("Initializing AgentGraph")
        self.tools = [
            VectorDatabaseTools.tool(),
            SQLTools.tool(),
        ]

        self.model = ChatGroq(
            model_name=settings.INSTANT_LLM,
            api_key=os.getenv("GROQ_API_KEY"),
        )
        logger.info("AgentGraph initialized successfully")

        # LangSmith dataset collection is optional; it needs network access and an API key.
        self.evaluator = None
        if os.getenv("LANGSMITH_API_KEY"):
            try:
                self.evaluator = LangsmithEvaluationService()
            except Exception as e:
                logger.warning("LangSmith evaluation disabled", error=str(e))

    @asynccontextmanager
    async def checkpointed_graph(self) -> AsyncIterator[CompiledStateGraph]:
        """Yield the agent graph wired to a SQLite checkpointer bound to the current event loop.

        A fresh connection is opened per call so the checkpointer never outlives the event loop it was
        created in (Django may run each async view in its own loop).
        """
        async with AsyncSqliteSaver.from_conn_string(str(settings.CHECKPOINT_DB_PATH)) as checkpointer:
            await checkpointer.setup()
            yield self.build_graph(checkpointer)

    async def route_message(self, state: AgentState) -> AgentState:
        """Route the message to the appropriate node.

        Args:
            state: The current state of the agent.

        Returns:
            AgentState: The updated state with router results.

        Raises:
            Exception: If there's an error during routing.
        """
        try:
            logger.info("Routing message", message_content=state.messages[-1].content)
            output_parser = PydanticOutputParser(pydantic_object=AgentRouterOutput)

            filtered_messages = self._prepare_messages_for_model(state.messages)

            output = await self.model.ainvoke(
                [
                    SystemMessage(
                        content=ROUTE_QUERY_SYSTEM_PROMPT.format(
                            channel=await state.channel.pretty_str(),
                            tools=self._pretty_str_tools(self.tools),
                            format_instructions=output_parser.get_format_instructions(),
                        )
                    ),
                    *filtered_messages,
                ]
            )

            try:
                output = output_parser.parse(output.content)
            except OutputParserException as e:
                logger.error("Error parsing output", error=e, traceback=traceback.format_exc())
                # Extract routing keywords if present in the output
                for route in ["Not relevant", "Yes", "No"]:
                    if route in output.content:
                        output = AgentRouterOutput(answer=route)
                        break
                else:
                    raise
            logger.info("Message routed successfully", router_result=output.answer)

            return {"router_results": output}
        except Exception as e:
            logger.error("Error routing message", error=e, traceback=traceback.format_exc())
            raise

    @staticmethod
    def router_condition(
        state: AgentState,
    ) -> Literal["static_not_relevant_reply", "non_tool_calls_reply", "tool_calls_reply"]:
        """Determine the next node based on the router results.

        Args:
            state: The current state of the agent.

        Returns:
            Literal: The next node to route to.
        """
        try:
            if state.router_results.answer == "Not relevant":
                logger.info("Router condition: Not relevant")
                return "static_not_relevant_reply"
            elif state.router_results.answer == "Yes":
                logger.info("Router condition: Yes - using tool calls")
                return "tool_calls_reply"
            else:
                logger.info("Router condition: No - using non-tool calls")
                return "non_tool_calls_reply"
        except Exception as e:
            logger.error("Error in router condition", error=e, traceback=traceback.format_exc())
            # Default to non-tool calls if there's an error
            return "non_tool_calls_reply"

    @staticmethod
    def static_not_relevant_reply(state: AgentState) -> AgentState:
        """Handle the static not relevant reply.

        Args:
            state: The current state of the agent.

        Returns:
            AgentState: The updated state with the static not relevant reply.
        """
        logger.info("Generating static not relevant reply")

        STATIC_REPLY = "I'm sorry, I can't answer, please try again with a different question."

        return {
            "messages": state.messages
            + [AIMessage(content=AgentOutput(placeholder=STATIC_REPLY, videos=[]).model_dump_json())]
        }

    async def non_tool_calls_reply(self, state: AgentState) -> AgentState:
        """Handle the non tool calls reply.

        Args:
            state: The current state of the agent.

        Returns:
            AgentState: The updated state with the non tool calls reply.

        Raises:
            Exception: If there's an error generating the reply.
        """
        try:
            logger.info("Generating non-tool calls reply")
            filtered_messages = self._prepare_messages_for_model(state.messages)
            output = await self.model.ainvoke(
                [
                    SystemMessage(
                        content=NON_TOOL_CALLS_SYSTEM_PROMPT.format(channel=str(state.channel), user=str(state.user))
                    ),
                    *filtered_messages,
                ]
            )
            try:
                output_parser = PydanticOutputParser(pydantic_object=AgentOutput)
                output.content = output_parser.parse(output.content).model_dump_json()
            except OutputParserException as e:
                logger.error("Error parsing output", error=e, traceback=traceback.format_exc())
                output.content = AgentOutput(
                    placeholder=str(output.content),
                    videos=[],
                ).model_dump_json()
            logger.info("Non-tool calls reply generated successfully")
            return {"messages": state.messages + [output]}
        except Exception as e:
            logger.error("Error generating non-tool calls reply", error=e, traceback=traceback.format_exc())
            raise

    def _prepare_messages_for_model(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """Prepare messages for the model by trimming and formatting them.

        Args:
            messages: The list of messages to prepare.

        Returns:
            List[BaseMessage]: A list of the prepared messages.
        """
        trimmed_messages = trim_messages(
            messages,
            strategy="last",
            token_counter=count_tokens_approximately,
            max_tokens=1000,
            start_on="human",
            include_system=False,
            allow_partial=False,
        )
        return [msg for msg in trimmed_messages if isinstance(msg, HumanMessage) or isinstance(msg, AIMessage)]

    def _pretty_str_tools(self, tools: list[StructuredTool]) -> str:
        """Pretty string tools.

        Args:
            tools: The list of tools to pretty string.

        Returns:
            str: The pretty string tools.
        """
        string_wrapper = ""
        for idx, tool in enumerate(tools):
            string_wrapper += f"""## Tool {idx + 1}:
            * Name: {tool.name}
            * Description: {tool.description}
            """
        return string_wrapper

    def build_graph(self, checkpointer: Optional[AsyncSqliteSaver] = None) -> CompiledStateGraph:
        """Build the agent graph.

        Args:
            checkpointer: The checkpointer used to persist the conversation.

        Returns:
            CompiledStateGraph: The compiled graph for the agent.
        """
        logger.info("Building agent graph")
        try:
            graph = StateGraph(input=InputAgentState, state_schema=AgentState)

            graph.add_node("route_message", self.route_message)
            graph.add_node("tool_calls_reply", react_agent)
            graph.add_node("non_tool_calls_reply", self.non_tool_calls_reply)
            graph.add_node("static_not_relevant_reply", self.static_not_relevant_reply)

            graph.add_conditional_edges(
                "route_message",
                self.router_condition,
                {
                    "static_not_relevant_reply": "static_not_relevant_reply",
                    "non_tool_calls_reply": "non_tool_calls_reply",
                    "tool_calls_reply": "tool_calls_reply",
                },
            )

            graph.add_edge("tool_calls_reply", END)
            graph.add_edge("non_tool_calls_reply", END)
            graph.add_edge("static_not_relevant_reply", END)

            graph.set_entry_point("route_message")

            compiled_graph = graph.compile(checkpointer=checkpointer)
            logger.info("Agent graph built successfully")
            return compiled_graph
        except Exception as e:
            logger.error("Error building agent graph", error=e, traceback=traceback.format_exc())
            raise

    async def invoke(self, message: str, channel: Channel, user: User) -> Dict[str, Any]:
        """Invoke the agent graph with a message.

        Args:
            message: The message to process.
            channel: The channel the message is from.
            user: The user who sent the message.

        Returns:
            Dict[str, Any]: The result of the agent graph execution.

        Raises:
            Exception: If there's an error during graph execution.
        """
        try:
            logger.info("Invoking agent graph", message=message)

            # Create initial state
            initial_state = {
                "messages": [HumanMessage(content=message)],
                "channel": channel,
                "user": user,
            }

            config = {
                "configurable": {
                    "thread_id": str(user.id),
                },
            }

            async with self.checkpointed_graph() as graph:
                result = await graph.ainvoke(initial_state, config)

            logger.info("Agent graph execution completed successfully")

            if self.evaluator is None:
                return result

            # Create and track the background task
            task = asyncio.create_task(self._background_add_example(result))
            # Ensure the task is not garbage collected
            task.add_done_callback(
                lambda t: logger.info(
                    "Background task completed"
                    if not t.exception()
                    else logger.error("Background task failed", error=t.exception())
                )
            )
            return result
        except RuntimeError as e:
            logger.error("Runtime error in agent graph", error=e, traceback=traceback.format_exc())
            raise
        except Exception as e:
            logger.error("Error in agent graph", error=e, traceback=traceback.format_exc())
            raise

    async def _background_add_example(self, result: Dict[str, Any]):
        """Add example to the dataset in the background.

        Args:
            result: The result from the agent graph execution
        """
        try:
            # Use the synchronous version to avoid async issues
            import threading

            def run_in_thread():
                try:
                    self.evaluator.add_example_sync(result)
                    logger.info("Successfully added example to dataset in background thread")
                except Exception as e:
                    logger.error(
                        "Error adding example to dataset in background thread",
                        error=e,
                        traceback=traceback.format_exc(),
                    )

            # Start a new thread to handle the synchronous operation
            thread = threading.Thread(target=run_in_thread)
            thread.daemon = True  # Allow the thread to exit when the main program exits
            thread.start()

            logger.info("Started background thread for adding example to dataset")
        except Exception as e:
            logger.error(
                "Error setting up background thread for adding example", error=e, traceback=traceback.format_exc()
            )

    @staticmethod
    def extract_response(result: Dict[str, Any]) -> Optional[str]:
        """Extract the final response from the agent's output.

        Args:
            result: The result of the agent graph execution.

        Returns:
            Optional[str]: The content of the last AI message, or None if no AI message is found.
        """
        try:
            messages = result.get("messages", [])
            if not messages:
                logger.warning("No messages found in agent result")
                return None

            # Find the last AI message
            for message in reversed(messages):
                if isinstance(message, BaseMessage) and not isinstance(message, HumanMessage):
                    logger.info("Extracted final response from agent output")
                    return message.content

            logger.warning("No AI message found in agent result")
            return None
        except Exception as e:
            logger.error("Error extracting response from agent output", error=e, traceback=traceback.format_exc())
            return None

    async def process_message(self, message: str, channel: Channel, user: User) -> Optional[str]:
        """Process a message and return just the response.

        This is a convenience method that combines invoke() and extract_response().

        Args:
            message: The message to process.
            channel: The channel the message is from.
            user: The user who sent the message.

        Returns:
            Optional[str]: The content of the last AI message, or None if no AI message is found.

        Raises:
            Exception: If there's an error during processing.
        """
        try:
            logger.info("Processing message", message=message)

            # Invoke the graph
            result = await self.invoke(message, channel, user)

            # Extract the response
            response = self.extract_response(result)

            if response:
                logger.info("Message processed successfully", response=response)
            else:
                logger.warning("No response generated for message")

            return response
        except Exception as e:
            logger.error("Error processing message", error=e, traceback=traceback.format_exc())
            raise

    async def get_chat_history(self, user_id: str) -> List[dict]:
        """Retrieve the chat history for a given thread ID.

        Args:
            user_id: The ID of the user to fetch history for.

        Returns:
            List[dict]: List of chat messages in the conversation history.

        Raises:
            Exception: If there's an error fetching the chat history.
        """
        try:
            async with self.checkpointed_graph() as graph:
                state = await graph.aget_state(config={"configurable": {"thread_id": user_id}})

            if not state:
                return []

            original_messages: List[BaseMessage] = state.values.get("messages", [])

            def process_message(msg: Dict[str, Any]) -> Optional[ChatMessage]:
                """Process a single message from the chat history."""
                content = msg["data"]["content"].strip()
                msg_type = msg.get("type")

                if msg_type == "ai" and not msg["data"].get("tool_call") and msg["data"].get("content"):
                    try:
                        validated_msg = AgentOutput.model_validate_json(content)
                        return ChatMessage(
                            placeholder=validated_msg.placeholder,
                            videos=validated_msg.videos,
                            type="ai",
                        )
                    except (JSONDecodeError, ValidationError):
                        return ChatMessage(placeholder=content, videos=None, type="ai")

                elif msg_type == "human":
                    if '"videos":' in content:
                        return None
                    return ChatMessage(placeholder=content, videos=None, type="human")

                return None

            updated_messages = [
                processed_msg
                for msg in messages_to_dict(original_messages)
                if (processed_msg := process_message(msg)) is not None
            ]

            return updated_messages

        except Exception as e:
            logger.error("Failed to fetch chat history", type="error", error=str(e), traceback=traceback.format_exc())
            raise

    async def clear_chat_history(self, user_id: str) -> None:
        """Clear all chat history for a given thread ID.

        Args:
            user_id: The ID of the user to clear history for.

        Raises:
            Exception: If there's an error clearing the chat history.
        """
        try:
            async with AsyncSqliteSaver.from_conn_string(str(settings.CHECKPOINT_DB_PATH)) as checkpointer:
                await checkpointer.setup()
                await checkpointer.adelete_thread(user_id)
            logger.info(f"Cleared chat history for user {user_id}")
        except Exception as e:
            logger.error("Failed to clear chat history", error=str(e), traceback=traceback.format_exc())
            raise


_graph_instance = None


async def get_graph_instance():
    """Get or create the shared AgentGraph instance.

    Returns:
        AgentGraph: The AgentGraph instance.
    """
    global _graph_instance

    if _graph_instance is None:
        logger.info("Creating new AgentGraph instance")
        _graph_instance = AgentGraph()
    return _graph_instance

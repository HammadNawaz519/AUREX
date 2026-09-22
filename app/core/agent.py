"""Autonomous natural language agent loop for AUREX.

Executes: PLAN -> VALIDATE -> EXECUTE -> VERIFY -> RESPOND.
Features local-first privacy routing, semantic memory lookups,
behavior pattern detection, and correction learning.
"""

import re
import json
import logging
import time
from typing import List, Dict, Any, Optional
from app.ai import get_ai_provider
from app.tools.base import get_tool_registry, ToolResult
from app.core.security import is_path_allowed
from app.core.permissions import get_permission_manager, ActionLevel
from app.core.context import get_context
from app.core.events import get_event_bus, AgentState
from app.core.ai_router import get_ai_router, RouteTarget
from app.memory.memory_manager import get_memory_manager
from app.memory.semantic_memory import get_semantic_memory
from app.learning.pattern_detector import get_pattern_detector
from app.learning.correction_learner import get_correction_learner
from app.knowledge.indexer import get_knowledge_indexer
from app.config.settings import get_settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are AUREX, an elite, intelligent, and calm Windows desktop AI assistant.
Your duty is to understand user intents and perform computer operations safely and accurately.

CRITICAL SECURITY RULES:
1. The C: drive is PERMANENTLY READ-ONLY and PROTECTED. NEVER attempt to write, delete, move, create, or overwrite any file on C:.
2. All file modifications (writing, creating, moving, deleting) must strictly target the approved workspace (e.g., D:\\AUREX, D:\\Projects, D:\\OS, D:\\Code).
3. Be calm, concise, and professional. Avoid conversational fluff.
4. If the user asks for a simple action (e.g. 'Open Chrome', 'Take a screenshot'), call the appropriate tool and reply with a brief, calm confirmation.
5. If the user asks for multiple steps (e.g. 'Open VS Code and check RAM'), call all necessary tools in sequence.
"""


class AurexAgent:
    def __init__(self):
        self.registry = get_tool_registry()
        self.context = get_context()
        self.event_bus = get_event_bus()
        self.memory = get_memory_manager()
        self.semantic_memory = get_semantic_memory()
        self.pattern_detector = get_pattern_detector()
        self.correction_learner = get_correction_learner()
        self.ai_router = get_ai_router()
        self.knowledge_indexer = get_knowledge_indexer()

    def process_input(self, user_text: str) -> str:
        """
        Main execution loop for user input with local-first hierarchy.
        """
        clean_text = user_text.strip()
        if not clean_text:
            return "I am listening. How can I assist you?"

        # 1. CORRECTION LEARNING CHECK ("No, I mean D:\OS", "No, use Firefox")
        is_corr, corr_msg = self.correction_learner.inspect_for_correction(clean_text)
        if is_corr:
            self.context.add_turn(clean_text, corr_msg)
            self.memory.add_history("user", clean_text)
            self.memory.add_history("assistant", corr_msg)
            return corr_msg

        # 2. CHECK FOR USER-DEFINED ALIASES ("coding" -> open VS Code)
        alias_action = self.memory.resolve_alias(clean_text)
        if alias_action:
            clean_text = alias_action

        # 3. CONVERSATIONAL ORDINAL RESOLUTION ("open the second one")
        resolved_ref = self.context.resolve_ordinal_reference(clean_text)
        if resolved_ref and any(w in clean_text.lower() for w in ["open", "read", "view", "launch"]):
            if resolved_ref.endswith((".py", ".txt", ".md", ".json", ".csv", ".pdf", ".docx", ".h", ".c")):
                res = self.registry.execute_tool("read_file", {"path": resolved_ref})
                ans = f"Opening {resolved_ref}:\n{res.data[:200]}..." if res.success else str(res.error)
                self.context.add_turn(clean_text, ans, tool_name="read_file", tool_data=resolved_ref)
                self.memory.add_history("user", clean_text)
                self.memory.add_history("assistant", ans)
                return ans

        # 4. PERSONAL CONTEXT & LOCATION MEMORY QUERIES
        # E.g., "Where do I keep my OS project?", "Where is my project?"
        clean_lower = clean_text.lower()
        if any(p in clean_lower for p in ["where do i keep", "where is my", "find my"]):
            matched_path = self.semantic_memory.search_locations(clean_text)
            if matched_path:
                ans = f"According to your saved project memory, it is located at: {matched_path}"
                self.context.add_turn(clean_text, ans)
                return ans

        # 5. WORKFLOW & ROUTINE REQUEST ("Start my usual development setup", "start work")
        matched_routine = self.semantic_memory.search_routines(clean_text)
        if matched_routine and any(w in clean_lower for w in ["start", "launch", "open", "run", "setup"]):
            actions = matched_routine.get("actions", [])
            if actions:
                self.event_bus.publish("state_changed", state=AgentState.EXECUTING)
                summaries = []
                for act in actions:
                    sub_res = self._fallback_local_execute(act)
                    summaries.append(sub_res)
                ans = f"Executed '{matched_routine['name']}':\n" + "\n".join(summaries)
                self.context.add_turn(clean_text, ans)
                self.event_bus.publish("state_changed", state=AgentState.SPEAKING)
                return ans

        # Set state to THINKING
        self.event_bus.publish("state_changed", state=AgentState.THINKING)
        self.event_bus.publish("task_started", task=clean_text)

        # 6. PRIVACY-FIRST AI ROUTER (Cost Optimization & Boundary Check)
        target, route_meta = self.ai_router.classify_request(clean_text)

        # 6A. ROUTE: 100% LOCAL EXECUTION (Zero Cloud Calls)
        if target == RouteTarget.LOCAL:
            local_res = self._fallback_local_execute(clean_text)
            self.context.add_turn(clean_text, local_res)
            self.memory.add_history("user", clean_text)
            self.memory.add_history("assistant", local_res)
            self.event_bus.publish("state_changed", state=AgentState.SPEAKING)
            self.event_bus.publish("task_completed", task=clean_text, result=local_res)
            return local_res

        # 6B. ROUTE: REAL-TIME INTERNET SEARCH
        if target == RouteTarget.INTERNET:
            query = clean_text
            for prefix in ["search the web for", "search for", "google", "look up", "what is the weather"]:
                if clean_lower.startswith(prefix):
                    query = clean_text[len(prefix):].strip()
                    break
            search_res = self.registry.execute_tool("search_web", {"query": query})
            ans = search_res.message if search_res.success else str(search_res.error)
            self.context.add_turn(clean_text, ans)
            self.memory.add_history("user", clean_text)
            self.memory.add_history("assistant", ans)
            self.event_bus.publish("state_changed", state=AgentState.SPEAKING)
            self.event_bus.publish("task_completed", task=clean_text, result=ans)
            return ans

        # 6C. ROUTE: LOCAL + GROQ (Summarize/Explain local files using local indexer excerpt)
        if target == RouteTarget.LOCAL_AND_GROQ:
            knowledge_matches = self.knowledge_indexer.search_local_knowledge(clean_text, limit=2)
            context_excerpt = ""
            if knowledge_matches:
                context_excerpt = f"\n[Local Document Excerpt: {knowledge_matches[0]['file_name']}]\n{knowledge_matches[0]['summary']}\n"
            clean_text = f"{clean_text}\n{context_excerpt}"

        # 6D. ROUTE: GROQ CLOUD REASONING
        try:
            provider = get_ai_provider()
            schemas = self.registry.get_schemas()
            history = self.context.get_context_summary()
            messages = list(history)
            messages.append({"role": "user", "content": clean_text})

            response = provider.chat_complete(
                messages=messages,
                tools=schemas,
                system_prompt=SYSTEM_PROMPT,
                temperature=0.1
            )

            tool_calls = response.get("tool_calls", [])
            response_text = response.get("text", "").strip()

            if tool_calls:
                self.event_bus.publish("state_changed", state=AgentState.EXECUTING)
                execution_summaries = []
                last_tool_data = None
                last_tool_name = None

                for tc in tool_calls:
                    fname = tc["name"]
                    fargs = tc["arguments"]
                    self.event_bus.publish("task_step", step=f"Running {fname}...")

                    result: ToolResult = self.registry.execute_tool(fname, fargs)
                    last_tool_name = fname
                    last_tool_data = result.data

                    if result.success:
                        execution_summaries.append(result.message or f"Completed {fname}.")
                        self.memory.log_activity(fname, "SUCCESS", result.message or f"Executed {fname}")
                        # Feed into behavior tracker for continuous self-learning
                        self.pattern_detector.record_and_analyze(
                            action_type=fname,
                            application=fargs.get("name"),
                            target_path=fargs.get("path") or fargs.get("destination"),
                            command=fargs.get("command"),
                            result_status="SUCCESS"
                        )
                    else:
                        err_msg = result.error or "Action failed."
                        execution_summaries.append(f"{fname}: {err_msg}")
                        self.memory.log_activity(fname, "FAILED", err_msg)

                final_answer = "\n".join(execution_summaries)
                if response_text and not final_answer:
                    final_answer = response_text

                self.context.add_turn(clean_text, final_answer, tool_name=last_tool_name, tool_data=last_tool_data)
                self.memory.add_history("user", clean_text)
                self.memory.add_history("assistant", final_answer)

                self.event_bus.publish("state_changed", state=AgentState.SPEAKING)
                self.event_bus.publish("task_completed", task=clean_text, result=final_answer)
                return final_answer

            elif response_text:
                self.context.add_turn(clean_text, response_text)
                self.memory.add_history("user", clean_text)
                self.memory.add_history("assistant", response_text)

                self.event_bus.publish("state_changed", state=AgentState.SPEAKING)
                self.event_bus.publish("task_completed", task=clean_text, result=response_text)
                return response_text

        except Exception as e:
            logger.warning(f"AI Provider execution failed, falling back to local heuristic intent parser: {e}")

        # Fallback local execution
        fallback_res = self._fallback_local_execute(clean_text)
        self.context.add_turn(clean_text, fallback_res)
        self.memory.add_history("user", clean_text)
        self.memory.add_history("assistant", fallback_res)

        self.event_bus.publish("state_changed", state=AgentState.SPEAKING)
        self.event_bus.publish("task_completed", task=clean_text, result=fallback_res)
        return fallback_res

    def _fallback_local_execute(self, text: str) -> str:
        """Local offline rule-based intent engine when in LOCAL mode or offline."""
        clean = text.lower().strip()

        # Check system info / CPU / RAM
        if any(k in clean for k in ["cpu", "ram", "memory", "usage", "system info", "performance"]):
            res = self.registry.execute_tool("get_system_information", {})
            return res.message if res.success else str(res.error)

        # Screenshot
        if any(k in clean for k in ["screenshot", "capture screen", "screen shot"]):
            res = self.registry.execute_tool("take_screenshot", {})
            return res.message if res.success else str(res.error)

        # Open Application
        open_match = re.match(r"(?:open|launch|start)\s+(chrome|vscode|vs code|code|notepad|calculator|calc|spotify|discord|terminal)", clean)
        if open_match:
            app_name = open_match.group(1)
            res = self.registry.execute_tool("open_application", {"name": app_name})
            if res.success:
                self.pattern_detector.record_and_analyze(action_type="open_application", application=app_name)
            return res.message if res.success else str(res.error)

        # Close Application
        close_match = re.match(r"(?:close|exit|quit|kill)\s+([a-zA-Z0-9_\-\.]+)", clean)
        if close_match:
            app_name = close_match.group(1)
            res = self.registry.execute_tool("close_application", {"name": app_name})
            return res.message if res.success else str(res.error)

        # Open URL
        url_match = re.search(r"(?:open|visit|go to)\s+(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9-]+\.(?:com|org|io|dev|net))", clean)
        if url_match:
            url = url_match.group(1)
            res = self.registry.execute_tool("open_url", {"url": url})
            return res.message if res.success else str(res.error)

        # Web Search
        search_match = re.match(r"(?:search|google|find on web|look up)\s+(.+)", clean)
        if search_match:
            q = search_match.group(1)
            res = self.registry.execute_tool("search_web", {"query": q})
            return res.message if res.success else str(res.error)

        # Create folder
        folder_match = re.match(r"(?:create|make)\s+(?:a\s+)?folder\s+(?:called\s+)?([^\s]+)(?:\s+on\s+([a-zA-Z]:[^\s]*))?", clean)
        if folder_match:
            name = folder_match.group(1)
            loc = folder_match.group(2)
            settings = get_settings()
            base_dir = loc if loc else settings.workspace_root
            target = f"{base_dir}\\{name}"
            res = self.registry.execute_tool("create_folder", {"path": target})
            return res.message if res.success else str(res.error)

        # Search files
        if "find" in clean and ("project" in clean or "file" in clean or "python" in clean):
            query = "*.py" if "python" in clean else "*.*"
            res = self.registry.execute_tool("search_files", {"query": query})
            return res.message if res.success else str(res.error)

        return (
            "I heard your request. Local intelligence processed your query; "
            "basic computer tools (Open Chrome, Check CPU/RAM, Take Screenshot, Search Web) remain active."
        )


_global_agent = AurexAgent()

def get_agent() -> AurexAgent:
    return _global_agent

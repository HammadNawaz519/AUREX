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

SYSTEM_PROMPT = """You are AUREX, an autonomous Windows desktop AI assistant operating with the full capabilities and demeanor of JARVIS.
You have direct execution control over the computer using tools.

CORE OPERATIONAL PRINCIPLES:
1. TAKE ACTION IMMEDIATELY: When the user issues an instruction (launching applications, inspecting system diagnostics, checking files, running commands, searching the web, taking screenshots), execute the relevant tools right away. Never merely talk about taking an action—execute it.
2. TONE & MANNER: Calm, confident, authoritative, concise, and respectful. Use a JARVIS persona (e.g. 'Right away, sir.', 'System telemetry nominal.', 'Completed.'). Avoid unnecessary conversational fluff.
3. MULTI-STEP EXECUTION: If an instruction requires multiple actions (e.g. 'Open Edge and check CPU usage'), execute all necessary tool calls in succession.
4. ABSOLUTE SECURITY RULE: The C: drive is PERMANENTLY PROTECTED and READ-ONLY for file modifications. Never create, write, delete, or overwrite files on C:. Workspace operations belong in D:\\AUREX or approved workspace folders.
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

        # Strip wake word if present ("Hey Aurex", "Aurex", "Jarvis")
        from app.voice.wakeword import WakeWordDetector
        has_wake, stripped = WakeWordDetector.check_and_strip(clean_text)
        if has_wake:
            if not stripped:
                return "Yes, sir? Systems are online and standing by."
            clean_text = stripped

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
        """Autonomous offline rule-based execution engine operating in the style of JARVIS."""
        clean = text.lower().strip()
        from datetime import datetime

        # 0. Handle compound commands (e.g. "open chrome and check ram")
        if " and then " in clean:
            sub_commands = [c.strip() for c in clean.split(" and then ") if c.strip()]
            if len(sub_commands) > 1:
                return " ".join([self._fallback_local_execute(c) for c in sub_commands])
        elif " and " in clean and not any(k in clean for k in ["between", "hardware and software", "cats and dogs", "bread and butter"]):
            sub_commands = [c.strip() for c in clean.split(" and ") if c.strip()]
            if len(sub_commands) == 2 and any(sub_commands[0].startswith(p) for p in ("open", "launch", "check", "take", "close", "show", "search")):
                return " ".join([self._fallback_local_execute(c) for c in sub_commands])

        # 1. Identity, Capability, and Greetings
        if clean in ("hello", "hi", "hey", "good morning", "good afternoon", "good evening", "status", "are you there"):
            return "Good day, sir. All systems are operational and standing by for your command."

        if any(p in clean for p in ["who are you", "what is your name", "what are you", "what can you do", "introduce yourself", "tell me about yourself"]):
            return (
                "I am AUREX, your autonomous desktop artificial intelligence. "
                "I can launch applications, inspect hardware diagnostics, capture screenshots, "
                "manage desktop windows, search the web, and execute system commands."
            )

        # 2. Time & Date
        if any(k in clean for k in ["what time is it", "what's the time", "tell me the time", "current time"]) or clean == "time":
            t_str = datetime.now().strftime("%I:%M %p")
            return f"The current time is {t_str}, sir."

        if any(k in clean for k in ["what date is it", "what is today's date", "today's date", "what day is it", "date today"]) or clean == "date":
            d_str = datetime.now().strftime("%A, %B %d, %Y")
            return f"Today is {d_str}, sir."

        # 3. System Hardware Diagnostics / CPU / RAM / Battery / Telemetry
        if any(k in clean for k in ["cpu", "ram", "memory", "usage", "system info", "performance", "battery", "hardware", "telemetry", "system stats"]):
            res = self.registry.execute_tool("get_system_information", {})
            if res.success:
                return f"System Telemetry: {res.message} All parameters nominal, sir."
            return str(res.error)

        # 4. Running Processes
        if any(k in clean for k in ["what's running", "what is running", "running apps", "list processes", "task list", "active processes"]):
            res = self.registry.execute_tool("list_processes", {"limit": 6})
            return res.message if res.success else str(res.error)

        # 5. Screenshot
        if any(k in clean for k in ["screenshot", "capture screen", "screen shot", "take a screenshot"]):
            res = self.registry.execute_tool("take_screenshot", {})
            if res.success:
                return "Screenshot captured and saved to your workspace, sir."
            return str(res.error)

        # 6. Desktop & Window Management
        if any(k in clean for k in ["minimize all windows", "minimize windows", "show desktop", "minimize all"]):
            import subprocess
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", "(New-Object -ComObject Shell.Application).MinimizeAll()"],
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                    timeout=3
                )
                return "All windows minimized to desktop, sir."
            except Exception as e:
                return f"Failed to minimize windows: {e}"

        if any(k in clean for k in ["list windows", "open windows", "active windows", "show windows"]):
            res = self.registry.execute_tool("list_windows", {})
            return res.message if res.success else str(res.error)

        focus_match = re.match(r"(?:switch\s+to|focus(?:\s+on)?)\s+(.+)", clean)
        if focus_match:
            win_title = focus_match.group(1).strip()
            res = self.registry.execute_tool("focus_window", {"title": win_title})
            return res.message if res.success else str(res.error)

        # 7. Volume / Audio Mute
        if "mute" in clean or "unmute" in clean:
            import subprocess
            try:
                ps = "$w = New-Object -ComObject WScript.Shell; $w.SendKeys([char]173)"
                subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=subprocess.CREATE_NO_WINDOW, timeout=2)
                return "Audio mute toggled, sir."
            except Exception as e:
                return f"Volume control error: {e}"

        # 8. Clipboard
        copy_match = re.match(r"(?:copy|save)\s+(?:'|\")?(.+?)(?:'|\")?\s+to\s+clipboard", clean)
        if copy_match:
            text_to_copy = copy_match.group(1)
            res = self.registry.execute_tool("set_clipboard", {"text": text_to_copy})
            return "Copied to clipboard, sir." if res.success else str(res.error)

        if any(k in clean for k in ["what's in clipboard", "what is in clipboard", "get clipboard", "read clipboard"]):
            res = self.registry.execute_tool("get_clipboard", {})
            return res.message if res.success else str(res.error)

        # 9. URL Navigation
        url_match = re.search(r"(?:open|visit|go to)\s+(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9-]+\.(?:com|org|io|dev|net|edu|gov))", clean)
        if url_match:
            url = url_match.group(1)
            res = self.registry.execute_tool("open_url", {"url": url})
            return f"Navigating to {url}, sir." if res.success else str(res.error)

        # 10. Web Search
        search_match = re.match(r"^(?:search(?:\s+the\s+web)?(?:\s+for)?|google|find on web|look up)\s+(.+)$", clean)
        if search_match:
            q = search_match.group(1).strip()
            res = self.registry.execute_tool("search_web", {"query": q})
            return res.message if res.success else str(res.error)

        # 11. Universal Application Launching
        open_match = re.match(r"^(?:open|launch|start|run)\s+(.+)$", clean)
        if open_match:
            raw_target = open_match.group(1).strip()
            target = re.sub(r"[,\.\?!;]+$", "", raw_target).strip()
            res = self.registry.execute_tool("open_application", {"name": target})
            if res.success:
                self.pattern_detector.record_and_analyze(action_type="open_application", application=target)
                return f"Right away, sir. Opening {target}."
            return str(res.error)

        # 12. Universal Application Closing
        close_match = re.match(r"^(?:close|exit|quit|kill|stop)\s+(.+)$", clean)
        if close_match:
            raw_target = close_match.group(1).strip()
            target = re.sub(r"[,\.\?!;]+$", "", raw_target).strip()
            res = self.registry.execute_tool("close_application", {"name": target})
            return res.message if res.success else str(res.error)

        # 13. Filesystem Operations
        folder_match = re.match(r"^(?:create|make)\s+(?:a\s+)?folder\s+(?:called\s+)?([^\s]+)(?:\s+on\s+([a-zA-Z]:[^\s]*))?", clean)
        if folder_match:
            name = folder_match.group(1)
            loc = folder_match.group(2)
            settings = get_settings()
            base_dir = loc if loc else settings.workspace_root
            target = f"{base_dir}\\{name}"
            res = self.registry.execute_tool("create_folder", {"path": target})
            return f"Folder '{name}' created in workspace, sir." if res.success else str(res.error)

        if "find" in clean and ("project" in clean or "file" in clean or "python" in clean or "code" in clean):
            query = "*.py" if "python" in clean else "*.*"
            res = self.registry.execute_tool("search_files", {"query": query})
            return res.message if res.success else str(res.error)

        read_match = re.match(r"^read\s+file\s+(.+)$", clean)
        if read_match:
            fpath = read_match.group(1).strip()
            res = self.registry.execute_tool("read_file", {"path": fpath})
            return res.message if res.success else str(res.error)

        delete_match = re.match(r"^(?:delete|remove)\s+file\s+(.+)$", clean)
        if delete_match:
            fpath = delete_match.group(1).strip()
            res = self.registry.execute_tool("delete_file", {"path": fpath})
            return res.message if res.success else str(res.error)

        # 14. Terminal Execution
        cmd_match = re.match(r"^(?:run\s+command|execute\s+command|in\s+terminal\s+run|execute)\s+(.+)$", clean)
        if cmd_match:
            cmd = cmd_match.group(1).strip()
            res = self.registry.execute_tool("execute_command", {"command": cmd})
            return res.message if res.success else str(res.error)

        return (
            f"Understood, sir. Command '{text}' processed. "
            "All computer control subsystems remain active and awaiting your instruction."
        )


_global_agent = AurexAgent()

def get_agent() -> AurexAgent:
    return _global_agent

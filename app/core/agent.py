"""Autonomous natural language agent loop for AUREX.

Full capability agent: PERCEIVE → UNDERSTAND → PLAN → ACT → VERIFY → LEARN.
Integrates voice, screen understanding, task planning, and computer-use tools.
"""

import re
import json
import logging
import time
import sys
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

SYSTEM_PROMPT = """You are AUREX, an autonomous Windows desktop AI assistant built specifically for Hammad.
You are the equivalent of JARVIS: exceptionally intelligent, fast, perceptive, proactive, and calm.

CORE PRINCIPLES:
1. PERSONALIZED: You serve Hammad. Be polite, confident, and articulate ("Right away, Hammad.", "On it, Hammad.", "Understood, Hammad.").
2. CONCISE FOR SPEECH: Keep spoken responses natural and concise (1 to 2 clear, direct sentences). Never recite long bullet lists or code aloud unless specifically asked.
3. EXECUTE PROACTIVELY: If Hammad asks to open an app, search, or perform an action, execute it directly with tools immediately.
4. SCREEN & VISION: When asked to analyze the screen, assignments, or windows, identify key buttons, text, and tasks with precision.
5. FAST & SHARP: Do not hesitate or overcomplicate simple tasks. Provide instant, high-intelligence answers.
"""

# ─── Intent Classification ──────────────────────────────────────────────────────

SCREEN_INTENT_PATTERNS = [
    r"look at\s+(my\s+)?(screen|this|assignment|page|document|window)",
    r"read\s+(this|the|my)\s+(assignment|document|page|screen|file)",
    r"what('s| is)\s+(on|visible|showing|displayed)",
    r"analyze\s+(my\s+)?(screen|this)",
    r"do\s+(everything|all\s+the\s+tasks?|what\s+it\s+says|the\s+assignment)",
    r"complete\s+(this|the|my)\s+(assignment|task|form|setup)",
    r"fill\s+(this|the|in)\s+form",
    r"click\s+(the|on)",
    r"scroll\s+(down|up|to)",
    r"type\s+(in|into)",
    r"find\s+(the|a)\s+(button|link|field|input)",
]

PLAN_INTENT_PATTERNS = [
    r"create\s+a?\s*plan",
    r"step\s+by\s+step",
    r"(do|complete)\s+(everything|all)",
    r"do\s+this\s+(assignment|task|project)",
    r"automate\s+",
    r"help\s+me\s+(complete|do|finish)",
]


def _needs_screen(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in SCREEN_INTENT_PATTERNS)

def _needs_plan(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in PLAN_INTENT_PATTERNS)


# ─── Main Agent ─────────────────────────────────────────────────────────────────

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

        # Screen awareness state
        self._screen_aware: bool = False
        self._screen_awareness_auto_off: bool = True  # disable after task

    # ─── Screen Awareness Toggle ─────────────────────────────────────────────

    def enable_screen_awareness(self):
        """Enable screen capture and understanding."""
        try:
            from app.vision.screen_understanding import get_screen_understanding_service
            svc = get_screen_understanding_service()
            svc.enable()
            self._screen_aware = True
            self.event_bus.publish("screen_aware_changed", active=True)
            logger.info("Screen awareness enabled.")
        except Exception as e:
            logger.warning(f"Screen awareness enable failed: {e}")

    def disable_screen_awareness(self):
        try:
            from app.vision.screen_understanding import get_screen_understanding_service
            get_screen_understanding_service().disable()
            self._screen_aware = False
            self.event_bus.publish("screen_aware_changed", active=False)
        except Exception:
            pass

    @property
    def is_screen_aware(self) -> bool:
        return self._screen_aware

    # ─── Main Process Loop ───────────────────────────────────────────────────

    def process_input(self, user_text: str) -> str:
        """Main AUREX execution loop: PERCEIVE → UNDERSTAND → PLAN → ACT → VERIFY → LEARN."""
        clean_text = user_text.strip()
        if not clean_text:
            return "I am listening. How can I assist you, sir?"

        # Strip wake word
        from app.voice.wakeword import WakeWordDetector
        has_wake, stripped = WakeWordDetector.check_and_strip(clean_text)
        if has_wake:
            if not stripped:
                return "Yes, sir. Systems are online and standing by."
            clean_text = stripped

        # Toggle commands
        lower = clean_text.lower()
        if any(p in lower for p in ["enable screen awareness", "screen aware on", "turn on screen awareness", "activate screen"]):
            self.enable_screen_awareness()
            return "Screen awareness activated. I can now see and understand your display, sir."

        if any(p in lower for p in ["disable screen awareness", "screen aware off", "turn off screen awareness", "stop watching"]):
            self.disable_screen_awareness()
            return "Screen awareness deactivated. Your display is private, sir."

        # Correction check
        is_corr, corr_msg = self.correction_learner.inspect_for_correction(clean_text)
        if is_corr:
            self.context.add_turn(clean_text, corr_msg)
            self.memory.add_history("user", clean_text)
            self.memory.add_history("assistant", corr_msg)
            return corr_msg

        # Alias resolution
        alias_action = self.memory.resolve_alias(clean_text)
        if alias_action:
            clean_text = alias_action

        # Ordinal reference resolution
        resolved_ref = self.context.resolve_ordinal_reference(clean_text)
        if resolved_ref and any(w in lower for w in ["open", "read", "view", "launch"]):
            if resolved_ref.endswith((".py", ".txt", ".md", ".json", ".csv", ".pdf", ".docx")):
                res = self.registry.execute_tool("read_file", {"path": resolved_ref})
                ans = f"Opening {resolved_ref}:\n{res.data[:200]}..." if res.success else str(res.error)
                self.context.add_turn(clean_text, ans, tool_name="read_file", tool_data=resolved_ref)
                self.memory.add_history("user", clean_text)
                self.memory.add_history("assistant", ans)
                return ans

        # Personal memory
        if any(p in lower for p in ["where do i keep", "where is my", "find my"]):
            matched_path = self.semantic_memory.search_locations(clean_text)
            if matched_path:
                ans = f"According to your saved project memory, it is at: {matched_path}"
                self.context.add_turn(clean_text, ans)
                return ans

        # Workflow/routine
        matched_routine = self.semantic_memory.search_routines(clean_text)
        if matched_routine and any(w in lower for w in ["start", "launch", "open", "run", "setup"]):
            actions = matched_routine.get("actions", [])
            if actions:
                self.event_bus.publish("state_changed", state=AgentState.EXECUTING)
                summaries = [self._fallback_local_execute(act) for act in actions]
                ans = f"Executed '{matched_routine['name']}':\n" + "\n".join(summaries)
                self.context.add_turn(clean_text, ans)
                self.event_bus.publish("state_changed", state=AgentState.SPEAKING)
                return ans

        self.event_bus.publish("state_changed", state=AgentState.THINKING)
        self.event_bus.publish("task_started", task=clean_text)

        # ── Screen-aware path ────────────────────────────────────────────────
        if _needs_screen(clean_text):
            return self._screen_aware_execute(clean_text)

        # ── Plan path ────────────────────────────────────────────────────────
        if _needs_plan(clean_text):
            return self._planned_execute(clean_text)

        # ── Standard AI routing ──────────────────────────────────────────────
        target, route_meta = self.ai_router.classify_request(clean_text)

        if target == RouteTarget.LOCAL:
            local_res = self._fallback_local_execute(clean_text)
            self.context.add_turn(clean_text, local_res)
            self.memory.add_history("user", clean_text)
            self.memory.add_history("assistant", local_res)
            self.event_bus.publish("state_changed", state=AgentState.SPEAKING)
            self.event_bus.publish("task_completed", task=clean_text, result=local_res)
            return local_res

        if target == RouteTarget.INTERNET:
            query = clean_text
            for prefix in ["search the web for", "search for", "google", "look up"]:
                if lower.startswith(prefix):
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

        if target == RouteTarget.LOCAL_AND_GROQ:
            knowledge_matches = self.knowledge_indexer.search_local_knowledge(clean_text, limit=2)
            if knowledge_matches:
                excerpt = f"\n[Local Document: {knowledge_matches[0]['file_name']}]\n{knowledge_matches[0]['summary']}\n"
                clean_text = f"{clean_text}\n{excerpt}"

        # Cloud AI reasoning
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
                        self.memory.log_activity(fname, "SUCCESS", result.message or "")
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
            logger.warning(f"AI provider failed, falling back to local: {e}")

        fallback_res = self._fallback_local_execute(clean_text)
        self.context.add_turn(clean_text, fallback_res)
        self.memory.add_history("user", clean_text)
        self.memory.add_history("assistant", fallback_res)
        self.event_bus.publish("state_changed", state=AgentState.SPEAKING)
        self.event_bus.publish("task_completed", task=clean_text, result=fallback_res)
        return fallback_res

    # ─── Screen-Aware Execution ──────────────────────────────────────────────

    def _screen_aware_execute(self, command: str) -> str:
        """
        OBSERVE → UNDERSTAND → PLAN → ACT → VERIFY
        Used when command requires screen perception.
        """
        # Auto-enable screen awareness if needed
        if not self._screen_aware:
            self.enable_screen_awareness()
            auto_enabled = True
        else:
            auto_enabled = False

        self.event_bus.publish("state_changed", state=AgentState.THINKING)

        try:
            from app.vision.screen_understanding import get_screen_understanding_service
            svc = get_screen_understanding_service()

            # OBSERVE
            self.event_bus.publish("task_step", step="Capturing screen...")
            screen_state = svc.capture_now()
            screen_context = screen_state.to_agent_context() if screen_state else "Screen capture unavailable."

            # Detect if this is a "read/scroll" task
            lower = command.lower()
            if any(k in lower for k in ["read", "scroll through", "go through", "look through"]):
                self.event_bus.publish("task_step", step="Reading document...")
                full_text = svc.scroll_and_read()
                if full_text:
                    screen_context = f"Full document content:\n{full_text[:3000]}"

            # PLAN for complex tasks
            if _needs_plan(command):
                return self._planned_execute(command, screen_context=screen_context)

            # Direct AI reasoning with screen context
            augmented_command = f"{command}\n\n[Screen State]\n{screen_context}"
            self.event_bus.publish("state_changed", state=AgentState.THINKING)

            try:
                provider = get_ai_provider()
                schemas = self.registry.get_schemas()
                response = provider.chat_complete(
                    messages=[{"role": "user", "content": augmented_command}],
                    tools=schemas,
                    system_prompt=SYSTEM_PROMPT,
                    temperature=0.1,
                )

                tool_calls = response.get("tool_calls", [])
                response_text = response.get("text", "").strip()

                if tool_calls:
                    self.event_bus.publish("state_changed", state=AgentState.EXECUTING)
                    results = []
                    for tc in tool_calls:
                        res = self.registry.execute_tool(tc["name"], tc["arguments"])
                        results.append(res.message if res.success else str(res.error))
                    answer = "\n".join(results) or response_text
                    self.event_bus.publish("state_changed", state=AgentState.SPEAKING)
                    self.event_bus.publish("task_completed", task=command, result=answer)
                    return answer

                if response_text:
                    self.event_bus.publish("state_changed", state=AgentState.SPEAKING)
                    self.event_bus.publish("task_completed", task=command, result=response_text)
                    return response_text

            except Exception as e:
                logger.warning(f"Screen-aware AI call failed: {e}")

            # Fallback with screen info
            ans = f"Screen captured. {screen_context[:300]}..."
            self.event_bus.publish("state_changed", state=AgentState.SPEAKING)
            return ans

        finally:
            if auto_enabled and self._screen_awareness_auto_off:
                self.disable_screen_awareness()

    # ─── Planned Execution ───────────────────────────────────────────────────

    def _planned_execute(self, command: str, screen_context: str = "") -> str:
        """Create and execute a structured multi-step plan."""
        from app.core.planner import get_task_planner

        self.event_bus.publish("state_changed", state=AgentState.THINKING)

        planner = get_task_planner()

        # Enable screen for planning if needed
        if not self._screen_aware and not screen_context:
            self.enable_screen_awareness()
            try:
                from app.vision.screen_understanding import get_screen_understanding_service
                state = get_screen_understanding_service().capture_now()
                if state:
                    screen_context = state.to_agent_context()
            except Exception:
                pass

        self.event_bus.publish("task_step", step="Building task plan...")
        plan = planner.create_plan_from_ai(command, screen_context=screen_context)

        # Announce plan
        plan_display = plan.to_display()
        self.event_bus.publish("plan_created", plan=plan_display)
        self.event_bus.publish("state_changed", state=AgentState.EXECUTING)

        # Execute
        result = planner.execute_plan(plan)

        if self._screen_awareness_auto_off:
            self.disable_screen_awareness()

        self.event_bus.publish("state_changed", state=AgentState.SPEAKING)
        self.event_bus.publish("task_completed", task=command, result=result)
        return result

    # ─── Local Fallback Engine ───────────────────────────────────────────────

    def _fallback_local_execute(self, text: str) -> str:
        """Autonomous offline rule-based execution engine, JARVIS style."""
        clean = text.lower().strip()
        from datetime import datetime

        # Compound commands
        if " and then " in clean:
            parts = [c.strip() for c in clean.split(" and then ") if c.strip()]
            if len(parts) > 1:
                return " ".join([self._fallback_local_execute(c) for c in parts])
        elif " and " in clean and not any(k in clean for k in ["between", "hardware and software", "bread and butter"]):
            parts = [c.strip() for c in clean.split(" and ") if c.strip()]
            if len(parts) == 2 and any(parts[0].startswith(p) for p in ("open", "launch", "check", "take", "close", "show", "search")):
                return " ".join([self._fallback_local_execute(c) for c in parts])

        # Identity & greetings
        if clean in ("hello", "hi", "hey", "good morning", "good afternoon", "good evening", "status", "are you there"):
            return "Good day, sir. All systems are operational and standing by for your command."

        if any(p in clean for p in ["who are you", "what is your name", "what are you", "what can you do", "introduce yourself"]):
            return (
                "I am AUREX, your autonomous desktop intelligence. "
                "I can see your screen, control applications, plan and execute complex tasks, "
                "browse the web, manage files, and learn your workflows. "
                "Simply say 'Hey AUREX' or double-clap to wake me at any time, sir."
            )

        # Time & date
        if any(k in clean for k in ["what time", "current time", "tell me the time"]) or clean == "time":
            return f"The current time is {datetime.now().strftime('%I:%M %p')}, sir."

        if any(k in clean for k in ["what date", "today's date", "what day"]) or clean == "date":
            return f"Today is {datetime.now().strftime('%A, %B %d, %Y')}, sir."

        # Screen awareness commands
        if any(k in clean for k in ["enable screen", "screen aware", "activate screen", "watch screen"]):
            self.enable_screen_awareness()
            return "Screen awareness activated. I can now see your display, sir."

        if any(k in clean for k in ["disable screen", "stop screen", "screen off", "stop watching"]):
            self.disable_screen_awareness()
            return "Screen awareness deactivated, sir."

        if any(k in clean for k in ["what's on screen", "what is on screen", "read screen", "analyze screen"]):
            return self._screen_aware_execute(text)

        # System diagnostics
        if any(k in clean for k in ["cpu", "ram", "memory", "usage", "system info", "performance", "battery", "hardware", "telemetry"]):
            res = self.registry.execute_tool("get_system_information", {})
            return f"System Telemetry: {res.message} All parameters nominal, sir." if res.success else str(res.error)

        # Processes
        if any(k in clean for k in ["what's running", "running apps", "list processes", "task list"]):
            res = self.registry.execute_tool("list_processes", {"limit": 6})
            return res.message if res.success else str(res.error)

        # Screenshot
        if any(k in clean for k in ["screenshot", "capture screen", "take a screenshot"]):
            res = self.registry.execute_tool("take_screenshot", {})
            return "Screenshot captured and saved to workspace, sir." if res.success else str(res.error)

        # Window management
        if any(k in clean for k in ["minimize all", "show desktop"]):
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

        if any(k in clean for k in ["list windows", "open windows", "active windows"]):
            res = self.registry.execute_tool("list_windows", {})
            return res.message if res.success else str(res.error)

        focus_match = re.match(r"(?:switch\s+to|focus(?:\s+on)?)\s+(.+)", clean)
        if focus_match:
            win_title = focus_match.group(1).strip()
            res = self.registry.execute_tool("focus_window", {"title": win_title})
            return res.message if res.success else str(res.error)

        # Volume
        if "mute" in clean or "unmute" in clean:
            import subprocess
            try:
                ps = "$w = New-Object -ComObject WScript.Shell; $w.SendKeys([char]173)"
                subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=2)
                return "Audio mute toggled, sir."
            except Exception as e:
                return f"Volume control error: {e}"

        # Clipboard
        copy_match = re.match(r"(?:copy|save)\s+(?:'|\")?(.+?)(?:'|\")?\s+to\s+clipboard", clean)
        if copy_match:
            res = self.registry.execute_tool("set_clipboard", {"text": copy_match.group(1)})
            return "Copied to clipboard, sir." if res.success else str(res.error)

        if any(k in clean for k in ["what's in clipboard", "get clipboard", "read clipboard"]):
            res = self.registry.execute_tool("get_clipboard", {})
            return res.message if res.success else str(res.error)

        # URL
        url_match = re.search(r"(?:open|visit|go to)\s+(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9-]+\.(?:com|org|io|dev|net|edu|gov))", clean)
        if url_match:
            url = url_match.group(1)
            res = self.registry.execute_tool("open_url", {"url": url})
            return f"Navigating to {url}, sir." if res.success else str(res.error)

        # Web search
        search_match = re.match(r"^(?:search(?:\s+the\s+web)?(?:\s+for)?|google|find on web|look up)\s+(.+)$", clean)
        if search_match:
            res = self.registry.execute_tool("search_web", {"query": search_match.group(1).strip()})
            return res.message if res.success else str(res.error)

        # App launch
        open_match = re.match(r"^(?:open|launch|start|run)\s+(.+)$", clean)
        if open_match:
            target = re.sub(r"[,\.?!;]+$", "", open_match.group(1).strip())
            res = self.registry.execute_tool("open_application", {"name": target})
            if res.success:
                self.pattern_detector.record_and_analyze(action_type="open_application", application=target)
                return f"Right away, sir. Opening {target}."
            return str(res.error)

        # App close
        close_match = re.match(r"^(?:close|exit|quit|kill|stop)\s+(.+)$", clean)
        if close_match:
            target = re.sub(r"[,\.?!;]+$", "", close_match.group(1).strip())
            res = self.registry.execute_tool("close_application", {"name": target})
            return res.message if res.success else str(res.error)

        # Folder creation
        folder_match = re.match(r"^(?:create|make)\s+(?:a\s+)?folder\s+(?:called\s+)?([^\s]+)(?:\s+on\s+([a-zA-Z]:[^\s]*))?", clean)
        if folder_match:
            name = folder_match.group(1)
            loc = folder_match.group(2)
            settings = get_settings()
            base_dir = loc if loc else settings.workspace_root
            res = self.registry.execute_tool("create_folder", {"path": f"{base_dir}\\{name}"})
            return f"Folder '{name}' created, sir." if res.success else str(res.error)

        # File read
        read_match = re.match(r"^read\s+file\s+(.+)$", clean)
        if read_match:
            res = self.registry.execute_tool("read_file", {"path": read_match.group(1).strip()})
            return res.message if res.success else str(res.error)

        # File delete
        delete_match = re.match(r"^(?:delete|remove)\s+file\s+(.+)$", clean)
        if delete_match:
            res = self.registry.execute_tool("delete_file", {"path": delete_match.group(1).strip()})
            return res.message if res.success else str(res.error)

        # Terminal
        cmd_match = re.match(r"^(?:run\s+command|execute\s+command|in\s+terminal\s+run|execute)\s+(.+)$", clean)
        if cmd_match:
            res = self.registry.execute_tool("execute_command", {"command": cmd_match.group(1).strip()})
            return res.message if res.success else str(res.error)

        return (
            f"Understood, sir. Awaiting your instruction. "
            "Say 'Hey AUREX, enable screen awareness' to let me see your display, "
            "or give me a specific command."
        )


_global_agent = AurexAgent()

def get_agent() -> AurexAgent:
    return _global_agent

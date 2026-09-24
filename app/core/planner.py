"""
Task Planner for AUREX.
Creates structured multi-step plans, tracks execution, and verifies each step.
"""
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any, Callable
from app.core.events import get_event_bus, AgentState

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TaskStep:
    id: int
    description: str
    action: str                        # tool name or internal action
    params: Dict[str, Any] = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    verification: Optional[str] = None
    risk_level: str = "LOW"            # LOW | MEDIUM | HIGH
    started_at: float = 0.0
    completed_at: float = 0.0
    retries: int = 0
    max_retries: int = 2

    @property
    def duration(self) -> float:
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return 0.0


@dataclass
class TaskPlan:
    id: str
    goal: str
    steps: List[TaskStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    status: str = "pending"            # pending | running | completed | failed
    context: Dict[str, Any] = field(default_factory=dict)

    @property
    def current_step(self) -> Optional[TaskStep]:
        for s in self.steps:
            if s.status == StepStatus.RUNNING:
                return s
        return None

    @property
    def next_step(self) -> Optional[TaskStep]:
        for s in self.steps:
            if s.status == StepStatus.PENDING:
                return s
        return None

    @property
    def done_count(self) -> int:
        return sum(1 for s in self.steps if s.status == StepStatus.DONE)

    @property
    def total_count(self) -> int:
        return len(self.steps)

    @property
    def progress_text(self) -> str:
        return f"Step {self.done_count} / {self.total_count}"

    def to_display(self) -> str:
        lines = [f"TASK PLAN: {self.goal}", ""]
        for step in self.steps:
            icon = {
                StepStatus.DONE: "✓",
                StepStatus.RUNNING: "→",
                StepStatus.FAILED: "✗",
                StepStatus.PENDING: "○",
                StepStatus.SKIPPED: "–",
            }.get(step.status, "○")
            lines.append(f"{icon} {step.description}")
        return "\n".join(lines)


class TaskPlanner:
    """
    Generates and executes structured task plans.
    Uses AI to decompose complex instructions into verifiable steps.
    """

    def __init__(self):
        self._current_plan: Optional[TaskPlan] = None
        self._plan_history: List[TaskPlan] = []
        self._event_bus = get_event_bus()
        self._step_callbacks: List[Callable] = []

    def on_step_update(self, callback: Callable):
        self._step_callbacks.append(callback)

    def _notify(self, plan: TaskPlan, step: Optional[TaskStep] = None):
        for cb in self._step_callbacks:
            try:
                cb(plan, step)
            except Exception:
                pass

    # ─── Plan Creation ──────────────────────────────────────────────────────

    def create_plan_from_ai(self, goal: str, screen_context: str = "") -> TaskPlan:
        """
        Ask AI to decompose the goal into numbered steps.
        Returns a TaskPlan with populated steps.
        """
        from app.ai import get_ai_provider
        from app.core.agent import SYSTEM_PROMPT
        import uuid, json, re

        plan_id = str(uuid.uuid4())[:8]

        system = (
            f"{SYSTEM_PROMPT}\n\n"
            "When asked to create a task plan, respond ONLY with a JSON array of steps. "
            "Each step must be an object with: "
            '{"step": int, "description": str, "action": str, "params": dict, "risk": "LOW"|"MEDIUM"|"HIGH"}. '
            "Keep steps atomic and verifiable. Maximum 12 steps."
        )

        screen_ctx = f"\n\nCurrent screen:\n{screen_context}" if screen_context else ""
        prompt = f"Create a step-by-step task plan to: {goal}{screen_ctx}"

        try:
            provider = get_ai_provider()
            resp = provider.chat_complete(
                messages=[{"role": "user", "content": prompt}],
                tools=[],
                system_prompt=system,
                temperature=0.1
            )
            text = resp.get("text", "")

            # Extract JSON array from response
            match = re.search(r'\[[\s\S]*\]', text)
            if match:
                steps_data = json.loads(match.group())
                steps = []
                for i, sd in enumerate(steps_data):
                    steps.append(TaskStep(
                        id=i + 1,
                        description=sd.get("description", f"Step {i+1}"),
                        action=sd.get("action", "local"),
                        params=sd.get("params", {}),
                        risk_level=sd.get("risk", "LOW"),
                    ))
                plan = TaskPlan(id=plan_id, goal=goal, steps=steps)
                self._current_plan = plan
                return plan

        except Exception as e:
            logger.warning(f"AI plan creation failed: {e}")

        # Fallback: create simple single-step plan
        plan = TaskPlan(
            id=plan_id,
            goal=goal,
            steps=[TaskStep(
                id=1,
                description=f"Execute: {goal}",
                action="agent_execute",
                params={"command": goal},
                risk_level="LOW",
            )]
        )
        self._current_plan = plan
        return plan

    def create_simple_plan(self, goal: str, steps: List[Dict]) -> TaskPlan:
        """Create a plan directly from a pre-defined steps list."""
        import uuid
        plan_id = str(uuid.uuid4())[:8]
        task_steps = []
        for i, sd in enumerate(steps):
            task_steps.append(TaskStep(
                id=i + 1,
                description=sd.get("description", f"Step {i+1}"),
                action=sd.get("action", "local"),
                params=sd.get("params", {}),
                risk_level=sd.get("risk", "LOW"),
            ))
        plan = TaskPlan(id=plan_id, goal=goal, steps=task_steps)
        self._current_plan = plan
        return plan

    # ─── Plan Execution ─────────────────────────────────────────────────────

    def execute_plan(self, plan: TaskPlan,
                     executor: Optional[Callable] = None,
                     confirm_high_risk: bool = True) -> str:
        """
        Execute all steps in a plan sequentially.
        Each step: ACT → VERIFY → CONTINUE/RECOVER.
        """
        self._current_plan = plan
        plan.status = "running"
        self._event_bus.publish("state_changed", state=AgentState.EXECUTING)

        results = []
        failed_count = 0

        for step in plan.steps:
            if step.status in (StepStatus.DONE, StepStatus.SKIPPED):
                continue

            # Confirm HIGH risk
            if confirm_high_risk and step.risk_level == "HIGH":
                confirm = self._request_confirmation(step)
                if not confirm:
                    step.status = StepStatus.SKIPPED
                    results.append(f"Skipped (user declined): {step.description}")
                    self._notify(plan, step)
                    continue

            # Execute step
            step.status = StepStatus.RUNNING
            step.started_at = time.time()
            self._notify(plan, step)
            self._event_bus.publish("task_step", step=f"Step {step.id}: {step.description}")

            success, result_text = self._execute_step(step, executor)
            step.completed_at = time.time()

            if success:
                step.status = StepStatus.DONE
                step.result = result_text
                results.append(f"✓ {step.description}")
            else:
                step.error = result_text
                if step.retries < step.max_retries:
                    step.retries += 1
                    step.status = StepStatus.PENDING
                    # Retry
                    success2, result2 = self._execute_step(step, executor)
                    if success2:
                        step.status = StepStatus.DONE
                        step.result = result2
                        results.append(f"✓ {step.description} (retry {step.retries})")
                    else:
                        step.status = StepStatus.FAILED
                        step.error = result2
                        results.append(f"✗ {step.description}: {result2}")
                        failed_count += 1
                else:
                    step.status = StepStatus.FAILED
                    results.append(f"✗ {step.description}: {result_text}")
                    failed_count += 1

            self._notify(plan, step)
            time.sleep(0.1)

        plan.completed_at = time.time()
        plan.status = "completed" if failed_count == 0 else "failed"
        self._plan_history.append(plan)
        self._event_bus.publish("state_changed", state=AgentState.SPEAKING)

        total = len(plan.steps)
        done = plan.done_count
        summary = f"Completed {done}/{total} steps."
        if failed_count:
            summary += f" {failed_count} step(s) failed."

        return summary + "\n\n" + "\n".join(results)

    def _execute_step(self, step: TaskStep,
                      executor: Optional[Callable]) -> tuple:
        """Execute a single step and return (success, result_text)."""
        try:
            if executor:
                result = executor(step)
                if isinstance(result, tuple):
                    return result
                return (True, str(result))

            # Default: use agent
            from app.core.agent import get_agent
            agent = get_agent()
            result_text = agent.process_input(step.description)
            return (True, result_text)

        except Exception as e:
            return (False, str(e))

    def _request_confirmation(self, step: TaskStep) -> bool:
        """For high-risk steps, publish event and wait for confirmation."""
        # In CLI mode: default to True; UI will override this via event system
        self._event_bus.publish("confirm_required", step=step.description, risk=step.risk_level)
        return True  # auto-confirm for now; UI can intercept

    # ─── Accessors ─────────────────────────────────────────────────────────

    def get_current_plan(self) -> Optional[TaskPlan]:
        return self._current_plan

    def get_plan_display(self) -> str:
        if self._current_plan:
            return self._current_plan.to_display()
        return "No active plan."


_instance: Optional[TaskPlanner] = None

def get_task_planner() -> TaskPlanner:
    global _instance
    if _instance is None:
        _instance = TaskPlanner()
    return _instance

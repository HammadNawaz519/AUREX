"""Short-term conversational context and entity resolver for AUREX."""

import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class ConversationTurn:
    user_input: str
    agent_response: str
    entities: List[str] = field(default_factory=list)
    tool_name: Optional[str] = None
    tool_data: Any = None


class AgentContext:
    def __init__(self, max_turns: int = 8):
        self.max_turns = max_turns
        self.turns: List[ConversationTurn] = []
        self.last_entities: List[str] = []
        self.last_active_project: Optional[str] = None

    def add_turn(
        self,
        user_input: str,
        agent_response: str,
        entities: Optional[List[str]] = None,
        tool_name: Optional[str] = None,
        tool_data: Any = None
    ):
        ent = entities or []
        # If tool returned a list of items (e.g. files), capture them as entities
        if isinstance(tool_data, list) and tool_data:
            if isinstance(tool_data[0], str):
                ent = tool_data
            elif isinstance(tool_data[0], dict) and "name" in tool_data[0]:
                ent = [d["name"] for d in tool_data]

        turn = ConversationTurn(
            user_input=user_input,
            agent_response=agent_response,
            entities=ent,
            tool_name=tool_name,
            tool_data=tool_data
        )
        self.turns.append(turn)
        if len(self.turns) > self.max_turns:
            self.turns.pop(0)

        if ent:
            self.last_entities = ent

    def resolve_ordinal_reference(self, text: str) -> Optional[str]:
        """
        Resolves phrases like 'open the second one', 'the third file', 'the last one'.
        """
        if not self.last_entities:
            return None

        clean = text.lower()
        ordinals = {
            "first": 0,
            "1st": 0,
            "second": 1,
            "2nd": 1,
            "third": 2,
            "3rd": 2,
            "fourth": 3,
            "4th": 3,
            "fifth": 4,
            "5th": 4,
            "sixth": 5,
            "6th": 5,
            "seventh": 6,
            "7th": 6,
            "eighth": 7,
            "8th": 7,
            "ninth": 8,
            "9th": 8,
            "tenth": 9,
            "10th": 9,
        }

        for word, idx in ordinals.items():
            if word in clean:
                if 0 <= idx < len(self.last_entities):
                    return self.last_entities[idx]

        if "last one" in clean or "the last" in clean:
            return self.last_entities[-1]

        return None

    def get_context_summary(self) -> List[Dict[str, str]]:
        """Returns messages formatted for LLM dialogue history."""
        msgs = []
        for t in self.turns:
            msgs.append({"role": "user", "content": t.user_input})
            msgs.append({"role": "assistant", "content": t.agent_response})
        return msgs

    def clear(self):
        self.turns.clear()
        self.last_entities.clear()
        self.last_active_project = None


_global_context = AgentContext()

def get_context() -> AgentContext:
    return _global_context

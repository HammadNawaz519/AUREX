"""Tests for natural language agent context resolution and planning."""

import unittest
from app.core.context import AgentContext
from app.core.agent import AurexAgent


class TestAgent(unittest.TestCase):
    def test_ordinal_reference_resolution(self):
        ctx = AgentContext()
        ctx.last_entities = [
            r"D:\AUREX\project\first.py",
            r"D:\AUREX\project\second.py",
            r"D:\AUREX\project\third.py"
        ]

        self.assertEqual(ctx.resolve_ordinal_reference("open the first one"), r"D:\AUREX\project\first.py")
        self.assertEqual(ctx.resolve_ordinal_reference("open the second one"), r"D:\AUREX\project\second.py")
        self.assertEqual(ctx.resolve_ordinal_reference("open the 3rd one"), r"D:\AUREX\project\third.py")
        self.assertEqual(ctx.resolve_ordinal_reference("open the last one"), r"D:\AUREX\project\third.py")

    def test_agent_fallback_system_info(self):
        agent = AurexAgent()
        res = agent._fallback_local_execute("check my cpu and ram usage")
        self.assertTrue("CPU Usage" in res or "RAM Usage" in res)

    def test_agent_fallback_screenshot(self):
        agent = AurexAgent()
        res = agent._fallback_local_execute("take a screenshot")
        self.assertTrue("Screenshot saved" in res or "screenshot" in res.lower())


if __name__ == "__main__":
    unittest.main()

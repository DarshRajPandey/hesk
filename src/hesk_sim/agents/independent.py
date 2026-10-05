"""Zero-communication control: each drone independently serves the task that is
best *for itself* (priority × best solo tier quality − travel), using only the
mission plan and tasks its own sensors discover. It never transmits.

This is the null hypothesis for coordination: any protocol that scores below
this line is worth less than radio silence.
"""
from __future__ import annotations

from typing import Optional

from hesk_sim.agents.base import AgentBase, best_feasible_tier
from hesk_sim.world import Intent

W_TRAVEL = 0.1


class IndependentAgent(AgentBase):
    def on_start(self) -> None:
        self.choice: Optional[Intent] = None

    def send_heartbeat(self) -> None:
        pass

    def on_task_discovered(self, task, now: float) -> None:
        self.tasks[task.id] = task

    def on_tick(self, now: float) -> None:
        if self.choice is not None:
            tier, _ = best_feasible_tier(self.body.caps, self.tasks[self.choice.task_id], now)
            if tier is not None:
                self.choice = Intent(self.choice.task_id, tier, (self.id,))
                return
        best, best_v = None, 0.0
        for tid, task in sorted(self.tasks.items()):
            if task.arrival > now:
                continue
            tier, q = best_feasible_tier(self.body.caps, task, now)
            if tier is None:
                continue
            v = task.defn.mission_priority * q - W_TRAVEL * self.travel_cost(task) + 1.0
            if v > best_v:
                best, best_v = Intent(tid, tier, (self.id,)), v
        self.choice = best

    def intent(self) -> Optional[Intent]:
        return self.choice

import unittest
import time
from typing import List, Dict

from hesk.core.types import DimType, PriorityClass
from hesk.capabilities.model import CapabilityState
from hesk.tasks.model import TaskDefinition, DegradationTier, TaskRequirement, DataFlowRequirement
from hesk.coalitions.formation import LinkMetrics

from hesk.degradation.model import DegradationTrigger, DegradationTriggerType, TraceAction
from hesk.degradation.logic import (
    ActiveTask, 
    TaskStatus, 
    LocalLedger, 
    handle_degradation_trigger
)

class MockLedger(LocalLedger):
    def __init__(self, tasks: List[ActiveTask]):
        self.tasks = tasks
        
    def get_affected_tasks(self, trigger: DegradationTrigger) -> List[ActiveTask]:
        # Return tasks assigned to the lost node
        return [t for t in self.tasks if t.assignee == trigger.source_node]
        
    def get_all_active_tasks(self) -> List[ActiveTask]:
        return self.tasks
        
    def release_task_resources(self, task: ActiveTask) -> List[str]:
        if isinstance(task.assignee, str):
            return [task.assignee]
        return []

class MockMetrics(LinkMetrics):
    def get_bandwidth(self, source: str, sink: str) -> float:
        return 3000.0  # Bandwidth for Tier 1 coalition
        
    def get_latency(self, source: str, sink: str) -> float:
        return 80.0

class TestDegradation(unittest.TestCase):

    def setUp(self):
        # Nodes
        self.nodes = [
            CapabilityState(node_id="Node_A", timestamp=0, dimensions={"camera": 0.9, "lidar": 0.8, "gpu": 0.7, "cuda": True}),
            CapabilityState(node_id="Node_B", timestamp=0, dimensions={"camera": 0.85, "localization": 0.9, "compute": 0.3}),
            CapabilityState(node_id="Node_C", timestamp=0, dimensions={"compute": 1.0, "cuda": True, "vram": 4096}),
            CapabilityState(node_id="Node_D", timestamp=0, dimensions={"thermal": 1, "camera": 0.4, "mobility": 0.9}),
            CapabilityState(node_id="Node_E", timestamp=0, dimensions={"radio": "strong", "relay": True}),
        ]
        
        # Tasks
        tier0 = DegradationTier(
            tier_level=0, quality_estimate=1.0,
            required={
                "camera": TaskRequirement(dim_type=DimType.CONTINUOUS, threshold=0.7),
                "lidar": TaskRequirement(dim_type=DimType.CONTINUOUS, threshold=0.8),
                "gpu": TaskRequirement(dim_type=DimType.CONTINUOUS, threshold=0.5),
                "cuda": TaskRequirement(dim_type=DimType.BOOLEAN, value=True)
            },
            data_flow=[
                DataFlowRequirement("camera", "gpu", 5000.0)
            ]
        )
        
        tier1 = DegradationTier(
            tier_level=1, quality_estimate=0.7,
            required={
                "camera": TaskRequirement(dim_type=DimType.CONTINUOUS, threshold=0.7),
                "compute": TaskRequirement(dim_type=DimType.CONTINUOUS, threshold=0.4),
            },
            data_flow=[
                DataFlowRequirement("camera", "compute", 3000.0)
            ]
        )
        
        mapping_def = TaskDefinition(
            task_id="mapping_zone_b",
            priority_class=PriorityClass.CRITICAL,
            mission_priority=0.91,
            q_min=0.40,
            tiers=[tier0, tier1]
        )
        
        self.mapping_task = ActiveTask(mapping_def, current_tier=0, status=TaskStatus.EXECUTING, assignee="Node_A")
        
        self.ledger = MockLedger([self.mapping_task])
        self.metrics = MockMetrics()

    def test_progressive_mapping_degradation(self):
        trigger = DegradationTrigger(
            trigger_type=DegradationTriggerType.NODE_LOSS,
            source_node="Node_A"
        )
        
        plan = handle_degradation_trigger(trigger, self.ledger, self.nodes, self.metrics)
        
        self.assertIsNotNone(plan)
        
        # Mapping task should have degraded to Tier 1 and formed a coalition {B, C}
        self.assertIn("mapping_zone_b", plan.tier_changes)
        old_tier, new_tier = plan.tier_changes["mapping_zone_b"]
        self.assertEqual(old_tier, 0)
        self.assertEqual(new_tier, 1)
        
        new_assignee = plan.new_assignments["mapping_zone_b"]
        # It should be a Coalition object
        self.assertTrue(hasattr(new_assignee, 'members'))
        self.assertIn("Node_B", new_assignee.members)
        self.assertIn("Node_C", new_assignee.members)
        
        # Check utility drop
        self.assertLess(plan.utility_after, plan.utility_before)
        
        # Check trace
        self.assertTrue(any(t.action == TraceAction.DEGRADE for t in plan.decision_trace))

if __name__ == '__main__':
    unittest.main()

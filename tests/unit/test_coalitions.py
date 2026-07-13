import unittest
import time
from dataclasses import dataclass
from typing import Optional

from hesk.core.types import DimType, NodeId
from hesk.capabilities.model import CapabilityState
from hesk.tasks.model import TaskRequirement
from hesk.coalitions.formation import form_coalition, LinkMetrics

@dataclass
class DataFlowRequirement:
    source_capability: str
    sink_capability: str
    bandwidth_kbps: float
    max_latency_ms: Optional[float] = None

class MockLinkMetrics(LinkMetrics):
    def get_bandwidth(self, source: str, sink: str) -> float:
        if (source == "Drone_B" and sink == "Rover_C") or (source == "Rover_C" and sink == "Drone_B"):
            return 8000.0
        return 0.0
        
    def get_latency(self, source: str, sink: str) -> float:
        if (source == "Drone_B" and sink == "Rover_C") or (source == "Rover_C" and sink == "Drone_B"):
            return 45.0
        return float('inf')

class TestCoalitions(unittest.TestCase):

    def setUp(self):
        # Requirements
        self.required = {
            "sensing.rgb": TaskRequirement(dim_type=DimType.CONTINUOUS, threshold=0.7),
            "localization": TaskRequirement(dim_type=DimType.CONTINUOUS, threshold=0.8),
            "compute.gpu": TaskRequirement(dim_type=DimType.CONTINUOUS, threshold=0.5)
        }
        
        # Data flows
        self.data_flows = [
            DataFlowRequirement(
                source_capability="sensing.rgb",
                sink_capability="compute.gpu",
                bandwidth_kbps=5000.0,
                max_latency_ms=200.0
            )
        ]
        
        # Nodes
        self.drone_b = CapabilityState(
            node_id="Drone_B",
            timestamp=time.time(),
            dimensions={
                "sensing.rgb": 0.9,
                "localization": 0.9,
                "compute.gpu": 0.2
            }
        )
        
        self.rover_c = CapabilityState(
            node_id="Rover_C",
            timestamp=time.time(),
            dimensions={
                "sensing.rgb": 0.1,
                "localization": 0.3,
                "compute.gpu": 0.8
            }
        )
        
        self.relay_d = CapabilityState(
            node_id="Relay_D",
            timestamp=time.time(),
            dimensions={
                "sensing.rgb": 0.0,
                "localization": 0.1,
                "compute.gpu": 0.3
            }
        )
        
        self.metrics = MockLinkMetrics()

    def test_mapping_zone_b_coalition(self):
        result = form_coalition(
            task_id="mapping_zone_b",
            required=self.required,
            data_flows=self.data_flows,
            candidates=[self.drone_b, self.rover_c, self.relay_d],
            link_metrics=self.metrics,
            initiator_id="Drone_B"
        )
        
        # Check success
        self.assertTrue(result.success, msg=f"Coalition failed: {result.rejection_reason}")
        
        c = result.coalition
        self.assertIsNotNone(c)
        
        # Check members
        self.assertIn("Drone_B", c.members)
        self.assertIn("Rover_C", c.members)
        self.assertNotIn("Relay_D", c.members)
        
        # Check role assignment
        self.assertEqual(c.role_assignment["sensing.rgb"], "Drone_B")
        self.assertEqual(c.role_assignment["localization"], "Drone_B")
        self.assertEqual(c.role_assignment["compute.gpu"], "Rover_C")
        
        # Check data flow plan
        self.assertEqual(len(c.data_flow_plan), 1)
        flow = c.data_flow_plan[0]
        self.assertEqual(flow.source_node, "Drone_B")
        self.assertEqual(flow.sink_node, "Rover_C")
        self.assertTrue(flow.feasible)
        self.assertEqual(flow.available_bw_kbps, 8000.0)

if __name__ == '__main__':
    unittest.main()

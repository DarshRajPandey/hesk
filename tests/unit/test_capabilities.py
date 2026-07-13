import unittest
from hesk.core.types import DimType
from hesk.capabilities.model import CapabilityDefinition, CapabilityState, LinkState

class TestCapabilities(unittest.TestCase):
    def test_capability_definition(self):
        cd = CapabilityDefinition(dimension="sensing_visual", dim_type=DimType.CONTINUOUS)
        self.assertEqual(cd.dimension, "sensing_visual")
        self.assertEqual(cd.dim_type, DimType.CONTINUOUS)

    def test_capability_state(self):
        state = CapabilityState(
            node_id="drone_1",
            timestamp=100.0,
            dimensions={"has_camera": True, "sensing_visual": 0.8}
        )
        self.assertEqual(state.node_id, "drone_1")
        self.assertEqual(state.timestamp, 100.0)
        self.assertTrue(state.get_dimension("has_camera"))
        self.assertEqual(state.get_dimension("sensing_visual"), 0.8)
        self.assertIsNone(state.get_dimension("lidar"))

    def test_link_state(self):
        link = LinkState(
            source_id="drone_1",
            target_id="drone_2",
            timestamp=105.0,
            bandwidth_kbps=1000.0,
            latency_ms=15.0,
            is_connected=True
        )
        self.assertTrue(link.is_connected)
        self.assertEqual(link.bandwidth_kbps, 1000.0)

if __name__ == '__main__':
    unittest.main()

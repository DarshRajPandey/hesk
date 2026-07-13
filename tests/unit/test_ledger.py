import unittest
from unittest.mock import patch
import time

from hesk.ledger.model import (
    StateSemanticType,
    Provenance,
    ObservationType
)
from hesk.ledger.ledger import LocalStateLedger

class TestLocalStateLedger(unittest.TestCase):

    def setUp(self):
        self.ledger_a = LocalStateLedger("Node_A")

    @patch('hesk.ledger.ledger.local_wall_time')
    def test_node_a_receives_state_update_from_node_b(self, mock_wall_time):
        # 1. Setup Node A's initial ledger state
        
        # mock wall time for node A initial writes
        mock_wall_time.return_value = 1000.0
        self.ledger_a.write_local("visited_zones", {"zone_1", "zone_2"}, StateSemanticType.SET_LIKE)
        
        mock_wall_time.return_value = 998.0
        self.ledger_a.write_local("task_owner.mapping_x", "node_7", StateSemanticType.EXCLUSIVE_OWNERSHIP)
        
        mock_wall_time.return_value = 999.5
        self.ledger_a.write_local("node_9.status", "ACTIVE", StateSemanticType.RESOURCE)
        
        # Manually adjust clocks to match the scenario
        # In reality write_local increments, so we just override the entry objects to match the doc
        self.ledger_a.entries["visited_zones"].lamport_clock = 5
        self.ledger_a.entries["task_owner.mapping_x"].lamport_clock = 3
        self.ledger_a.entries["node_9.status"].lamport_clock = 4
        self.ledger_a.lamport_clock = 5

        # 2. Process Node B's state update containing 3 entries
        source_clock = 7
        
        from hesk.ledger.model import StateExchangeMessage, LedgerEntry, BandwidthMode
        
        # Entry 1: visited_zones
        provenance1 = Provenance(origin="Node_B", observation_type=ObservationType.DIRECT, original_clock=7, hops=0)
        entry1 = LedgerEntry(
            key="visited_zones", value={"zone_2", "zone_3"}, semantic_type=StateSemanticType.SET_LIKE,
            source_node="Node_B", lamport_clock=7, wall_time=1002.0, confidence=1.0, provenance=provenance1
        )
        
        # Entry 2: task_owner.mapping_x
        provenance2 = Provenance(origin="Node_B", observation_type=ObservationType.DIRECT, original_clock=6, hops=0)
        entry2 = LedgerEntry(
            key="task_owner.mapping_x", value="node_8", semantic_type=StateSemanticType.EXCLUSIVE_OWNERSHIP,
            source_node="Node_B", lamport_clock=6, wall_time=1001.0, confidence=1.0, provenance=provenance2
        )
        
        # Entry 3: node_9.status
        provenance3 = Provenance(origin="Node_B", observation_type=ObservationType.DIRECT, original_clock=8, hops=0)
        entry3 = LedgerEntry(
            key="node_9.status", value="SUSPECTED_UNREACHABLE", semantic_type=StateSemanticType.RESOURCE,
            source_node="Node_B", lamport_clock=8, wall_time=1003.0, confidence=0.9, provenance=provenance3
        )
        
        message = StateExchangeMessage(
            sender_id="Node_B",
            sender_clock=source_clock,
            version_vector={"Node_B": 10},
            entries=[entry1, entry2, entry3],
            bandwidth_mode=BandwidthMode.DELTA
        )
        
        self.ledger_a.process_message(message)

        # 3. Assertions
        
        # Lamport clock updated
        self.assertEqual(self.ledger_a.lamport_clock, 8) # max(5, 7) + 1 = 8
        
        # Entry 1: SET_LIKE should union
        val1, _ = self.ledger_a.read("visited_zones")
        self.assertEqual(val1, {"zone_1", "zone_2", "zone_3"})
        
        # Entry 2: EXCLUSIVE_OWNERSHIP should conflict
        val2, meta2 = self.ledger_a.read("task_owner.mapping_x")
        self.assertEqual(val2, "node_7") # Keep local
        self.assertTrue(meta2["has_conflict"])
        
        # Entry 3: RESOURCE should accept new value
        val3, _ = self.ledger_a.read("node_9.status")
        self.assertEqual(val3, "SUSPECTED_UNREACHABLE")

if __name__ == '__main__':
    unittest.main()

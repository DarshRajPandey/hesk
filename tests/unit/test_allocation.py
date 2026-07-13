import unittest
import math
from typing import Dict

from hesk.capabilities.model import CapabilityState
from hesk.tasks.model import Bid
from hesk.tasks.allocation import (
    compute_scarcity,
    compute_scarcity_penalty,
    compute_exec_cost,
    compute_energy_cost,
    compute_system_cost,
    evaluate_bids
)

class TestScarcityAllocation(unittest.TestCase):
    
    def setUp(self):
        # 0.1 for all
        self.thetas = {
            "thermal": 0.1,
            "rgb": 0.1,
            "compute": 0.1,
            "lidar": 0.1
        }
        
        # Node A: Thermal drone
        self.node_a = CapabilityState(node_id="A", timestamp=0.0, dimensions={
            "thermal": 0.95, "rgb": 0.80, "compute": 0.60, "lidar": 0.00
        })
        self.energy_a = 0.70
        self.mq_a = 0.80
        
        # Node B: Lidar drone
        self.node_b = CapabilityState(node_id="B", timestamp=0.0, dimensions={
            "thermal": 0.00, "rgb": 0.85, "compute": 0.70, "lidar": 0.50
        })
        self.energy_b = 0.80
        self.mq_b = 0.85
        
        # Node C: Compute drone
        self.node_c = CapabilityState(node_id="C", timestamp=0.0, dimensions={
            "thermal": 0.00, "rgb": 0.75, "compute": 0.90, "lidar": 0.00
        })
        self.energy_c = 0.65
        self.mq_c = 0.75
        
        # Node D: Lidar drone 2
        self.node_d = CapabilityState(node_id="D", timestamp=0.0, dimensions={
            "thermal": 0.00, "rgb": 0.60, "compute": 0.40, "lidar": 0.80
        })
        self.energy_d = 0.90
        self.mq_d = 0.60
        
        # Node E: Standard drone
        self.node_e = CapabilityState(node_id="E", timestamp=0.0, dimensions={
            "thermal": 0.00, "rgb": 0.70, "compute": 0.55, "lidar": 0.00
        })
        self.energy_e = 0.75
        self.mq_e = 0.70
        
        self.swarm = [self.node_a, self.node_b, self.node_c, self.node_d, self.node_e]
        
    def test_scarcity_computation(self):
        # thermal >= 0.1 is only A (1/5) => scarcity = 0.8
        sig_thermal = compute_scarcity("thermal", self.swarm, 0.1)
        self.assertAlmostEqual(sig_thermal, 0.80)
        
        # rgb >= 0.1 is everyone (5/5) => scarcity = 0.0
        sig_rgb = compute_scarcity("rgb", self.swarm, 0.1)
        self.assertAlmostEqual(sig_rgb, 0.00)
        
        # compute >= 0.1 is everyone (5/5) => scarcity = 0.0
        sig_compute = compute_scarcity("compute", self.swarm, 0.1)
        self.assertAlmostEqual(sig_compute, 0.00)
        
        # lidar >= 0.1 is B and D (2/5) => scarcity = 0.6
        sig_lidar = compute_scarcity("lidar", self.swarm, 0.1)
        self.assertAlmostEqual(sig_lidar, 0.60)
        
    def test_node_a_costs(self):
        # Exec cost: (1 - 0.80) + (1 - 0.70) = 0.20 + 0.30 = 0.50
        exec_cost = compute_exec_cost(self.mq_a, self.energy_a)
        self.assertAlmostEqual(exec_cost, 0.50)
        
        # Energy cost: 0.1 / 0.70 = 0.143
        energy_cost = compute_energy_cost(0.1, self.energy_a)
        self.assertAlmostEqual(energy_cost, 0.142857, places=3)
        
        # Scarcity penalty: required is just rgb
        required = {"rgb"}
        # A has thermal (0.95 >= 0.1) => penalty += sigma_thermal (0.8)
        # A has compute (0.60 >= 0.1) => penalty += sigma_compute (0.0)
        # A has no lidar (0.0 < 0.1) => penalty += 0
        penalty = compute_scarcity_penalty(self.node_a, required, self.swarm, self.thetas)
        self.assertAlmostEqual(penalty, 0.80)
        
        # System cost
        sys_cost = compute_system_cost(
            match_quality=self.mq_a,
            energy=self.energy_a,
            base_consumption=0.1,
            scarcity_penalty=penalty,
            w_exec=1.0,
            w_energy=0.5,
            w_scarcity=2.0
        )
        # 1.0*0.50 + 0.5*0.142857 + 2.0*0.80 = 0.50 + 0.0714 + 1.60 = 2.171
        # Note: The document's example says scarcity_penalty(A) = 0.760 because it multiplied by capability (0.95 * 0.8 = 0.76).
        # Wait, the doc text states: "We use an indicator function instead of raw multiplier. Penalty contribution from thermal: 0.8 * 1 = 0.8". 
        # But the doc's math shows: "thermal contribution: 0.80 * 0.95 = 0.760" and sums it to 0.760. 
        # It's a typo in the doc's worked example math. The doc's definition is:
        # scarcity_penalty = sum(sigma_d * I(c_{i,d} >= theta_d)). So 0.8 * 1 = 0.8.
        # Let's assert based on our indicator function implementation (0.8).
        self.assertAlmostEqual(sys_cost, 2.171, places=2)

    def test_full_allocation_scenario(self):
        required = {"rgb"}
        bids = []
        
        test_data = [
            (self.node_a, self.energy_a, self.mq_a),
            (self.node_b, self.energy_b, self.mq_b),
            (self.node_c, self.energy_c, self.mq_c),
            (self.node_d, self.energy_d, self.mq_d),
            (self.node_e, self.energy_e, self.mq_e)
        ]
        
        for state, en, mq in test_data:
            pen = compute_scarcity_penalty(state, required, self.swarm, self.thetas)
            sc = compute_system_cost(
                match_quality=mq, energy=en, base_consumption=0.1, 
                scarcity_penalty=pen, w_exec=1.0, w_energy=0.5, w_scarcity=2.0
            )
            bids.append(Bid(
                task_id="map_zone_b",
                node_id=state.node_id,
                system_cost=sc,
                match_quality=mq,
                energy=en,
                cap_snapshot=state
            ))
            
        result = evaluate_bids(bids, "map_zone_b")
        
        self.assertEqual(result.assigned_node, "E")
        self.assertEqual(result.runner_up_node, "C")

if __name__ == '__main__':
    unittest.main()

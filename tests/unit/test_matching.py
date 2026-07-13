import unittest
import math

from hesk.core.types import DimType
from hesk.capabilities.model import CapabilityState
from hesk.tasks.model import TaskRequirement
from hesk.capabilities.matching import compute_full_match

class TestCapabilityMatching(unittest.TestCase):
    
    def setUp(self):
        # Setup mapping_zone_b requirements
        self.r_req = {
            "localization": TaskRequirement(dim_type=DimType.CONTINUOUS, threshold=0.70),
            "sensing_visual": TaskRequirement(dim_type=DimType.CONTINUOUS, threshold=0.60),
            "has_camera": TaskRequirement(dim_type=DimType.BOOLEAN, value=True)
        }
        
        self.r_pref = {
            "lidar": TaskRequirement(dim_type=DimType.CONTINUOUS, threshold=0.80),
            "compute_gpu": TaskRequirement(dim_type=DimType.CAPACITY, threshold=8.0),
            "model_runtime": TaskRequirement(dim_type=DimType.CATEGORICAL, required_set={"tensorrt", "onnx"})
        }
        
        # Setup drone_alpha state
        self.drone_alpha = CapabilityState(
            node_id="drone_alpha",
            timestamp=0.0,
            dimensions={
                "localization": 0.85,
                "sensing_visual": 0.91,
                "has_camera": True,
                "lidar": 0.72,
                "compute_gpu": 12.0,
                "model_runtime": "tensorrt",
                "energy": 0.63
            }
        )

    def test_drone_alpha_self_evaluation(self):
        # Part (a): age_s = 0
        match_result = compute_full_match(
            c_i=self.drone_alpha,
            r_j_required=self.r_req,
            r_j_preferred=self.r_pref,
            age_s=0.0
        )
        
        # Eligibility
        self.assertTrue(match_result.eligible)
        self.assertEqual(len(match_result.unmet_required), 0)
        self.assertEqual(len(match_result.missing_dimensions), 0)
        
        # Quality calculation checks:
        # lidar: 0.72 < 0.80 -> 0.0
        # compute_gpu: 12.0 >= 8.0 -> sat=1. surplus = 4.0. headroom = min(4.0/8.0, 1.0) = 0.5. 
        #   score = (0.8*1) + (0.2*0.5) = 0.9
        # model_runtime: "tensorrt" in set -> 1.0
        # total = (0.0 + 0.9 + 1.0) / 3 = 1.9 / 3 = 0.6333...
        self.assertAlmostEqual(match_result.quality, 0.6333333333333333)
        self.assertEqual(match_result.confidence, 1.0)
        self.assertAlmostEqual(match_result.weighted_quality, 0.6333333333333333)

    def test_drone_alpha_stale_remote(self):
        # Part (b): age_s = 45
        match_result = compute_full_match(
            c_i=self.drone_alpha,
            r_j_required=self.r_req,
            r_j_preferred=self.r_pref,
            age_s=45.0
        )
        
        self.assertTrue(match_result.eligible)
        
        # Confidence = 0.5 ** (45/30) = 0.5 ** 1.5
        expected_conf = 0.5 ** 1.5
        self.assertAlmostEqual(match_result.confidence, expected_conf)
        
        # Quality should remain same as self-evaluation
        self.assertAlmostEqual(match_result.quality, 0.6333333333333333)
        
        # Weighted quality is product
        self.assertAlmostEqual(match_result.weighted_quality, 0.6333333333333333 * expected_conf)

if __name__ == '__main__':
    unittest.main()

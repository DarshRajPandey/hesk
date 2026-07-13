import unittest
from hesk.core.types import DimType, PriorityClass
from hesk.tasks.model import TaskRequirement, DataFlowRequirement, DegradationTier, TaskDefinition

class TestTasks(unittest.TestCase):
    def test_valid_task_requirement(self):
        req_bool = TaskRequirement(dim_type=DimType.BOOLEAN, value=True)
        self.assertTrue(req_bool.value)

        req_cont = TaskRequirement(dim_type=DimType.CONTINUOUS, threshold=0.7)
        self.assertEqual(req_cont.threshold, 0.7)

        req_cat = TaskRequirement(dim_type=DimType.CATEGORICAL, required_set={"onnx", "tensorrt"})
        self.assertIn("onnx", req_cat.required_set)

    def test_invalid_task_requirement(self):
        with self.assertRaises(ValueError):
            TaskRequirement(dim_type=DimType.BOOLEAN)  # missing value
        with self.assertRaises(ValueError):
            TaskRequirement(dim_type=DimType.CAPACITY) # missing threshold
        with self.assertRaises(ValueError):
            TaskRequirement(dim_type=DimType.CATEGORICAL) # missing required_set

    def test_valid_degradation_tier(self):
        tier = DegradationTier(
            tier_level=0,
            quality_estimate=1.0,
            required={"has_camera": TaskRequirement(dim_type=DimType.BOOLEAN, value=True)}
        )
        self.assertEqual(tier.tier_level, 0)
        self.assertEqual(tier.quality_estimate, 1.0)

    def test_invalid_degradation_tier(self):
        with self.assertRaises(ValueError):
            DegradationTier(tier_level=0, quality_estimate=1.5, required={})

    def test_valid_task_definition(self):
        tier0 = DegradationTier(tier_level=0, quality_estimate=1.0, required={})
        tier1 = DegradationTier(tier_level=1, quality_estimate=0.8, required={})
        
        task = TaskDefinition(
            task_id="mapping_1",
            priority_class=PriorityClass.IMPORTANT,
            mission_priority=0.8,
            q_min=0.5,
            tiers=[tier0, tier1]
        )
        self.assertEqual(task.task_id, "mapping_1")
        self.assertEqual(len(task.tiers), 2)

    def test_invalid_task_definition_tier_ordering(self):
        tier0 = DegradationTier(tier_level=0, quality_estimate=0.8, required={})
        tier1 = DegradationTier(tier_level=1, quality_estimate=0.9, required={}) # quality increased!
        
        with self.assertRaisesRegex(ValueError, "strictly less than"):
            TaskDefinition(
                task_id="mapping_1",
                priority_class=PriorityClass.IMPORTANT,
                mission_priority=0.8,
                q_min=0.5,
                tiers=[tier0, tier1]
            )
            
    def test_invalid_task_definition_tier_level_jump(self):
        tier0 = DegradationTier(tier_level=0, quality_estimate=1.0, required={})
        tier2 = DegradationTier(tier_level=2, quality_estimate=0.8, required={}) # skipped tier 1
        
        with self.assertRaisesRegex(ValueError, "contiguous"):
            TaskDefinition(
                task_id="mapping_1",
                priority_class=PriorityClass.IMPORTANT,
                mission_priority=0.8,
                q_min=0.5,
                tiers=[tier0, tier2]
            )

    def test_invalid_task_definition_below_q_min(self):
        tier0 = DegradationTier(tier_level=0, quality_estimate=1.0, required={})
        tier1 = DegradationTier(tier_level=1, quality_estimate=0.4, required={}) # below q_min=0.5
        
        with self.assertRaisesRegex(ValueError, "below minimum acceptable quality"):
            TaskDefinition(
                task_id="mapping_1",
                priority_class=PriorityClass.IMPORTANT,
                mission_priority=0.8,
                q_min=0.5,
                tiers=[tier0, tier1]
            )

if __name__ == '__main__':
    unittest.main()

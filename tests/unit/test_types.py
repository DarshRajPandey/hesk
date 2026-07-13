import unittest
from hesk.core.types import DimType, PriorityClass

class TestTypes(unittest.TestCase):
    def test_dim_type_enum(self):
        self.assertEqual(len(DimType), 4)
        self.assertIn(DimType.BOOLEAN, DimType)
        self.assertIn(DimType.CONTINUOUS, DimType)
        self.assertIn(DimType.CAPACITY, DimType)
        self.assertIn(DimType.CATEGORICAL, DimType)

    def test_priority_class_enum(self):
        self.assertEqual(len(PriorityClass), 3)
        self.assertIn(PriorityClass.CRITICAL, PriorityClass)
        self.assertIn(PriorityClass.IMPORTANT, PriorityClass)
        self.assertIn(PriorityClass.OPTIONAL, PriorityClass)

if __name__ == '__main__':
    unittest.main()

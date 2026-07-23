from __future__ import annotations

import unittest

from tkr.claim_validation import VALIDATOR_VERSION
from tkr.engineering import ENGINEERING_VERSION, build_key, load_engineering_profile
from tkr.entity_normalization import NORMALIZER_VERSION
from tkr.knowledge_models import KNOWLEDGE_SYSTEM_VERSION


class R3RuntimeIdentityTests(unittest.TestCase):
    def test_r3_runtime_versions_are_explicit(self) -> None:
        self.assertEqual(KNOWLEDGE_SYSTEM_VERSION, "6.0.0rc1-r3")
        self.assertEqual(ENGINEERING_VERSION, "6.0.0rc1-r3")
        self.assertEqual(VALIDATOR_VERSION, "tkr-claim-validator-v2-r3")
        self.assertEqual(NORMALIZER_VERSION, "tkr-entity-normalizer-v3")

    def test_build_key_is_bound_to_r3_runtime_identity(self) -> None:
        profile = load_engineering_profile("balanced")
        key = build_key("a" * 64, profile)
        self.assertTrue(key.startswith("bld_"))
        self.assertEqual(len(key), 44)


if __name__ == "__main__":
    unittest.main()

import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("validator", ROOT / "conformance" / "validate_claims.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
BASE = json.loads((ROOT / "conformance" / "tenir-gov" / "5.7.0" / "reg-arch-v0.4.json").read_text())

class TestClaims(unittest.TestCase):
    def test_intake_valid(self):
        self.assertEqual(module.validate(BASE), [])
    def test_missing_version_rejected(self):
        c = copy.deepcopy(BASE)
        del c["reference"]["version"]
        self.assertTrue(module.validate(c))
    def test_unpinned_demonstrated_rejected(self):
        c = copy.deepcopy(BASE)
        c["status"] = "DEMONSTRATED"
        self.assertTrue(module.validate(c))
    def test_bad_commit_rejected(self):
        c = copy.deepcopy(BASE)
        c["implementation_commit"] = "latest"
        self.assertTrue(module.validate(c))
    def test_duplicate_applicability_rejected(self):
        c = copy.deepcopy(BASE)
        c["reference"]["applicability"] = ["010", "010"]
        self.assertTrue(module.validate(c))
    def test_missing_evidence_hash_rejected(self):
        c = copy.deepcopy(BASE)
        c["evidence"] = [{"id": "e", "run_id": "r", "timestamp": "2026-10-25T00:00:00Z"}]
        self.assertTrue(module.validate(c))

if __name__ == "__main__":
    unittest.main()

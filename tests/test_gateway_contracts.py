import pathlib
import subprocess
import unittest


class GatewayContracts(unittest.TestCase):
    def run_contract(self, command):
        root = pathlib.Path(__file__).parents[1]
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_closed_assignment_completion_and_canonical_contract(self):
        self.run_contract(['node', 'tests/bridge/policy.test.mjs'])

    def test_authorized_attempt_snapshot(self):
        self.run_contract(['node', 'tests/bridge/attempt-consistency.test.mjs'])

    def test_narrow_production_cookie_patch(self):
        self.run_contract(['python3', 'tests/bridge/cookie-domain.test.py'])

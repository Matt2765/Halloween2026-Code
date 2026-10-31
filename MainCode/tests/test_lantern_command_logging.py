"""Keep lantern command failures available after live history rolls over."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock


class LanternCommandLoggingTests(unittest.TestCase):
    def test_failure_logged_once_without_debug_and_pending_stays_quiet(self):
        path = Path(__file__).resolve().parents[1] / "control/remote_sensor_monitor.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == "_log_dropdown_commands"]
        log = Mock()
        scope = {"_log_event": log}
        exec(compile(tree, str(path), "exec"), scope)
        record = dict(id="LANTERN1", op="lantern", duration_ms=1, status="pending")
        records, logged = {"cue": record}, {}
        emit = scope["_log_dropdown_commands"]
        emit(records, logged)
        log.assert_not_called()
        record.update(status="unconfirmed", reason="result_timeout")
        emit(records, logged)
        emit(records, logged)
        log.assert_called_once_with("LANTERN1 lantern cue 1 unconfirmed: result_timeout")
        records.clear()
        emit(records, logged)
        self.assertEqual(logged, {})


if __name__ == "__main__":
    unittest.main()

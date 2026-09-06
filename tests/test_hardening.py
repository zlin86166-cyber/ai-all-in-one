from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai_hub.db import Database
from ai_hub.scheduler import Scheduler
from ai_hub.security import action_fingerprint, require_write_mode, validate_network_url, validate_workspace_command
from ai_hub.workspace_guard import ScopedWorkspaceGuard, ScopeViolation


class HardeningTests(unittest.TestCase):
    def test_observe_is_read_only(self):
        with self.assertRaises(PermissionError): require_write_mode("observe")

    def test_workspace_terminal_blocks_parent_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/"project"; root.mkdir()
            with self.assertRaises(PermissionError): validate_workspace_command("Get-Content ..\\secret.txt", root, "workspace")

    def test_selected_file_guard_rolls_back_out_of_scope_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); allowed=root/"a.txt"; other=root/"b.txt"
            allowed.write_text("a",encoding="utf-8"); other.write_text("b",encoding="utf-8")
            guard=ScopedWorkspaceGuard(root,[str(allowed)], max_backup_bytes=1024*1024)
            try:
                allowed.write_text("new a",encoding="utf-8"); other.write_text("bad",encoding="utf-8")
                with self.assertRaises(ScopeViolation): guard.enforce()
                self.assertEqual(other.read_text(encoding="utf-8"),"b")
                self.assertEqual(allowed.read_text(encoding="utf-8"),"new a")
            finally: guard.close()

    def test_approval_is_consumed_once(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Database(Path(directory)/"x.sqlite3"); payload={"x":1}; fp=action_fingerprint("system",payload)
            approval=db.create_approval("system","test",fp,payload); db.resolve_approval(approval["id"],True)
            self.assertTrue(db.approval_valid(approval["id"],fp)); self.assertFalse(db.approval_valid(approval["id"],fp))

    def test_calibration_requires_verified_examples(self):
        from ai_hub.evaluator import FeasibilityEvaluator
        class FakeDB:
            @staticmethod
            def feasibility_examples():
                return [{"verified": False, "success": True, "factors": {}} for _ in range(100)]
        self.assertIsNone(FeasibilityEvaluator(FakeDB())._calibration())

    def test_scheduler_cross_midnight(self):
        self.assertTrue(Scheduler._within_window("23:30","22:00","02:00")); self.assertTrue(Scheduler._within_window("01:00","22:00","02:00")); self.assertFalse(Scheduler._within_window("12:00","22:00","02:00"))

    @mock.patch("socket.getaddrinfo", return_value=[(None,None,None,None,("127.0.0.1",80))])
    def test_public_research_blocks_loopback(self,_):
        with self.assertRaises(PermissionError): validate_network_url("http://example.test/")


    def test_operator_ui_and_truthful_progress_contracts(self):
        root = Path(__file__).resolve().parents[1]
        web = (root / "web" / "index.html").read_text(encoding="utf-8")
        app = (root / "web" / "app.js").read_text(encoding="utf-8")
        providers = (root / "ai_hub" / "providers.py").read_text(encoding="utf-8")
        self.assertIn('data-view="integrations"', web)
        self.assertIn('/api/integrations/play', app)
        self.assertIn('progressLabel(progress)', app)
        self.assertNotIn('min(94, progress + 0.35)', providers)
        self.assertNotIn('min(96, progress + 0.4)', providers)

    def test_training_source_has_validation_and_assistant_masking(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "training" / "train_lora.py").read_text(encoding="utf-8")
        self.assertIn('--eval-dataset', source)
        self.assertIn('[-100]*mask', source)
        self.assertIn('EarlyStoppingCallback', source)
        self.assertIn('training-curve.json', source)
        self.assertIn('smoke_test', source)


if __name__=="__main__": unittest.main()

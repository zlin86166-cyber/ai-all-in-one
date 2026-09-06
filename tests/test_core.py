from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from ai_hub.application import AIHubApplication
from ai_hub.crawler import TextExtractor
from ai_hub.config import MODEL_CATALOG, AppPaths
from ai_hub.db import Database
from ai_hub.evaluator import FeasibilityEvaluator
from ai_hub.images import ImageGenerationManager
from ai_hub.models import ModelManager
from ai_hub.providers import FileTransferProvider, ProviderContext
from ai_hub.security import FULL_ACCESS_PHRASE, action_fingerprint, classify_command, path_inside, requires_account_approval, scoped_path, SecurityError


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = Database(self.root / "test.sqlite3")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_project_conversation_and_message_roundtrip(self) -> None:
        project = self.database.ensure_project(str(self.root), "Test")
        conversation = self.database.create_conversation(project["id"])
        message = self.database.add_message(conversation["id"], "user", "build the app", metadata={"x": 1})
        self.assertEqual(message["metadata"], {"x": 1})
        self.assertEqual(self.database.get_conversation(conversation["id"])["title"], "build the app")

    def test_approval_fingerprint_must_match(self) -> None:
        payload = {"command": "winget install example"}
        fingerprint = action_fingerprint("download", payload)
        approval = self.database.create_approval("download", "Install", fingerprint, payload)
        self.assertFalse(self.database.approval_valid(approval["id"], fingerprint))
        self.database.resolve_approval(approval["id"], True)
        self.assertTrue(self.database.approval_valid(approval["id"], fingerprint))
        self.assertFalse(self.database.approval_valid(approval["id"], "wrong"))

    def test_task_event_order(self) -> None:
        project = self.database.ensure_project(str(self.root))
        task = self.database.create_task("fake", "Title", "Prompt", None, project["id"], 10, None)
        self.database.add_task_event(task["id"], "one")
        self.database.add_task_event(task["id"], "two")
        self.assertEqual([item["message"] for item in self.database.list_task_events(task["id"])], ["one", "two"])

    def test_schedule_interval_and_feedback_roundtrip(self) -> None:
        project = self.database.ensure_project(str(self.root))
        task = self.database.create_task("fake", "Title", "Prompt", None, project["id"], 10, None)
        feedback = self.database.set_task_feedback(task["id"], False, "needs revision")
        self.assertFalse(feedback["success"])
        schedule = self.database.create_schedule(
            {
                "name": "draw",
                "prompt": "a white room",
                "project_id": project["id"],
                "provider_ids": [],
                "interval_minutes": 30,
                "mode": "image",
            }
        )
        self.assertEqual(schedule["interval_minutes"], 30)

    def test_global_fts_search_finds_chinese_messages_and_tasks(self) -> None:
        project = self.database.ensure_project(str(self.root), "極客工作站")
        conversation = self.database.create_conversation(project["id"])
        self.database.add_message(conversation["id"], "user", "建立可查詢的本機向量資料庫")
        task = self.database.create_task(
            "codex", "資料庫索引", "加入全文快速查詢", conversation["id"], project["id"], 20, None
        )
        self.database.update_task(task["id"], status="completed", result="索引驗證完成")
        message_hits = self.database.search("本機向量資料庫")
        task_hits = self.database.search("索引驗證完成")
        self.assertTrue(any(item["kind"] == "message" for item in message_hits))
        self.assertTrue(any(item["kind"] == "task" for item in task_hits))


class SecurityTests(unittest.TestCase):
    def test_scoped_path_accepts_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertTrue(path_inside(root / "src" / "app.py", root))
            self.assertEqual(scoped_path(root / "src", root), (root / "src").resolve())

    def test_scoped_path_rejects_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            root.mkdir()
            with self.assertRaises(SecurityError):
                scoped_path(root.parent / "secret.txt", root)

    def test_destructive_command_is_gated(self) -> None:
        result = classify_command("Remove-Item C:\\Temp\\x -Recurse -Force")
        self.assertEqual(result["kind"], "destructive")
        self.assertTrue(result["requires_approval"])

    def test_normal_test_command_is_not_double_gated(self) -> None:
        result = classify_command("python -m unittest discover -v")
        self.assertFalse(result["requires_approval"])

    def test_chinese_account_and_publish_prompt_is_gated(self) -> None:
        self.assertTrue(requires_account_approval("使用我的帳號建立網站並上架 APK"))

    def test_full_access_is_process_local_and_not_revoked_by_second_instance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = AIHubApplication(root)
            first.unlock_full_access(FULL_ACCESS_PHRASE, 10)
            second = AIHubApplication(root)
            self.assertTrue(first.full_access_unlocked())
            self.assertFalse(second.full_access_unlocked())
            first.stop()
            second.stop()


class EvaluatorTests(unittest.TestCase):
    def test_evaluator_returns_evidence_and_eta(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "test.sqlite3")
            evaluator = FeasibilityEvaluator(database)
            result = evaluator.evaluate(
                "修改選取檔案並執行測試驗證",
                ["codex"],
                {"codex": {"available": True}},
                {"memory": {"total_gb": 16}},
                "workspace",
                ["app.py"],
            )
            self.assertGreaterEqual(result["score"], 0)
            self.assertLessEqual(result["score"], 100)
            self.assertGreater(result["estimated_seconds"], 0)
            self.assertEqual(len(result["factors"]), 8)

    def test_real_metrics_affect_history_samples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "test.sqlite3")
            database.add_metric("codex", "small", 10, 9, True)
            result = FeasibilityEvaluator(database).evaluate(
                "run tests", ["codex"], {"codex": {"available": True}},
                {"memory": {"total_gb": 16}}, "workspace"
            )
            self.assertEqual(result["history_samples"], 1)


class CrawlerTests(unittest.TestCase):
    def test_html_text_extraction_ignores_script(self) -> None:
        parser = TextExtractor()
        parser.feed("<html><title>Docs</title><script>bad()</script><main><h1>Hello</h1><p>World</p></main></html>")
        title, text = parser.result()
        self.assertEqual(title, "Docs")
        self.assertIn("Hello", text)
        self.assertNotIn("bad()", text)


class ImageWorkflowTests(unittest.TestCase):
    def test_standard_comfyui_workflow_wires_output(self) -> None:
        workflow = ImageGenerationManager._workflow(
            "clean white studio", "blurry", "model.safetensors", 768, 512, 20, 42
        )
        self.assertEqual(workflow["4"]["inputs"]["ckpt_name"], "model.safetensors")
        self.assertEqual(workflow["5"]["inputs"]["width"], 768)
        self.assertEqual(workflow["9"]["inputs"]["images"], ["8", 0])


class ProviderAndModelTests(unittest.TestCase):
    def test_file_transfer_copies_bytes_and_reports_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            target = root / "target.bin"
            source.write_bytes(b"ai-hub-transfer" * 100)
            context = ProviderContext(
                prompt=json.dumps({"source": str(source), "target": str(target)}),
                project_path=root,
                permission_mode="workspace",
            )
            result = FileTransferProvider().run(
                context,
                lambda _stage, _message, _progress, _level: None,
                threading.Event(),
            )
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual(len(result.metadata["sha256"]), 64)

    def test_catalog_never_exceeds_user_50b_cap(self) -> None:
        sizes = [float(item["parameters_b"]) for item in MODEL_CATALOG if item.get("parameters_b")]
        self.assertTrue(sizes)
        self.assertLessEqual(max(sizes), 50)
        self.assertTrue(any("DeepSeek-R1-0528-Qwen3-8B" in item["id"] for item in MODEL_CATALOG))

    def test_training_preflight_validates_jsonl_and_hardware(self) -> None:
        class LimitedHardware:
            @staticmethod
            def snapshot():
                return {"memory": {"total_gb": 16}, "disk": {"free_gb": 100}}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "training.jsonl"
            example = {"messages": [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}]}
            dataset.write_text("\n".join(json.dumps(example) for _ in range(8)), encoding="utf-8")
            manager = ModelManager(AppPaths.create(root), LimitedHardware(), None)  # type: ignore[arg-type]
            result = manager.training_preflight("deepseek-r1:7b", str(dataset))
            self.assertTrue(result["dataset"]["valid"])
            self.assertFalse(result["ready"])
            self.assertTrue(any("RAM" in blocker or "CUDA" in blocker for blocker in result["blockers"]))


if __name__ == "__main__":
    unittest.main()

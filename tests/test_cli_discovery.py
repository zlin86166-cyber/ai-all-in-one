from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_hub.cli_discovery import scan_local_ai_clis


class CliDiscoveryTests(unittest.TestCase):
    def test_finds_known_commands_case_insensitively_without_running_them(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            command = root / "Tools" / "CODEX.CMD"
            command.parent.mkdir()
            command.write_text("@echo off\necho placeholder\n", encoding="utf-8")

            snapshot = scan_local_ai_clis(roots=[root])

        self.assertEqual(snapshot["directories"], 2)
        self.assertEqual(
            [(item["id"], item["command"]) for item in snapshot["results"]],
            [("codex", "codex")],
        )
        self.assertTrue(snapshot["results"][0]["path"].endswith("CODEX.CMD"))

    def test_finds_nested_node_and_python_cli_shims_without_walking_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            node_bin = root / "project" / "node_modules" / ".bin"
            node_bin.mkdir(parents=True)
            (node_bin / "gemini.cmd").write_text("@echo off\n", encoding="utf-8")
            (root / "project" / "node_modules" / "large-package").mkdir()

            venv_scripts = root / "project" / ".venv" / "Scripts"
            venv_scripts.mkdir(parents=True)
            (venv_scripts / "aider.exe").write_bytes(b"test stub")

            snapshot = scan_local_ai_clis(roots=[root])

        self.assertEqual({item["id"] for item in snapshot["results"]}, {"gemini", "aider"})
        self.assertEqual(snapshot["directories"], 2)

    def test_checks_local_path_shims_and_skips_network_path_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "scan-root"
            root.mkdir()
            path_dir = base / "path-bin"
            path_dir.mkdir()
            command = path_dir / "codex.cmd"
            command.write_text("@echo off\n", encoding="utf-8")

            path_value = os.pathsep.join((str(path_dir), r"\\server\share"))
            with patch.dict(os.environ, {"PATH": path_value}):
                snapshot = scan_local_ai_clis(roots=[root], search_path=True)

        self.assertEqual(snapshot["path_directories"], 1)
        self.assertEqual([(item["id"], item["path"]) for item in snapshot["results"]], [("codex", str(command))])

    def test_prunes_system_cache_names_and_reparse_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            hidden = root / "Windows" / "System32"
            hidden.mkdir(parents=True)
            (hidden / "codex.exe").write_bytes(b"not executed")
            (root / ".git" / "objects").mkdir(parents=True)
            (root / ".git" / "objects" / "gemini.cmd").write_text("", encoding="utf-8")

            snapshot = scan_local_ai_clis(roots=[root])

        self.assertEqual(snapshot["results"], [])
        self.assertEqual(snapshot["directories"], 1)

    def test_cancel_event_stops_scan_and_reports_partial_results(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "codex.cmd").write_text("", encoding="utf-8")
            cancel = threading.Event()

            def stop_before_walk(_snapshot: dict[str, object]) -> None:
                cancel.set()

            snapshot = scan_local_ai_clis(roots=[root], cancel_event=cancel, progress=stop_before_walk)

        self.assertTrue(snapshot["cancelled"])
        self.assertEqual(snapshot["directories"], 0)
        self.assertEqual(snapshot["results"], [])


if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "coredump-full-analysis" / "scripts" / "reporting" / "generate_gerrit_web_report.py"

spec = importlib.util.spec_from_file_location("generate_gerrit_web_report", SCRIPT_PATH)
gerrit_report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gerrit_report)


class GerritWebReportCollectionTests(unittest.TestCase):
    def write_json(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_collects_submitted_commit_json(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.write_json(
                workspace / "5.崩溃分析" / "gerrit" / "commit_abc123.json",
                {
                    "commit_hash": "abc123",
                    "branch": "auto-fix/dde-dock/v1_2_3",
                    "target_branch": "develop/eagle",
                    "package": "dde-dock",
                    "version": "1.2.3",
                    "reviewers": ["reviewer@example.com"],
                    "time": "2026-05-08T10:00:00+08:00",
                    "status": "submitted",
                },
            )

            records, warnings = gerrit_report.collect_workspace_records(workspace)

            self.assertEqual([], warnings)
            self.assertEqual(1, len(records))
            record = records[0]
            self.assertEqual("abc123", record.commit_hash)
            self.assertEqual("dde-dock", record.package)
            self.assertEqual("1.2.3", record.version)
            self.assertEqual("develop/eagle", record.target_branch)
            self.assertEqual(["reviewer@example.com"], record.reviewers)
            self.assertEqual("submitted", record.local_status)
            self.assertIn("5.崩溃分析/gerrit/commit_abc123.json", record.source_files)

    def test_collects_submitted_auto_fix_commit_hashes(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.write_json(
                workspace / "5.崩溃分析" / "dde-dock" / "version_1_2_3" / "auto_fix_clusters_result.json",
                {
                    "package": "dde-dock",
                    "version": "1.2.3",
                    "target_branch": "origin/develop/eagle",
                    "submitted": True,
                    "commit_hashes": ["abc123", "def456"],
                    "auto_fixed": [
                        {
                            "description": "修复空指针崩溃",
                            "files_changed": ["src/a.cpp", "src/b.cpp"],
                        }
                    ],
                    "clusters": [
                        {
                            "cluster": {
                                "title": "QScreen geometry crash",
                                "signal": "SIGSEGV",
                                "count": 12,
                            }
                        }
                    ],
                },
            )

            records, warnings = gerrit_report.collect_workspace_records(workspace)

            self.assertEqual([], warnings)
            self.assertEqual(["abc123", "def456"], [record.commit_hash for record in records])
            for record in records:
                self.assertEqual("dde-dock", record.package)
                self.assertEqual("1.2.3", record.version)
                self.assertEqual("origin/develop/eagle", record.target_branch)
                self.assertEqual("修复空指针崩溃", record.fix_description)
                self.assertEqual(["src/a.cpp", "src/b.cpp"], record.files_changed)
                self.assertEqual("QScreen geometry crash", record.cluster_title)
                self.assertEqual("SIGSEGV", record.signal)
                self.assertEqual(12, record.crash_count)

    def test_merges_duplicate_commit_sources(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.write_json(
                workspace / "5.崩溃分析" / "gerrit" / "commit_abc123.json",
                {
                    "commit_hash": "abc123",
                    "target_branch": "develop/eagle",
                    "package": "dde-dock",
                    "version": "1.2.3",
                    "reviewers": ["reviewer@example.com"],
                    "status": "submitted",
                },
            )
            self.write_json(
                workspace / "5.崩溃分析" / "dde-dock" / "version_1_2_3" / "auto_fix_result.json",
                {
                    "package": "dde-dock",
                    "version": "1.2.3",
                    "submitted": True,
                    "commit_hash": "abc123",
                    "auto_fixed": [
                        {
                            "reason": "cherry-picked known upstream fix",
                            "files_changed": ["src/fix.cpp"],
                        }
                    ],
                },
            )

            records, warnings = gerrit_report.collect_workspace_records(workspace)

            self.assertEqual([], warnings)
            self.assertEqual(1, len(records))
            record = records[0]
            self.assertEqual("abc123", record.commit_hash)
            self.assertEqual("dde-dock", record.package)
            self.assertEqual("1.2.3", record.version)
            self.assertEqual(["reviewer@example.com"], record.reviewers)
            self.assertEqual(["src/fix.cpp"], record.files_changed)
            self.assertEqual(2, len(record.source_files))

    def test_invalid_json_is_warning_not_failure(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bad_file = workspace / "5.崩溃分析" / "gerrit" / "commit_bad.json"
            bad_file.parent.mkdir(parents=True, exist_ok=True)
            bad_file.write_text("{not-json", encoding="utf-8")

            records, warnings = gerrit_report.collect_workspace_records(workspace)

            self.assertEqual([], records)
            self.assertEqual(1, len(warnings))
            self.assertIn("commit_bad.json", warnings[0].path)
            self.assertIn("JSON", warnings[0].message)

    def test_empty_workspace_returns_empty_records(self):
        with TemporaryDirectory() as tmp:
            records, warnings = gerrit_report.collect_workspace_records(Path(tmp))

            self.assertEqual([], records)
            self.assertEqual([], warnings)

    def test_generate_report_writes_data_and_page(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.write_json(
                workspace / "5.崩溃分析" / "gerrit" / "commit_abc123.json",
                {
                    "commit_hash": "abc123",
                    "target_branch": "develop/eagle",
                    "package": "dde-dock",
                    "version": "1.2.3",
                    "status": "submitted",
                },
            )

            output_dir = gerrit_report.generate_report(workspace, enrich=False)

            data_path = output_dir / "data.json"
            page_path = output_dir / "index.html"
            self.assertTrue(data_path.exists())
            self.assertTrue(page_path.exists())
            payload = json.loads(data_path.read_text(encoding="utf-8"))
            page = page_path.read_text(encoding="utf-8")
            self.assertEqual(1, payload["summary"]["total_records"])
            self.assertEqual("dde-dock", payload["records"][0]["package"])
            self.assertIn("Gerrit Web Report", page)
            self.assertIn("abc123", page)
            self.assertIn("textContent", page)

    def test_generate_report_writes_empty_report(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            output_dir = gerrit_report.generate_report(workspace, enrich=False)

            payload = json.loads((output_dir / "data.json").read_text(encoding="utf-8"))
            page = (output_dir / "index.html").read_text(encoding="utf-8")
            self.assertEqual(0, payload["summary"]["total_records"])
            self.assertIn("未发现已提交 Gerrit 的修复变更", page)

    def test_port_available_detects_bound_port(self):
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            host, port = sock.getsockname()
            self.assertFalse(gerrit_report.port_available(host, port))


if __name__ == "__main__":
    unittest.main()

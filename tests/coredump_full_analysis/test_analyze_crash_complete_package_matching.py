import subprocess
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "coredump-full-analysis" / "scripts" / "analyze_crash_complete.sh"


class AgentEntrypointTests(unittest.TestCase):
    def test_run_analysis_agent_does_not_hardcode_openclaw_script_directory(self):
        script = (REPO_ROOT / "run_analysis_agent.sh").read_text(encoding="utf-8")

        self.assertNotIn('cd "$HOME/.openclaw/skills/coredump-analysis-skills/coredump-full-analysis/scripts"', script)


class PackageMatchingTests(unittest.TestCase):
    def run_find_debs(self, arch: str) -> str:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            downloads = tmp_path / "downloads"
            downloads.mkdir()
            (downloads / "dde-session-ui_5.8.16-1_amd64.deb").write_text("", encoding="utf-8")
            (downloads / "dde-session-ui-dbgsym_5.8.16-1_amd64.deb").write_text("", encoding="utf-8")

            script_copy = tmp_path / "analyze_crash_complete.sh"
            content = SCRIPT_PATH.read_text(encoding="utf-8")
            content = content.replace('\n# 运行\nmain "$@"\n', '\n')
            script_copy.write_text(content, encoding="utf-8")

            command = textwrap.dedent(
                f"""
                set -euo pipefail
                source {script_copy}
                find_deb_files_for_version {downloads} dde-session-ui 5.8.16 {arch}
                """
            )
            result = subprocess.run(
                ["bash", "-c", command],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return result.stdout

    def test_x86_matches_amd64_deb_and_dbgsym_files(self):
        output = self.run_find_debs("x86")

        self.assertIn("dde-session-ui_5.8.16-1_amd64.deb", output)
        self.assertIn("dde-session-ui-dbgsym_5.8.16-1_amd64.deb", output)


if __name__ == "__main__":
    unittest.main()

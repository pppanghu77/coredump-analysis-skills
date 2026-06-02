import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / 'run_analysis_cron.sh'


class RunAnalysisCronScriptTests(unittest.TestCase):
    def test_help_describes_weekly_pure_analysis_flow(self):
        result = subprocess.run(
            ['bash', str(SCRIPT_PATH), '--help'],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(0, result.returncode)
        self.assertIn('默认计算最近7天日期窗口；若结果无数据则自动回退到最近15天', result.stdout)
        self.assertIn('AUTO_FIX_SUBMIT=false', result.stdout)
        self.assertIn('run_analysis_agent.sh', result.stdout)
        self.assertIn('validate_workspace.sh', result.stdout)

    def test_script_uses_agent_engine_and_keeps_reports_in_workspace(self):
        content = SCRIPT_PATH.read_text(encoding='utf-8')
        self.assertIn('AUTO_FIX_SUBMIT=false', content)
        self.assertIn('bash "$SCRIPT_DIR/run_analysis_agent.sh"', content)
        self.assertIn('bash "$SCRIPT_DIR/coredump-full-analysis/scripts/validate_workspace.sh"', content)
        self.assertNotIn('Desktop', content)
        self.assertNotIn('|| true', content)
        self.assertIn("date +%Y-%m-%d -d '6 days ago'", content)
        self.assertIn("date +%Y-%m-%d -d '14 days ago'", content)
        self.assertIn('get_valid_records', content)
        self.assertIn('reset_workspace_contents', content)


if __name__ == '__main__':
    unittest.main()

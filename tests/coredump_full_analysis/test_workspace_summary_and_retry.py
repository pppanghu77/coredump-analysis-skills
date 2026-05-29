import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_SCRIPT = REPO_ROOT / 'coredump-full-analysis' / 'scripts' / 'reporting' / 'generate_workspace_summary.py'
VERIFY_SCRIPT = REPO_ROOT / 'coredump-full-analysis' / 'scripts' / 'validation' / 'verify_retry_targets.py'
SUMMARY_DIR_NAME = '6.总结报告'


class WorkspaceSummaryAndRetryTests(unittest.TestCase):
    def create_workspace(self, root: Path) -> Path:
        workspace = root / 'workspace'
        (workspace / '2.数据筛选').mkdir(parents=True)
        (workspace / '3.代码管理' / 'dde-dock' / '.git').mkdir(parents=True)
        (workspace / '4.包管理' / 'downloads').mkdir(parents=True)
        (workspace / '5.崩溃分析' / 'dde-dock' / 'version_5_9_1').mkdir(parents=True)
        (workspace / '5.崩溃分析' / 'dde-launcher' / 'version_5_7_25_1').mkdir(parents=True)
        (workspace / SUMMARY_DIR_NAME).mkdir(parents=True)

        (workspace / '4.包管理' / 'downloads' / 'dde-dock_5.9.1_amd64.deb').write_text('deb', encoding='utf-8')
        (workspace / '5.崩溃分析' / 'dde-dock' / 'version_5_9_1' / 'analysis.json').write_text(json.dumps({
            'version': '5.9.1',
            'crashes': [
                {
                    'signal': 'SIGSEGV',
                    'count': 3,
                    'app_layer_symbol': 'DockItem::paint',
                    'app_layer_library': 'dde-dock',
                    'description': 'null pointer',
                    'fix_reason': 'app-layer ownership clear',
                    'stack_info': 'DockItem::paint -> QWidget::event',
                }
            ],
        }, ensure_ascii=False), encoding='utf-8')
        (workspace / '5.崩溃分析' / 'dde-dock' / 'full_analysis_report.md').write_text('# full\n', encoding='utf-8')
        (workspace / '5.崩溃分析' / 'dde-dock' / 'AI_analysis_report.md').write_text('# ai\n', encoding='utf-8')

        (workspace / '2.数据筛选' / 'dde-dock_crash_statistics.json').write_text(json.dumps({
            'summary': {
                'total_records': 10,
                'valid_records': 8,
                'unique_crashes': 2,
                'duplicate_crashes': 6,
                'versions_count': 1,
                'analysis_time': '2026-05-28 09:00:00',
            },
            'by_signal': {'SIGSEGV': 8},
            'by_version': {'5.9.1': {'total_crashes': 8, 'unique_crashes': 2}},
        }, ensure_ascii=False), encoding='utf-8')
        (workspace / '2.数据筛选' / 'dde-launcher_crash_statistics.json').write_text(json.dumps({
            'summary': {
                'total_records': 5,
                'valid_records': 5,
                'unique_crashes': 1,
                'duplicate_crashes': 4,
                'versions_count': 1,
                'analysis_time': '2026-05-28 09:00:00',
            },
            'by_signal': {'SIGABRT': 5},
            'by_version': {'5.7.25.1': {'total_crashes': 5, 'unique_crashes': 1}},
        }, ensure_ascii=False), encoding='utf-8')
        (workspace / '2.数据筛选' / 'dde-launcher_crash_versions.txt').write_text('dde-launcher:5.7.25.1-1:5\n', encoding='utf-8')

        (workspace / SUMMARY_DIR_NAME / 'package_status.tsv').write_text(
            '2026-05-28T09:00:00\tdde-dock\tcompleted\t0\tdone\n'
            '2026-05-28T09:00:00\tdde-launcher\tfailed\t1\tsource missing\n',
            encoding='utf-8',
        )
        (workspace / SUMMARY_DIR_NAME / 'version_status.tsv').write_text(
            '2026-05-28T09:01:00\tdde-launcher\t5.7.25.1\tsource\tfailed\trepo missing\n',
            encoding='utf-8',
        )
        (workspace / SUMMARY_DIR_NAME / 'run_context.json').write_text(json.dumps({
            'packages': 'dde-dock,dde-launcher',
            'date_range_label': '全部可下载数据（不按日期过滤）',
        }, ensure_ascii=False), encoding='utf-8')
        return workspace

    def test_generate_workspace_summary_outputs_retry_artifacts(self):
        with TemporaryDirectory() as tmp:
            workspace = self.create_workspace(Path(tmp))
            result = subprocess.run([
                'python3', str(SUMMARY_SCRIPT),
                '--workspace', str(workspace),
                '--packages', 'dde-dock,dde-launcher',
                '--status-file', str(workspace / SUMMARY_DIR_NAME / 'package_status.tsv'),
                '--version-status-file', str(workspace / SUMMARY_DIR_NAME / 'version_status.tsv'),
                '--date-range-label', '全部可下载数据（不按日期过滤）',
            ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

            summary_dir = workspace / SUMMARY_DIR_NAME
            manifest = json.loads((summary_dir / 'run_manifest.json').read_text(encoding='utf-8'))
            retry_packages = (summary_dir / 'retry_packages.txt').read_text(encoding='utf-8')
            retry_versions = (summary_dir / 'retry_versions.tsv').read_text(encoding='utf-8')
            retry_summary = (summary_dir / 'retry_summary.md').read_text(encoding='utf-8')
            retry_commands = (summary_dir / 'retry_commands.sh').read_text(encoding='utf-8')
            retry_version_commands = (summary_dir / 'retry_versions.sh').read_text(encoding='utf-8')

        package_map = {entry['package']: entry for entry in manifest['packages']}
        self.assertEqual('completed', package_map['dde-dock']['status'])
        self.assertEqual('failed', package_map['dde-launcher']['status'])
        self.assertIn('dde-launcher\n', retry_packages)
        self.assertIn('dde-launcher\t5.7.25.1\tsource', retry_versions)
        self.assertIn('需要重跑的包: 1', retry_summary)
        self.assertIn('需要重跑的版本: 1', retry_summary)
        self.assertIn('verify_retry_targets.py', retry_commands)
        self.assertIn('generate_workspace_summary.py', retry_commands)
        self.assertIn('verify_retry_targets.py', retry_version_commands)
        self.assertIn('retry_versions.md 已生成', result.stdout)

    def test_verify_retry_targets_reports_remaining_items(self):
        with TemporaryDirectory() as tmp:
            summary_dir = Path(tmp) / SUMMARY_DIR_NAME
            summary_dir.mkdir(parents=True)
            (summary_dir / 'retry_packages.txt').write_text('# 需要重跑的包\ndde-launcher\n', encoding='utf-8')
            (summary_dir / 'retry_versions.tsv').write_text(
                'package\tversion\tfailed_steps\tretry_strategy\tlast_message\tcommand\tstep_command\n'
                'dde-launcher\t5.7.25.1\tsource\tfull\trepo missing\tcmd\tstep\n',
                encoding='utf-8',
            )
            targets = Path(tmp) / 'targets.tsv'
            targets.write_text('dde-launcher\t5.7.25.1\n', encoding='utf-8')

            result = subprocess.run([
                'python3', str(VERIFY_SCRIPT),
                '--summary-dir', str(summary_dir),
                '--packages', 'dde-launcher,dde-dock',
                '--versions-file', str(targets),
            ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        self.assertEqual(1, result.returncode)
        self.assertIn('remaining packages: 1', result.stdout)
        self.assertIn('remaining versions: 1', result.stdout)
        self.assertIn('dde-launcher', result.stdout)
        self.assertIn('dde-launcher\t5.7.25.1', result.stdout)

    def test_verify_retry_targets_succeeds_when_targets_cleared(self):
        with TemporaryDirectory() as tmp:
            summary_dir = Path(tmp) / SUMMARY_DIR_NAME
            summary_dir.mkdir(parents=True)
            (summary_dir / 'retry_packages.txt').write_text('# 需要重跑的包\n', encoding='utf-8')
            (summary_dir / 'retry_versions.tsv').write_text(
                'package\tversion\tfailed_steps\tretry_strategy\tlast_message\tcommand\tstep_command\n',
                encoding='utf-8',
            )
            targets = Path(tmp) / 'targets.tsv'
            targets.write_text('dde-launcher\t5.7.25.1\n', encoding='utf-8')

            result = subprocess.run([
                'python3', str(VERIFY_SCRIPT),
                '--summary-dir', str(summary_dir),
                '--packages', 'dde-launcher',
                '--versions-file', str(targets),
            ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        self.assertEqual(0, result.returncode)
        self.assertIn('remaining packages: 0', result.stdout)
        self.assertIn('remaining versions: 0', result.stdout)


if __name__ == '__main__':
    unittest.main()

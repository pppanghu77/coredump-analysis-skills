import csv
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / 'coredump-full-analysis' / 'scripts'
SCRIPT_PATH = SCRIPT_DIR / 'analyze_crash_per_version.py'


class AnalyzeCrashPerVersionVersionMatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(SCRIPT_DIR))
        spec = importlib.util.spec_from_file_location('analyze_crash_per_version', SCRIPT_PATH)
        if spec is None or spec.loader is None:
            raise AssertionError('failed to load analyze_crash_per_version module spec')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.module = module

    def write_filtered_csv(self, path: Path, rows):
        fieldnames = [
            'Version', 'Package', 'Count', 'Exe', 'Sig', 'StackInfo',
            'StackSignature', 'StackInfo_Size', 'Stack_Frames_Count',
            'App_Layer_Library', 'App_Layer_Symbol', 'First_Seen',
            'Baseline', 'Sys_V_Number'
        ]
        with path.open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def test_analyze_version_matches_rows_with_non_one_epoch_prefix(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            filter_dir = workspace / '2.数据筛选'
            filter_dir.mkdir(parents=True)

            filtered_csv = filter_dir / 'filtered_kwin-x11_crash_data.csv'
            self.write_filtered_csv(filtered_csv, [
                {
                    'Version': '4:5.27.2.101-1',
                    'Package': 'kwin-x11',
                    'Count': '3',
                    'Exe': '/usr/bin/kwin_x11',
                    'Sig': 'SIGSEGV',
                    'StackInfo': '#0  0x00007f7adab875cb raise (libpthread.so.0)\n#1  0x00007f7adadc7833 _ZN6KCrash19defaultCrashHandlerEi (libKF5Crash.so.5)\n#2  0x0000000000464709 n/a (kwin_x11)',
                    'StackSignature': 'sig-1',
                    'StackInfo_Size': '3',
                    'Stack_Frames_Count': '3',
                    'App_Layer_Library': 'libKF5Crash.so.5',
                    'App_Layer_Symbol': '_ZN6KCrash19defaultCrashHandlerEi',
                    'First_Seen': '2026-06-16T00:00:00+08:00',
                    'Baseline': 'pro-20-std-0036',
                    'Sys_V_Number': '1070',
                }
            ])
            (filter_dir / 'kwin-x11_crash_statistics.json').write_text(
                json.dumps({'by_version': {'4:5.27.2.101-1': {'unique_crashes': 1, 'total_crashes': 3}}}, ensure_ascii=False),
                encoding='utf-8',
            )

            result = self.module.analyze_version(
                package='kwin-x11',
                version='5.27.2.101',
                workspace=str(workspace),
                max_crashes=0,
                addr2line_max_frames=500,
                analysis_mode='ai-only',
                ai_only_reason='test',
            )

        self.assertEqual(1, result['summary']['unique_crashes'])
        self.assertEqual(3, result['summary']['total_crash_records'])
        self.assertEqual('5.27.2.101', result['version_clean'])
        self.assertEqual({'unique_crashes': 1, 'total_crashes': 3}, result['version_stats'])
        self.assertEqual('SIGSEGV', result['crashes'][0]['signal'])


if __name__ == '__main__':
    unittest.main()

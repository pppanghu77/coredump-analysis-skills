import os
import subprocess
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / 'run_analysis_agent.sh'


def script_without_runtime_validation() -> str:
    content = SCRIPT_PATH.read_text(encoding='utf-8')
    runtime_start_marker = '\n# 加载流程开关配置（数据筛选为必需步骤，不提供关闭开关）\n'
    package_functions_marker = '\n# 包名处理函数\n'
    date_label_marker = '\nif [[ -z "$START_DATE" && -z "$END_DATE" ]]; then\n'
    progress_functions_marker = '\n# 进度报告函数\n'
    main_block_marker = '\n# 并行启动所有包的分析\n'
    for marker, label in (
        (runtime_start_marker, 'runtime start marker'),
        (package_functions_marker, 'package functions marker'),
        (date_label_marker, 'date label marker'),
        (progress_functions_marker, 'progress functions marker'),
        (main_block_marker, 'main block marker'),
    ):
        if marker not in content:
            raise AssertionError(f'{label} not found in run_analysis_agent.sh')

    prelude = content.split(runtime_start_marker, 1)[0]
    package_functions = content.split(package_functions_marker, 1)[1].split(date_label_marker, 1)[0]
    progress_functions = content.split(progress_functions_marker, 1)[1].split(main_block_marker, 1)[0]
    return (
        prelude
        + '\n# runtime entrypoint disabled in tests\n'
        + package_functions_marker
        + package_functions
        + progress_functions_marker
        + progress_functions
        + '\n'
    )


class RunAnalysisAgentHelpTests(unittest.TestCase):
    def run_script(self, *args, env=None):
        return subprocess.run(
            ['bash', str(SCRIPT_PATH), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )

    def test_help_mentions_default_progress_interval_and_auto_fix(self):
        result = self.run_script('--help')
        self.assertEqual(0, result.returncode)
        self.assertIn('--auto-fix-submit 当前默认已开启（仅真实代码修改可提交 Gerrit）', result.stdout)
        self.assertIn('AUTO_FIX_SUBMIT=false bash run_analysis_agent.sh', result.stdout)
        self.assertIn('--progress 不带数值时，默认使用 180 秒', result.stdout)

    def test_help_describes_project_and_package_roles(self):
        result = self.run_script('--help')
        self.assertEqual(0, result.returncode)
        self.assertIn('项目名：可选，Gerrit 仓库路径；用于代码下载与 Gerrit 归属', result.stdout)
        self.assertIn('包名：必填；用于搜索崩溃数据（Metabase）以及下载 deb/dbgsym', result.stdout)
        self.assertIn('默认按包名下载崩溃数据；如需覆盖下载键，请在下游分析脚本中显式传入 --data-download-name', result.stdout)

    def test_auto_fix_submit_respects_environment_override(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            script_copy = tmp_path / 'run_analysis_agent.sh'
            script_copy.write_text(script_without_runtime_validation(), encoding='utf-8')
            cmd = textwrap.dedent(f'''\
                set -euo pipefail
                export AUTO_FIX_SUBMIT=false
                source {script_copy}
                printf 'AUTO_FIX_SUBMIT=%s\n' "$AUTO_FIX_SUBMIT"
            ''')
            result = subprocess.run(['bash', '-c', cmd], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        self.assertIn('AUTO_FIX_SUBMIT=false', result.stdout)

    def test_progress_rejects_non_integer(self):
        result = self.run_script('--progress', 'bad')
        self.assertNotEqual(0, result.returncode)
        self.assertIn('参数 --progress 需要整数秒数', result.stdout)

    def test_interval_rejects_non_integer(self):
        result = self.run_script('--interval', '12x')
        self.assertNotEqual(0, result.returncode)
        self.assertIn('参数 --interval 需要整数秒数', result.stdout)

    def test_packages_requires_value(self):
        result = self.run_script('--packages')
        self.assertNotEqual(0, result.returncode)
        self.assertIn('参数 --packages 缺少取值', result.stdout)

    def test_progress_without_value_is_accepted_by_help_path(self):
        result = self.run_script('--progress', '--help')
        self.assertEqual(0, result.returncode)
        self.assertIn('默认使用 180 秒', result.stdout)

    def test_missing_packages_file_reports_error(self):
        with TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env.update(HOME=tmp, SKILLS_DIR=tmp)
            result = self.run_script(env=env)
        self.assertNotEqual(0, result.returncode)
        self.assertIn('必须指定 --packages 参数，且 packages.txt 不存在', result.stdout)

    def test_empty_packages_file_reports_error(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / 'packages.txt').write_text('\n# only comments\n', encoding='utf-8')
            env = os.environ.copy()
            env.update(HOME=tmp, SKILLS_DIR=str(tmp_path))
            result = self.run_script(env=env)
        self.assertNotEqual(0, result.returncode)
        self.assertIn('packages.txt 为空', result.stdout)


class PackagesFileParsingTests(unittest.TestCase):
    def test_parse_packages_file_supports_project_and_branch_mappings(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            packages_file = tmp_path / 'packages.txt'
            packages_file.write_text(textwrap.dedent('''\
                # comments allowed
                dde-dock
                go-lib:golang-github-linuxdeepin-go-lib-dev
                dde-network-core:dcc-network-plugin,deepin-service-plugin-network,dock-network-plugin
                base/lightdm:lightdm uos
            '''), encoding='utf-8')
            script_copy = tmp_path / 'run_analysis_agent.sh'
            script_copy.write_text(script_without_runtime_validation(), encoding='utf-8')
            cmd = textwrap.dedent(f'''\
                set -euo pipefail
                source {script_copy}
                parse_packages_file {packages_file} >/tmp/parsed_packages.txt
                parsed=$(cat /tmp/parsed_packages.txt)
                printf 'PACKAGES=%s\n' "$parsed"
                printf 'PROJECT_lightdm=%s\n' "$(get_package_project lightdm)"
                printf 'BRANCH_lightdm=%s\n' "$(get_package_branch lightdm)"
                printf 'PROJECT_go=%s\n' "$(get_package_project golang-github-linuxdeepin-go-lib-dev)"
                printf 'PROJECT_network=%s\n' "$(get_package_project deepin-service-plugin-network)"
            ''')
            result = subprocess.run(['bash', '-c', cmd], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        self.assertIn('PACKAGES=dde-dock,golang-github-linuxdeepin-go-lib-dev,dcc-network-plugin,deepin-service-plugin-network,dock-network-plugin,lightdm', result.stdout)
        self.assertIn('PROJECT_lightdm=base/lightdm', result.stdout)
        self.assertIn('BRANCH_lightdm=origin/uos', result.stdout)
        self.assertIn('PROJECT_go=go-lib', result.stdout)
        self.assertIn('PROJECT_network=dde-network-core', result.stdout)

    def test_default_packages_load_uses_package_name_for_download_mapping(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            packages_file = tmp_path / 'packages.txt'
            packages_file.write_text(textwrap.dedent('''\
                dde-network-core:dcc-network-plugin,deepin-service-plugin-network,dock-network-plugin
                deepin-authentication:deepin-authenticate,libdeepin-authenticate
                deepin-kde/kwin:kwin-x11,kwin-wayland uos
            '''), encoding='utf-8')
            script_copy = tmp_path / 'run_analysis_agent.sh'
            script_copy.write_text(script_without_runtime_validation(), encoding='utf-8')
            cmd = textwrap.dedent(f'''\
                set -euo pipefail
                source {script_copy}
                PACKAGES_FILE={packages_file}
                load_default_packages_if_needed >/dev/null
                printf 'PACKAGES=%s\n' "$PACKAGES"
                printf 'DOWNLOAD_NETWORK=%s\n' "$(get_package_data_download_name deepin-service-plugin-network)"
                printf 'PROJECT_NETWORK=%s\n' "$(get_package_project deepin-service-plugin-network)"
                printf 'DOWNLOAD_AUTH=%s\n' "$(get_package_data_download_name libdeepin-authenticate)"
                printf 'PROJECT_AUTH=%s\n' "$(get_package_project libdeepin-authenticate)"
                printf 'DOWNLOAD_KWIN=%s\n' "$(get_package_data_download_name kwin-x11)"
                printf 'PROJECT_KWIN=%s\n' "$(get_package_project kwin-x11)"
                printf 'BRANCH_KWIN=%s\n' "$(get_package_branch kwin-x11)"
            ''')
            result = subprocess.run(['bash', '-c', cmd], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        self.assertIn('PACKAGES=dcc-network-plugin,deepin-service-plugin-network,dock-network-plugin,deepin-authenticate,libdeepin-authenticate,kwin-x11,kwin-wayland', result.stdout)
        self.assertIn('DOWNLOAD_NETWORK=deepin-service-plugin-network', result.stdout)
        self.assertIn('PROJECT_NETWORK=dde-network-core', result.stdout)
        self.assertIn('DOWNLOAD_AUTH=libdeepin-authenticate', result.stdout)
        self.assertIn('PROJECT_AUTH=deepin-authentication', result.stdout)
        self.assertIn('DOWNLOAD_KWIN=kwin-x11', result.stdout)
        self.assertIn('PROJECT_KWIN=deepin-kde/kwin', result.stdout)
        self.assertIn('BRANCH_KWIN=origin/uos', result.stdout)

    def test_default_packages_load_preserves_project_download_mappings(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            packages_file = tmp_path / 'packages.txt'
            packages_file.write_text(textwrap.dedent('''\
                dde-network-core:dcc-network-plugin,deepin-service-plugin-network,dock-network-plugin
                deepin-authentication:deepin-authenticate,libdeepin-authenticate
            '''), encoding='utf-8')
            script_copy = tmp_path / 'run_analysis_agent.sh'
            script_copy.write_text(script_without_runtime_validation(), encoding='utf-8')
            cmd = textwrap.dedent(f'''\
                set -euo pipefail
                source {script_copy}
                PACKAGES_FILE={packages_file}
                load_default_packages_if_needed >/dev/null
                printf 'PACKAGES=%s\n' "$PACKAGES"
                printf 'DOWNLOAD_NETWORK=%s\n' "$(get_package_data_download_name deepin-service-plugin-network)"
                printf 'PROJECT_NETWORK=%s\n' "$(get_package_project deepin-service-plugin-network)"
                printf 'DOWNLOAD_AUTH=%s\n' "$(get_package_data_download_name libdeepin-authenticate)"
                printf 'PROJECT_AUTH=%s\n' "$(get_package_project libdeepin-authenticate)"
            ''')
            result = subprocess.run(['bash', '-c', cmd], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        self.assertIn('PACKAGES=dcc-network-plugin,deepin-service-plugin-network,dock-network-plugin,deepin-authenticate,libdeepin-authenticate', result.stdout)
        self.assertIn('DOWNLOAD_NETWORK=deepin-service-plugin-network', result.stdout)
        self.assertIn('PROJECT_NETWORK=dde-network-core', result.stdout)
        self.assertIn('DOWNLOAD_AUTH=libdeepin-authenticate', result.stdout)
        self.assertIn('PROJECT_AUTH=deepin-authentication', result.stdout)

    def test_explicit_packages_still_loads_mapping_metadata_from_packages_file(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            packages_file = tmp_path / 'packages.txt'
            packages_file.write_text('deepin-kde/kwin:kwin-x11 uos\n', encoding='utf-8')
            script_copy = tmp_path / 'run_analysis_agent.sh'
            script_copy.write_text(script_without_runtime_validation(), encoding='utf-8')
            cmd = textwrap.dedent(f'''\
                set -euo pipefail
                source {script_copy}
                PACKAGES='kwin-x11'
                PACKAGES_FILE={packages_file}
                load_default_packages_if_needed >/dev/null
                printf 'PACKAGES=%s\n' "$PACKAGES"
                printf 'PROJECT_KWIN=%s\n' "$(get_package_project kwin-x11)"
                printf 'DOWNLOAD_KWIN=%s\n' "$(get_package_data_download_name kwin-x11)"
                printf 'BRANCH_KWIN=%s\n' "$(get_package_branch kwin-x11)"
            ''')
            result = subprocess.run(['bash', '-c', cmd], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        self.assertIn('PACKAGES=kwin-x11', result.stdout)
        self.assertIn('PROJECT_KWIN=deepin-kde/kwin', result.stdout)
        self.assertIn('DOWNLOAD_KWIN=kwin-x11', result.stdout)
        self.assertIn('BRANCH_KWIN=origin/uos', result.stdout)

    def test_parse_packages_file_ignores_blank_and_comment_lines(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            packages_file = tmp_path / 'packages.txt'
            packages_file.write_text('\n# a\n\n dde-dock \n# b\n', encoding='utf-8')
            script_copy = tmp_path / 'run_analysis_agent.sh'
            script_copy.write_text(script_without_runtime_validation(), encoding='utf-8')
            cmd = textwrap.dedent(f'''\
                set -euo pipefail
                source {script_copy}
                parse_packages_file {packages_file}
            ''')
            result = subprocess.run(['bash', '-c', cmd], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        self.assertEqual('dde-dock\n', result.stdout)


    def test_apply_target_branch_override_updates_all_packages(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            script_copy = tmp_path / 'run_analysis_agent.sh'
            script_copy.write_text(script_without_runtime_validation(), encoding='utf-8')
            cmd = textwrap.dedent(f'''\
                set -euo pipefail
                source {script_copy}
                PACKAGES='dde-dock,dde-launcher'
                parse_packages_file /dev/null >/dev/null
                build_package_array
                TARGET_BRANCH='origin/feature/test'
                apply_target_branch_override
                printf 'BRANCH_DOCK=%s\n' "$(get_package_branch dde-dock)"
                printf 'BRANCH_LAUNCHER=%s\n' "$(get_package_branch dde-launcher)"
                printf 'DEFAULT=%s\n' "$DEFAULT_TARGET_BRANCH"
            ''')
            result = subprocess.run(['bash', '-c', cmd], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        self.assertIn('BRANCH_DOCK=origin/feature/test', result.stdout)
        self.assertIn('BRANCH_LAUNCHER=origin/feature/test', result.stdout)
        self.assertIn('DEFAULT=origin/feature/test', result.stdout)

    def test_launch_package_omits_data_download_name_when_it_matches_package(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            script_copy = tmp_path / 'run_analysis_agent.sh'
            script_copy.write_text(script_without_runtime_validation(), encoding='utf-8')
            scripts_dir = tmp_path / 'coredump-full-analysis' / 'scripts'
            scripts_dir.mkdir(parents=True)
            argv_file = tmp_path / 'argv.txt'
            (scripts_dir / 'analyze_crash_complete.sh').write_text(textwrap.dedent(f'''\
                #!/bin/bash
                printf '%s\n' "$@" > {argv_file}
            '''), encoding='utf-8')
            os.chmod(scripts_dir / 'analyze_crash_complete.sh', 0o755)
            cmd = textwrap.dedent(f'''\
                set -euo pipefail
                source {script_copy}
                SKILLS_DIR={tmp_path}
                WORKSPACE={tmp_path / 'workspace'}
                PACKAGE_STATUS_FILE={tmp_path / 'package_status.tsv'}
                AUTO_FIX_SUBMIT=false
                SUDO_PASSWORD=''
                launch_package kwin-x11
            ''')
            subprocess.run(['bash', '-c', cmd], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            argv = argv_file.read_text(encoding='utf-8')

        self.assertIn('--packages\nkwin-x11\n', argv)
        self.assertNotIn('--data-download-name\n', argv)

    def test_launch_package_passes_data_download_name_when_it_differs_from_package(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            script_copy = tmp_path / 'run_analysis_agent.sh'
            script_copy.write_text(script_without_runtime_validation(), encoding='utf-8')
            scripts_dir = tmp_path / 'coredump-full-analysis' / 'scripts'
            scripts_dir.mkdir(parents=True)
            argv_file = tmp_path / 'argv.txt'
            (scripts_dir / 'analyze_crash_complete.sh').write_text(textwrap.dedent(f'''\
                #!/bin/bash
                printf '%s\n' "$@" > {argv_file}
            '''), encoding='utf-8')
            os.chmod(scripts_dir / 'analyze_crash_complete.sh', 0o755)
            cmd = textwrap.dedent(f'''\
                set -euo pipefail
                source {script_copy}
                SKILLS_DIR={tmp_path}
                WORKSPACE={tmp_path / 'workspace'}
                PACKAGE_STATUS_FILE={tmp_path / 'package_status.tsv'}
                AUTO_FIX_SUBMIT=false
                SUDO_PASSWORD=''
                PACKAGE_DATA_DOWNLOAD_MAP['kwin-x11']='kwin-download-key'
                launch_package kwin-x11
            ''')
            subprocess.run(['bash', '-c', cmd], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            argv = argv_file.read_text(encoding='utf-8')

        self.assertIn('--packages\nkwin-x11\n', argv)
        self.assertIn('--data-download-name\nkwin-download-key\n', argv)

    def test_output_summary_lists_auto_fix_overview_path(self):
        content = SCRIPT_PATH.read_text(encoding='utf-8')
        self.assertIn('Auto-fix汇总: $WORKSPACE/$SUMMARY_DIR_NAME/auto_fix_overview.md', content)


if __name__ == '__main__':
    unittest.main()

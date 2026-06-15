import subprocess
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "coredump-full-analysis" / "scripts" / "analyze_crash_complete.sh"


class AgentEntrypointTests(unittest.TestCase):
    def test_run_analysis_agent_does_not_hardcode_openclaw_script_directory(self):
        script = (REPO_ROOT / "run_analysis_agent.sh").read_text(encoding="utf-8")

        self.assertNotIn('cd "$HOME/.openclaw/skills/coredump-analysis-skills/coredump-full-analysis/scripts"', script)


class PackageMatchingTests(unittest.TestCase):
    def load_script_without_main(self, tmp_path: Path) -> Path:
        script_copy = tmp_path / "analyze_crash_complete.sh"
        content = SCRIPT_PATH.read_text(encoding="utf-8")
        content = content.replace('\n# 运行\nmain "$@"\n', '\n')
        script_copy.write_text(content, encoding="utf-8")
        return script_copy

    def run_find_debs(self, arch: str) -> str:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            downloads = tmp_path / "downloads"
            downloads.mkdir()
            (downloads / "dde-session-ui_5.8.16-1_amd64.deb").write_text("", encoding="utf-8")
            (downloads / "dde-session-ui-dbgsym_5.8.16-1_amd64.deb").write_text("", encoding="utf-8")

            script_copy = self.load_script_without_main(tmp_path)

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

    def run_download_data(
        self,
        package: str,
        data_download_name: str = "",
        expected_csv_name: Optional[str] = None,
        arch: str = "x86",
        existing_csv_names: Optional[List[str]] = None,
    ) -> str:
        if expected_csv_name is None:
            download_key = data_download_name or package
            csv_arch_suffix = "AARCH64" if arch in {"arm", "arm64", "aarch64"} else "X86"
            expected_csv_name = f"{download_key.replace('/', '_')}_{csv_arch_suffix}_crash_test.csv"

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workspace = tmp_path / "workspace"
            data_download_dir = workspace / "1.数据下载"
            data_download_dir.mkdir(parents=True)
            for existing_csv_name in existing_csv_names or []:
                (data_download_dir / existing_csv_name).write_text("cached\n", encoding="utf-8")

            skills_dir = tmp_path / "skills"
            download_script = skills_dir / "coredump-data-download" / "scripts" / "download_metabase_csv.sh"
            download_script.parent.mkdir(parents=True)
            download_script.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    package_arg="${{@: -3:1}}"
                    echo "PACKAGE_ARG=$package_arg" >&2
                    printf 'header\\n' > {data_download_dir / expected_csv_name}
                    """
                ),
                encoding="utf-8",
            )
            download_script.chmod(0o755)

            script_copy = self.load_script_without_main(tmp_path)
            command = textwrap.dedent(
                f"""
                set -euo pipefail
                source {script_copy}
                WORKSPACE={workspace}
                SKILLS_DIR={skills_dir}
                PACKAGE={package!r}
                DATA_DOWNLOAD_NAME={data_download_name!r}
                SYS_VERSION=test-system
                ARCH={arch!r}
                START_DATE=
                END_DATE=
                download_data
                """
            )
            result = subprocess.run(
                ["bash", "-c", command],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return result.stdout + result.stderr + f"\nRETURN_CODE={result.returncode}\n"

    def run_download_data_for_slash_data_download_name(
        self,
        package: str,
        data_download_name: str,
    ) -> str:
        return self.run_download_data(
            package=package,
            data_download_name=data_download_name,
        )

    def run_main_with_zero_row_filtered_output(self, package: str) -> subprocess.CompletedProcess:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workspace = tmp_path / "workspace"
            skills_dir = tmp_path / "skills"
            config_dir = tmp_path / "config"
            config_dir.mkdir(parents=True)
            (config_dir / "package-server.env").write_text("", encoding="utf-8")

            download_script = skills_dir / "coredump-data-download" / "scripts" / "download_metabase_csv.sh"
            download_script.parent.mkdir(parents=True)
            download_script.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    printf 'download_header\\n' > "$PWD/{package}_X86_crash_test.csv"
                    """
                ),
                encoding="utf-8",
            )
            download_script.chmod(0o755)

            filter_script = skills_dir / "coredump-data-filter" / "scripts" / "filter_crash_data.py"
            filter_script.parent.mkdir(parents=True)
            filter_script.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import argparse
                    from pathlib import Path

                    parser = argparse.ArgumentParser()
                    parser.add_argument("--workspace", required=True)
                    parser.add_argument("--input-csv", required=True)
                    parser.add_argument("package")
                    args = parser.parse_args()

                    output_dir = Path(args.workspace) / "2.数据筛选"
                    output_dir.mkdir(parents=True, exist_ok=True)
                    (output_dir / f"filtered_{args.package}_crash_data.csv").write_text("col1,col2\\n", encoding="utf-8")
                    (output_dir / f"{args.package}_crash_versions.txt").write_text("5.8.32-1:1\\n", encoding="utf-8")
                    (output_dir / f"{args.package}_crash_statistics.json").write_text('{"summary":{"raw":0,"valid":0,"unique":0,"versions":0}}', encoding="utf-8")
                    """
                ),
                encoding="utf-8",
            )
            filter_script.chmod(0o755)

            package_script = skills_dir / "coredump-package-management" / "scripts" / "scan_and_download.py"
            package_script.parent.mkdir(parents=True)
            package_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            package_script.chmod(0o755)

            analysis_script = skills_dir / "coredump-full-analysis" / "scripts" / "analyze_crash_per_version.py"
            analysis_script.parent.mkdir(parents=True)
            analysis_script.write_text(
                "#!/usr/bin/env python3\nfrom pathlib import Path\nPath(__file__).resolve().parents[3].joinpath(\"analysis_was_called.marker\").write_text(\"called\\n\", encoding=\"utf-8\")\n",
                encoding="utf-8",
            )
            analysis_script.chmod(0o755)

            full_report_script = skills_dir / "coredump-full-analysis" / "scripts" / "reporting" / "generate_full_report.py"
            full_report_script.parent.mkdir(parents=True, exist_ok=True)
            full_report_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            full_report_script.chmod(0o755)

            ai_report_script = skills_dir / "coredump-full-analysis" / "scripts" / "reporting" / "generate_ai_report.py"
            ai_report_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            ai_report_script.chmod(0o755)

            final_report_script = skills_dir / "coredump-full-analysis" / "scripts" / "reporting" / "generate_final_report.py"
            final_report_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            final_report_script.chmod(0o755)

            load_accounts_script = tmp_path / "load_accounts.sh"
            load_accounts_script.write_text(
                textwrap.dedent(
                    """\
                    load_accounts_or_die() {
                        GERRIT_USER=tester
                        GERRIT_SSH_KEY=/tmp/nonexistent
                    }
                    """
                ),
                encoding="utf-8",
            )
            load_accounts_script.chmod(0o755)

            marker_path = tmp_path / "analysis_was_called.marker"
            script_copy = self.load_script_without_main(tmp_path)
            command = textwrap.dedent(
                f"""
                set -euo pipefail
                source {script_copy}
                SCRIPT_DIR={tmp_path!s}
                CONFIG_DIR={config_dir!s}
                LOAD_ACCOUNTS_SCRIPT={load_accounts_script!s}
                SKILLS_DIR={skills_dir!s}
                PACKAGE={package!r}
                SYS_VERSION=test-system
                ARCH=x86
                WORKSPACE={workspace!s}
                ENABLE_CODE_MANAGEMENT=false
                ENABLE_PACKAGE_MANAGEMENT=false
                AUTO_FIX_SUBMIT=false
                main --packages {package}
                """
            )
            result = subprocess.run(
                ["bash", "-c", command],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            marker_status = f"\nANALYSIS_MARKER_EXISTS={marker_path.exists()}\n"
            return subprocess.CompletedProcess(
                args=result.args,
                returncode=result.returncode,
                stdout=result.stdout + marker_status,
                stderr=result.stderr + marker_status,
            )

    def test_x86_matches_amd64_deb_and_dbgsym_files(self):
        output = self.run_find_debs("x86")

        self.assertIn("dde-session-ui_5.8.16-1_amd64.deb", output)
        self.assertIn("dde-session-ui-dbgsym_5.8.16-1_amd64.deb", output)

    def test_download_data_defaults_to_package_name_without_explicit_download_override(self):
        output = self.run_download_data_for_slash_data_download_name(
            package="kwin-x11",
            data_download_name="",
        )

        self.assertIn("kwin-x11", output)
        self.assertIn("kwin-x11_X86_crash_test.csv", output)

    def test_download_data_accepts_sanitized_csv_name_for_slash_project(self):
        output = self.run_download_data_for_slash_data_download_name(
            package="kwin-x11",
            data_download_name="deepin-kde/kwin",
        )

        self.assertIn("deepin-kde/kwin", output)
        self.assertIn("deepin-kde_kwin_X86_crash_test.csv", output)

    def test_download_data_does_not_reuse_sanitized_cached_csv_from_wrong_architecture(self):
        output = self.run_download_data(
            package="kwin-x11",
            data_download_name="deepin-kde/kwin",
            arch="aarch64",
            existing_csv_names=["deepin-kde_kwin_X86_crash_cached.csv"],
        )

        self.assertNotIn("复用当前 workspace 已下载数据", output)
        self.assertIn("PACKAGE_ARG=deepin-kde/kwin", output)
        self.assertIn("deepin-kde_kwin_AARCH64_crash_test.csv", output)
        self.assertIn("RETURN_CODE=0", output)

    def test_download_data_reuses_x86_csv_when_arch_is_amd64(self):
        output = self.run_download_data(
            package="kwin-x11",
            arch="amd64",
            existing_csv_names=["kwin-x11_X86_crash_cached.csv"],
        )

        self.assertIn("复用当前 workspace 已下载数据", output)
        self.assertIn("kwin-x11_X86_crash_cached.csv", output)
        self.assertNotIn("PACKAGE_ARG=kwin-x11", output)
        self.assertIn("RETURN_CODE=0", output)

    def test_zero_row_download_is_reported_and_skipped(self):
        result = self.run_main_with_zero_row_filtered_output(package="kwin-x11")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("download_empty_skipped", result.stderr)
        self.assertIn("package=kwin-x11", result.stderr)
        self.assertIn("download_key=kwin-x11", result.stderr)
        self.assertIn("no effective rows", result.stderr)
        self.assertIn("skipping package", result.stderr)
        self.assertIn("--data-download-name", result.stderr)
        self.assertIn("project-level download", result.stderr)
        self.assertIn("ANALYSIS_MARKER_EXISTS=False", result.stderr)


if __name__ == "__main__":
    unittest.main()

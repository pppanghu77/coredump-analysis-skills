#!/bin/bash
#=============================================================================
# 失败步骤重跑执行器
# 将重跑结果反写到 6.总结报告/version_status.tsv
#=============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUMMARY_DIR_NAME="6.总结报告"

PACKAGE=""
VERSION=""
WORKSPACE=""
STRATEGY=""
ARCH=""
SYS_VERSION=""
START_DATE=""
END_DATE=""

show_help() {
    cat << EOF
用法:
  $0 --package <name> --version <version> --workspace <dir> --strategy <name> [选项]

选项:
  --package <name>        包名
  --version <version>     版本号
  --workspace <dir>       工作目录
  --strategy <name>       重跑策略: analysis_only | package_then_analysis | full_version_rerun
  --arch <arch>           架构
  --sys-version <ver>     系统版本
  --start-date <date>     开始日期
  --end-date <date>       结束日期
  --help, -h              显示帮助
EOF
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --package)
            PACKAGE="$2"
            shift 2
            ;;
        --version)
            VERSION="$2"
            shift 2
            ;;
        --workspace)
            WORKSPACE="$2"
            shift 2
            ;;
        --strategy)
            STRATEGY="$2"
            shift 2
            ;;
        --arch)
            ARCH="$2"
            shift 2
            ;;
        --sys-version)
            SYS_VERSION="$2"
            shift 2
            ;;
        --start-date)
            START_DATE="$2"
            shift 2
            ;;
        --end-date)
            END_DATE="$2"
            shift 2
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            echo "未知参数: $1" >&2
            show_help >&2
            exit 1
            ;;
    esac
done

if [[ -z "$PACKAGE" || -z "$VERSION" || -z "$WORKSPACE" || -z "$STRATEGY" ]]; then
    echo "错误: 必须指定 --package, --version, --workspace, --strategy" >&2
    exit 1
fi

ensure_status_file() {
    mkdir -p "$WORKSPACE/$SUMMARY_DIR_NAME"
    if [[ ! -f "$WORKSPACE/$SUMMARY_DIR_NAME/version_status.tsv" ]]; then
        printf "#timestamp\tpackage\tversion\tstep\tstatus\tmessage\n" > "$WORKSPACE/$SUMMARY_DIR_NAME/version_status.tsv"
    fi
}

log_status() {
    local step="$1"
    local status="$2"
    local message="${3:-}"
    ensure_status_file
    printf "%s\t%s\t%s\t%s\t%s\t%s\n" \
        "$(date '+%Y-%m-%dT%H:%M:%S')" \
        "$PACKAGE" \
        "$VERSION" \
        "$step" \
        "$status" \
        "$message" >> "$WORKSPACE/$SUMMARY_DIR_NAME/version_status.tsv"
}

analysis_json_path() {
    local version_dir="${VERSION//./_}"
    version_dir="${version_dir//+/_}"
    version_dir="${version_dir//-/_}"
    printf "%s/5.崩溃分析/%s/version_%s/analysis.json" "$WORKSPACE" "$PACKAGE" "$version_dir"
}

find_deb_files_for_version() {
    local dl_dir="$1"
    find "$dl_dir" -maxdepth 1 -type f \( \
        -name "${PACKAGE}_${VERSION}_*.deb" -o \
        -name "${PACKAGE}_${VERSION}-*.deb" -o \
        -name "${PACKAGE}_${VERSION}+*.deb" -o \
        -name "${PACKAGE}_${VERSION}.*.deb" -o \
        -name "${PACKAGE}-dbgsym_${VERSION}_*.deb" -o \
        -name "${PACKAGE}-dbgsym_${VERSION}-*.deb" -o \
        -name "${PACKAGE}-dbgsym_${VERSION}+*.deb" -o \
        -name "${PACKAGE}-dbgsym_${VERSION}.*.deb" \
    \) 2>/dev/null
}

run_analysis_only() {
    if python3 "$SCRIPT_DIR/analyze_crash_per_version.py" \
        --package "$PACKAGE" \
        --version "$VERSION" \
        --workspace "$WORKSPACE" \
        --max-crashes 50; then
        if [[ -f "$(analysis_json_path)" ]]; then
            log_status "analysis" "ok" "retry analysis succeeded"
            return 0
        fi
        log_status "analysis" "failed_no_output" "retry analysis did not generate analysis.json"
        return 1
    fi

    log_status "analysis" "failed" "retry analysis command failed"
    return 1
}

run_package_then_analysis() {
    local download_dir="$WORKSPACE/4.包管理/downloads"
    mkdir -p "$download_dir"

    if python3 "$SCRIPT_DIR/../../coredump-package-management/scripts/scan_and_download.py" \
        -d "$download_dir" \
        "$PACKAGE" "$VERSION"; then
        if [[ -n "$(find_deb_files_for_version "$download_dir")" ]]; then
            log_status "package" "ok" "retry package download succeeded"
        else
            log_status "package" "failed_no_matching_package" "retry package download found no matching files"
            return 1
        fi
    else
        log_status "package" "failed" "retry package download command failed"
        return 1
    fi

    run_analysis_only
}

run_full_version_rerun() {
    local cmd=(bash "$SCRIPT_DIR/analyze_crash_complete.sh"
        --package "$PACKAGE"
        --workspace "$WORKSPACE"
        --versions "$VERSION")
    [[ -n "$ARCH" ]] && cmd+=(--arch "$ARCH")
    [[ -n "$SYS_VERSION" ]] && cmd+=(--sys-version "$SYS_VERSION")
    [[ -n "$START_DATE" ]] && cmd+=(--start-date "$START_DATE")
    [[ -n "$END_DATE" ]] && cmd+=(--end-date "$END_DATE")
    "${cmd[@]}"
}

case "$STRATEGY" in
    analysis_only)
        run_analysis_only
        ;;
    package_then_analysis)
        run_package_then_analysis
        ;;
    full_version_rerun)
        run_full_version_rerun
        ;;
    *)
        echo "错误: 不支持的 strategy: $STRATEGY" >&2
        exit 1
        ;;
esac

#!/bin/bash
#=============================================================================
# 每7天执行一次的崩溃分析自动化入口
# 默认分析最近7天；若无数据则自动回退到最近15天，走当前主链路纯分析流程
#=============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

show_help() {
    cat <<'EOF'
崩溃分析周自动化入口

用途:
  - 作为仓库唯一保留的 unattended / cron 自动化流程
  - 每次执行时默认计算最近7天日期窗口；若结果无数据则自动回退到最近15天
  - 固定以纯分析模式运行（AUTO_FIX_SUBMIT=false）
  - 调用 run_analysis_agent.sh 作为主分析引擎
  - 分析完成后自动执行 coredump-full-analysis/scripts/validate_workspace.sh 验收

可选环境变量:
  WORKSPACE_ROOT               工作目录根路径，默认: $HOME
  ANALYSIS_PACKAGES            显式包列表；为空时使用 packages.txt 默认项目集
  ANALYSIS_SYS_VERSION         系统版本范围，默认: 1070-1075
  ANALYSIS_ARCH                架构，默认: amd64
  ANALYSIS_PROGRESS_INTERVAL   进度监控秒数，默认: 180
  SKIP_VALIDATE                设为 true 时跳过验收

示例:
  run_analysis_cron.sh
  WORKSPACE_ROOT=/data/uos run_analysis_cron.sh
  ANALYSIS_PACKAGES=dde-session-ui,startdde run_analysis_cron.sh
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    show_help
    exit 0
fi

generate_workspace_with_timestamp() {
    local root_dir="$1"
    echo "$root_dir/coredump-workspace-$(date +%Y%m%d-%H%M%S)"
}

reset_workspace_contents() {
    rm -rf "$WORKSPACE/1.数据下载" \
           "$WORKSPACE/2.数据筛选" \
           "$WORKSPACE/3.代码管理" \
           "$WORKSPACE/4.包管理" \
           "$WORKSPACE/5.崩溃分析" \
           "$WORKSPACE/6.总结报告" \
           "$WORKSPACE/logs"
}

get_valid_records() {
    python3 - <<'PY' "$WORKSPACE/6.总结报告/run_manifest.json"
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
if not path.exists():
    print(-1)
    raise SystemExit(0)
try:
    data = json.loads(path.read_text(encoding='utf-8'))
except Exception:
    print(-1)
    raise SystemExit(0)
print(int(data.get('totals', {}).get('valid_records', 0) or 0))
PY
}

run_analysis_window() {
    local start_date="$1"
    local end_date="$2"
    local label="$3"

    echo "[$label] 执行纯分析..."
    echo "日期范围: $start_date 至 $end_date"

    local cmd=(bash "$SCRIPT_DIR/run_analysis_agent.sh"
        --start-date "$start_date"
        --end-date "$end_date"
        --sys-version "$ANALYSIS_SYS_VERSION"
        --arch "$ANALYSIS_ARCH"
        --workspace "$WORKSPACE"
        --progress "$ANALYSIS_PROGRESS_INTERVAL")

    if [[ -n "$ANALYSIS_PACKAGES" ]]; then
        cmd+=(--packages "$ANALYSIS_PACKAGES")
    fi

    AUTO_FIX_SUBMIT=false "${cmd[@]}"
}

WORKSPACE_ROOT="${WORKSPACE_ROOT:-$HOME}"
ANALYSIS_PACKAGES="${ANALYSIS_PACKAGES:-}"
ANALYSIS_SYS_VERSION="${ANALYSIS_SYS_VERSION:-1070-1075}"
ANALYSIS_ARCH="${ANALYSIS_ARCH:-amd64}"
ANALYSIS_PROGRESS_INTERVAL="${ANALYSIS_PROGRESS_INTERVAL:-180}"
SKIP_VALIDATE="${SKIP_VALIDATE:-false}"

WORKSPACE="$(generate_workspace_with_timestamp "$WORKSPACE_ROOT")"
mkdir -p "$WORKSPACE"

LOG_FILE="$WORKSPACE/cron_analysis_$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

NOW_DATE="$(date +%Y-%m-%d)"
PRIMARY_START_DATE="$(date +%Y-%m-%d -d '6 days ago')"
FALLBACK_START_DATE="$(date +%Y-%m-%d -d '14 days ago')"
END_DATE="$NOW_DATE"

EXEC_TIME="$(date '+%Y-%m-%d %H:%M:%S')"

echo "========================================"
echo "崩溃分析周自动化开始: $EXEC_TIME"
echo "========================================"
echo "工作目录: $WORKSPACE"
echo "默认日期范围: $PRIMARY_START_DATE 至 $END_DATE"
echo "回退日期范围: $FALLBACK_START_DATE 至 $END_DATE"
echo "系统版本: $ANALYSIS_SYS_VERSION"
echo "架构: $ANALYSIS_ARCH"
echo "进度间隔: ${ANALYSIS_PROGRESS_INTERVAL}秒"
if [[ -n "$ANALYSIS_PACKAGES" ]]; then
    echo "包集: $ANALYSIS_PACKAGES"
else
    echo "包集: packages.txt 默认项目集"
fi

run_analysis_window "$PRIMARY_START_DATE" "$END_DATE" "1/3"
analysis_exit=$?
if [[ $analysis_exit -ne 0 ]]; then
    echo "❌ 最近7天崩溃分析失败，退出码: $analysis_exit"
    exit $analysis_exit
fi

valid_records=$(get_valid_records)
echo "最近7天 valid_records: $valid_records"
if [[ "$valid_records" == "0" ]]; then
    echo "最近7天无有效崩溃记录，自动回退到最近15天窗口重跑..."
    reset_workspace_contents
    run_analysis_window "$FALLBACK_START_DATE" "$END_DATE" "2/3"
    analysis_exit=$?
    if [[ $analysis_exit -ne 0 ]]; then
        echo "❌ 最近15天回退分析失败，退出码: $analysis_exit"
        exit $analysis_exit
    fi
    valid_records=$(get_valid_records)
    echo "最近15天 valid_records: $valid_records"
else
    echo "最近7天已有有效崩溃记录，不触发15天回退。"
fi

echo "[3/3] 分析完成"

if [[ "$SKIP_VALIDATE" != "true" ]]; then
    echo "执行 workspace 验收..."
    bash "$SCRIPT_DIR/coredump-full-analysis/scripts/validate_workspace.sh" --workspace "$WORKSPACE"
    validate_exit=$?
    if [[ $validate_exit -ne 0 ]]; then
        echo "❌ workspace 验收失败，退出码: $validate_exit"
        exit $validate_exit
    fi
    echo "✅ workspace 验收完成"
else
    echo "已跳过 workspace 验收"
fi

echo "========================================"
echo "周自动化执行完成"
echo "日志文件: $LOG_FILE"
echo "workspace: $WORKSPACE"
echo "包级报告目录: $WORKSPACE/5.崩溃分析/"
echo "汇总报告目录: $WORKSPACE/6.总结报告/"
echo "========================================"

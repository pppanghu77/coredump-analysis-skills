#!/bin/bash
#=============================================================================
# 崩溃分析 Agent 调用脚本
# 用法: bash run_analysis_agent.sh --packages dde-session-ui [--start-date 2026-03-14] [--end-date 2026-04-14] [--sys-version 1070-1075]
#=============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 生成带时间戳的workspace路径
generate_workspace_with_timestamp() {
    local root_dir="${1:-$HOME}"
    echo "$root_dir/coredump-workspace-$(date +%Y%m%d-%H%M%S)"
}

# 默认值
PACKAGES=""
START_DATE=""
END_DATE=""
SYS_VERSION="1070-1075"
SKILLS_DIR="${SKILLS_DIR:-$SCRIPT_DIR}"
PACKAGES_FILE="$SKILLS_DIR/packages.txt"
LOAD_ACCOUNTS_SCRIPT="$SKILLS_DIR/coredump-full-analysis/scripts/load_accounts.sh"

ARCH="amd64"  # 默认使用 amd64 架构
WORKSPACE=""
RUN_BACKGROUND=false
PROGRESS_INTERVAL=0  # 0表示禁用进度监控，非0表示启用(秒)
AUTO_FIX_SUBMIT=false
TARGET_BRANCH="origin/develop/eagle"
REVIEWERS=()
SUMMARY_DIR_NAME="6.总结报告"
GENERATE_GERRIT_WEB_REPORT=true
SERVE_GERRIT_WEB_REPORT=false
PACKAGE_STATUS_FILE=""
LOG_DIR=""

# 显示帮助
show_help() {
    cat << EOF
${BLUE}=============================================================================
崩溃分析 Agent - 可复用的自动化崩溃分析工具
=============================================================================${NC}

${GREEN}用法:${NC}
    $0 --packages <包名列表> [选项]

${GREEN}必需参数:${NC}
    --packages <names>     要分析的包名（支持多包，逗号分隔）
                           例如: dde-session-ui
                           多包: dde-control-center,dde-dock,dde-launcher
                           不指定: 自动从 packages.txt 读取24个默认项目

${GREEN}可选参数:${NC}
    --start-date <date>   开始日期 (默认: 不限制，下载所有可取数据)
                           例如: 2026-03-14
    --end-date <date>     结束日期 (默认: 不限制，下载所有可取数据)
                           例如: 2026-04-14
    --sys-version <ver>   系统版本范围 (默认: 1070-1075)
                           例如: 1070, 1070-1075, 1070-1075
    --arch <arch>        架构 (默认: amd64)
                           例如: x86, x86_64, arm64
    --workspace <dir>      工作目录 (默认: ~/coredump-workspace-YYYYMMDD-HHMMSS)
    --background          后台运行
    --progress [秒]       启用进度监控 (默认: 180秒)
    --interval <秒>       进度报告间隔 (默认: 180秒)
    --auto-fix-submit     分析后自动检查 target branch 是否已修复，并对已注册 fixer 的模式尝试自动提交
    --target-branch <br>  自动修复提交目标分支 (默认: origin/develop/eagle)
    --reviewer <email>    自动提交时附加 reviewer，可多次指定
    --no-gerrit-web-report      禁用分析结束后的 Gerrit 网页报告生成
    --serve-gerrit-web-report   分析结束后启动本地服务查看 Gerrit 网页报告
    --help, -h           显示帮助

${GREEN}示例:${NC}
    # 全量分析（读取 packages.txt，分析全部24个默认项目）
    $0

    # 分析单个包所有能下载的崩溃 (x86)
    $0 --packages dde-session-ui

    # 分析单个包指定日期范围内的崩溃 (x86)
    $0 --packages dde-session-ui --start-date 2026-03-14 --end-date 2026-04-14

    # 并行分析多个包
    $0 --packages dde-control-center,dde-dock,dde-launcher,dde-session-ui,dde-session-shell,startdde,dde-daemon

    # 多包 + 进度监控 (每3分钟报告一次)
    $0 --packages dde-control-center,dde-dock --progress 180

    # 分析 dde-dock 指定版本范围
    $0 --packages dde-dock --sys-version 1060-1075

    # 后台运行
    $0 --packages dde-session-ui --background

    # 带进度监控 (每3分钟报告一次)
    $0 --packages dde-session-ui --progress

    # 带进度监控 (每2分钟报告一次)
    $0 --packages dde-session-ui --progress 120

    # 分析后自动检查已修复并提交可自动修复的问题
    $0 --packages dde-launcher --auto-fix-submit --target-branch origin/develop/eagle

    # 分析完成后启动 Gerrit 网页报告本地服务
    $0 --packages dde-dock --auto-fix-submit --serve-gerrit-web-report

${GREEN}兼容说明:${NC}
    仍兼容旧参数 --package，但新文档统一使用 --packages

${GREEN}输出文件:${NC}
    <workspace>/2.数据筛选/<package>_crash_statistics.json  - 统计报告
    <workspace>/2.数据筛选/filtered_<package>_crash_data.csv - 筛选后数据
    <workspace>/6.总结报告/gerrit-web-report/index.html - Gerrit网页报告

${BLUE}=============================================================================
${NC}
EOF
}

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --package)
            # 兼容单包参数
            PACKAGES="$2"
            shift 2
            ;;
        --packages)
            # 支持逗号分隔的多包列表
            PACKAGES="$2"
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
        --sys-version)
            SYS_VERSION="$2"
            shift 2
            ;;
        --arch)
            ARCH="$2"
            shift 2
            ;;
        --workspace)
            WORKSPACE="$2"
            shift 2
            ;;
        --background)
            RUN_BACKGROUND=true
            shift
            ;;
        --progress)
            PROGRESS_INTERVAL="${2:-180}"
            shift 2
            ;;
        --interval)
            PROGRESS_INTERVAL="$2"
            shift 2
            ;;
        --auto-fix-submit)
            AUTO_FIX_SUBMIT=true
            shift
            ;;
        --target-branch)
            TARGET_BRANCH="$2"
            shift 2
            ;;
        --reviewer)
            REVIEWERS+=("$2")
            shift 2
            ;;
        --no-gerrit-web-report)
            GENERATE_GERRIT_WEB_REPORT=false
            shift
            ;;
        --serve-gerrit-web-report)
            SERVE_GERRIT_WEB_REPORT=true
            shift
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            echo -e "${RED}未知参数: $1${NC}"
            show_help
            exit 1
            ;;
    esac
done

# 验证必需参数
if [[ -z "$PACKAGES" ]]; then
    # 未指定 --packages，尝试从 packages.txt 读取默认项目列表
    if [[ -f "$PACKAGES_FILE" ]]; then
        echo -e "${YELLOW}未指定 --packages，从 $PACKAGES_FILE 读取默认项目列表${NC}"
        PACKAGES=$(grep -v '^#' "$PACKAGES_FILE" | grep -v '^$' | tr '\n' ',' | sed 's/,$//')
        if [[ -z "$PACKAGES" ]]; then
            echo -e "${RED}错误: packages.txt 为空${NC}"
            exit 1
        fi
        echo -e "${GREEN}已加载 $(echo "$PACKAGES" | tr ',' '\n' | wc -l) 个分析项目${NC}"
    else
        echo -e "${RED}错误: 必须指定 --packages 参数，且 packages.txt 不存在${NC}"
        show_help
        exit 1
    fi
fi

# 转换为数组（支持逗号分隔）
IFS=',' read -ra PACKAGE_ARRAY <<< "$PACKAGES"
PACKAGE_COUNT=${#PACKAGE_ARRAY[@]}

# 包名处理函数
# 搜索崩溃时使用不带base/的包名，下载和分析代码时使用带base/的包名
get_crash_search_name() {
    local pkg="$1"
    # 去掉base/前缀用于崩溃数据搜索
    echo "${pkg#base/}"
}

get_download_name() {
    local pkg="$1"
    # 保留base/前缀用于下载和代码分析
    echo "$pkg"
}

if [[ -z "$START_DATE" && -z "$END_DATE" ]]; then
    DATE_RANGE_LABEL="全部可下载数据（不按日期过滤）"
elif [[ -n "$START_DATE" && -n "$END_DATE" ]]; then
    DATE_RANGE_LABEL="$START_DATE 至 $END_DATE"
elif [[ -n "$START_DATE" ]]; then
    DATE_RANGE_LABEL="$START_DATE 至 最新可下载"
else
    DATE_RANGE_LABEL="最早可下载 至 $END_DATE"
fi

echo -e "${BLUE}=============================================================================${NC}"
echo -e "${BLUE}                    崩溃分析 Agent 启动${NC}"
echo -e "${BLUE}=============================================================================${NC}"
echo ""
echo -e "${GREEN}分析参数:${NC}"
echo "  包名: $PACKAGES"
echo "  待分析包数量: $PACKAGE_COUNT"
echo "  架构: $ARCH"
echo "  日期范围: $DATE_RANGE_LABEL"
echo "  系统版本: $SYS_VERSION"
echo "  工作目录: $WORKSPACE"
if [[ "$PROGRESS_INTERVAL" -gt 0 ]]; then
    echo "  进度监控: ${PROGRESS_INTERVAL}秒"
fi
echo "  自动修复提交: $AUTO_FIX_SUBMIT"
echo "  自动修复目标分支: $TARGET_BRANCH"
echo "  Gerrit网页报告: $GENERATE_GERRIT_WEB_REPORT"
echo "  Gerrit网页服务: $SERVE_GERRIT_WEB_REPORT"
echo ""

# 从 accounts.json 读取凭据
if [[ ! -f "$LOAD_ACCOUNTS_SCRIPT" ]]; then
    echo -e "${RED}错误: 账号加载脚本不存在: $LOAD_ACCOUNTS_SCRIPT${NC}"
    exit 1
fi
source "$LOAD_ACCOUNTS_SCRIPT"
load_accounts_or_die metabase gerrit shuttle system

export GERRIT_USERNAME="$GERRIT_USER"

if [[ -z "$WORKSPACE" ]]; then
    local_workspace_root="${ACCOUNTS_WORKSPACE_ROOT:-$HOME}"
    if [[ -z "$local_workspace_root" ]]; then
        local_workspace_root="$HOME"
    fi
    WORKSPACE=$(generate_workspace_with_timestamp "$local_workspace_root")
fi

LOG_DIR="$WORKSPACE/$SUMMARY_DIR_NAME/logs"
mkdir -p "$LOG_DIR"

echo -e "${YELLOW}已从 accounts.json 加载账号配置${NC}"

# 进度报告函数
report_progress() {
    local elapsed=$1
    local pkg=$2
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}[$timestamp] 进度报告 (已运行 ${elapsed}秒)${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    local pkg_index=1
    for pkg in "${PACKAGE_ARRAY[@]}"; do
        echo -e "${GREEN}【${pkg_index}/${PACKAGE_COUNT}】${pkg}${NC}"

        # 统计下载目录中的CSV文件
        local csv_count=$(find "$WORKSPACE/1.数据下载" -name "${pkg}_X86_crash_*.csv" 2>/dev/null | wc -l)
        echo -e "  步骤① 数据下载: CSV文件: ${csv_count}个"

        # 统计筛选数据
        local filtered_file="$WORKSPACE/2.数据筛选/filtered_${pkg}_crash_data.csv"
        local stats_file="$WORKSPACE/2.数据筛选/${pkg}_crash_statistics.json"
        if [[ -f "$filtered_file" ]]; then
            local filtered_lines=$(wc -l < "$filtered_file" 2>/dev/null || echo "0")
            echo -e "  步骤② 数据筛选: 筛选后记录数: $((filtered_lines - 1))"
        fi
        if [[ -f "$stats_file" ]] && command -v jq &> /dev/null; then
            local unique=$(jq -r '.unique_crashes // .统计摘要.唯一崩溃数 // 0' "$stats_file" 2>/dev/null || echo "未知")
            local total=$(jq -r '.total_records // .统计摘要.总记录数 // 0' "$stats_file" 2>/dev/null || echo "未知")
            echo -e "    唯一崩溃: ${unique}, 总记录: ${total}"
        fi

        # 统计崩溃分析（已分析的版本）
        local analysis_dir="$WORKSPACE/5.崩溃分析/${pkg}"
        if [[ -d "$analysis_dir" ]]; then
            local version_count=$(find "$analysis_dir" -name "analysis.json" 2>/dev/null | wc -l)
            echo -e "  步骤⑤ 崩溃分析: 已分析版本: ${version_count}个"
        fi

        ((pkg_index++)) || true
    done

    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

ensure_summary_dir() {
    mkdir -p "$WORKSPACE/$SUMMARY_DIR_NAME"
}

write_run_context() {
    ensure_summary_dir
    python3 - "$WORKSPACE/$SUMMARY_DIR_NAME/run_context.json" <<'PY'
import json
import os
import sys

path = sys.argv[1]
data = {
    "workspace": os.environ.get("WORKSPACE", ""),
    "packages": os.environ.get("PACKAGES", ""),
    "arch": os.environ.get("ARCH", ""),
    "sys_version": os.environ.get("SYS_VERSION", ""),
    "start_date": os.environ.get("START_DATE", ""),
    "end_date": os.environ.get("END_DATE", ""),
    "date_range_label": os.environ.get("DATE_RANGE_LABEL", ""),
    "summary_dir_name": os.environ.get("SUMMARY_DIR_NAME", ""),
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
PY
}

init_package_status_file() {
    ensure_summary_dir
    write_run_context
    PACKAGE_STATUS_FILE="$WORKSPACE/$SUMMARY_DIR_NAME/package_status.tsv"
    if [[ ! -f "$PACKAGE_STATUS_FILE" ]]; then
        printf "#timestamp\tpackage\tstatus\texit_code\tmessage\n" > "$PACKAGE_STATUS_FILE"
    fi
}

log_package_status() {
    local package="$1"
    local status="$2"
    local exit_code="${3:-}"
    local message="${4:-}"
    ensure_summary_dir
    printf "%s\t%s\t%s\t%s\t%s\n" \
        "$(date '+%Y-%m-%dT%H:%M:%S')" \
        "$package" \
        "$status" \
        "$exit_code" \
        "$message" >> "$PACKAGE_STATUS_FILE"
}

generate_workspace_reports() {
    local failed_csv="$1"
    local summary_script="$SKILLS_DIR/coredump-full-analysis/scripts/generate_workspace_summary.py"
    if [[ ! -f "$summary_script" ]]; then
        echo -e "${YELLOW}⚠️ 未找到 workspace 汇总脚本: $summary_script${NC}"
        return 0
    fi

    local failed_packages=""
    if [[ -n "$failed_csv" ]]; then
        failed_packages="$failed_csv"
    fi

    ensure_summary_dir
    echo -e "${YELLOW}生成 workspace 汇总报告...${NC}"
    python3 "$summary_script" \
        --workspace "$WORKSPACE" \
        --packages "$PACKAGES" \
        --date-range-label "$DATE_RANGE_LABEL" \
        --status-file "$PACKAGE_STATUS_FILE" \
        --version-status-file "$WORKSPACE/$SUMMARY_DIR_NAME/version_status.tsv" \
        --failed-packages "$failed_packages"
}

generate_gerrit_web_report() {
    if [[ "$GENERATE_GERRIT_WEB_REPORT" != "true" ]]; then
        return 0
    fi

    local report_script="$SKILLS_DIR/coredump-full-analysis/scripts/generate_gerrit_web_report.py"
    if [[ ! -f "$report_script" ]]; then
        echo -e "${YELLOW}⚠️ 未找到 Gerrit 网页报告脚本: $report_script${NC}"
        return 0
    fi

    local cmd=(python3 "$report_script" --workspace "$WORKSPACE")
    if [[ "$SERVE_GERRIT_WEB_REPORT" == "true" ]]; then
        cmd+=(--serve)
    fi

    echo -e "${YELLOW}生成 Gerrit 网页报告...${NC}"
    if "${cmd[@]}"; then
        echo -e "${GREEN}✅ Gerrit 网页报告已生成: $WORKSPACE/$SUMMARY_DIR_NAME/gerrit-web-report/index.html${NC}"
    else
        echo -e "${YELLOW}⚠️ Gerrit 网页报告生成失败，主分析结果不受影响${NC}"
    fi
}

# 检查进程是否还在运行
is_running() {
    kill -0 "$1" 2>/dev/null
}

# 启动单个包的崩溃分析
launch_package() {
    local pkg="$1"
    log_package_status "$pkg" "running" "" "analysis started"
    cd "$SKILLS_DIR/coredump-full-analysis/scripts"
    local cmd=(bash analyze_crash_complete.sh
        --packages "$pkg"
        --arch "$ARCH"
        --sys-version "$SYS_VERSION"
        --workspace "$WORKSPACE")
    [[ -n "$START_DATE" ]] && cmd+=(--start-date "$START_DATE")
    [[ -n "$END_DATE" ]] && cmd+=(--end-date "$END_DATE")
    [[ "$AUTO_FIX_SUBMIT" == "true" ]] && cmd+=(--auto-fix-submit)
    [[ -n "$TARGET_BRANCH" ]] && cmd+=(--target-branch "$TARGET_BRANCH")
    local reviewer
    for reviewer in "${REVIEWERS[@]}"; do
        cmd+=(--reviewer "$reviewer")
    done
    if SUDO_PASSWORD="$SUDO_PASSWORD" PROGRESS_INTERVAL="$PROGRESS_INTERVAL" "${cmd[@]}" 2>&1; then
        # 如果启用了自动修复提交，调用修复映射脚本
        if [[ "$AUTO_FIX_SUBMIT" == "true" ]]; then
            echo -e "${YELLOW}开始修复映射和Gerrit提交...${NC}"
            local fix_script="$SKILLS_DIR/coredump-crash-analysis/scripts/analyze_with_fix_mapping.py"
            if [[ -f "$fix_script" ]]; then
                # 获取用于崩溃搜索的包名（去掉base/前缀）
                local search_pkg=$(get_crash_search_name "$pkg")
                python3 "$fix_script" \
                    --package "$search_pkg" \
                    --workspace "$WORKSPACE" \
                    --target-branch "$TARGET_BRANCH" 2>&1
                local fix_exit_code=$?
                if [[ $fix_exit_code -eq 0 ]]; then
                    echo -e "${GREEN}✅ 修复映射完成${NC}"
                else
                    echo -e "${RED}❌ 修复映射失败${NC}"
                fi
            else
                echo -e "${YELLOW}⚠️ 修复映射脚本不存在: $fix_script${NC}"
            fi
        fi
        log_package_status "$pkg" "completed" "0" "analysis completed"
        return 0
    fi

    local exit_code=$?
    log_package_status "$pkg" "failed" "$exit_code" "analysis exited with failure"
    return "$exit_code"
}

# 并行启动所有包的分析
if [[ "$RUN_BACKGROUND" == "true" ]]; then
    init_package_status_file
    echo -e "${YELLOW}后台运行模式${NC}"
    echo "并行启动 $PACKAGE_COUNT 个包的分析..."
    declare -a PIDS
    for pkg in "${PACKAGE_ARRAY[@]}"; do
        launch_package "$pkg" > "$LOG_DIR/analysis_${pkg}.log" 2>&1 &
        pid=$!
        PIDS+=($pid)
        echo -e "${GREEN}✅ $pkg 已启动 (PID: $pid)${NC}"
    done

    (
        overall_exit=0
        for pid in "${PIDS[@]}"; do
            wait "$pid" || overall_exit=$?
        done
        generate_workspace_reports "" >> "$LOG_DIR/analysis_workspace_summary.log" 2>&1
        generate_gerrit_web_report >> "$LOG_DIR/analysis_workspace_summary.log" 2>&1
        exit "$overall_exit"
    ) &
    summary_pid=$!
    echo ""
    echo "使用 'jobs' 查看后台任务，或查看各包日志:"
    for pkg in "${PACKAGE_ARRAY[@]}"; do
        echo "  tail -f $LOG_DIR/analysis_${pkg}.log  # $pkg"
    done
    echo "  tail -f $LOG_DIR/analysis_workspace_summary.log  # workspace 汇总"
    echo "  后台汇总进程 PID: $summary_pid"

elif [[ "$PROGRESS_INTERVAL" -gt 0 ]]; then
    init_package_status_file
    # 启用进度监控模式：并行启动所有包
    echo -e "${YELLOW}启用进度监控 (间隔: ${PROGRESS_INTERVAL}秒)${NC}"
    echo "并行启动 $PACKAGE_COUNT 个包的分析..."
    echo ""

    declare -a PIDS
    for pkg in "${PACKAGE_ARRAY[@]}"; do
        launch_package "$pkg" > "$LOG_DIR/analysis_${pkg}.log" 2>&1 &
        pid=$!
        PIDS+=($pid)
        echo -e "${GREEN}🚀 $pkg 已启动 (PID: $pid)${NC}"
    done

    # 初始化
    START_TIME=$(date +%s)
    LAST_REPORT_TIME=$START_TIME

    # 监控循环：检查所有进程是否结束
    any_running() {
        for pid in "${PIDS[@]}"; do
            if kill -0 "$pid" 2>/dev/null; then
                return 0
            fi
        done
        return 1
    }

    while any_running; do
        CURRENT_TIME=$(date +%s)
        ELAPSED=$((CURRENT_TIME - START_TIME))
        INTERVAL_PASSED=$((CURRENT_TIME - LAST_REPORT_TIME))

        if [[ $INTERVAL_PASSED -ge $PROGRESS_INTERVAL ]]; then
            report_progress $ELAPSED ""
            LAST_REPORT_TIME=$CURRENT_TIME
        fi

        sleep 5  # 每5秒检查一次
    done

    # 等待所有进程结束
    ALL_EXIT_CODE=0
    for pid in "${PIDS[@]}"; do
        wait "$pid" || ALL_EXIT_CODE=$?
    done

    # 最终进度报告
    END_TIME=$(date +%s)
    TOTAL_ELAPSED=$((END_TIME - START_TIME))

    echo ""
    echo -e "${BLUE}=============================================================================${NC}"
    echo -e "${BLUE}                    分析流程已结束${NC}"
    echo -e "${BLUE}=============================================================================${NC}"
    echo ""
    echo -e "${GREEN}最终状态:${NC}"
    echo "  总耗时: ${TOTAL_ELAPSED}秒 ($(($TOTAL_ELAPSED / 60))分$(($TOTAL_ELAPSED % 60))秒)"
    echo ""

    report_progress $TOTAL_ELAPSED ""

    echo -e "${GREEN}输出文件:${NC}"
    for pkg in "${PACKAGE_ARRAY[@]}"; do
        echo "  $pkg:"
        echo "    统计报告: $WORKSPACE/2.数据筛选/${pkg}_crash_statistics.json"
        echo "    筛选数据: $WORKSPACE/2.数据筛选/filtered_${pkg}_crash_data.csv"
        echo "    分析报告: $WORKSPACE/5.崩溃分析/${pkg}/"
    done
    generate_workspace_reports ""
    generate_gerrit_web_report
    echo "  Workspace汇总: $WORKSPACE/$SUMMARY_DIR_NAME/run_manifest.md"
    echo "  跨包汇总: $WORKSPACE/$SUMMARY_DIR_NAME/all_packages_summary.md"
    echo "  Gerrit网页报告: $WORKSPACE/$SUMMARY_DIR_NAME/gerrit-web-report/index.html"
    echo "  问题簇汇总: $WORKSPACE/$SUMMARY_DIR_NAME/root_cause_clusters.md"
    echo "  失败包清单: $WORKSPACE/$SUMMARY_DIR_NAME/retry_packages.txt"
    echo "  失败版本清单: $WORKSPACE/$SUMMARY_DIR_NAME/retry_versions.md"
    echo "  重跑脚本: $WORKSPACE/$SUMMARY_DIR_NAME/retry_commands.sh"
    echo "  版本重跑脚本: $WORKSPACE/$SUMMARY_DIR_NAME/retry_versions.sh"
    echo "  失败步骤重跑脚本: $WORKSPACE/$SUMMARY_DIR_NAME/retry_failed_steps.sh"
    echo "  闭环校验: python3 coredump-full-analysis/scripts/validate_workspace_retry_closure.py --workspace $WORKSPACE"
    echo "  一键验收: bash coredump-full-analysis/scripts/validate_workspace.sh --workspace $WORKSPACE"
    echo "  验收报告: $WORKSPACE/$SUMMARY_DIR_NAME/acceptance_report.txt"
    echo "  验收状态: $WORKSPACE/$SUMMARY_DIR_NAME/acceptance_status.json"

    if [[ $ALL_EXIT_CODE -eq 0 ]]; then
        echo ""
        echo -e "${GREEN}✅ 所有包崩溃分析流程完成！${NC}"
    else
        echo ""
        echo -e "${RED}❌ 分析流程异常退出${NC}"
    fi

    exit $ALL_EXIT_CODE

else
    init_package_status_file
    # 前台顺序执行
    PACKAGE_IDX=1
    OVERALL_EXIT_CODE=0
    FAILED_PACKAGES=()
    for pkg in "${PACKAGE_ARRAY[@]}"; do
        echo -e "${BLUE}=============================================================================${NC}"
        echo -e "${BLUE}  [$PACKAGE_IDX/$PACKAGE_COUNT] 分析包: $pkg${NC}"
        echo -e "${BLUE}=============================================================================${NC}"
        if launch_package "$pkg"; then
            echo -e "${GREEN}✅ $pkg 分析完成${NC}"
        else
            pkg_exit_code=$?
            OVERALL_EXIT_CODE=$pkg_exit_code
            FAILED_PACKAGES+=("$pkg")
            echo -e "${RED}❌ $pkg 分析失败，继续下一个包${NC}"
        fi
        ((PACKAGE_IDX++)) || true
    done

    failed_csv=""
    if [[ ${#FAILED_PACKAGES[@]} -gt 0 ]]; then
        failed_csv=$(printf "%s," "${FAILED_PACKAGES[@]}")
        failed_csv="${failed_csv%,}"
    fi
    generate_workspace_reports "$failed_csv"
    generate_gerrit_web_report

    if [[ ${#FAILED_PACKAGES[@]} -gt 0 ]]; then
        echo ""
        echo -e "${RED}以下包分析失败:${NC}"
        printf '  - %s\n' "${FAILED_PACKAGES[@]}"
        echo ""
        echo "Workspace汇总: $WORKSPACE/$SUMMARY_DIR_NAME/run_manifest.md"
        echo "Gerrit网页报告: $WORKSPACE/$SUMMARY_DIR_NAME/gerrit-web-report/index.html"
        echo "失败包清单: $WORKSPACE/$SUMMARY_DIR_NAME/retry_packages.txt"
        echo "失败版本清单: $WORKSPACE/$SUMMARY_DIR_NAME/retry_versions.md"
        echo "重跑脚本: $WORKSPACE/$SUMMARY_DIR_NAME/retry_commands.sh"
        echo "版本重跑脚本: $WORKSPACE/$SUMMARY_DIR_NAME/retry_versions.sh"
        echo "失败步骤重跑脚本: $WORKSPACE/$SUMMARY_DIR_NAME/retry_failed_steps.sh"
        echo "闭环校验: python3 coredump-full-analysis/scripts/validate_workspace_retry_closure.py --workspace $WORKSPACE"
        echo "一键验收: bash coredump-full-analysis/scripts/validate_workspace.sh --workspace $WORKSPACE"
        echo "验收报告: $WORKSPACE/$SUMMARY_DIR_NAME/acceptance_report.txt"
        echo "验收状态: $WORKSPACE/$SUMMARY_DIR_NAME/acceptance_status.json"
        exit "$OVERALL_EXIT_CODE"
    fi
fi

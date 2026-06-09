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
PARSED_PACKAGES=""
START_DATE=""
END_DATE=""
SYS_VERSION="1070-1075"
SKILLS_DIR="${SKILLS_DIR:-$SCRIPT_DIR}"
PACKAGES_FILE="$SKILLS_DIR/packages.txt"
LOAD_ACCOUNTS_SCRIPT="$SKILLS_DIR/coredump-full-analysis/scripts/load_accounts.sh"
ANALYSIS_CONFIG_FILE="${ANALYSIS_CONFIG_FILE:-$SKILLS_DIR/analysis_config.json}"

ARCH="amd64"  # 默认使用 amd64 架构
WORKSPACE=""
RUN_BACKGROUND=false
PROGRESS_INTERVAL=0  # 0表示禁用进度监控，非0表示启用(秒)
DEFAULT_PROGRESS_INTERVAL=180
ENABLE_CODE_MANAGEMENT="${ENABLE_CODE_MANAGEMENT:-}"
ENABLE_PACKAGE_MANAGEMENT="${ENABLE_PACKAGE_MANAGEMENT:-}"
AUTO_FIX_SUBMIT="${AUTO_FIX_SUBMIT:-}"
MAX_CRASHES="${MAX_CRASHES:-}"
ADDR2LINE_MAX_FRAMES="${ADDR2LINE_MAX_FRAMES:-}"
DEFAULT_TARGET_BRANCH="origin/develop/eagle"
TARGET_BRANCH=""  # 命令行指定时覆盖默认值
REVIEWERS=()
SUMMARY_DIR_NAME="6.总结报告"

# 包-分支映射（关联数组）
declare -A PACKAGE_BRANCH_MAP
# 包-项目映射（关联数组）：包名 → Gerrit 项目名
declare -A PACKAGE_PROJECT_MAP
# 包-崩溃数据下载名称映射（关联数组）：包名 → Metabase 下载名称；一项目多包时为项目名
declare -A PACKAGE_DATA_DOWNLOAD_MAP
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

${GREEN}默认行为:${NC}
    - 不指定 --packages 时：自动从 packages.txt 读取当前启用的 24 个默认项目
    - 流程开关和崩溃分析层数默认读取 analysis_config.json（数据筛选必做，代码管理/包管理/自动修复提交可配置）
    - 分析层数默认：max_crashes=0（全部），addr2line_max_frames=500
    - --auto-fix-submit 仅提交真实代码修改；可通过 AUTO_FIX_SUBMIT=false 或 --no-auto-fix-submit 临时关闭
    - --progress 不带数值时，默认使用 ${DEFAULT_PROGRESS_INTERVAL} 秒

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
    --arch <arch>         架构 (默认: amd64)
                           例如: x86, x86_64, arm64
    --workspace <dir>     工作目录 (默认: ~/coredump-workspace-YYYYMMDD-HHMMSS)
    --background          后台运行
    --progress [秒]       启用进度监控；不带值时默认 ${DEFAULT_PROGRESS_INTERVAL} 秒
    --interval <秒>       进度报告间隔 (默认: ${DEFAULT_PROGRESS_INTERVAL} 秒)
    --auto-fix-submit     分析后自动检查 target branch 是否已修复，并仅在真实代码修改时自动提交 Gerrit
                           （默认读取 analysis_config.json，也可通过环境变量 AUTO_FIX_SUBMIT=false 关闭）
    --no-auto-fix-submit  本次运行显式关闭自动修复/提交
    --target-branch <br>  强制所有包使用同一分支 (覆盖 packages.txt 中的配置)
    --reviewer <email>    自动提交时附加 reviewer，可多次指定
    --no-gerrit-web-report      禁用分析结束后的 Gerrit 网页报告生成
    --serve-gerrit-web-report   分析结束后启动本地服务查看 Gerrit 网页报告
    --help, -h            显示帮助

${GREEN}分支规则:${NC}
    默认分支: origin/develop/eagle
    packages.txt 格式: [项目名:]包名[,...] [分支名]
    --target-branch 可强制覆盖所有包的分支

${GREEN}packages.txt 示例:${NC}
    dde-dock                                        # 项目=包名，分支=develop/eagle
    go-lib:golang-github-linuxdeepin-go-lib-dev     # 项目=go-lib，包名=golang-github-linuxdeepin-go-lib-dev
    base/lightdm:lightdm uos                        # 项目=base/lightdm，包名=lightdm，分支=uos
    dde-network-core:dcc-network-plugin,deepin-service-plugin-network,dock-network-plugin  # 一项目多包

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

    # 纯分析自动化：不执行自动修复/提交检查
    AUTO_FIX_SUBMIT=false $0 --packages dde-session-ui --start-date 2026-03-14 --end-date 2026-04-14

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

require_value() {
    local flag="$1"
    local value="$2"
    if [[ -z "$value" || "$value" == --* ]]; then
        echo -e "${RED}参数 $flag 缺少取值${NC}" >&2
        exit 1
    fi
}

is_integer() {
    [[ "$1" =~ ^[0-9]+$ ]]
}

normalize_bool() {
    local value="$1"
    local default_value="${2:-true}"
    case "${value,,}" in
        true|1|yes|y|on|enable|enabled) echo "true" ;;
        false|0|no|n|off|disable|disabled) echo "false" ;;
        *) echo "$default_value" ;;
    esac
}

read_config_bool() {
    local jq_path="$1"
    local default_value="$2"
    if [[ -f "$ANALYSIS_CONFIG_FILE" ]] && command -v jq &> /dev/null; then
        local value
        value=$(jq -r "$jq_path // empty" "$ANALYSIS_CONFIG_FILE" 2>/dev/null || true)
        if [[ -n "$value" && "$value" != "null" ]]; then
            normalize_bool "$value" "$default_value"
            return 0
        fi
    fi
    echo "$default_value"
}

read_config_int() {
    local jq_path="$1"
    local default_value="$2"
    if [[ -f "$ANALYSIS_CONFIG_FILE" ]] && command -v jq &> /dev/null; then
        local value
        value=$(jq -r "$jq_path // empty" "$ANALYSIS_CONFIG_FILE" 2>/dev/null || true)
        if [[ "$value" =~ ^[0-9]+$ ]]; then
            echo "$value"
            return 0
        fi
    fi
    echo "$default_value"
}

load_workflow_config() {
    local config_code_management
    local config_package_management
    local config_auto_fix_submit
    local config_max_crashes
    local config_addr2line_max_frames

    config_code_management=$(read_config_bool '.workflow.enable_code_management' true)
    config_package_management=$(read_config_bool '.workflow.enable_package_management' true)
    config_auto_fix_submit=$(read_config_bool '.workflow.enable_auto_fix_submit' true)
    config_max_crashes=$(read_config_int '.analysis.max_crashes' 0)
    config_addr2line_max_frames=$(read_config_int '.analysis.addr2line_max_frames' 500)

    ENABLE_CODE_MANAGEMENT=$(normalize_bool "${ENABLE_CODE_MANAGEMENT:-$config_code_management}" "$config_code_management")
    ENABLE_PACKAGE_MANAGEMENT=$(normalize_bool "${ENABLE_PACKAGE_MANAGEMENT:-$config_package_management}" "$config_package_management")
    AUTO_FIX_SUBMIT=$(normalize_bool "${AUTO_FIX_SUBMIT:-$config_auto_fix_submit}" "$config_auto_fix_submit")
    MAX_CRASHES="${MAX_CRASHES:-$config_max_crashes}"
    ADDR2LINE_MAX_FRAMES="${ADDR2LINE_MAX_FRAMES:-$config_addr2line_max_frames}"
}

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --package)
            require_value "$1" "$2"
            PACKAGES="$2"
            shift 2
            ;;
        --packages)
            require_value "$1" "$2"
            PACKAGES="$2"
            shift 2
            ;;
        --start-date)
            require_value "$1" "$2"
            START_DATE="$2"
            shift 2
            ;;
        --end-date)
            require_value "$1" "$2"
            END_DATE="$2"
            shift 2
            ;;
        --sys-version)
            require_value "$1" "$2"
            SYS_VERSION="$2"
            shift 2
            ;;
        --arch)
            require_value "$1" "$2"
            ARCH="$2"
            shift 2
            ;;
        --workspace)
            require_value "$1" "$2"
            WORKSPACE="$2"
            shift 2
            ;;
        --background)
            RUN_BACKGROUND=true
            shift
            ;;
        --progress)
            if [[ -n "$2" && "$2" != --* ]]; then
                if ! is_integer "$2"; then
                    echo -e "${RED}参数 --progress 需要整数秒数: $2${NC}" >&2
                    exit 1
                fi
                PROGRESS_INTERVAL="$2"
                shift 2
            else
                PROGRESS_INTERVAL="$DEFAULT_PROGRESS_INTERVAL"
                shift
            fi
            ;;
        --interval)
            require_value "$1" "$2"
            if ! is_integer "$2"; then
                echo -e "${RED}参数 --interval 需要整数秒数: $2${NC}" >&2
                exit 1
            fi
            PROGRESS_INTERVAL="$2"
            shift 2
            ;;
        --auto-fix-submit)
            AUTO_FIX_SUBMIT=true
            shift
            ;;
        --no-auto-fix-submit)
            AUTO_FIX_SUBMIT=false
            shift
            ;;
        --target-branch)
            require_value "$1" "$2"
            TARGET_BRANCH="$2"
            shift 2
            ;;
        --reviewer)
            require_value "$1" "$2"
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

# 解析 packages.txt 并填充包-分支映射
# 格式: [项目名:]包名[,...] [分支名]
parse_packages_file() {
    local file="$1"
    local packages=""
    while IFS= read -r line || [[ -n "$line" ]]; do
        # 跳过注释和空行
        line=$(echo "$line" | sed 's/#.*//' | xargs)
        [[ -z "$line" ]] && continue

        # 解析分支名（最后一个字段，如果不像包名则为分支）
        local branch=""
        local main_part="$line"
        local last_field=$(echo "$line" | awk '{print $NF}')
        # 如果最后一个字段不含 / 和 , 和 :，可能是分支名
        if [[ "$last_field" != *"/"* && "$last_field" != *","* && "$last_field" != *":"* ]]; then
            # 检查是否是分支名（不是单个包名的情况）
            local fields_count=$(echo "$line" | awk '{print NF}')
            if [[ $fields_count -gt 1 ]]; then
                branch="$last_field"
                main_part=$(echo "$line" | awk '{for(i=1;i<NF;i++) printf $i" "; print ""}' | xargs)
            fi
        fi

        # 解析 [项目名:]包名[,...]
        local project=""
        local pkg_list=""
        if [[ "$main_part" == *":"* ]]; then
            # 格式: 项目名:包名1,包名2
            project=$(echo "$main_part" | cut -d':' -f1)
            pkg_list=$(echo "$main_part" | cut -d':' -f2)
        else
            # 格式: 包名（项目名=包名）
            pkg_list="$main_part"
        fi

        # 设置映射
        local default_branch="${branch:-develop/eagle}"
        IFS=',' read -ra PKGS <<< "$pkg_list"
        for pkg in "${PKGS[@]}"; do
            pkg=$(echo "$pkg" | xargs)  # trim
            [[ -z "$pkg" ]] && continue

            # 设置项目映射和数据下载名称映射。
            # project:pkg1,pkg2 表示多个二进制包属于同一个源码项目，崩溃数据下载按项目名执行，筛选/包管理按实际包名执行。
            if [[ -n "$project" ]]; then
                PACKAGE_PROJECT_MAP["$pkg"]="$project"
                PACKAGE_DATA_DOWNLOAD_MAP["$pkg"]="$project"
            else
                PACKAGE_PROJECT_MAP["$pkg"]="$pkg"
                PACKAGE_DATA_DOWNLOAD_MAP["$pkg"]="$pkg"
            fi

            # 设置分支映射
            PACKAGE_BRANCH_MAP["$pkg"]="origin/$default_branch"

            # 拼接包名
            if [[ -n "$packages" ]]; then
                packages="$packages,$pkg"
            else
                packages="$pkg"
            fi
        done
    done < "$file"
    PARSED_PACKAGES="$packages"
    echo "$packages"
}

# 获取包的分支
get_package_branch() {
    local pkg="$1"
    echo "${PACKAGE_BRANCH_MAP[$pkg]:-$DEFAULT_TARGET_BRANCH}"
}

# 获取包对应的 Gerrit 项目名
get_package_project() {
    local pkg="$1"
    echo "${PACKAGE_PROJECT_MAP[$pkg]:-$pkg}"
}

# 获取包对应的崩溃数据下载名称
get_package_data_download_name() {
    local pkg="$1"
    echo "${PACKAGE_DATA_DOWNLOAD_MAP[$pkg]:-$pkg}"
}

load_default_packages_if_needed() {
    if [[ -n "$PACKAGES" ]]; then
        return 0
    fi

    if [[ ! -f "$PACKAGES_FILE" ]]; then
        echo -e "${RED}错误: 必须指定 --packages 参数，且 packages.txt 不存在${NC}"
        show_help
        exit 1
    fi

    echo -e "${YELLOW}未指定 --packages，从 $PACKAGES_FILE 读取默认项目列表${NC}"
    parse_packages_file "$PACKAGES_FILE" >/dev/null
    PACKAGES="$PARSED_PACKAGES"
    if [[ -z "$PACKAGES" ]]; then
        echo -e "${RED}错误: packages.txt 为空${NC}"
        exit 1
    fi

    local local_count
    local_count=$(echo "$PACKAGES" | tr ',' '\n' | wc -l)
    echo -e "${GREEN}已加载 ${local_count} 个分析项目${NC}"
}

build_package_array() {
    IFS=',' read -ra PACKAGE_ARRAY <<< "$PACKAGES"
    PACKAGE_COUNT=${#PACKAGE_ARRAY[@]}
}

apply_target_branch_override() {
    if [[ -z "$TARGET_BRANCH" ]]; then
        return 0
    fi

    local pkg
    for pkg in "${PACKAGE_ARRAY[@]}"; do
        PACKAGE_BRANCH_MAP["$pkg"]="$TARGET_BRANCH"
    done
    DEFAULT_TARGET_BRANCH="$TARGET_BRANCH"
}

has_non_default_mapping() {
    local pkg
    for pkg in "${PACKAGE_ARRAY[@]}"; do
        local local_branch
        local local_project
        local local_download_name
        local_branch=$(get_package_branch "$pkg")
        local_project=$(get_package_project "$pkg")
        local_download_name=$(get_package_data_download_name "$pkg")
        if [[ "$local_branch" != "$DEFAULT_TARGET_BRANCH" || "$local_project" != "$pkg" || "$local_download_name" != "$pkg" ]]; then
            return 0
        fi
    done
    return 1
}

print_non_default_mappings() {
    has_non_default_mapping || return 0

    echo -e "${CYAN}包-项目-下载名称-分支映射:${NC}"
    local pkg
    for pkg in "${PACKAGE_ARRAY[@]}"; do
        local local_branch
        local local_project
        local local_download_name
        local_branch=$(get_package_branch "$pkg")
        local_project=$(get_package_project "$pkg")
        local_download_name=$(get_package_data_download_name "$pkg")
        if [[ "$local_branch" != "$DEFAULT_TARGET_BRANCH" || "$local_project" != "$pkg" || "$local_download_name" != "$pkg" ]]; then
            echo -e "  ${pkg} → 项目:${local_project}, 数据下载:${local_download_name}, 分支:${local_branch}"
        fi
    done
    echo ""
}

# 加载流程开关配置（数据筛选为必需步骤，不提供关闭开关）
load_workflow_config

# 验证必需参数
load_default_packages_if_needed
build_package_array
apply_target_branch_override

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
echo "  流程配置文件: $ANALYSIS_CONFIG_FILE"
echo "  代码管理: $ENABLE_CODE_MANAGEMENT"
echo "  包管理: $ENABLE_PACKAGE_MANAGEMENT"
echo "  自动修复提交: $AUTO_FIX_SUBMIT"
echo "  单版本最大分析崩溃数: $MAX_CRASHES"
echo "  addr2line最大解析帧数: $ADDR2LINE_MAX_FRAMES"
echo "  默认分支: $DEFAULT_TARGET_BRANCH"
echo "  Gerrit网页报告: $GENERATE_GERRIT_WEB_REPORT"
echo "  Gerrit网页服务: $SERVE_GERRIT_WEB_REPORT"
echo ""

# 显示包-分支映射
print_non_default_mappings

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

    print_auto_fix_progress_summary
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

print_auto_fix_progress_summary() {
    local overview_json="$WORKSPACE/$SUMMARY_DIR_NAME/auto_fix_overview.json"
    if [[ ! -f "$overview_json" ]]; then
        echo -e "${YELLOW}Auto-fix汇总: 尚未生成（通常在 workspace 汇总后出现）${NC}"
        return 0
    fi

    python3 - "$overview_json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
with path.open(encoding='utf-8') as f:
    data = json.load(f)
counts = data.get('category_counts', {})
print('Auto-fix汇总:')
print(f"  已产出结果版本: {data.get('total_versions_with_auto_fix_results', 0)}")
print(f"  真修复已提交: {counts.get('code_fix_submitted', 0)}")
print(f"  历史无效说明文档提交: {counts.get('legacy_analysis_report_submitted', 0)}")
print(f"  需人工处理: {counts.get('manual_required', 0)}")
print(f"  源码缺失: {counts.get('source_repo_missing', 0)}")
PY
}

ensure_summary_dir() {
    mkdir -p "$WORKSPACE/$SUMMARY_DIR_NAME"
}

write_run_context() {
    ensure_summary_dir
    python3 - "$WORKSPACE/$SUMMARY_DIR_NAME/run_context.json" "$WORKSPACE" "$PACKAGES" "$ARCH" "$SYS_VERSION" "$START_DATE" "$END_DATE" "$DATE_RANGE_LABEL" "$SUMMARY_DIR_NAME" <<'PY'
import json
import sys

path, workspace, packages, arch, sys_version, start_date, end_date, date_range_label, summary_dir_name = sys.argv[1:10]
data = {
    "workspace": workspace,
    "packages": packages,
    "arch": arch,
    "sys_version": sys_version,
    "start_date": start_date,
    "end_date": end_date,
    "date_range_label": date_range_label,
    "summary_dir_name": summary_dir_name,
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
    local summary_script="$SKILLS_DIR/coredump-full-analysis/scripts/reporting/generate_workspace_summary.py"
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

    local report_script="$SKILLS_DIR/coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py"
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

start_package_jobs() {
    local pids_name="$1"
    local status_icon="${2:-✅}"
    local pid
    local pkg

    for pkg in "${PACKAGE_ARRAY[@]}"; do
        launch_package "$pkg" > "$LOG_DIR/analysis_${pkg}.log" 2>&1 &
        pid=$!
        eval "$pids_name+=(\"$pid\")"
        echo -e "${GREEN}${status_icon} $pkg 已启动 (PID: $pid)${NC}"
    done
}

any_pid_running() {
    local pid
    for pid in "$@"; do
        if is_running "$pid"; then
            return 0
        fi
    done
    return 1
}

wait_for_pids() {
    local overall_exit=0
    local pid
    for pid in "$@"; do
        wait "$pid" || overall_exit=$?
    done
    return "$overall_exit"
}

print_workspace_output_paths() {
    echo -e "${GREEN}输出文件:${NC}"
    local pkg
    for pkg in "${PACKAGE_ARRAY[@]}"; do
        echo "  $pkg:"
        echo "    统计报告: $WORKSPACE/2.数据筛选/${pkg}_crash_statistics.json"
        echo "    筛选数据: $WORKSPACE/2.数据筛选/filtered_${pkg}_crash_data.csv"
        echo "    分析报告: $WORKSPACE/5.崩溃分析/${pkg}/"
    done
    echo "  Workspace汇总: $WORKSPACE/$SUMMARY_DIR_NAME/run_manifest.md"
    echo "  跨包汇总: $WORKSPACE/$SUMMARY_DIR_NAME/all_packages_summary.md"
    echo "  Auto-fix汇总: $WORKSPACE/$SUMMARY_DIR_NAME/auto_fix_overview.md"
    echo "  Gerrit网页报告: $WORKSPACE/$SUMMARY_DIR_NAME/gerrit-web-report/index.html"
    echo "  问题簇汇总: $WORKSPACE/$SUMMARY_DIR_NAME/root_cause_clusters.md"
    echo "  失败包清单: $WORKSPACE/$SUMMARY_DIR_NAME/retry_packages.txt"
    echo "  失败版本清单: $WORKSPACE/$SUMMARY_DIR_NAME/retry_versions.md"
    echo "  重跑脚本: $WORKSPACE/$SUMMARY_DIR_NAME/retry_commands.sh"
    echo "  版本重跑脚本: $WORKSPACE/$SUMMARY_DIR_NAME/retry_versions.sh"
    echo "  失败步骤重跑脚本: $WORKSPACE/$SUMMARY_DIR_NAME/retry_failed_steps.sh"
    echo "  闭环校验: python3 coredump-full-analysis/scripts/validation/validate_workspace_retry_closure.py --workspace $WORKSPACE"
    echo "  一键验收: bash coredump-full-analysis/scripts/validate_workspace.sh --workspace $WORKSPACE"
    echo "  验收报告: $WORKSPACE/$SUMMARY_DIR_NAME/acceptance_report.txt"
    echo "  验收状态: $WORKSPACE/$SUMMARY_DIR_NAME/acceptance_status.json"
}

# 启动单个包的崩溃分析
launch_package() {
    local pkg="$1"
    local pkg_branch=$(get_package_branch "$pkg")
    local pkg_project=$(get_package_project "$pkg")
    local pkg_data_download_name=$(get_package_data_download_name "$pkg")
    log_package_status "$pkg" "running" "" "analysis started (project: $pkg_project, data_download: $pkg_data_download_name, branch: $pkg_branch)"
    cd "$SKILLS_DIR/coredump-full-analysis/scripts"
    local cmd=(bash analyze_crash_complete.sh
        --packages "$pkg"
        --project "$pkg_project"
        --data-download-name "$pkg_data_download_name"
        --arch "$ARCH"
        --sys-version "$SYS_VERSION"
        --workspace "$WORKSPACE"
        --target-branch "$pkg_branch"
        --max-crashes "$MAX_CRASHES"
        --addr2line-max-frames "$ADDR2LINE_MAX_FRAMES")
    [[ -n "$START_DATE" ]] && cmd+=(--start-date "$START_DATE")
    [[ -n "$END_DATE" ]] && cmd+=(--end-date "$END_DATE")
    [[ "$AUTO_FIX_SUBMIT" == "true" ]] && cmd+=(--auto-fix-submit)
    [[ "$AUTO_FIX_SUBMIT" != "true" ]] && cmd+=(--no-auto-fix-submit)
    local reviewer
    for reviewer in "${REVIEWERS[@]}"; do
        cmd+=(--reviewer "$reviewer")
    done
    if SUDO_PASSWORD="$SUDO_PASSWORD" PROGRESS_INTERVAL="$PROGRESS_INTERVAL" ANALYSIS_CONFIG_FILE="$ANALYSIS_CONFIG_FILE" ENABLE_CODE_MANAGEMENT="$ENABLE_CODE_MANAGEMENT" ENABLE_PACKAGE_MANAGEMENT="$ENABLE_PACKAGE_MANAGEMENT" AUTO_FIX_SUBMIT="$AUTO_FIX_SUBMIT" MAX_CRASHES="$MAX_CRASHES" ADDR2LINE_MAX_FRAMES="$ADDR2LINE_MAX_FRAMES" DATA_DOWNLOAD_NAME="$pkg_data_download_name" "${cmd[@]}" 2>&1; then
        # 如果启用了自动修复提交，调用修复映射脚本
        if [[ "$AUTO_FIX_SUBMIT" == "true" ]]; then
            echo -e "${YELLOW}开始修复映射和Gerrit提交 (项目: $pkg_project, 分支: $pkg_branch)...${NC}"
            local fix_script="$SKILLS_DIR/coredump-crash-analysis/scripts/analyze_with_fix_mapping.py"
            if [[ -f "$fix_script" ]]; then
                # 获取用于崩溃搜索的包名（去掉base/前缀）
                local search_pkg=$(get_crash_search_name "$pkg")
                python3 "$fix_script" \
                    --package "$search_pkg" \
                    --project "$pkg_project" \
                    --workspace "$WORKSPACE" \
                    --target-branch "$pkg_branch" 2>&1
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
    declare -a PIDS=()
    start_package_jobs PIDS "✅"

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

    declare -a PIDS=()
    start_package_jobs PIDS "🚀"

    # 初始化
    START_TIME=$(date +%s)
    LAST_REPORT_TIME=$START_TIME

    # 监控循环：检查所有进程是否结束
    while any_pid_running "${PIDS[@]}"; do
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
    wait_for_pids "${PIDS[@]}" || ALL_EXIT_CODE=$?

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

    generate_workspace_reports ""
    generate_gerrit_web_report
    print_workspace_output_paths

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
        print_workspace_output_paths
        exit "$OVERALL_EXIT_CODE"
    fi
fi

#!/bin/bash
#=============================================================================
# 通用崩溃分析完整流程
# 组合使用 5 个 Skills 进行一站式崩溃分析
#=============================================================================

set -e

# 配色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 脚本目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Skills目录（脚本所在目录的父目录）
SKILLS_DIR="${SKILLS_DIR:-$SCRIPT_DIR/../..}"
CONFIG_DIR="$SCRIPT_DIR/../config"
LOAD_ACCOUNTS_SCRIPT="$SCRIPT_DIR/load_accounts.sh"
ANALYSIS_CONFIG_FILE="${ANALYSIS_CONFIG_FILE:-$SKILLS_DIR/analysis_config.json}"

source "$CONFIG_DIR/package-server.env" 2>/dev/null || true

# 默认值
PACKAGE="${PACKAGE:-}"
GERRIT_PROJECT="${GERRIT_PROJECT:-}"  # Gerrit 项目名，为空时使用 PACKAGE
DATA_DOWNLOAD_NAME="${DATA_DOWNLOAD_NAME:-}"  # 崩溃数据下载名称，为空时使用 PACKAGE
START_DATE="${START_DATE:-}"
END_DATE="${END_DATE:-}"
SYS_VERSION="${SYS_VERSION:-1070-1075}"
ARCH="${ARCH:-amd64}"  # 默认使用 amd64 架构
SELECTED_VERSIONS="${SELECTED_VERSIONS:-}"
WORKSPACE="${WORKSPACE:-}"
PROGRESS_INTERVAL="${PROGRESS_INTERVAL:-180}"  # 进度上报间隔（秒），0表示禁用
MAX_CRASHES="${MAX_CRASHES:-}"  # 单版本最大分析崩溃数，0表示分析全部
ADDR2LINE_MAX_FRAMES="${ADDR2LINE_MAX_FRAMES:-}"  # addr2line 最大解析帧数
ENABLE_CODE_MANAGEMENT="${ENABLE_CODE_MANAGEMENT:-}"
ENABLE_PACKAGE_MANAGEMENT="${ENABLE_PACKAGE_MANAGEMENT:-}"
AUTO_FIX_SUBMIT="${AUTO_FIX_SUBMIT:-}"
ENABLE_LOCAL_REUSE="${ENABLE_LOCAL_REUSE:-}"
REUSE_SOURCE_CODE="${REUSE_SOURCE_CODE:-}"
REUSE_DEB_PACKAGES="${REUSE_DEB_PACKAGES:-}"
WORKSPACE_SEARCH_ROOT="${WORKSPACE_SEARCH_ROOT:-}"
MAX_WORKSPACE_SCAN="${MAX_WORKSPACE_SCAN:-}"
TARGET_BRANCH="${TARGET_BRANCH:-origin/develop/eagle}"
REVIEWERS=()
SUMMARY_DIR_NAME="6.总结报告"
VERSION_STATUS_FILE=""
REUSABLE_WORKSPACES_FILE=""
STEP_STATUS=""
STEP_MESSAGE=""

generate_workspace_with_timestamp() {
    local root_dir="${1:-$HOME}"
    echo "$root_dir/coredump-workspace-$(date +%Y%m%d-%H%M%S)"
}

# 获取 Gerrit 项目名（如果未指定则使用包名）
get_gerrit_project() {
    if [[ -n "$GERRIT_PROJECT" ]]; then
        echo "$GERRIT_PROJECT"
    else
        echo "$PACKAGE"
    fi
}

# 获取崩溃数据下载名称。普通包默认使用 PACKAGE；packages.txt 中 project:pkg1,pkg2 映射由上层显式传入 project。
get_data_download_name() {
    if [[ -n "$DATA_DOWNLOAD_NAME" ]]; then
        echo "$DATA_DOWNLOAD_NAME"
    else
        echo "$PACKAGE"
    fi
}

ensure_summary_dir() {
    mkdir -p "$WORKSPACE/$SUMMARY_DIR_NAME"
}

init_status_files() {
    ensure_summary_dir
    VERSION_STATUS_FILE="$WORKSPACE/$SUMMARY_DIR_NAME/version_status.tsv"
    if [[ ! -f "$VERSION_STATUS_FILE" ]]; then
        printf "#timestamp\tpackage\tversion\tstep\tstatus\tmessage\n" > "$VERSION_STATUS_FILE"
    fi
}

# 架构验证和默认值处理
validate_architecture() {
    # 如果 ARCH 为空或无效，默认使用 amd64
    if [[ -z "$ARCH" || "$ARCH" == "none" ]]; then
        echo -e "${YELLOW}⚠️ 未指定架构参数，默认使用 amd64${NC}"
        ARCH="amd64"
    fi
    
    # 验证架构是否支持
    case "$ARCH" in
        x86|x86_64|amd64|i386)
            # 架构有效
            ;;
        arm)
            # arm 架构映射到 aarch64
            ARCH="aarch64"
            ;;
        arm64)
            # arm64 架构映射到 aarch64
            ARCH="aarch64"
            ;;
        *)
            echo -e "${YELLOW}⚠️ 不支持的架构: $ARCH，默认使用 amd64${NC}"
            ARCH="amd64"
            ;;
    esac
}

set_step_result() {
    STEP_STATUS="$1"
    STEP_MESSAGE="$2"
}

log_version_status() {
    local version="$1"
    local step="$2"
    local status="$3"
    local message="${4:-}"
    ensure_summary_dir
    printf "%s\t%s\t%s\t%s\t%s\t%s\n" \
        "$(date '+%Y-%m-%dT%H:%M:%S')" \
        "$PACKAGE" \
        "$version" \
        "$step" \
        "$status" \
        "$message" >> "$VERSION_STATUS_FILE"
}

version_selected() {
    local version="$1"
    local selected="${SELECTED_VERSIONS:-}"
    if [[ -z "$selected" ]]; then
        return 0
    fi

    local normalized
    normalized=$(echo "$version" | sed 's/^1://' | sed 's/-1$//')
    local candidate
    IFS=',' read -ra _selected_array <<< "$selected"
    for candidate in "${_selected_array[@]}"; do
        candidate=$(echo "$candidate" | xargs)
        candidate=$(echo "$candidate" | sed 's/^1://' | sed 's/-1$//')
        if [[ -n "$candidate" && "$candidate" == "$normalized" ]]; then
            return 0
        fi
    done
    return 1
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

read_config_string() {
    local jq_path="$1"
    local default_value="${2:-}"
    if [[ -f "$ANALYSIS_CONFIG_FILE" ]] && command -v jq &> /dev/null; then
        local value
        value=$(jq -r "$jq_path // empty" "$ANALYSIS_CONFIG_FILE" 2>/dev/null || true)
        if [[ -n "$value" && "$value" != "null" ]]; then
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
    local config_enable_local_reuse
    local config_reuse_source_code
    local config_reuse_deb_packages
    local config_workspace_search_root
    local config_max_workspace_scan

    config_code_management=$(read_config_bool '.workflow.enable_code_management' true)
    config_package_management=$(read_config_bool '.workflow.enable_package_management' true)
    config_auto_fix_submit=$(read_config_bool '.workflow.enable_auto_fix_submit' false)
    config_max_crashes=$(read_config_int '.analysis.max_crashes' 0)
    config_addr2line_max_frames=$(read_config_int '.analysis.addr2line_max_frames' 500)
    config_enable_local_reuse=$(read_config_bool '.reuse.enable_local_reuse' true)
    config_reuse_source_code=$(read_config_bool '.reuse.reuse_source_code' true)
    config_reuse_deb_packages=$(read_config_bool '.reuse.reuse_deb_packages' true)
    config_workspace_search_root=$(read_config_string '.reuse.workspace_search_root' '')
    config_max_workspace_scan=$(read_config_int '.reuse.max_workspace_scan' 20)

    ENABLE_CODE_MANAGEMENT=$(normalize_bool "${ENABLE_CODE_MANAGEMENT:-$config_code_management}" "$config_code_management")
    ENABLE_PACKAGE_MANAGEMENT=$(normalize_bool "${ENABLE_PACKAGE_MANAGEMENT:-$config_package_management}" "$config_package_management")
    AUTO_FIX_SUBMIT=$(normalize_bool "${AUTO_FIX_SUBMIT:-$config_auto_fix_submit}" "$config_auto_fix_submit")
    MAX_CRASHES="${MAX_CRASHES:-$config_max_crashes}"
    ADDR2LINE_MAX_FRAMES="${ADDR2LINE_MAX_FRAMES:-$config_addr2line_max_frames}"
    ENABLE_LOCAL_REUSE=$(normalize_bool "${ENABLE_LOCAL_REUSE:-$config_enable_local_reuse}" "$config_enable_local_reuse")
    REUSE_SOURCE_CODE=$(normalize_bool "${REUSE_SOURCE_CODE:-$config_reuse_source_code}" "$config_reuse_source_code")
    REUSE_DEB_PACKAGES=$(normalize_bool "${REUSE_DEB_PACKAGES:-$config_reuse_deb_packages}" "$config_reuse_deb_packages")
    WORKSPACE_SEARCH_ROOT="${WORKSPACE_SEARCH_ROOT:-$config_workspace_search_root}"
    MAX_WORKSPACE_SCAN="${MAX_WORKSPACE_SCAN:-$config_max_workspace_scan}"
    [[ "$MAX_WORKSPACE_SCAN" =~ ^[0-9]+$ && "$MAX_WORKSPACE_SCAN" -gt 0 ]] || MAX_WORKSPACE_SCAN=20
}

# 检查配置完整性
check_config() {
    echo -e "${BLUE}检查配置完整性...${NC}"
    
    # 架构验证
    validate_architecture
    echo -e "${BLUE}使用架构: $ARCH${NC}"
    
    if [[ ! -f "$LOAD_ACCOUNTS_SCRIPT" ]]; then
        echo -e "${RED}错误: 账号加载脚本不存在: $LOAD_ACCOUNTS_SCRIPT${NC}"
        return 1
    fi
    source "$LOAD_ACCOUNTS_SCRIPT"
    local required_services=("metabase")
    if [[ "$ENABLE_CODE_MANAGEMENT" == "true" ]]; then
        required_services+=("gerrit")
    fi
    load_accounts_or_die "${required_services[@]}"
    GERRIT_USERNAME="$GERRIT_USER"
    if [[ -z "$WORKSPACE" ]] || [[ "$WORKSPACE" == "./workspace" ]]; then
        local workspace_root="${ACCOUNTS_WORKSPACE_ROOT:-$HOME}"
        [[ -z "$workspace_root" ]] && workspace_root="$HOME"
        WORKSPACE="$(generate_workspace_with_timestamp "$workspace_root")"
    fi
    echo -e "${GREEN}✅ 配置检查通过${NC}"
}

# 帮助信息
show_help() {
    cat << EOF
${BLUE}=============================================================================
dde-dock/dde-control-center 等包崩溃分析完整流程
=============================================================================${NC}

${GREEN}用法:${NC}
    $0 [选项]

${GREEN}首次使用:${NC}
    先完善仓库根目录 accounts.json，缺少必需账号或密码时流程会直接暂停

${GREEN}账号配置方式:${NC}
    唯一入口: 仓库根目录 accounts.json
           \$SKILLS_DIR/accounts.json

${GREEN}选项:${NC}
    --packages <name>      包名（必需，文档推荐写法）
                           例如: dde-dock, dde-control-center, dde-launcher
    --package <name>       兼容旧参数，等价于 --packages
    --project <name>       Gerrit 项目名（可选，默认与包名相同）
                           例如: go-lib, base/lightdm
    --data-download-name <name>  崩溃数据下载名称（可选，默认与包名相同；一项目多包时由上层传项目名）
    --start-date <date>   开始日期（格式: YYYY-MM-DD；默认不限制）
                           例如: 2026-04-05
    --end-date <date>     结束日期（格式: YYYY-MM-DD；默认不限制）
                           例如: 2026-04-08
    --sys-version <ver>   系统版本范围（默认: 1070-1075）
                           例如: 1070, 1070-1075
    --arch <arch>         架构（默认: x86）
                           例如: x86, x86_64, arm64
    --versions <list>     仅分析指定版本，逗号分隔
                           例如: 5.8.32,5.8.33
    --auto-fix-submit     分析后自动检查 target branch 是否已修复，并仅在真实代码修改时自动提交 Gerrit
    --no-auto-fix-submit  本次运行显式关闭自动修复/提交
    --target-branch <br>  自动修复提交目标分支（默认: origin/develop/eagle）
    --reviewer <email>    自动提交时附加 reviewer，可多次指定
    --max-crashes <n>     单版本最大分析崩溃数（默认: 0，分析全部）
    --addr2line-max-frames <n>  addr2line 最大解析帧数（默认: 500）
    --workspace <dir>      工作目录（默认: 自动创建带时间戳的目录 ~/coredump-workspace-YYYYMMDD-HHMMSS）
    --help, -h            显示此帮助信息

${GREEN}示例:${NC}
    # 分析最近3天的dde-dock崩溃
    $0 --packages dde-dock --start-date 2026-04-05 --end-date 2026-04-08

    # 使用 accounts.json 中的账号
    $0 --packages dde-session-ui --start-date 2026-03-14 --end-date 2026-04-14

    # 仅重跑指定版本
    $0 --packages dde-session-ui --workspace /path/to/workspace --versions 5.8.32

    # 分析后自动检查已修复并提交可自动修复的问题
    $0 --packages dde-launcher --auto-fix-submit --target-branch origin/develop/eagle

${BLUE}=============================================================================
${NC}
EOF
}

# 解析参数
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --packages)
                PACKAGE="$2"
                shift 2
                ;;
            --package)
                PACKAGE="$2"
                shift 2
                ;;
            --project)
                GERRIT_PROJECT="$2"
                shift 2
                ;;
            --data-download-name)
                DATA_DOWNLOAD_NAME="$2"
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
            --versions)
                SELECTED_VERSIONS="$2"
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
                TARGET_BRANCH="$2"
                shift 2
                ;;
            --reviewer)
                REVIEWERS+=("$2")
                shift 2
                ;;
            --max-crashes)
                MAX_CRASHES="$2"
                shift 2
                ;;
            --addr2line-max-frames)
                ADDR2LINE_MAX_FRAMES="$2"
                shift 2
                ;;
            --workspace)
                WORKSPACE="$2"
                shift 2
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
    if [[ -z "$PACKAGE" ]]; then
        echo -e "${RED}错误: 必须指定 --packages 参数${NC}"
        show_help
        exit 1
    fi

}

auto_fix_and_submit_for_version() {
    local package="$1"
    local version="$2"
    local auto_fix_script="$SCRIPT_DIR/auto_fix_submit.py"

    if [[ "$AUTO_FIX_SUBMIT" != "true" ]]; then
        set_step_result "skipped" "auto fix submit disabled"
        return 0
    fi

    if [[ ! -f "$auto_fix_script" ]]; then
        set_step_result "skipped" "auto_fix_submit.py missing"
        return 0
    fi

    echo -e "${YELLOW}━━━ 步骤6: 自动修复与提交检查 $version ━━━${NC}"
    local cmd=(python3 "$auto_fix_script"
        --package "$package"
        --version "$version"
        --workspace "$WORKSPACE"
        --target-branch "$TARGET_BRANCH")

    local reviewer
    for reviewer in "${REVIEWERS[@]}"; do
        cmd+=(--reviewer "$reviewer")
    done

    if "${cmd[@]}" 2>&1; then
        set_step_result "ok" "auto fix submit check completed"
        return 0
    fi

    set_step_result "failed" "auto fix submit check failed"
    return 1
}

# 打印进度
print_step() {
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}步骤 $1: $2${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# 检查依赖
check_dependencies() {
    print_step 0 "检查依赖..."

    local deps=("curl" "jq" "python3" "git" "ssh")
    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &> /dev/null; then
            echo -e "${RED}错误: 缺少依赖 '$dep'${NC}"
            exit 1
        fi
    done

    # 检查SSH密钥
    if [[ ! -f "$GERRIT_SSH_KEY" ]]; then
        echo -e "${YELLOW}警告: SSH密钥 $GERRIT_SSH_KEY 不存在${NC}"
        echo "Gerrit克隆可能需要手动配置SSH密钥"
    fi

    echo -e "${GREEN}✅ 依赖检查完成${NC}"
}

# 创建工作目录
setup_workspace() {
    print_step 1 "创建工作目录"

    mkdir -p "$WORKSPACE"/{1.数据下载,2.数据筛选,3.代码管理,4.包管理/downloads,5.崩溃分析}

    echo -e "${GREEN}✅ 工作目录已创建: $WORKSPACE${NC}"
}

# 包名处理函数
# 搜索崩溃时使用不带base/的包名，下载和分析代码时使用带base/的包名
get_crash_search_name() {
    local pkg="$1"
    # 去掉base/前缀用于崩溃数据搜索
    echo "${pkg#base/}"
}

# 步骤1: 下载数据
download_data() {
    print_step 1 "数据下载" >&2

    local download_script="$SKILLS_DIR/coredump-data-download/scripts/download_metabase_csv.sh"

    if [[ ! -f "$download_script" ]]; then
        echo -e "${RED}错误: 下载脚本不存在: $download_script${NC}" >&2
        exit 1
    fi

    # 下载名称可与当前分析包不同：一项目多包场景按项目下载，后续仍按 PACKAGE 筛选。
    local download_name
    download_name=$(get_data_download_name)
    local search_package
    search_package=$(get_crash_search_name "$download_name")
    local sanitized_search_package="${search_package//\//_}"

    # 根据 ARCH 参数确定CSV文件名中的架构后缀
    local csv_arch_suffix
    case "$ARCH" in
        x86) csv_arch_suffix="X86" ;;
        x86_64|amd64) csv_arch_suffix="X86" ;;
        arm|arm64|aarch64) csv_arch_suffix="AARCH64" ;;  # arm/arm64/aarch64 都使用 AARCH64 文件名后缀
        *) csv_arch_suffix="$ARCH" ;;
    esac

    # 直接使用原始脚本，不复制到workspace
    echo -e "${YELLOW}当前分析包: $PACKAGE${NC}" >&2
    echo -e "${YELLOW}崩溃数据下载名称: $download_name${NC}" >&2
    echo -e "${YELLOW}执行: bash $download_script${NC}" >&2
    echo "" >&2

    cd "$WORKSPACE/1.数据下载"

    # 同一 workspace 内多子包共用同一项目下载数据；已存在时直接复用，避免重复拉取。
    local existing_csv=""
    existing_csv=$(find "$WORKSPACE/1.数据下载" -type f \( -name "${search_package}_${csv_arch_suffix}_crash_*.csv" -o -name "${sanitized_search_package}_${csv_arch_suffix}_crash_*.csv" \) 2>/dev/null | sort | tail -1 || true)
    if [[ -n "$existing_csv" ]]; then
        local existing_lines
        existing_lines=$(wc -l < "$existing_csv" 2>/dev/null || echo 0)
        echo -e "${GREEN}✅ 复用当前 workspace 已下载数据: $existing_csv ($existing_lines 行)${NC}" >&2
        printf "%s" "$existing_csv"
        return 0
    fi

    local cmd=(bash "$download_script" --sys-version "$SYS_VERSION")
    [[ -n "$START_DATE" ]] && cmd+=(--start-date "$START_DATE")
    [[ -n "$END_DATE" ]] && cmd+=(--end-date "$END_DATE")
    cmd+=("$search_package" "$ARCH" crash)
    echo -e "${YELLOW}执行: ${cmd[*]}${NC}" >&2
    "${cmd[@]}" >&2

    # 查找下载的文件（优先匹配原始搜索名，同时兼容 slash -> underscore 的文件名）
    local csv_file=$(find "$WORKSPACE/1.数据下载" -type f \( -name "${search_package}_${csv_arch_suffix}_crash_*.csv" -o -name "${sanitized_search_package}_${csv_arch_suffix}_crash_*.csv" \) | sort | tail -1)

    if [[ -z "$csv_file" ]]; then
        # 下载失败，尝试使用旧的CSV文件
        local old_csv=$(find "$WORKSPACE/1.数据下载" -type f \( -name "${search_package}_${csv_arch_suffix}_crash_*.csv" -o -name "${sanitized_search_package}_${csv_arch_suffix}_crash_*.csv" \) 2>/dev/null | sort | tail -1)
        if [[ -n "$old_csv" ]]; then
            local old_lines=$(wc -l < "$old_csv")
            echo -e "${YELLOW}⚠️ 本次下载未产生新数据，回退使用旧文件: $old_csv ($old_lines 行)${NC}" >&2
            printf "%s" "$old_csv"
            return 0
        fi
        echo -e "${RED}错误: 数据下载失败，未找到CSV文件${NC}" >&2
        exit 1
    fi

    local line_count=$(wc -l < "$csv_file")
    echo -e "${GREEN}✅ 数据下载完成: $csv_file ($line_count 行)${NC}" >&2

    # 返回CSV文件路径到stdout
    printf "%s" "$csv_file"
}

# 步骤2: 数据筛选/去重
filter_data() {
    # 所有输出必须重定向到 stderr，确保 stdout 只有文件路径
    print_step 2 "数据筛选/去重" >&2

    local input_csv="$1"
    local filter_script="$SKILLS_DIR/coredump-data-filter/scripts/filter_crash_data.py"

    if [[ ! -f "$filter_script" ]]; then
        echo -e "${RED}错误: 筛选脚本不存在: $filter_script${NC}" >&2
        exit 1
    fi

    # 获取用于崩溃搜索的包名（去掉base/前缀）
    local search_package=$(get_crash_search_name "$PACKAGE")

    echo -e "${YELLOW}执行: python3 $filter_script --workspace $WORKSPACE --input-csv $input_csv $search_package${NC}" >&2
    echo "" >&2

    # 直接使用原始脚本，输出全部发送到 stderr。input_csv 可能是项目级下载文件，筛选脚本按实际包名过滤。
    cd "$WORKSPACE/2.数据筛选"
    python3 "$filter_script" --workspace "$WORKSPACE" --input-csv "$input_csv" "$search_package" >&2

    local filtered_csv="$WORKSPACE/2.数据筛选/filtered_${search_package}_crash_data.csv"
    local stats_json="$WORKSPACE/2.数据筛选/${search_package}_crash_statistics.json"

    if [[ -f "$filtered_csv" ]]; then
        echo -e "${GREEN}✅ 数据筛选完成${NC}" >&2
    fi

    if [[ -f "$stats_json" ]]; then
        echo -e "${GREEN}✅ 统计报告已生成${NC}" >&2
        echo "" >&2
        echo -e "${YELLOW}统计摘要:${NC}" >&2
        jq '.summary' "$stats_json" >&2 || cat "$stats_json" >&2
    fi

    # 只向 stdout 输出文件路径（无任何其他输出）
    printf "%s" "$filtered_csv"
}

filtered_csv_has_rows() {
    local filtered_csv="$1"

    [[ -f "$filtered_csv" ]] || return 1

    awk '
        NR > 1 && $0 ~ /[^[:space:]]/ { found = 1; exit }
        END { exit(found ? 0 : 1) }
    ' "$filtered_csv"
}

# 步骤3: 代码管理 - 为每个崩溃版本切换代码分支
download_source() {
    print_step 3 "代码管理" >&2

    local filtered_csv="$1"
    local source_script="$SKILLS_DIR/coredump-code-management/scripts/download_crash_source.sh"
    local gerrit_project=$(get_gerrit_project)

    if [[ ! -f "$source_script" ]]; then
        echo -e "${RED}错误: 代码管理脚本不存在: $source_script${NC}"
        return 1
    fi

    echo -e "${YELLOW}Gerrit 项目: $gerrit_project${NC}"

    # 从崩溃版本列表获取所有需要处理的版本
    local versions_txt="$WORKSPACE/2.数据筛选/${PACKAGE}_crash_versions.txt"
    if [[ -f "$versions_txt" ]]; then
        echo -e "${YELLOW}从版本列表读取需要处理的版本...${NC}"
        local version_count=$(wc -l < "$versions_txt")
        echo -e "${YELLOW}共 ${version_count} 个版本需要处理${NC}"
        echo ""

        # 逐个版本处理
        local success_count=0
        local fail_count=0
        while IFS= read -r version_line; do
            [[ -z "$version_line" ]] && continue

            # 版本格式可能是 "epoch:version:count" 或 "version:count"
            # 正确的提取方式：去掉最后一个冒号及其后面的内容（count），然后去掉 epoch 前缀
            local version_with_count="$version_line"
            local count="${version_with_count##*:}"  # 取最后一个冒号后面的内容
            local rest="${version_with_count%:*}"     # 去掉最后一个冒号及后面的内容
            # 如果还有冒号，说明有 epoch，去掉它
            local version="${rest#*:}"

            # 清理版本号（移除 epoch 前缀和 -1 后缀）
            local clean_version=$(echo "$version" | sed 's/^1://' | sed 's/-1$//')

            echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
            echo -e "${YELLOW}处理版本: $version -> $clean_version${NC}"
            echo ""

            # 设置环境变量并执行脚本（使用 gerrit_project 而非 PACKAGE）
            if COREDUMP_WORKSPACE="$WORKSPACE" GERRIT_USER="$GERRIT_USER" GERRIT_HOST="${GERRIT_HOST:-gerrit.uniontech.com}" GERRIT_PORT="${GERRIT_PORT:-29418}" \
               bash "$source_script" "$gerrit_project" "$clean_version"; then
                ((success_count++)) || true
            else
                ((fail_count++)) || true
            fi
            echo ""
        done < "$versions_txt"

        echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${GREEN}代码管理完成: 成功 ${success_count} 个版本${NC}"
        if [[ $fail_count -gt 0 ]]; then
            echo -e "${YELLOW}失败 ${fail_count} 个版本${NC}"
        fi
    else
        echo -e "${YELLOW}未找到版本列表文件${NC}"
    fi
}

# ============================================================
# 以下是按版本处理的步骤（3+4+5 整合为版本循环）
# ============================================================

get_workspace_search_root() {
    if [[ -n "$WORKSPACE_SEARCH_ROOT" ]]; then
        echo "$WORKSPACE_SEARCH_ROOT"
        return 0
    fi

    # 默认 workspace 由 check_config() 基于 accounts.json paths.workspace 或 $HOME 生成。
    # 历史复用必须扫描同一个根目录，而不是 $SKILLS_DIR；否则默认生成在 ~/coredump-workspace-* 的历史数据会被漏掉。
    if [[ -n "$WORKSPACE" ]]; then
        dirname "$WORKSPACE"
    else
        echo "$HOME"
    fi
}

build_reusable_workspaces_list() {
    local search_root
    search_root=$(get_workspace_search_root)
    local max_scan="${MAX_WORKSPACE_SCAN:-20}"
    [[ "$max_scan" =~ ^[0-9]+$ && "$max_scan" -gt 0 ]] || max_scan=20

    if [[ ! -d "$search_root" ]]; then
        return 0
    fi

    local current_workspace_real=""
    if [[ -n "$WORKSPACE" && -e "$WORKSPACE" ]]; then
        current_workspace_real=$(realpath "$WORKSPACE" 2>/dev/null || true)
    fi

    find "$search_root" -maxdepth 1 -type d -name 'coredump-workspace-*' -printf '%T@\t%p\n' 2>/dev/null \
        | sort -nr \
        | cut -f2- \
        | while IFS= read -r workspace_dir; do
            local workspace_real
            workspace_real=$(realpath "$workspace_dir" 2>/dev/null || echo "$workspace_dir")
            if [[ -n "$current_workspace_real" && "$workspace_real" == "$current_workspace_real" ]]; then
                continue
            fi
            echo "$workspace_dir"
        done \
        | head -n "$max_scan"
}

init_reusable_workspaces_cache() {
    REUSABLE_WORKSPACES_FILE="$WORKSPACE/$SUMMARY_DIR_NAME/reusable_workspaces.txt"
    : > "$REUSABLE_WORKSPACES_FILE" || return 1

    if [[ "$ENABLE_LOCAL_REUSE" != "true" ]]; then
        return 0
    fi

    build_reusable_workspaces_list > "$REUSABLE_WORKSPACES_FILE" || return 1
    local count
    count=$(grep -c . "$REUSABLE_WORKSPACES_FILE" 2>/dev/null || echo 0)
    echo -e "${BLUE}本地复用 workspace 缓存: $REUSABLE_WORKSPACES_FILE (${count} 个)${NC}"
}

list_reusable_workspaces() {
    if [[ -n "$REUSABLE_WORKSPACES_FILE" && -f "$REUSABLE_WORKSPACES_FILE" ]]; then
        cat "$REUSABLE_WORKSPACES_FILE"
    else
        build_reusable_workspaces_list
    fi
}

source_repo_available_for_reuse() {
    local repo_dir="$1"
    [[ -d "$repo_dir/.git" ]]
}

source_repo_at_exact_version() {
    local repo_dir="$1"
    local version="$2"
    [[ -d "$repo_dir/.git" ]] || return 1

    local current_tag
    current_tag=$(git -C "$repo_dir" describe --tags --exact-match 2>/dev/null || true)
    [[ "$current_tag" == "$version" ]]
}

copy_reusable_source_repo() {
    local source_repo="$1"
    local target_repo="$2"

    [[ -d "$source_repo/.git" ]] || return 1
    mkdir -p "$(dirname "$target_repo")" || return 1
    rm -rf "$target_repo" || return 1

    if command -v rsync &> /dev/null; then
        rsync -a --delete "$source_repo/" "$target_repo/" || return 1
    else
        cp -a "$source_repo" "$target_repo" || return 1
    fi

    [[ -d "$target_repo/.git" ]] || return 1
}

find_reusable_source_repo() {
    local gerrit_project="$1"
    local version="$2"
    local workspace_dir

    while IFS= read -r workspace_dir; do
        [[ -n "$workspace_dir" ]] || continue
        local candidate_repo="$workspace_dir/3.代码管理/$gerrit_project"
        if source_repo_available_for_reuse "$candidate_repo"; then
            echo "$candidate_repo"
            return 0
        fi
    done < <(list_reusable_workspaces)

    return 1
}

copy_reusable_deb_files() {
    local deb_files="$1"
    local target_dir="$2"
    local copied=0
    mkdir -p "$target_dir" || return 1

    while IFS= read -r deb_file; do
        [[ -n "$deb_file" && -f "$deb_file" ]] || continue
        local target_file="$target_dir/$(basename "$deb_file")"
        if [[ ! -f "$target_file" ]]; then
            cp "$deb_file" "$target_file" || return 1
        fi
        ((copied++)) || true
    done <<< "$deb_files"

    echo "$copied"
}

find_reusable_deb_files() {
    local package="$1"
    local clean_version="$2"
    local arch="$3"
    local workspace_dir

    while IFS= read -r workspace_dir; do
        [[ -n "$workspace_dir" ]] || continue
        local candidate_dl_dir="$workspace_dir/4.包管理/downloads"
        [[ -d "$candidate_dl_dir" ]] || continue
        local deb_files
        deb_files=$(find_deb_files_for_version "$candidate_dl_dir" "$package" "$clean_version" "$arch")
        if [[ -n "$deb_files" ]]; then
            printf '%s\n' "$deb_files"
            return 0
        fi
    done < <(list_reusable_workspaces)

    return 1
}

# 步骤3: 切换代码到指定版本
download_source_for_version() {
    local package="$1"
    local version="$2"
    local source_script="$SKILLS_DIR/coredump-code-management/scripts/download_crash_source.sh"
    local gerrit_project=$(get_gerrit_project)

    echo -e "${YELLOW}━━━ 步骤3: 切换代码到 $version (项目: $gerrit_project) ━━━${NC}"

    if [[ "$ENABLE_CODE_MANAGEMENT" != "true" ]]; then
        echo -e "${YELLOW}⚠️ 代码管理已通过配置关闭，跳过源码克隆/切换${NC}"
        set_step_result "skipped_disabled" "code management disabled by config"
        return 0
    fi

    # 检查当前 workspace 是否已有该项目源码；只有已在目标 tag 时才跳过 checkout。
    local repo_dir="$WORKSPACE/3.代码管理/$gerrit_project"
    if source_repo_at_exact_version "$repo_dir" "$version"; then
        echo -e "${GREEN}✅ 源码已存在且版本匹配 ($version)，跳过切换${NC}"
        set_step_result "ok" "source already at correct version"
        return 0
    elif source_repo_available_for_reuse "$repo_dir"; then
        echo -e "${GREEN}✅ 源码已存在且项目匹配 ($gerrit_project)，继续切换到目标版本${NC}"
    elif [[ "$ENABLE_LOCAL_REUSE" == "true" && "$REUSE_SOURCE_CODE" == "true" ]]; then
        # 优先复用历史 workspace 中同项目源码；复用后继续执行 checkout，避免源码版本与 coredump 不一致。
        echo -e "${BLUE}🔍 搜索本地历史 workspace 中可复用源码...${NC}"
        local reusable_repo
        reusable_repo=$(find_reusable_source_repo "$gerrit_project" "$version" || true)
        if [[ -n "$reusable_repo" ]]; then
            echo -e "${GREEN}✅ 找到可复用源码: $reusable_repo${NC}"
            if copy_reusable_source_repo "$reusable_repo" "$repo_dir" && source_repo_available_for_reuse "$repo_dir"; then
                if source_repo_at_exact_version "$repo_dir" "$version"; then
                    echo -e "${GREEN}✅ 源码已复制到当前 workspace 且版本匹配: $repo_dir${NC}"
                    set_step_result "ok" "source reused from local workspace at correct version: $reusable_repo"
                    return 0
                fi
                echo -e "${GREEN}✅ 源码已复制到当前 workspace，继续切换到目标版本: $repo_dir${NC}"
            else
                echo -e "${YELLOW}⚠️ 复用源码复制或项目校验失败，继续执行 Gerrit clone/checkout${NC}"
                rm -rf "$repo_dir" || true
            fi
        else
            echo -e "${YELLOW}⚠️ 未找到可复用源码，执行 Gerrit clone/checkout${NC}"
        fi
    fi

    if [[ ! -f "$source_script" ]]; then
        echo -e "${RED}错误: 代码管理脚本不存在: $source_script${NC}" >&2
        set_step_result "failed_missing_script" "source download script missing"
        return 1
    fi

    # 设置环境变量并执行脚本（使用 gerrit_project 而非 package）。
    # 该脚本会在已有/复用仓库中 fetch tags，并按目标版本执行 checkout/reset。
    local source_exit=0
    if COREDUMP_WORKSPACE="$WORKSPACE" GERRIT_USER="$GERRIT_USER" GERRIT_HOST="${GERRIT_HOST:-gerrit.uniontech.com}" GERRIT_PORT="${GERRIT_PORT:-29418}" \
       bash "$source_script" "$gerrit_project" "$version" >&2; then
        set_step_result "ok" "source checkout ready"
        echo -e "${GREEN}✅ 代码切换完成${NC}"
        return 0
    else
        source_exit=$?
        if [[ "$source_exit" -eq 2 ]]; then
            set_step_result "skipped_no_matching_tag" "no matching source tag found"
            echo -e "${YELLOW}⚠️ 未找到目标 tag，当前版本将使用 AI-only 堆栈分析${NC}"
            return 2
        fi
        set_step_result "failed" "source checkout failed"
        echo -e "${RED}❌ 代码切换失败${NC}"
        echo -e "${YELLOW}提示：如果是 Gerrit 克隆失败，请确认是否已将 ~/.ssh/id_rsa.pub 配置到 Gerrit 的设置-\"SSH Keys\" 里面${NC}"
        return 1
    fi
}

# 步骤4: 下载指定版本的包
download_packages_for_version() {
    local package="$1"
    local version="$2"
    local dl_script="$SKILLS_DIR/coredump-package-management/scripts/scan_and_download.py"
    local dl_dir="$WORKSPACE/4.包管理/downloads"
    local skipped_versions_file="$WORKSPACE/4.包管理/downloads/skipped_versions.txt"

    if [[ ! -f "$dl_script" ]]; then
        echo -e "${RED}错误: 包下载脚本不存在: $dl_script${NC}" >&2
        set_step_result "failed_missing_script" "package download script missing"
        return 1
    fi

    echo -e "${YELLOW}━━━ 步骤4: 下载 $version 的包 ━━━${NC}"

    if [[ "$ENABLE_PACKAGE_MANAGEMENT" != "true" ]]; then
        echo -e "${YELLOW}⚠️ 包管理已通过配置关闭，跳过 deb/dbgsym 下载${NC}"
        set_step_result "skipped_disabled" "package management disabled by config"
        return 0
    fi

    # 创建下载目录
    mkdir -p "$dl_dir" || {
        echo -e "${RED}错误: 无法创建下载目录: $dl_dir${NC}" >&2
        set_step_result "failed" "cannot create package download dir"
        return 1
    }

    # 清理版本号（用于下载）
    local clean_version=$(echo "$version" | sed 's/^1://' | sed 's/-1$//')

    if ! can_install_deb_packages; then
        echo -e "${YELLOW}⚠️ 未配置 sudo 密码且当前用户无免密 sudo，跳过 deb/dbgsym 下载${NC}"
        set_step_result "skipped_no_sudo" "no sudo capability, skip package download"
        return 0
    fi

    # 检查当前 workspace 是否已有该版本的deb包
    if [[ -n "$(find_deb_files_for_version "$dl_dir" "$package" "$clean_version" "$ARCH")" ]]; then
        clear_skipped_version_entry "$skipped_versions_file" "$package" "$clean_version" || true
        echo -e "${GREEN}✅ $package $clean_version 的deb包已存在，跳过下载${NC}"
        set_step_result "ok" "deb packages already exist"
        return 0
    fi

    # 优先复用历史 workspace 中的 deb/dbgsym 包
    if [[ "$ENABLE_LOCAL_REUSE" == "true" && "$REUSE_DEB_PACKAGES" == "true" ]]; then
        echo -e "${BLUE}🔍 搜索本地历史 workspace 中可复用 deb/dbgsym...${NC}"
        local reusable_deb_files
        reusable_deb_files=$(find_reusable_deb_files "$package" "$clean_version" "$ARCH" || true)
        if [[ -n "$reusable_deb_files" ]]; then
            local source_dir
            source_dir=$(dirname "$(printf '%s\n' "$reusable_deb_files" | head -n 1)")
            local copied_count
            if copied_count=$(copy_reusable_deb_files "$reusable_deb_files" "$dl_dir"); then
                if [[ -n "$(find_deb_files_for_version "$dl_dir" "$package" "$clean_version" "$ARCH")" ]]; then
                    clear_skipped_version_entry "$skipped_versions_file" "$package" "$clean_version" || true
                    echo -e "${GREEN}✅ 复用 deb/dbgsym 文件 ${copied_count} 个，来源: $source_dir${NC}"
                    set_step_result "ok" "deb packages reused from local workspace: $source_dir"
                    return 0
                fi
                echo -e "${YELLOW}⚠️ deb/dbgsym 复制后校验失败，继续执行包下载${NC}"
            else
                echo -e "${YELLOW}⚠️ deb/dbgsym 复制失败，继续执行包下载${NC}"
            fi
        else
            echo -e "${YELLOW}⚠️ 未找到可复用 deb/dbgsym，执行包下载${NC}"
        fi
    fi

    # 下载该版本的包和调试符号（使用位置参数格式）
    echo -e "${YELLOW}下载 $package ${clean_version} ...${NC}"

    # 调用下载脚本（忽略其退出码），传入架构参数
    python3 "$dl_script" \
        -d "$dl_dir" \
        --arch "$ARCH" \
        "$package" "$clean_version" 2>&1 || true

    # 使用 find 检查文件是否存在，允许 Debian 构建后缀：
    #   pkg_1.2.3_arm64.deb / pkg_1.2.3-1_arm64.deb
    #   pkg_1.2.3+build_arm64.deb / pkg_1.2.3.1-1_arm64.deb
    if [[ -d "$dl_dir" ]] && [[ -n "$(find_deb_files_for_version "$dl_dir" "$package" "$clean_version" "$ARCH")" ]]; then
        clear_skipped_version_entry "$skipped_versions_file" "$package" "$clean_version" || true
        echo -e "${GREEN}✅ 包下载完成${NC}"
        set_step_result "ok" "deb packages downloaded"
        return 0
    else
        echo -e "${YELLOW}⚠️ 未找到 $package $clean_version 的包（精确版本不匹配），跳过${NC}"
        echo "$package $clean_version (精确版本不匹配)" >> "$skipped_versions_file"
        set_step_result "skipped_no_matching_package" "no matching deb/dbgsym package found"
        return 1
    fi
}

can_install_deb_packages() {
    if [[ -n "$SUDO_PASSWORD" && "$SUDO_PASSWORD" != "null" && "$SUDO_PASSWORD" != "在此处输入"* ]]; then
        return 0
    fi

    sudo -n true 2>/dev/null
}

find_deb_files_for_version() {
    local dl_dir="$1"
    local package="$2"
    local version="$3"
    local arch="$4"

    # 根据 ARCH 参数确定文件名中的架构后缀
    local arch_suffix
    case "$arch" in
        x86) arch_suffix="amd64" ;;
        x86_64) arch_suffix="amd64" ;;
        arm64) arch_suffix="arm64" ;;
        aarch64) arch_suffix="arm64" ;;  # aarch64 对应 deb 包的 arm64
        *) arch_suffix="$arch" ;;
    esac

    [[ -d "$dl_dir" ]] || return 0

    # deb/dbgsym 本地复用必须同时匹配包名、版本号/dbgsym版本号和架构。
    find "$dl_dir" -maxdepth 1 -type f \( \
        -name "${package}_${version}_${arch_suffix}.deb" -o \
        -name "${package}_${version}-*_${arch_suffix}.deb" -o \
        -name "${package}_${version}-${arch_suffix}.deb" -o \
        -name "${package}_${version}+*_${arch_suffix}.deb" -o \
        -name "${package}_${version}.*_${arch_suffix}.deb" -o \
        -name "${package}-dbgsym_${version}_${arch_suffix}.deb" -o \
        -name "${package}-dbgsym_${version}-*_${arch_suffix}.deb" -o \
        -name "${package}-dbgsym_${version}-${arch_suffix}.deb" -o \
        -name "${package}-dbgsym_${version}+*_${arch_suffix}.deb" -o \
        -name "${package}-dbgsym_${version}.*_${arch_suffix}.deb" \
    \) 2>/dev/null
}

version_in_skipped_file() {
    local skip_file="$1"
    local package="$2"
    local clean_version="$3"

    [[ -f "$skip_file" ]] || return 1
    awk -v pkg="$package" -v ver="$clean_version" '
        NF >= 2 && $1 == pkg && $2 == ver { found = 1; exit }
        END { exit(found ? 0 : 1) }
    ' "$skip_file"
}

clear_skipped_version_entry() {
    local skip_file="$1"
    local package="$2"
    local clean_version="$3"
    local tmp_file=""

    [[ -f "$skip_file" ]] || return 0

    tmp_file=$(mktemp "${TMPDIR:-/tmp}/coredump-skipped-version.XXXXXX") || return 1
    awk -v pkg="$package" -v ver="$clean_version" '
        !(NF >= 2 && $1 == pkg && $2 == ver)
    ' "$skip_file" > "$tmp_file" || {
        rm -f "$tmp_file"
        return 1
    }
    mv "$tmp_file" "$skip_file"
}

run_dpkg_install_locked() {
    local deb_file="$1"
    local lock_file="${TMPDIR:-/tmp}/coredump-dpkg-install.lock"

    if command -v flock >/dev/null 2>&1; then
        (
            flock 9
            if [[ -n "$SUDO_PASSWORD" && "$SUDO_PASSWORD" != "null" && "$SUDO_PASSWORD" != "在此处输入"* ]]; then
                expect -c "
set deb_file \"$deb_file\"
set sudo_pass \"$SUDO_PASSWORD\"
spawn sudo dpkg -i \$deb_file
expect {
    -re \"(password|请输入密码)\" {
        send \"\$sudo_pass\r\"
        expect eof
    }
    eof {
        exit 0
    }
}
" 2>&1 || true
            else
                sudo -n dpkg -i "$deb_file" 2>&1 || true
            fi
        ) 9>"$lock_file"
    else
        if [[ -n "$SUDO_PASSWORD" && "$SUDO_PASSWORD" != "null" && "$SUDO_PASSWORD" != "在此处输入"* ]]; then
            expect -c "
set deb_file \"$deb_file\"
set sudo_pass \"$SUDO_PASSWORD\"
spawn sudo dpkg -i \$deb_file
expect {
    -re \"(password|请输入密码)\" {
        send \"\$sudo_pass\r\"
        expect eof
    }
    eof {
        exit 0
    }
}
" 2>&1 || true
        else
            sudo -n dpkg -i "$deb_file" 2>&1 || true
        fi
    fi
}

verify_installed_deb_files() {
    local deb_files="$1"
    local deb_file=""
    local pkg_name=""
    local pkg_version=""
    local status_line=""

    while IFS= read -r deb_file; do
        [[ -n "$deb_file" && -f "$deb_file" ]] || continue
        pkg_name=$(dpkg-deb -f "$deb_file" Package 2>/dev/null || true)
        pkg_version=$(dpkg-deb -f "$deb_file" Version 2>/dev/null || true)
        [[ -n "$pkg_name" && -n "$pkg_version" ]] || return 1

        status_line=$(dpkg-query -W -f='${Status}\t${Version}\n' "$pkg_name" 2>/dev/null || true)
        [[ "$status_line" == *"install ok installed"* ]] || return 1
        [[ "$status_line" == *$'\t'"$pkg_version" ]] || return 1
    done <<< "$deb_files"

    return 0
}

split_deb_files_for_install() {
    local deb_files="$1"
    local main_files=""
    local dbgsym_files=""
    local deb_file=""

    while IFS= read -r deb_file; do
        [[ -z "$deb_file" ]] && continue
        if [[ "$deb_file" == *"-dbgsym_"* ]] || [[ "$deb_file" == *"dbgsym"* ]]; then
            dbgsym_files+="$deb_file"$'\n'
        else
            main_files+="$deb_file"$'\n'
        fi
    done <<< "$deb_files"

    printf '%s__SPLIT__\n%s' "$main_files" "$dbgsym_files"
}

# 步骤5: 安装包并分析指定版本的崩溃
analyze_crashes_for_version() {
    local package="$1"
    local version="$2"
    local filtered_csv="$3"
    local analysis_mode="${4:-full}"
    local analysis_reason="${5:-}"
    local analyze_script="$SKILLS_DIR/coredump-full-analysis/scripts/analyze_crash_per_version.py"
    local dl_dir="$WORKSPACE/4.包管理/downloads"
    local skip_file="$WORKSPACE/4.包管理/downloads/skipped_versions.txt"
    local effective_analysis_mode="$analysis_mode"
    local effective_ai_only_reason=""
    local effective_degraded_reason=""

    if [[ ! -f "$analyze_script" ]]; then
        echo -e "${RED}错误: 分析脚本不存在: $analyze_script${NC}" >&2
        set_step_result "failed_missing_script" "version analysis script missing"
        return 1
    fi

    echo -e "${YELLOW}━━━ 步骤5: 分析 $version 的崩溃 ━━━${NC}"

    # 清理版本号
    local clean_version=$(echo "$version" | sed 's/^1://' | sed 's/-1$//')

    # 检查是否该版本被跳过（deb包不存在）
    if [[ "$analysis_mode" == "ai-only" ]]; then
        effective_ai_only_reason="$analysis_reason"
        echo -e "${YELLOW}⚠️ AI-only 模式：跳过源码/deb/dbgsym/addr2line/objdump/git，仅基于崩溃堆栈分析 (${effective_ai_only_reason:-fallback})${NC}"
    elif [[ "$ENABLE_PACKAGE_MANAGEMENT" != "true" ]]; then
        effective_analysis_mode="degraded-full"
        effective_degraded_reason="package_management_disabled"
        echo -e "${YELLOW}⚠️ 包管理已通过配置关闭，进入降级增强分析${NC}"
    elif version_in_skipped_file "$skip_file" "$package" "$clean_version"; then
        effective_analysis_mode="degraded-full"
        effective_degraded_reason="package_marked_missing"
        echo -e "${YELLOW}⚠️ 该版本 deb 包已标记缺失，进入降级增强分析${NC}"
    else
        # 安装该版本的 deb 包（包括调试符号包 dbgsym）
        # 使用 find 避免 ls 在多文件时返回1的问题
        if [[ -d "$dl_dir" ]]; then
            local deb_files=$(find_deb_files_for_version "$dl_dir" "$package" "$clean_version" "$ARCH" || true)
            if [[ -n "$deb_files" ]]; then
                local can_install=false
                local split_output=""
                local main_deb_files=""
                local dbgsym_deb_files=""
                local deb_file=""
                local install_verified=false

                if [[ -n "$SUDO_PASSWORD" && "$SUDO_PASSWORD" != "null" && "$SUDO_PASSWORD" != "在此处输入"* ]]; then
                    can_install=true
                elif can_install_deb_packages; then
                    can_install=true
                fi

                if [[ "$can_install" == "true" ]]; then
                    echo -e "${YELLOW}安装 deb 包:${NC}"
                    split_output=$(split_deb_files_for_install "$deb_files")
                    main_deb_files="${split_output%%__SPLIT__*}"
                    dbgsym_deb_files="${split_output#*__SPLIT__}"

                    while IFS= read -r deb_file; do
                        [[ -z "$deb_file" ]] && continue
                        if [[ -f "$deb_file" ]]; then
                            echo -e "  安装: $(basename "$deb_file")${NC}"
                            run_dpkg_install_locked "$deb_file"
                        fi
                    done <<< "$main_deb_files"

                    while IFS= read -r deb_file; do
                        [[ -z "$deb_file" ]] && continue
                        if [[ -f "$deb_file" ]]; then
                            echo -e "  安装: $(basename "$deb_file")${NC}"
                            run_dpkg_install_locked "$deb_file"
                        fi
                    done <<< "$dbgsym_deb_files"

                    if verify_installed_deb_files "$deb_files"; then
                        install_verified=true
                        echo -e "${GREEN}✅ deb/dbgsym 安装校验通过${NC}"
                    fi
                else
                    echo -e "${YELLOW}⚠️ 未配置 sudo 密码且当前用户无免密 sudo，无法安装 deb，进入降级增强分析${NC}"
                    effective_analysis_mode="degraded-full"
                    effective_degraded_reason="package_install_unavailable"
                fi

                if [[ "$can_install" == "true" && "$install_verified" != "true" ]]; then
                    echo -e "${YELLOW}⚠️ deb/dbgsym 安装未通过校验，进入降级增强分析${NC}"
                    effective_analysis_mode="degraded-full"
                    effective_degraded_reason="package_install_failed"
                fi
            else
                effective_analysis_mode="degraded-full"
                effective_degraded_reason="package_files_missing"
                echo -e "${YELLOW}⚠️ 当前 workspace 未找到可安装 deb 文件，进入降级增强分析${NC}"
            fi
        fi
    fi

    if [[ "$effective_analysis_mode" == "degraded-full" ]]; then
        echo -e "${YELLOW}⚠️ 降级增强分析：保留规则/addr2line/git/LLM 路径，但标记为安装失败降级 (${effective_degraded_reason:-fallback})${NC}"
    fi

    # 执行分析（使用 analyze_crash_per_version.py 保存 JSON 报告）
    # 将脚本目录加入 PYTHONPATH，确保 enhanced_analysis 等模块可导入
    local analyze_script_dir
    analyze_script_dir="$(cd "$(dirname "$analyze_script")" && pwd)"
    local analyze_cmd=(python3 "$analyze_script"
        --package "$package"
        --version "$clean_version"
        --workspace "$WORKSPACE"
        --max-crashes "$MAX_CRASHES"
        --addr2line-max-frames "$ADDR2LINE_MAX_FRAMES"
        --analysis-mode "$effective_analysis_mode")
    if [[ -n "$effective_ai_only_reason" ]]; then
        analyze_cmd+=(--ai-only-reason "$effective_ai_only_reason")
    fi
    if [[ -n "$effective_degraded_reason" ]]; then
        analyze_cmd+=(--degraded-reason "$effective_degraded_reason")
    fi
    PYTHONPATH="$analyze_script_dir:${PYTHONPATH:-}" \
    "${analyze_cmd[@]}" 2>&1 || true

    local version_dir="${clean_version//./_}"
    version_dir="${version_dir//+/_}"
    version_dir="${version_dir//-/_}"
    local analysis_json="$WORKSPACE/5.崩溃分析/$package/version_${version_dir}/analysis.json"

    if [[ -f "$analysis_json" ]]; then
        set_step_result "ok" "analysis.json generated (mode=${effective_analysis_mode})"
        echo -e "${GREEN}✅ 版本 $version 分析完成${NC}"
        return 0
    fi

    set_step_result "failed_no_output" "analysis.json not generated"
    echo -e "${YELLOW}⚠️ 版本 $version 未生成 analysis.json${NC}"
    return 1
}

# 步骤4: 包管理（保留用于批量生成任务）
download_packages() {
    print_step 4 "包管理" >&2

    local filtered_csv="$1"
    local gen_script="$SKILLS_DIR/coredump-package-management/scripts/generate_tasks.py"
    local dl_script="$SKILLS_DIR/coredump-package-management/scripts/scan_and_download.py"
    local dl_dir="$WORKSPACE/4.包管理/downloads"

    if [[ ! -f "$gen_script" ]]; then
        echo -e "${RED}错误: 任务生成脚本不存在: $gen_script${NC}"
        exit 1
    fi

    # 创建下载目录
    mkdir -p "$dl_dir"

    echo -e "${YELLOW}生成下载任务...${NC}"

    # 生成任务
    python3 "$gen_script" --crash-data "$filtered_csv" --workspace "$WORKSPACE"

    local tasks_file="$WORKSPACE/4.包管理/downloads/download_tasks.json"

    if [[ -f "$tasks_file" ]]; then
        echo -e "${GREEN}✅ 下载任务已生成: $tasks_file${NC}"
        echo ""

        # 提取高优先级任务数量
        local high_count=$(jq '[.tasks[] | select(.priority == "high")] | length' "$tasks_file" 2>/dev/null || echo "0")

        if [[ "$high_count" -gt 0 ]]; then
            echo -e "${YELLOW}高优先级任务: $high_count 个${NC}"

            # 提取高优先级任务到临时文件
            jq '[.tasks[] | select(.priority == "high")] | {tasks: .}' "$tasks_file" > "$WORKSPACE/4.包管理/downloads/high_priority_tasks.json"

            # 执行高优先级下载
            echo -e "${YELLOW}开始下载高优先级包...${NC}"
            python3 "$dl_script" \
                --batch "$WORKSPACE/4.包管理/downloads/high_priority_tasks.json" \
                --download-dir "$dl_dir"

            echo -e "${GREEN}✅ 高优先级包下载完成${NC}"
        else
            echo -e "${YELLOW}没有高优先级任务${NC}"
        fi

        # 下载所有任务（中低优先级）
        echo ""
        echo -e "${YELLOW}下载中低优先级包...${NC}"
        python3 "$dl_script" \
            --batch "$tasks_file" \
            --download-dir "$dl_dir" &

        echo -e "${GREEN}✅ 包下载任务已提交（后台运行）${NC}"
    fi
}

# 步骤5: 崩溃分析
analyze_crashes() {
    print_step 5 "崩溃分析" >&2

    local filtered_csv="$1"
    local analyze_script="$SKILLS_DIR/coredump-crash-analysis/scripts/analyze_crash_final.py"
    local centralized_dir="$SKILLS_DIR/coredump-crash-analysis/centralized"

    if [[ ! -f "$analyze_script" ]]; then
        echo -e "${RED}错误: 分析脚本不存在: $analyze_script${NC}"
        exit 1
    fi

    # 设置 PYTHONPATH 包含 centralized 模块路径
    export PYTHONPATH="$centralized_dir:$PYTHONPATH"

    echo -e "${YELLOW}执行崩溃分析...${NC}"
    echo ""

    cd "$WORKSPACE/5.崩溃分析"
    PYTHONPATH="$analyze_script_dir:${PYTHONPATH:-}" \
    python3 "$analyze_script" \
        --workspace "$WORKSPACE" \
        --package "$PACKAGE" \
        --csv "$filtered_csv" 2>&1 | head -50 || true

    # 生成分析报告
    local report_file="$WORKSPACE/5.崩溃分析/${PACKAGE}_crash_analysis_report.md"

    local date_range_label
    if [[ -z "$START_DATE" && -z "$END_DATE" ]]; then
        date_range_label="全部可下载数据（不按日期过滤）"
    elif [[ -n "$START_DATE" && -n "$END_DATE" ]]; then
        date_range_label="$START_DATE 至 $END_DATE"
    elif [[ -n "$START_DATE" ]]; then
        date_range_label="$START_DATE 至 最新可下载"
    else
        date_range_label="最早可下载 至 $END_DATE"
    fi

    cat > "$report_file" << EOF
# $PACKAGE 崩溃分析报告

**分析时间**: $(date '+%Y-%m-%d %H:%M:%S')
**数据范围**: $date_range_label
**包名**: $PACKAGE

## 目录结构

- 统计报告: \`$WORKSPACE/2.数据筛选/${PACKAGE}_crash_statistics.json\`
- 筛选数据: \`$WORKSPACE/2.数据筛选/filtered_${PACKAGE}_crash_data.csv\`
- 源码目录: \`$WORKSPACE/3.代码管理/$PACKAGE\`
- 下载的包: \`$WORKSPACE/4.包管理/downloads/\`
- 分析报告: \`$WORKSPACE/5.崩溃分析/\`

---
*报告生成时间: $(date '+%Y-%m-%d %H:%M:%S')*
EOF

    echo -e "${GREEN}✅ 分析报告已生成: $report_file${NC}"
}

# 进度上报函数
report_progress() {
    local elapsed=$1
    local current_version=$2
    local processed=$3
    local total=$4
    local success=$5
    local fail=$6
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}[$timestamp] 进度报告 (已运行 ${elapsed}秒)${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}步骤① 数据下载:${NC} 已完成"
    echo -e "${GREEN}步骤② 数据筛选:${NC} 已完成"
    echo -e "${GREEN}步骤③ 代码管理:${NC} 已创建分支"
    echo -e "${GREEN}步骤④ 包管理:${NC} 已下载 deb/dbgsym 包"
    echo -e "${GREEN}步骤⑤ 崩溃分析:${NC} 正在分析..."
    echo ""
    echo -e "  当前版本: ${current_version}"
    echo -e "  进度: ${processed}/${total} 个版本"
    echo -e "  成功: ${success}, 失败: ${fail}"
    echo ""

    # 统计下载目录中的 CSV 文件
    local download_dir="$WORKSPACE/1.数据下载"
    if [[ -d "$download_dir" ]]; then
        local csv_count=$(find "$download_dir" -name "*.csv" 2>/dev/null | wc -l)
        echo -e "  CSV文件: ${csv_count}个"
    fi

    # 统计已分析的版本
    local analysis_dir="$WORKSPACE/5.崩溃分析/$PACKAGE"
    if [[ -d "$analysis_dir" ]]; then
        local analyzed_count=$(find "$analysis_dir" -name "analysis.json" 2>/dev/null | wc -l)
        echo -e "  已分析版本: ${analyzed_count}个"
    fi

    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# 主函数
main() {
    # 1. 解析命令行参数
    parse_args "$@"

    # 2. 加载流程开关配置（数据筛选为必需步骤，不提供关闭开关）
    load_workflow_config
    echo -e "${BLUE}流程配置:${NC} config=$ANALYSIS_CONFIG_FILE, code_management=$ENABLE_CODE_MANAGEMENT, package_management=$ENABLE_PACKAGE_MANAGEMENT, auto_fix_submit=$AUTO_FIX_SUBMIT, max_crashes=$MAX_CRASHES, addr2line_max_frames=$ADDR2LINE_MAX_FRAMES, local_reuse=$ENABLE_LOCAL_REUSE, reuse_source=$REUSE_SOURCE_CODE, reuse_deb=$REUSE_DEB_PACKAGES, reuse_root=${WORKSPACE_SEARCH_ROOT:-$SKILLS_DIR}, max_workspace_scan=$MAX_WORKSPACE_SCAN"

    # 3. 检查配置完整性
    check_config

    # 4. 检查依赖
    check_dependencies

    # 5. 创建工作目录
    setup_workspace
    init_status_files
    init_reusable_workspaces_cache || echo -e "${YELLOW}⚠️ 初始化本地复用 workspace 缓存失败，将按需扫描${NC}"

    # 5. 执行分析步骤
    # 步骤1+2: 数据下载和筛选（只执行一次）
    local csv_file=$(download_data)
    local filtered_csv=$(filter_data "$csv_file")

    if ! filtered_csv_has_rows "$filtered_csv"; then
        local download_key
        download_key=$(get_data_download_name)
        echo -e "${YELLOW}⚠️ download_empty_skipped: package=$PACKAGE download_key=$download_key filtered_csv=$filtered_csv reason=no effective rows found; skipping package. If project-level download is intended, use --data-download-name to set the project download key.${NC}" >&2
        return 0
    fi

    # 步骤3+4+5: 按版本循环执行
    # 从版本列表读取每个版本，依次执行：切换代码→下载包→分析崩溃
    local versions_txt="$WORKSPACE/2.数据筛选/${PACKAGE}_crash_versions.txt"
    if [[ -f "$versions_txt" ]]; then
        local version_count=0
        while IFS= read -r version_line; do
            [[ -z "$version_line" ]] && continue
            local version_with_count="${version_line}"
            local rest="${version_with_count%:*}"
            local version="${rest#*:}"
            local clean_version=$(echo "$version" | sed 's/^1://' | sed 's/-1$//')
            if version_selected "$clean_version"; then
                ((version_count++)) || true
            fi
        done < "$versions_txt"
        echo -e "${YELLOW}共 ${version_count} 个版本需要分析${NC}"
        if [[ -n "$SELECTED_VERSIONS" ]]; then
            echo -e "${YELLOW}版本过滤: ${SELECTED_VERSIONS}${NC}"
        fi
        echo ""

        local success_count=0
        local fail_count=0
        local processed_count=0
        local ANALYSIS_START_TIME=$(date +%s)
        local LAST_PROGRESS_TIME=$ANALYSIS_START_TIME

        while IFS= read -r version_line; do
            [[ -z "$version_line" ]] && continue

            # 版本格式可能是 "epoch:version:count" 或 "version:count"
            # 正确的提取方式：去掉最后一个冒号及其后面的内容（count），然后去掉 epoch 前缀
            local version_with_count="${version_line}"
            local count="${version_with_count##*:}"  # 取最后一个冒号后面的内容
            local rest="${version_with_count%:*}"     # 去掉最后一个冒号及后面的内容
            # 如果还有冒号，说明有 epoch，去掉它
            local version="${rest#*:}"

            # 清理版本号（移除 epoch 前缀和 -1 后缀）
            local clean_version=$(echo "$version" | sed 's/^1://' | sed 's/-1$//')

            if ! version_selected "$clean_version"; then
                continue
            fi

            echo -e "${BLUE}════════════════════════════════════════════════════════════════════════${NC}"
            echo -e "${GREEN}处理版本: $version -> $clean_version${NC}"
            echo -e "${BLUE}════════════════════════════════════════════════════════════════════════${NC}"

            # 步骤3: 切换代码到该版本
            if download_source_for_version "$PACKAGE" "$clean_version"; then
                ((success_count++)) || true
            else
                ((fail_count++)) || true
                log_version_status "$clean_version" "source" "${STEP_STATUS:-unknown}" "${STEP_MESSAGE:-}"
                if [[ "${STEP_STATUS:-}" == "skipped_no_matching_tag" ]]; then
                    log_version_status "$clean_version" "package" "skipped_ai_only" "skip package download because source tag is missing"
                    if analyze_crashes_for_version "$PACKAGE" "$clean_version" "$filtered_csv" "ai-only" "source_tag_missing"; then
                        ((success_count++)) || true
                    else
                        ((fail_count++)) || true
                    fi
                    log_version_status "$clean_version" "analysis" "${STEP_STATUS:-unknown}" "${STEP_MESSAGE:-}"
                    log_version_status "$clean_version" "autofix" "skipped_ai_only" "skip auto fix for AI-only analysis"

                    ((processed_count++)) || true
                    if [[ "$PROGRESS_INTERVAL" -gt 0 ]]; then
                        local CURRENT_TIME=$(date +%s)
                        local ELAPSED=$((CURRENT_TIME - ANALYSIS_START_TIME))
                        local INTERVAL_PASSED=$((CURRENT_TIME - LAST_PROGRESS_TIME))
                        if [[ $INTERVAL_PASSED -ge $PROGRESS_INTERVAL ]]; then
                            report_progress "$ELAPSED" "$clean_version" "$processed_count" "$version_count" "$success_count" "$fail_count"
                            LAST_PROGRESS_TIME=$CURRENT_TIME
                        fi
                    fi
                    continue
                fi
                log_version_status "$clean_version" "package" "skipped_source_failed" "skip package download because source checkout failed"
                log_version_status "$clean_version" "analysis" "skipped_source_failed" "skip crash analysis because source checkout failed"
                log_version_status "$clean_version" "autofix" "skipped_source_failed" "skip auto fix because source checkout failed"

                ((processed_count++)) || true
                if [[ "$PROGRESS_INTERVAL" -gt 0 ]]; then
                    local CURRENT_TIME=$(date +%s)
                    local ELAPSED=$((CURRENT_TIME - ANALYSIS_START_TIME))
                    local INTERVAL_PASSED=$((CURRENT_TIME - LAST_PROGRESS_TIME))
                    if [[ $INTERVAL_PASSED -ge $PROGRESS_INTERVAL ]]; then
                        report_progress "$ELAPSED" "$clean_version" "$processed_count" "$version_count" "$success_count" "$fail_count"
                        LAST_PROGRESS_TIME=$CURRENT_TIME
                    fi
                fi
                continue
            fi
            log_version_status "$clean_version" "source" "${STEP_STATUS:-unknown}" "${STEP_MESSAGE:-}"

            # 步骤4: 下载该版本的包
            if download_packages_for_version "$PACKAGE" "$clean_version"; then
                ((success_count++)) || true
            else
                ((fail_count++)) || true
            fi
            log_version_status "$clean_version" "package" "${STEP_STATUS:-unknown}" "${STEP_MESSAGE:-}"

            if [[ "${STEP_STATUS:-}" == "skipped_no_matching_package" ]]; then
                if analyze_crashes_for_version "$PACKAGE" "$clean_version" "$filtered_csv" "ai-only" "package_missing"; then
                    ((success_count++)) || true
                else
                    ((fail_count++)) || true
                fi
                log_version_status "$clean_version" "analysis" "${STEP_STATUS:-unknown}" "${STEP_MESSAGE:-}"
                log_version_status "$clean_version" "autofix" "skipped_ai_only" "skip auto fix for AI-only analysis"

                ((processed_count++)) || true
                if [[ "$PROGRESS_INTERVAL" -gt 0 ]]; then
                    local CURRENT_TIME=$(date +%s)
                    local ELAPSED=$((CURRENT_TIME - ANALYSIS_START_TIME))
                    local INTERVAL_PASSED=$((CURRENT_TIME - LAST_PROGRESS_TIME))
                    if [[ $INTERVAL_PASSED -ge $PROGRESS_INTERVAL ]]; then
                        report_progress "$ELAPSED" "$clean_version" "$processed_count" "$version_count" "$success_count" "$fail_count"
                        LAST_PROGRESS_TIME=$CURRENT_TIME
                    fi
                fi
                continue
            fi

            # 步骤5: 安装包并分析崩溃
            if analyze_crashes_for_version "$PACKAGE" "$clean_version" "$filtered_csv"; then
                ((success_count++)) || true
            else
                ((fail_count++)) || true
            fi
            log_version_status "$clean_version" "analysis" "${STEP_STATUS:-unknown}" "${STEP_MESSAGE:-}"

            if auto_fix_and_submit_for_version "$PACKAGE" "$clean_version"; then
                ((success_count++)) || true
            else
                ((fail_count++)) || true
            fi
            log_version_status "$clean_version" "autofix" "${STEP_STATUS:-unknown}" "${STEP_MESSAGE:-}"

            echo ""

            # 进度上报
            ((processed_count++)) || true
            if [[ "$PROGRESS_INTERVAL" -gt 0 ]]; then
                local CURRENT_TIME=$(date +%s)
                local ELAPSED=$((CURRENT_TIME - ANALYSIS_START_TIME))
                local INTERVAL_PASSED=$((CURRENT_TIME - LAST_PROGRESS_TIME))
                if [[ $INTERVAL_PASSED -ge $PROGRESS_INTERVAL ]]; then
                    report_progress "$ELAPSED" "$clean_version" "$processed_count" "$version_count" "$success_count" "$fail_count"
                    LAST_PROGRESS_TIME=$CURRENT_TIME
                fi
            fi

        done < "$versions_txt"

        echo -e "${BLUE}════════════════════════════════════════════════════════════════════════${NC}"
        echo -e "${GREEN}所有版本分析完成${NC}"
        echo -e "${BLUE}════════════════════════════════════════════════════════════════════════${NC}"

        # 步骤6: 生成完整分析报告和AI分析报告
        echo ""
        echo -e "${YELLOW}━━━ 步骤6: 生成完整分析报告 ━━━${NC}"

        local full_report_script="$SKILLS_DIR/coredump-full-analysis/scripts/reporting/generate_full_report.py"
        local ai_report_script="$SKILLS_DIR/coredump-full-analysis/scripts/reporting/generate_ai_report.py"

        if [[ -f "$full_report_script" ]]; then
            python3 "$full_report_script" \
                --package "$PACKAGE" \
                --workspace "$WORKSPACE" 2>&1
        else
            echo -e "${YELLOW}⚠️ 完整报告生成脚本不存在: $full_report_script${NC}"
        fi

        if [[ -f "$ai_report_script" ]]; then
            python3 "$ai_report_script" \
                --package "$PACKAGE" \
                --workspace "$WORKSPACE" 2>&1
        else
            echo -e "${YELLOW}⚠️ AI分析报告生成脚本不存在: $ai_report_script${NC}"
        fi

        echo -e "${GREEN}✅ 分析报告已生成${NC}"

        # 步骤7: 生成统一的总结报告
        echo ""
        echo -e "${YELLOW}━━━ 步骤7: 生成总结报告 ━━━${NC}"

        # 生成 version_list.txt（从 crash_versions.txt 转换格式）
        local version_list_txt="$WORKSPACE/2.数据筛选/version_list.txt"
        if [[ -f "$versions_txt" ]]; then
            echo -e "${YELLOW}生成版本清单...${NC}"
            > "$version_list_txt"
            while IFS= read -r line; do
                [[ -z "$line" ]] && continue
                # 格式: 5.8.14-1:1101 -> 5.8.14-1|1101|medium
                version="${line%%:*}"
                count="${line##*:}"
                echo "${version}|${count}|medium" >> "$version_list_txt"
            done < "$versions_txt"
            echo -e "${GREEN}✅ 版本清单已生成: $version_list_txt${NC}"
        fi

        local final_report_script="$SKILLS_DIR/coredump-full-analysis/scripts/reporting/generate_final_report.py"
        if [[ -f "$final_report_script" ]]; then
            mkdir -p "$WORKSPACE/$SUMMARY_DIR_NAME"
            python3 "$final_report_script" \
                --package "$PACKAGE" \
                --workspace "$WORKSPACE" \
                --output-dir "$WORKSPACE/$SUMMARY_DIR_NAME" 2>&1 || true
            echo -e "${GREEN}✅ 总结报告已生成${NC}"
        else
            echo -e "${YELLOW}⚠️ 总结报告脚本不存在: $final_report_script${NC}"
        fi
    fi

    echo ""
    echo -e "${GREEN}"
    echo "============================================================================="
    echo "✅ 崩溃分析流程完成！"
    echo "============================================================================="
    echo -e "${NC}"
    echo "📊 统计报告: $WORKSPACE/2.数据筛选/${PACKAGE}_crash_statistics.json"
    echo "📋 筛选数据: $WORKSPACE/2.数据筛选/filtered_${PACKAGE}_crash_data.csv"
    echo "📄 分析报告: $WORKSPACE/$SUMMARY_DIR_NAME/"
    echo ""
}

# 运行
main "$@"

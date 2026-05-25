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

# Skills目录（脚本所在目录的父目录）
SKILLS_DIR="${SKILLS_DIR:-$HOME/.openclaw/skills/coredump-analysis-skills}"

# 脚本目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$SCRIPT_DIR/../config"
LOAD_ACCOUNTS_SCRIPT="$SCRIPT_DIR/load_accounts.sh"

source "$CONFIG_DIR/package-server.env" 2>/dev/null || true

# 默认值
PACKAGE="${PACKAGE:-}"
START_DATE="${START_DATE:-}"
END_DATE="${END_DATE:-}"
SYS_VERSION="${SYS_VERSION:-1070-1075}"
ARCH="${ARCH:-amd64}"  # 默认使用 amd64 架构
SELECTED_VERSIONS="${SELECTED_VERSIONS:-}"
WORKSPACE="${WORKSPACE:-}"
PROGRESS_INTERVAL="${PROGRESS_INTERVAL:-180}"  # 进度上报间隔（秒），0表示禁用
AUTO_FIX_SUBMIT="${AUTO_FIX_SUBMIT:-false}"
TARGET_BRANCH="${TARGET_BRANCH:-origin/develop/eagle}"
REVIEWERS=()
SUMMARY_DIR_NAME="6.总结报告"
VERSION_STATUS_FILE=""
STEP_STATUS=""
STEP_MESSAGE=""

generate_workspace_with_timestamp() {
    local root_dir="${1:-$HOME}"
    echo "$root_dir/coredump-workspace-$(date +%Y%m%d-%H%M%S)"
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
    load_accounts_or_die metabase gerrit shuttle system
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
           ~/.openclaw/skills/coredump-analysis-skills/accounts.json

${GREEN}选项:${NC}
    --packages <name>      包名（必需，文档推荐写法）
                           例如: dde-dock, dde-control-center, dde-launcher
    --package <name>       兼容旧参数，等价于 --packages
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
    --auto-fix-submit     分析后自动检查 target branch 是否已修复，并对已注册 fixer 的模式尝试自动提交
    --target-branch <br>  自动修复提交目标分支（默认: origin/develop/eagle）
    --reviewer <email>    自动提交时附加 reviewer，可多次指定
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
            --target-branch)
                TARGET_BRANCH="$2"
                shift 2
                ;;
            --reviewer)
                REVIEWERS+=("$2")
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

    # 获取用于崩溃搜索的包名（去掉base/前缀）
    local search_package=$(get_crash_search_name "$PACKAGE")

    # 直接使用原始脚本，不复制到workspace
    echo -e "${YELLOW}执行: bash $download_script${NC}" >&2
    echo "" >&2

    cd "$WORKSPACE/1.数据下载"
    local cmd=(bash "$download_script" --sys-version "$SYS_VERSION")
    [[ -n "$START_DATE" ]] && cmd+=(--start-date "$START_DATE")
    [[ -n "$END_DATE" ]] && cmd+=(--end-date "$END_DATE")
    cmd+=("$search_package" "$ARCH" crash)
    echo -e "${YELLOW}执行: ${cmd[*]}${NC}" >&2
    "${cmd[@]}" >&2

    # 根据 ARCH 参数确定CSV文件名中的架构后缀
    local csv_arch_suffix
    case "$ARCH" in
        x86) csv_arch_suffix="X86" ;;
        x86_64) csv_arch_suffix="X86" ;;
        arm|arm64|aarch64) csv_arch_suffix="AARCH64" ;;  # arm/arm64/aarch64 都使用 AARCH64 文件名后缀
        *) csv_arch_suffix="$ARCH" ;;
    esac

    # 查找下载的文件（使用搜索包名）
    local csv_file=$(find "$WORKSPACE/1.数据下载" -name "${search_package}_${csv_arch_suffix}_crash_*.csv" -type f | sort | tail -1)

    if [[ -z "$csv_file" ]]; then
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

    echo -e "${YELLOW}执行: python3 $filter_script --workspace $WORKSPACE $search_package${NC}" >&2
    echo "" >&2

    # 直接使用原始脚本，输出全部发送到 stderr
    cd "$WORKSPACE/2.数据筛选"
    python3 "$filter_script" --workspace "$WORKSPACE" "$search_package" >&2

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

# 步骤3: 代码管理 - 为每个崩溃版本切换代码分支
download_source() {
    print_step 3 "代码管理" >&2

    local filtered_csv="$1"
    local source_script="$SKILLS_DIR/coredump-code-management/scripts/download_crash_source.sh"

    if [[ ! -f "$source_script" ]]; then
        echo -e "${RED}错误: 代码管理脚本不存在: $source_script${NC}"
        return 1
    fi

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
            local version_with_count="${version_line}"
            local count="${version_with_count##*:}"  # 取最后一个冒号后面的内容
            local rest="${version_with_count%:*}"     # 去掉最后一个冒号及后面的内容
            # 如果还有冒号，说明有 epoch，去掉它
            local version="${rest#*:}"

            # 清理版本号（移除 epoch 前缀和 -1 后缀）
            local clean_version=$(echo "$version" | sed 's/^1://' | sed 's/-1$//')

            echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
            echo -e "${YELLOW}处理版本: $version -> $clean_version${NC}"
            echo ""

            # 设置环境变量并执行脚本
            if COREDUMP_WORKSPACE="$WORKSPACE" GERRIT_USER="$GERRIT_USER" GERRIT_HOST="${GERRIT_HOST:-gerrit.uniontech.com}" GERRIT_PORT="${GERRIT_PORT:-29418}" \
               bash "$source_script" "$PACKAGE" "$clean_version"; then
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

# 步骤3: 切换代码到指定版本
download_source_for_version() {
    local package="$1"
    local version="$2"
    local source_script="$SKILLS_DIR/coredump-code-management/scripts/download_crash_source.sh"

    if [[ ! -f "$source_script" ]]; then
        echo -e "${RED}错误: 代码管理脚本不存在: $source_script${NC}" >&2
        return 1
    fi

    echo -e "${YELLOW}━━━ 步骤3: 切换代码到 $version ━━━${NC}"

    # 设置环境变量并执行脚本
    if COREDUMP_WORKSPACE="$WORKSPACE" GERRIT_USER="$GERRIT_USER" GERRIT_HOST="${GERRIT_HOST:-gerrit.uniontech.com}" GERRIT_PORT="${GERRIT_PORT:-29418}" \
       bash "$source_script" "$package" "$version" >&2; then
        set_step_result "ok" "source checkout ready"
        echo -e "${GREEN}✅ 代码切换完成${NC}"
        return 0
    else
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

    # 创建下载目录
    mkdir -p "$dl_dir"

    # 清理版本号（用于下载）
    local clean_version=$(echo "$version" | sed 's/^1://' | sed 's/-1$//')

    if ! can_install_deb_packages; then
        echo -e "${YELLOW}⚠️ 未配置 sudo 密码且当前用户无免密 sudo，跳过 deb/dbgsym 下载${NC}"
        set_step_result "skipped_no_sudo" "no sudo capability, skip package download"
        return 0
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

    find "$dl_dir" -maxdepth 1 -type f \( \
        -name "${package}_${version}_${arch_suffix}.deb" -o \
        -name "${package}_${version}-*_${arch_suffix}.deb" -o \
        -name "${package}-${arch_suffix}_${version}_${arch_suffix}.deb" -o \
        -name "${package}_${version}-${arch_suffix}.deb" -o \
        -name "${package}_${version}+*.deb" -o \
        -name "${package}_${version}.*.deb" -o \
        -name "${package}-dbgsym_${version}_${arch_suffix}.deb" -o \
        -name "${package}-dbgsym_${version}-*_${arch_suffix}.deb" -o \
        -name "${package}-dbgsym_${version}-${arch_suffix}.deb" -o \
        -name "${package}-dbgsym_${version}+*.deb" -o \
        -name "${package}-dbgsym_${version}.*.deb" \
    \) 2>/dev/null | sort
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
    local analyze_script="$SKILLS_DIR/coredump-full-analysis/scripts/analyze_crash_per_version.py"
    local dl_dir="$WORKSPACE/4.包管理/downloads"
    local skip_file="$WORKSPACE/4.包管理/downloads/skipped_versions.txt"

    if [[ ! -f "$analyze_script" ]]; then
        echo -e "${RED}错误: 分析脚本不存在: $analyze_script${NC}" >&2
        set_step_result "failed_missing_script" "version analysis script missing"
        return 1
    fi

    echo -e "${YELLOW}━━━ 步骤5: 分析 $version 的崩溃 ━━━${NC}"

    # 清理版本号
    local clean_version=$(echo "$version" | sed 's/^1://' | sed 's/-1$//')

    # 检查是否该版本被跳过（deb包不存在）
    if [[ -f "$skip_file" ]] && grep -q "^$package $clean_version" "$skip_file" 2>/dev/null; then
        echo -e "${YELLOW}⚠️ 该版本 deb 包不存在，跳过安装，直接使用 AI 分析${NC}"
    else
        # 安装该版本的 deb 包（包括调试符号包 dbgsym）
        # 使用 find 避免 ls 在多文件时返回1的问题
        if [[ -d "$dl_dir" ]]; then
            local deb_files=$(find_deb_files_for_version "$dl_dir" "$package" "$clean_version" "$ARCH" || true)
            if [[ -n "$deb_files" ]]; then
                local can_install=false
                local use_expect=false
                local split_output=""
                local main_deb_files=""
                local dbgsym_deb_files=""
                local deb_file=""

                if [[ -n "$SUDO_PASSWORD" && "$SUDO_PASSWORD" != "null" && "$SUDO_PASSWORD" != "在此处输入"* ]]; then
                    can_install=true
                    use_expect=true
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
                            if [[ "$use_expect" == "true" ]]; then
                                # 使用 expect 自动输入密码，避免 sudo requiretty 问题
                                # 匹配中英文密码提示: "password" 或 "请输入密码"
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
                    done <<< "$main_deb_files"

                    while IFS= read -r deb_file; do
                        [[ -z "$deb_file" ]] && continue
                        if [[ -f "$deb_file" ]]; then
                            echo -e "  安装: $(basename "$deb_file")${NC}"
                            if [[ "$use_expect" == "true" ]]; then
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
                    done <<< "$dbgsym_deb_files"
                else
                    echo -e "${YELLOW}⚠️ 未配置 sudo 密码且当前用户无免密 sudo，跳过 deb 安装${NC}"
                fi
            fi
        fi
    fi

    # 执行分析（使用 analyze_crash_per_version.py 保存 JSON 报告）
    python3 "$analyze_script" \
        --package "$package" \
        --version "$clean_version" \
        --workspace "$WORKSPACE" \
        --max-crashes 50 2>&1 || true

    local version_dir="${clean_version//./_}"
    version_dir="${version_dir//+/_}"
    version_dir="${version_dir//-/_}"
    local analysis_json="$WORKSPACE/5.崩溃分析/$package/version_${version_dir}/analysis.json"

    if [[ -f "$analysis_json" ]]; then
        set_step_result "ok" "analysis.json generated"
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

    # 2. 检查配置完整性
    check_config

    # 3. 检查依赖
    check_dependencies

    # 4. 创建工作目录
    setup_workspace
    init_status_files

    # 5. 执行分析步骤
    # 步骤1+2: 数据下载和筛选（只执行一次）
    local csv_file=$(download_data)
    local filtered_csv=$(filter_data "$csv_file")

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
            fi
            log_version_status "$clean_version" "source" "${STEP_STATUS:-unknown}" "${STEP_MESSAGE:-}"

            # 步骤4: 下载该版本的包
            if download_packages_for_version "$PACKAGE" "$clean_version"; then
                ((success_count++)) || true
            else
                ((fail_count++)) || true
            fi
            log_version_status "$clean_version" "package" "${STEP_STATUS:-unknown}" "${STEP_MESSAGE:-}"

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

        local full_report_script="$SKILLS_DIR/coredump-full-analysis/scripts/generate_full_report.py"
        local ai_report_script="$SKILLS_DIR/coredump-full-analysis/scripts/generate_ai_report.py"

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

        local final_report_script="$SKILLS_DIR/coredump-full-analysis/scripts/generate_final_report.py"
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

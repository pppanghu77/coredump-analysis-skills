#!/bin/bash
#=============================================================================
# dde-session-ui 崩溃分析循环流程 - 主入口脚本
# 功能：协调执行完整的崩溃分析循环流程，包括下载、筛选、循环分析各版本
#=============================================================================

set -e

# 配色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Skills目录
SKILLS_DIR="${SKILLS_DIR:-$SCRIPT_DIR/../..}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOAD_ACCOUNTS_SCRIPT="$SCRIPT_DIR/load_accounts.sh"
source "$SCRIPT_DIR/../config/loop.env" 2>/dev/null || true

# 默认值
PACKAGE="${PACKAGE:-}"
START_DATE="${START_DATE:-}"
END_DATE="${END_DATE:-}"
SYS_VERSION="${SYS_VERSION:-1070-1075}"
WORKSPACE="${WORKSPACE:-}"
MIN_CRASH_COUNT="${MIN_CRASH_COUNT:-5}"
AUTO_SUBMIT_GERRIT="${AUTO_SUBMIT_GERRIT:-false}"
CONTINUE_FROM="${CONTINUE_FROM:-}"
REANALYZE="${REANALYZE:-false}"

# 帮助信息
show_help() {
    cat << EOF
${BLUE}=============================================================================
  dde-session-ui 崩溃分析循环流程
=============================================================================${NC}

${GREEN}用法:${NC}
    $0 [选项]

${GREEN}选项:${NC}
    --package <name>       包名（必需）
                           例如: dde-session-ui
    --start-date <date>   开始日期（格式: YYYY-MM-DD；默认不限制）
                           例如: 2026-04-01
    --end-date <date>     结束日期（格式: YYYY-MM-DD；默认不限制）
                           例如: 2026-04-08
    --sys-version <ver>   系统版本范围（默认: 1070-1075）
                           例如: 1070, 1070-1075
    --workspace <dir>      工作目录（默认: ./workspace）
    --min-crash-count <n> 最小崩溃次数阈值（默认: 5）
    --auto-submit-gerrit  自动提交到Gerrit（默认: false）
    --continue-from <ver> 从指定版本继续
    --reanalyze           重新分析所有版本（清除已分析标记）
    --help, -h            显示此帮助信息

${GREEN}示例:${NC}
    # 分析所有能下载的dde-session-ui崩溃
    $0 --package dde-session-ui --workspace /path/to/workspace

    # 从指定版本继续分析
    $0 --package dde-session-ui --continue-from "5.8.32"

    # 自动提交到Gerrit
    $0 --package dde-session-ui --auto-submit-gerrit

${BLUE}=============================================================================
${NC}
EOF
}

# 解析参数
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
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
            --workspace)
                WORKSPACE="$2"
                shift 2
                ;;
            --min-crash-count)
                MIN_CRASH_COUNT="$2"
                shift 2
                ;;
            --auto-submit-gerrit)
                AUTO_SUBMIT_GERRIT="true"
                shift
                ;;
            --continue-from)
                CONTINUE_FROM="$2"
                shift 2
                ;;
            --reanalyze)
                REANALYZE="true"
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
    if [[ -z "$PACKAGE" ]]; then
        echo -e "${RED}错误: 必须指定 --package 参数${NC}"
        show_help
        exit 1
    fi

}

# 打印进度
print_phase() {
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${MAGENTA}阶段 $1: $2${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# 打印步骤
print_step() {
    echo -e "${CYAN}  [$1] $2${NC}"
}

# 检查依赖
check_dependencies() {
    print_step "检查" "依赖环境..."

    local deps=("curl" "jq" "python3" "git" "ssh")
    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &> /dev/null; then
            echo -e "${RED}    错误: 缺少依赖 '$dep'${NC}"
            exit 1
        fi
    done

    # 检查SSH密钥
    if [[ -n "$GERRIT_SSH_KEY" ]] && [[ ! -f "$GERRIT_SSH_KEY" ]]; then
        echo -e "${YELLOW}    警告: SSH密钥 $GERRIT_SSH_KEY 不存在${NC}"
        echo "    Gerrit克隆可能需要手动配置SSH密钥"
    fi

    echo -e "${GREEN}    ✅ 依赖检查完成${NC}"
}

load_required_accounts() {
    print_step "检查" "账号配置..."

    if [[ ! -f "$LOAD_ACCOUNTS_SCRIPT" ]]; then
        echo -e "${RED}    错误: 账号加载脚本不存在: $LOAD_ACCOUNTS_SCRIPT${NC}"
        exit 1
    fi

    source "$LOAD_ACCOUNTS_SCRIPT"
    load_accounts_or_die metabase gerrit shuttle system
    if [[ -z "$WORKSPACE" ]] || [[ "$WORKSPACE" == "./workspace" ]]; then
        local workspace_root="${ACCOUNTS_WORKSPACE_ROOT:-$HOME}"
        [[ -z "$workspace_root" ]] && workspace_root="$HOME"
        WORKSPACE="$workspace_root/coredump-workspace-$(date +%Y%m%d-%H%M%S)"
    fi
    echo -e "${GREEN}    ✅ 已从 accounts.json 加载账号配置${NC}"
}

# 创建工作目录
setup_workspace() {
    print_step "准备" "工作目录..."

    mkdir -p "$WORKSPACE"/{1.数据下载,2.数据筛选,3.代码管理,4.包管理/下载包,5.崩溃分析,final_report}

    echo -e "${GREEN}    ✅ 工作目录已创建: $WORKSPACE${NC}"
}

# 阶段1: 准备工作
phase1_prepare() {
    print_phase "1" "准备工作（一次性执行）"

    local skills_dir="$SKILLS_DIR"

    # 1.1 下载数据
    print_step "1.1" "下载崩溃数据..."
    local download_script="$skills_dir/coredump-data-download/scripts/download_metabase_csv.sh"
    # 如果存在fixed版本，优先使用
    local download_script_fixed="$skills_dir/coredump-data-download/scripts/download_metabase_csv_fixed.sh"
    if [[ -f "$download_script_fixed" ]]; then
        download_script="$download_script_fixed"
    fi
    if [[ ! -f "$download_script" ]]; then
        echo -e "${RED}    错误: 下载脚本不存在: $download_script${NC}"
        exit 1
    fi
    cp "$download_script" "$WORKSPACE/1.数据下载/download_metabase_csv.sh"
    chmod +x "$WORKSPACE/1.数据下载/download_metabase_csv.sh"

    cd "$WORKSPACE/1.数据下载"
    local cmd="./download_metabase_csv.sh"
    [[ -n "$START_DATE" ]] && cmd="$cmd --start-date $START_DATE"
    [[ -n "$END_DATE" ]] && cmd="$cmd --end-date $END_DATE"
    [[ -n "$SYS_VERSION" ]] && cmd="$cmd --sys-version $SYS_VERSION"
    # 根据 ARCH 参数确定架构
    local download_arch
    case "$ARCH" in
        x86) download_arch="x86" ;;
        x86_64) download_arch="x86_64" ;;
        arm|arm64) download_arch="aarch64" ;;  # arm/arm64 映射到 aarch64 下载
        *) download_arch="$ARCH" ;;
    esac
    cmd="$cmd $PACKAGE $download_arch crash"

    echo -e "${YELLOW}    执行: $cmd${NC}"
    eval "$cmd"

    # 获取绝对路径
    local workspace_abs=$(cd "$WORKSPACE" 2>/dev/null || cd "$(pwd)/$WORKSPACE" && pwd)
    # 根据 ARCH 参数确定CSV文件名中的架构后缀
    local csv_arch_suffix
    case "$download_arch" in
        x86) csv_arch_suffix="X86" ;;
        x86_64) csv_arch_suffix="X86" ;;
        arm|arm64|aarch64) csv_arch_suffix="AARCH64" ;;  # arm/arm64/aarch64 都使用 AARCH64 文件名后缀
        *) csv_arch_suffix="$download_arch" ;;
    esac
    local csv_file=$(find "$workspace_abs" -path "*/1.数据下载/*" -name "${PACKAGE}_${csv_arch_suffix}_crash_*.csv" -o -name "${PACKAGE}_X86_64_crash_*.csv" -type f 2>/dev/null | sort | tail -1)
    if [[ -z "$csv_file" ]]; then
        echo -e "${RED}    错误: 数据下载失败，未找到CSV文件${NC}"
        exit 1
    fi
    echo -e "${GREEN}    ✅ 数据下载完成: $csv_file${NC}"

    # 1.2 筛选去重
    print_step "1.2" "筛选去重崩溃数据..."
    local filter_script="$skills_dir/coredump-data-filter/scripts/filter_crash_data.py"
    if [[ ! -f "$filter_script" ]]; then
        echo -e "${RED}    错误: 筛选脚本不存在: $filter_script${NC}"
        exit 1
    fi
    cp "$filter_script" "$WORKSPACE/2.数据筛选/"
    chmod +x "$WORKSPACE/2.数据筛选/filter_crash_data.py"

    # 修改脚本中的WORKSPACE路径
    sed -i "s|WORKSPACE = \"/home/wubw/Desktop/coredump/workspace\"|WORKSPACE = \"$WORKSPACE\"|g" \
        "$WORKSPACE/2.数据筛选/filter_crash_data.py"

    cd "$WORKSPACE/2.数据筛选"
    python3 filter_crash_data.py "$PACKAGE"

    local filtered_csv="$WORKSPACE/2.数据筛选/filtered_${PACKAGE}_crash_data.csv"
    if [[ ! -f "$filtered_csv" ]]; then
        echo -e "${RED}    错误: 数据筛选失败${NC}"
        exit 1
    fi
    echo -e "${GREEN}    ✅ 数据筛选完成${NC}"

    # 1.3 生成版本清单
    print_step "1.3" "生成版本清单..."
    if [[ -f "$SCRIPT_DIR/reporting/generate_version_list.py" ]]; then
        cp "$SCRIPT_DIR/reporting/generate_version_list.py" "$WORKSPACE/2.数据筛选/"
        chmod +x "$WORKSPACE/2.数据筛选/generate_version_list.py"
        cd "$WORKSPACE/2.数据筛选"
        python3 generate_version_list.py \
            "${PACKAGE}_crash_statistics.json" \
            "version_list.txt" \
            --min-crash-count "$MIN_CRASH_COUNT"

        if [[ ! -f "version_list.txt" ]]; then
            echo -e "${RED}    错误: 版本清单生成失败${NC}"
            exit 1
        fi
        echo -e "${GREEN}    ✅ 版本清单已生成: version_list.txt${NC}"

        # 显示版本清单
        echo ""
        echo -e "${CYAN}    版本清单:${NC}"
        cat "version_list.txt"
    else
        echo -e "${YELLOW}    警告: generate_version_list.py 不存在，跳过版本清单生成${NC}"
    fi

    # 1.4 下载所有版本的deb/dbgsym包
    print_step "1.4" "下载所有版本的deb/dbgsym包..."

    # 使用新的批量下载脚本
    local batch_download_script="$SCRIPT_DIR/download_all_version_packages.sh"
    if [[ -f "$batch_download_script" ]]; then
        cp "$batch_download_script" "$WORKSPACE/"
        chmod +x "$WORKSPACE/download_all_version_packages.sh"

        cd "$DOWNLOAD_DIR"
        echo -e "${CYAN}    开始批量下载包...${NC}"
        bash "$WORKSPACE/download_all_version_packages.sh" "$WORKSPACE" "$PACKAGE"
        echo -e "${GREEN}    ✅ 包下载完成${NC}"
    else
        echo -e "${YELLOW}    警告: 批量下载脚本不存在，跳过包下载${NC}"
    fi

    # 1.5 克隆代码仓库（仅克隆master）
    print_step "1.5" "克隆代码仓库..."
    local source_script="$skills_dir/coredump-code-management/scripts/download_crash_source.sh"
    if [[ -f "$source_script" ]]; then
        cp "$source_script" "$WORKSPACE/3.代码管理/"
        chmod +x "$WORKSPACE/3.代码管理/download_crash_source.sh"

        cd "$WORKSPACE/3.代码管理"

        # 检查是否已克隆
        if [[ -d "$PACKAGE" ]]; then
            echo -e "${GREEN}    ✅ 代码仓库已存在: $PACKAGE${NC}"
        else
            # 克隆仓库
            local gerrit_user="${GERRIT_USER}"
            local gerrit_host="${GERRIT_HOST:-gerrit.uniontech.com}"
            local gerrit_port="${GERRIT_PORT:-29418}"

            echo -e "${YELLOW}    克隆仓库: ssh://${gerrit_user}@${gerrit_host}:${gerrit_port}/${PACKAGE}${NC}"
            git clone "ssh://${gerrit_user}@${gerrit_host}:${gerrit_port}/${PACKAGE}" 2>/dev/null || {
                echo -e "${YELLOW}    警告: 克隆失败，请手动克隆或检查SSH配置${NC}"
                echo -e "${YELLOW}    提示：请确认是否已将 ~/.ssh/id_rsa.pub 配置到 Gerrit 的设置-\"SSH Keys\" 里面${NC}"
            }

            if [[ -d "$PACKAGE/.git" ]]; then
                # 配置hooks
                scp -p -P $gerrit_port ${gerrit_user}@${gerrit_host}:hooks/commit-msg "$PACKAGE/.git/hooks/" 2>/dev/null || true
                echo -e "${GREEN}    ✅ 代码仓库克隆完成${NC}"
            fi
        fi
    else
        echo -e "${YELLOW}    警告: download_crash_source.sh 不存在，跳过代码克隆${NC}"
    fi
}

# 阶段2: 循环分析各版本
phase2_loop_analyze() {
    print_phase "2" "循环分析各版本"

    local version_list="$WORKSPACE/2.数据筛选/version_list.txt"
    local analyzed_file="$WORKSPACE/analyzed_versions.txt"

    if [[ ! -f "$version_list" ]]; then
        echo -e "${RED}    错误: 版本清单不存在: $version_list${NC}"
        exit 1
    fi

    # 复制相关脚本到工作区
    if [[ -f "$SCRIPT_DIR/sync_version.sh" ]]; then
        cp "$SCRIPT_DIR/sync_version.sh" "$WORKSPACE/"
        chmod +x "$WORKSPACE/sync_version.sh"
    fi
    if [[ -f "$SCRIPT_DIR/install_package.sh" ]]; then
        cp "$SCRIPT_DIR/install_package.sh" "$WORKSPACE/"
        chmod +x "$WORKSPACE/install_package.sh"
    fi
    if [[ -f "$SCRIPT_DIR/analyze_single_version.sh" ]]; then
        cp "$SCRIPT_DIR/analyze_single_version.sh" "$WORKSPACE/"
        chmod +x "$WORKSPACE/analyze_single_version.sh"
    fi
    if [[ -f "$SCRIPT_DIR/analyze_crash_per_version.py" ]]; then
        cp "$SCRIPT_DIR/analyze_crash_per_version.py" "$WORKSPACE/"
        chmod +x "$WORKSPACE/analyze_crash_per_version.py"
    fi
    if [[ -f "$SCRIPT_DIR/submit_to_gerrit.sh" ]]; then
        cp "$SCRIPT_DIR/submit_to_gerrit.sh" "$WORKSPACE/"
        chmod +x "$WORKSPACE/submit_to_gerrit.sh"
    fi
    if [[ -f "$SCRIPT_DIR/reporting/generate_issue_doc.py" ]]; then
        cp "$SCRIPT_DIR/reporting/generate_issue_doc.py" "$WORKSPACE/"
        chmod +x "$WORKSPACE/generate_issue_doc.py"
    fi
    if [[ -f "$SCRIPT_DIR/create_patch.sh" ]]; then
        cp "$SCRIPT_DIR/create_patch.sh" "$WORKSPACE/"
        chmod +x "$WORKSPACE/create_patch.sh"
    fi

    # 统计信息
    local total_versions=$(grep -v '^#' "$version_list" | grep -v '^$' | wc -l)
    local current_version=0
    local start_analyzing=false

    # 如果设置了reanalyze，清除 analyzed_versions.txt
    if [[ "$REANALYZE" = true ]]; then
        if [[ -f "$analyzed_file" ]]; then
            echo -e "${YELLOW}  重新分析模式：清除已分析标记${NC}"
            rm -f "$analyzed_file"
        fi
    fi

    echo -e "${CYAN}    共发现 $total_versions 个版本需要分析${NC}"
    echo ""

    # 遍历版本清单
    while IFS='|' read -r version count priority; do
        # 跳过注释和空行
        [[ "$version" =~ ^#.*$ ]] && continue
        [[ -z "$version" ]] && continue

        # 如果指定了继续版本，跳过之前已分析的
        if [[ -n "$CONTINUE_FROM" ]] && [[ "$start_analyzing" = false ]]; then
            if [[ "$version" == "$CONTINUE_FROM" ]]; then
                start_analyzing=true
            else
                continue
            fi
        fi

        current_version=$((current_version + 1))
        version_clean=$(echo "$version" | sed 's/^1://' | sed 's/-1$//')
        version_dir=$(echo "$version_clean" | sed 's/\./_/g' | sed 's/+/_/g' | sed 's/-/_/g')

        echo -e "${MAGENTA}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${CYAN}  [$current_version/$total_versions] 分析版本: ${version} (崩溃次数: ${count}, 优先级: ${priority})${NC}"
        echo -e "${MAGENTA}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

        # 检查是否已经分析过
        if [[ -f "$analyzed_file" ]] && grep -q "^$version$" "$analyzed_file"; then
            echo -e "${YELLOW}    版本 $version 已分析过，跳过${NC}"
            echo ""
            continue
        fi

        # 分析单个版本
        if [[ -f "$WORKSPACE/analyze_single_version.sh" ]]; then
            [[ "$AUTO_SUBMIT_GERRIT" = "true" ]] && bash "$WORKSPACE/analyze_single_version.sh" --package "$PACKAGE" --version "$version" --workspace "$WORKSPACE" --auto-submit-gerrit || bash "$WORKSPACE/analyze_single_version.sh" --package "$PACKAGE" --version "$version" --workspace "$WORKSPACE"

            if [[ $? -eq 0 ]]; then
                echo -e "${GREEN}    ✅ 版本 $version 分析完成${NC}"
                echo "$version" >> "$analyzed_file"
            else
                echo -e "${RED}    ❌ 版本 $version 分析失败${NC}"
            fi
        else
            echo -e "${RED}    错误: analyze_single_version.sh 不存在${NC}"
        fi

        echo ""
    done < "$version_list"

    echo -e "${GREEN}    ✅ 循环分析完成，共分析了 $current_version 个版本${NC}"
}

# 阶段3: 生成最终报告
phase3_generate_report() {
    print_phase "3" "生成最终报告"

    if [[ -f "$SCRIPT_DIR/reporting/generate_final_report.py" ]]; then
        cp "$SCRIPT_DIR/reporting/generate_final_report.py" "$WORKSPACE/"
        chmod +x "$WORKSPACE/generate_final_report.py"

        cd "$WORKSPACE"
        local cmd=(python3 generate_final_report.py
            --workspace "$WORKSPACE"
            --package "$PACKAGE")
        [[ -n "$START_DATE" ]] && cmd+=(--start-date "$START_DATE")
        [[ -n "$END_DATE" ]] && cmd+=(--end-date "$END_DATE")
        "${cmd[@]}"

        echo -e "${GREEN}    ✅ 最终报告已生成: $WORKSPACE/final_report/final_conclusion.md${NC}"
    else
        echo -e "${YELLOW}    警告: generate_final_report.py 不存在，跳过报告生成${NC}"
    fi
}

# 主函数
main() {
    echo -e "${BLUE}"
    echo "============================================================================="
    echo "            dde-session-ui 崩溃分析循环流程"
    echo "============================================================================="
    echo -e "${NC}"

    parse_args "$@"
    load_required_accounts
    check_dependencies
    setup_workspace

    echo ""
    echo -e "${CYAN}配置信息:${NC}"
    echo -e "  包名: ${PACKAGE}"
    echo -e "  工作目录: ${WORKSPACE}"
    if [[ -z "$START_DATE" && -z "$END_DATE" ]]; then
        echo -e "  日期范围: 全部可下载数据（不按日期过滤）"
    elif [[ -n "$START_DATE" && -n "$END_DATE" ]]; then
        echo -e "  日期范围: ${START_DATE} 至 ${END_DATE}"
    elif [[ -n "$START_DATE" ]]; then
        echo -e "  日期范围: ${START_DATE} 至 最新可下载"
    else
        echo -e "  日期范围: 最早可下载 至 ${END_DATE}"
    fi
    echo -e "  最小崩溃次数: ${MIN_CRASH_COUNT}"
    echo -e "  自动提交Gerrit: ${AUTO_SUBMIT_GERRIT}"
    echo ""

    # 执行三个阶段
    phase1_prepare
    phase2_loop_analyze
    phase3_generate_report

    echo ""
    echo -e "${GREEN}"
    echo "============================================================================="
    echo "✅ 崩溃分析流程完成！"
    echo "============================================================================="
    echo -e "${NC}"
    echo -e "${CYAN}输出文件:${NC}"
    echo -e "  版本清单: $WORKSPACE/2.数据筛选/version_list.txt"
    echo -e "  筛选数据: $WORKSPACE/2.数据筛选/filtered_${PACKAGE}_crash_data.csv"
    echo -e "  版本分析: $WORKSPACE/5.崩溃分析/"
    echo -e "  最终报告: $WORKSPACE/final_report/final_conclusion.md"
    echo ""
}

# 运行
main "$@"

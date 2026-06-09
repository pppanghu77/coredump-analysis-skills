#!/bin/bash
#=============================================================================
# 崩溃源码下载脚本
# 功能：根据崩溃数据文件中的包名和版本号，下载对应版本的源代码
# 使用方法：
#   ./download_crash_source.sh <崩溃数据文件路径> [行号]
#   如果不指定行号，默认处理第一行（跳过表头）
#
# 改进：
#   - 所有 git 操作使用绝对路径，不依赖当前目录
#   - 版本切换逻辑：精确匹配 -> 模糊匹配；找不到 tag 时失败，避免源码版本失真
#   - 添加 git fetch 失败重试
#=============================================================================

set -e

# 配色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# 配置 - 默认使用当前目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${COREDUMP_WORKSPACE:-$SCRIPT_DIR/../../..}"
CODE_DIR="${WORKSPACE}/3.代码管理"
LOAD_ACCOUNTS_SCRIPT="$SCRIPT_DIR/../../coredump-full-analysis/scripts/load_accounts.sh"
source "$LOAD_ACCOUNTS_SCRIPT"
load_accounts_or_die gerrit
GERRIT_HOST="${GERRIT_HOST:-gerrit.uniontech.com}"
GERRIT_PORT="${GERRIT_PORT:-29418}"
GIT_SSH_COMMAND_DEFAULT="ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=8"

# 解析参数
CRASH_DATA_FILE="$1"
LINE_NUM="${2:-2}"  # 默认第2行（跳过表头）

show_help() {
    cat << EOF
${BLUE}=============================================================================
崩溃源码下载工具${NC}

${GREEN}用法:${NC}
    $0 <崩溃数据文件路径> [行号]
    $0 <package> <version>

${GREEN}示例:${NC}
    $0 /path/to/filtered_crash_data.csv 2
    $0 dde-launcher 5.6.15.1-1

${BLUE}=============================================================================${NC}
EOF
}

# 检查参数
if [ -z "$1" ]; then
    show_help
    exit 1
fi

# 支持两种调用方式
if [ -f "$1" ]; then
    # 方式1：从崩溃数据文件读取
    CRASH_DATA_FILE="$1"

    if [ ! -f "$CRASH_DATA_FILE" ]; then
        echo -e "${RED}错误：文件不存在: $CRASH_DATA_FILE${NC}"
        exit 1
    fi

    echo "=========================================="
    echo "崩溃源码下载工具"
    echo "=========================================="
    echo "工作目录: $WORKSPACE"
    echo "代码目录: $CODE_DIR"

    # 读取指定行的数据
    echo ""
    echo "正在读取崩溃数据文件..."
    CRASH_LINE=$(sed -n "${LINE_NUM}p" "$CRASH_DATA_FILE")

    if [ -z "$CRASH_LINE" ]; then
        echo -e "${RED}错误：第 $LINE_NUM 行没有数据${NC}"
        exit 1
    fi

    # 解析包名和版本号
    PACKAGE=$(echo "$CRASH_LINE" | cut -d',' -f2)
    VERSION=$(echo "$CRASH_LINE" | cut -d',' -f1)
else
    # 方式2：直接指定包名和版本
    PACKAGE="$1"
    VERSION="$2"
fi

if [ -z "$PACKAGE" ] || [ -z "$VERSION" ]; then
    echo -e "${RED}错误：包名和版本不能为空${NC}"
    show_help
    exit 1
fi

# 清理版本号
VERSION_CLEAN=$(echo "$VERSION" | sed 's/^1://' | sed 's/-1$//')

echo ""
echo "崩溃信息："
echo "   包名: $PACKAGE"
echo "   完整版本: $VERSION"
echo "   清理版本: $VERSION_CLEAN"
echo ""

# 确保代码目录存在
if [ ! -d "$CODE_DIR" ]; then
    echo "创建代码管理目录: $CODE_DIR"
    mkdir -p "$CODE_DIR"
fi

CODE_PATH="$CODE_DIR/$PACKAGE"

# --------------------
# 下载或更新代码仓库
# --------------------
if [ -d "$CODE_PATH/.git" ]; then
    echo -e "${CYAN}[1] 代码已存在，更新仓库...${NC}"

    # 使用绝对路径更新
    GIT_SSH_COMMAND="$GIT_SSH_COMMAND_DEFAULT" git -C "$CODE_PATH" fetch --tags origin 2>/dev/null || {
        echo -e "${YELLOW}  git fetch 失败，尝试重试...${NC}"
        sleep 2
        GIT_SSH_COMMAND="$GIT_SSH_COMMAND_DEFAULT" git -C "$CODE_PATH" fetch --tags origin 2>/dev/null || true
    }
else
    echo -e "${CYAN}[1] 下载源代码...${NC}"

    # 克隆仓库
    if GIT_SSH_COMMAND="$GIT_SSH_COMMAND_DEFAULT" git clone "ssh://${GERRIT_USER}@${GERRIT_HOST}:${GERRIT_PORT}/${PACKAGE}" "$CODE_PATH" 2>/dev/null; then
        echo -e "${GREEN}  克隆成功${NC}"

        # 配置 commit-msg hooks
        echo "  配置 commit-msg hooks..."
        scp -p -P $GERRIT_PORT ${GERRIT_USER}@${GERRIT_HOST}:hooks/commit-msg "$CODE_PATH/.git/hooks/" 2>/dev/null || {
            echo -e "${YELLOW}  警告：复制 hooks 失败${NC}"
        }
    else
        echo -e "${YELLOW}  Gerrit 克隆失败，尝试 GitHub 镜像...${NC}"
        echo -e "${YELLOW}  请确认是否已将 ~/.ssh/id_rsa.pub 配置到 Gerrit 的设置-\"SSH Keys\" 里面${NC}"
        if git clone "https://github.com/linuxdeepin/${PACKAGE}.git" "$CODE_PATH" 2>/dev/null; then
            echo -e "${GREEN}  GitHub 镜像克隆成功${NC}"
        else
            echo -e "${RED}错误：克隆代码失败${NC}"
            echo -e "${YELLOW}提示：如果 Gerrit 无法访问，请检查是否已将 ~/.ssh/id_rsa.pub 配置到 Gerrit 的设置-\"SSH Keys\" 里面${NC}"
            exit 1
        fi
    fi
fi

# --------------------
# 切换到对应版本
# --------------------
echo ""
echo -e "${CYAN}[2] 切换到版本分支${NC}"

cd "$CODE_PATH"

# 尝试查找精确匹配的 tag
CHECKOUT_TAG=""
CHECKOUT_METHOD=""

# 1. 精确匹配
if git -C "$CODE_PATH" tag | grep -qE "^${VERSION_CLEAN}$"; then
    CHECKOUT_TAG="$VERSION_CLEAN"
    CHECKOUT_METHOD="精确匹配"
fi

# 2. 模糊匹配
if [ -z "$CHECKOUT_TAG" ]; then
    MATCHING_TAG=$(git -C "$CODE_PATH" tag | grep -E "^${VERSION_CLEAN}" | sort -V | tail -1)
    if [ -n "$MATCHING_TAG" ]; then
        CHECKOUT_TAG="$MATCHING_TAG"
        CHECKOUT_METHOD="模糊匹配"
    fi
fi

if [ -n "$CHECKOUT_TAG" ]; then
    echo -e "  切换方式: ${GREEN}$CHECKOUT_METHOD${NC}"
    echo -e "  目标版本: ${GREEN}$CHECKOUT_TAG${NC}"

    # 创建新分支并切换
    FIX_BRANCH="${PACKAGE}-${VERSION_CLEAN}"
    echo -e "  创建分支: ${YELLOW}$FIX_BRANCH${NC}"

    if git -C "$CODE_PATH" checkout -b "$FIX_BRANCH" "$CHECKOUT_TAG" 2>/dev/null; then
        echo -e "  ${GREEN}✅ 分支创建成功${NC}"

        # 硬重置到版本标签，确保代码与版本完全一致
        echo -e "  执行: git reset --hard $CHECKOUT_TAG"
        if git -C "$CODE_PATH" reset --hard "$CHECKOUT_TAG" 2>/dev/null; then
            echo -e "  ${GREEN}✅ 代码重置成功${NC}"
        else
            echo -e "  ${YELLOW}⚠️ 代码重置失败，使用当前状态${NC}"
        fi
    else
        # 分支可能已存在，尝试切换并重置
        echo -e "  ${YELLOW}分支已存在，尝试切换...${NC}"
        if git -C "$CODE_PATH" checkout "$FIX_BRANCH" 2>/dev/null && \
           git -C "$CODE_PATH" reset --hard "$CHECKOUT_TAG" 2>/dev/null; then
            echo -e "  ${GREEN}✅ 切换并重置成功${NC}"
        else
            echo -e "  ${RED}❌ 切换失败${NC}"
            exit 1
        fi
    fi
else
    echo -e "${RED}  ❌ 未找到匹配的 tag: $VERSION_CLEAN${NC}"
    echo -e "${YELLOW}  为避免源码版本与 coredump 不一致，停止当前版本分析${NC}"
    exit 2
fi

# 显示当前信息
echo ""
echo "=========================================="
echo "完成！"
echo "=========================================="
echo "代码目录: $CODE_PATH"
echo "当前版本: $(git -C "$CODE_PATH" describe --tags --exact-match 2>/dev/null || echo 'N/A')"
echo "当前分支: $(git -C "$CODE_PATH" branch --show-current 2>/dev/null || echo 'detached')"
echo "=========================================="
echo ""

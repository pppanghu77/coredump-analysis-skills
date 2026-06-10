#!/usr/bin/env bash
set -euo pipefail

# 下载 dde-file-manager 崩溃数据（全架构）
# 依赖: coredump-data-download/scripts/download_metabase_csv.sh
#        accounts.json (Metabase 认证)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DOWNLOAD_SCRIPT="$SKILLS_ROOT/coredump-data-download/scripts/download_metabase_csv.sh"

PACKAGE="dde-file-manager"
SYS_VERSION=""
START_DATE=""
END_DATE=""
OUTPUT_DIR=""

usage() {
    cat <<EOF
用法: $0 [选项]

选项:
  --sys-version N      系统版本号过滤 (如 1075)
  --start-date YYYY-MM-DD  开始日期
  --end-date YYYY-MM-DD    结束日期
  --output-dir DIR     输出目录 (默认: 自动创建 download_<timestamp>/)
  -h, --help           显示帮助

说明:
  下载 dde-file-manager 全架构崩溃数据（不区分架构过滤）。
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sys-version)
            SYS_VERSION="${2:-}"; shift 2 ;;
        --start-date)
            START_DATE="${2:-}"; shift 2 ;;
        --end-date)
            END_DATE="${2:-}"; shift 2 ;;
        --output-dir)
            OUTPUT_DIR="${2:-}"; shift 2 ;;
        -h|--help)
            usage; exit 0 ;;
        *)
            echo "未知选项: $1"; usage; exit 1 ;;
    esac
done

if [[ -z "$SYS_VERSION" ]]; then
    echo "错误: 必须指定 --sys-version"
    exit 1
fi
if [[ -z "$START_DATE" || -z "$END_DATE" ]]; then
    echo "错误: 必须指定 --start-date 和 --end-date"
    exit 1
fi
if [[ ! -f "$DOWNLOAD_SCRIPT" ]]; then
    echo "错误: 找不到下载脚本 $DOWNLOAD_SCRIPT"
    exit 1
fi

TS="${START_DATE//-/}_${END_DATE//-/}"
if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="$SCRIPT_DIR/../data/download_${TS}"
fi
mkdir -p "$OUTPUT_DIR"

echo "=========================================="
echo "dde-file-manager 崩溃数据下载"
echo "=========================================="
echo "系统版本: $SYS_VERSION"
echo "日期范围: $START_DATE ~ $END_DATE"
echo "架构: 全架构"
echo "输出目录: $OUTPUT_DIR"
echo ""

# 去掉代理，Metabase 是内网服务
unset https_proxy http_proxy HTTPS_PROXY HTTP_PROXY

bash "$DOWNLOAD_SCRIPT" \
    --sys-version "$SYS_VERSION" \
    --start-date "$START_DATE" \
    --end-date "$END_DATE" \
    --output-dir "$OUTPUT_DIR" \
    --file-date "${START_DATE//-/}_${END_DATE//-/}" \
    "$PACKAGE" "all" crash

# 找到下载的 CSV
DOWNLOADED_CSV="$(ls -t "$OUTPUT_DIR"/*.csv 2>/dev/null | head -1)"

if [[ -z "$DOWNLOADED_CSV" || ! -f "$DOWNLOADED_CSV" ]]; then
    echo "错误: 下载失败，未生成 CSV 文件"
    exit 1
fi

lines=$(wc -l < "$DOWNLOADED_CSV")
echo ""
echo "=========================================="
echo "下载完成"
echo "文件: $DOWNLOADED_CSV"
echo "行数: $lines (含表头)"
echo "=========================================="

# 输出最终 CSV 路径供后续步骤使用
echo "$DOWNLOADED_CSV" > "$OUTPUT_DIR/.merged_csv_path"

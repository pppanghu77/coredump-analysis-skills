#!/usr/bin/env bash
set -euo pipefail

# 从 DB9 下载崩溃汇总 → 更新 kanban report_summary.csv
# 崩溃率为总量加权平均（非单一版本）

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
KANBAN_DATA="$PROJECT_ROOT/kanban/data/dde-file-manager"
ACCOUNTS="$PROJECT_ROOT/accounts.json"

# 加载 DB9 账号
MB_URL="$(python3 -c "import json; print(json.load(open('$ACCOUNTS')).get('metabase_summary',{}).get('url',''))")"
MB_USER="$(python3 -c "import json; print(json.load(open('$ACCOUNTS')).get('metabase_summary',{}).get('account',{}).get('username',''))")"
MB_PASS="$(python3 -c "import json; print(json.load(open('$ACCOUNTS')).get('metabase_summary',{}).get('account',{}).get('password',''))")"

PACKAGE="dde-file-manager"
SYS_VERSION=""
START_DATE=""
END_DATE=""

usage() {
    cat <<EOF
用法: $0 [选项]

从 Metabase DB9 下载 dde-file-manager 崩溃汇总数据，更新 kanban report_summary.csv
崩溃率 = 各版本崩溃率按主机数加权平均（总量，非单一版本）

选项:
  --sys-version N        系统版本号 (如 1075) [必填]
  --start-date YYYY-MM-DD  开始日期 [必填]
  --end-date YYYY-MM-DD    结束日期 [必填]
  -h, --help             显示帮助
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sys-version) SYS_VERSION="${2:-}"; shift 2 ;;
        --start-date)  START_DATE="${2:-}"; shift 2 ;;
        --end-date)    END_DATE="${2:-}"; shift 2 ;;
        -h|--help)     usage; exit 0 ;;
        *) echo "未知选项: $1"; usage; exit 1 ;;
    esac
done

[[ -z "$SYS_VERSION" ]] && { echo "错误: --sys-version 必填"; exit 1; }
[[ -z "$START_DATE" || -z "$END_DATE" ]] && { echo "错误: --start-date 和 --end-date 必填"; exit 1; }

# 去代理
unset https_proxy http_proxy HTTPS_PROXY HTTP_PROXY

PERIOD="${START_DATE//-/}-${END_DATE//-/}"
# 报告日期 = 数据周期尾日
REPORT_DATE="$END_DATE"
# 数据周期格式: 2026.05.25-05.31
PERIOD_LABEL="${START_DATE:0:4}.${START_DATE:5:2}.${START_DATE:8:2}-${END_DATE:5:2}.${END_DATE:8:2}"

echo "=========================================="
echo "kanban report_summary 更新 (DB9)"
echo "=========================================="
echo "系统版本: $SYS_VERSION"
echo "日期范围: $PERIOD_LABEL"
echo ""

# 登录
SESSION=$(curl -fsS \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"$MB_USER\",\"password\":\"$MB_PASS\"}" \
    "${MB_URL}/api/session" | jq -r '.id')

# 查询 DB9 table 182
QUERY=$(jq -cn --arg pkg "$PACKAGE" --arg period "$PERIOD" --arg sv "$SYS_VERSION" '{
    database: 9, type: "query",
    query: {
        "source-table": 182,
        filter: ["and",
            ["=", ["field", 3181, null], $pkg],
            ["=", ["field", 3187, null], $period],
            ["=", ["field", 3184, null], $sv]
        ]
    }
}')

RESP=$(curl -fsS -H 'Content-Type: application/json' -H "X-Metabase-Session:${SESSION}" \
    -d "$QUERY" "${MB_URL}/api/dataset")

# 计算总量崩溃率（加权平均）
python3 << PYEOF
import json, sys, csv, os

data = json.loads('''$RESP''')
rows = data['data']['rows']
cols = [c['display_name'] for c in data['data']['cols']]

# 找到列索引
idx_ver = cols.index('应用版本')
idx_hosts = cols.index('崩溃主机数')
idx_rate = cols.index('崩溃率(万分之)')
idx_crashes = cols.index('崩溃次数')

total_crashes = 0
total_hosts = 0
total_rate_weighted = 0.0
versions_info = []

for r in rows:
    hosts = int(r[idx_hosts]) if r[idx_hosts] else 0
    crashes = int(r[idx_crashes]) if r[idx_crashes] else 0
    rate = float(r[idx_rate]) if r[idx_rate] else 0.0
    ver = r[idx_ver] if r[idx_ver] else ''

    total_crashes += crashes
    total_hosts += hosts
    total_rate_weighted += rate * hosts
    versions_info.append((ver, hosts, crashes, rate))

# 总量崩溃率 = 各版本崩溃率直接求和（同 Metabase sum 聚合）
overall_rate = round(sum(r[idx_rate] for r in rows if r[idx_rate]), 2)

# 最新版本 = 崩溃数最多的
latest_ver = max(versions_info, key=lambda x: x[1])[0] if versions_info else ''

print(f"总崩溃: {total_crashes}")
print(f"总主机: {total_hosts}")
print(f"总量崩溃率: {overall_rate}‱ (各版本加权平均)")
print(f"最新版本: {latest_ver}")
print(f"涉及版本: {len(versions_info)}")

# ---- 更新 report_summary.csv ----
kanban = '$KANBAN_DATA'
report_path = os.path.join(kanban, 'report_summary.csv')

# 读取现有数据
existing = []
new_fields = ['报告日期', '数据周期', '崩溃率(‱)', '最新版本']
if os.path.exists(report_path):
    with open(report_path) as f:
        reader = csv.DictReader(f)
        existing = list(reader)

# 移除备注列，只保留4列
clean_rows = []
for row in existing:
    clean_rows.append({
        '报告日期': row.get('报告日期', ''),
        '数据周期': row.get('数据周期', ''),
        '崩溃率(‱)': row.get('崩溃率(‱)', ''),
        '最新版本': row.get('最新版本', ''),
    })

# 检查是否已有同周期记录，有则更新，无则追加
found = False
for row in clean_rows:
    if row['数据周期'] == '$PERIOD_LABEL':
        row['崩溃率(‱)'] = str(overall_rate)
        row['最新版本'] = latest_ver
        found = True
        break

if not found:
    clean_rows.append({
        '报告日期': '$REPORT_DATE',
        '数据周期': '$PERIOD_LABEL',
        '崩溃率(‱)': str(overall_rate),
        '最新版本': latest_ver,
    })

with open(report_path, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=new_fields)
    w.writeheader()
    for row in clean_rows:
        w.writerow({k: row.get(k, '') for k in new_fields})

print(f"\n看板已更新: {report_path}")
print(f"周期: $PERIOD_LABEL  崩溃率: {overall_rate}‱  版本: {latest_ver}")
PYEOF

echo ""
echo "=========================================="
echo "完成"
echo "=========================================="

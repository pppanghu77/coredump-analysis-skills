#!/usr/bin/env python3
"""
崩溃堆栈聚类分析流程 (按周独立闭环)

每周独立闭环：下载 → 按版本分类 → 仅最新稳定版本聚类。
不同周之间互不合并。包名通过 --package 参数传入，适用于任意 deb 包。

依赖：
  - coredump-data-download/scripts/download_metabase_csv.sh  (subprocess 调用)
  - ./split_by_version.py
  - ./stack_analyzer.py
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_ROOT = SCRIPT_DIR.parent.parent
DOWNLOAD_SCRIPT = SKILLS_ROOT / "coredump-data-download" / "scripts" / "download_metabase_csv.sh"
SPLIT_SCRIPT = SCRIPT_DIR / "split_by_version.py"
ANALYZE_SCRIPT = SCRIPT_DIR / "stack_analyzer.py"
ACCOUNTS_PATH = SKILLS_ROOT / "accounts.json"

# DB9 table 182 字段 ID（崩溃汇总，按周预聚合）
DB9_FIELD_PACKAGE = 3181
DB9_FIELD_PERIOD = 3187
DB9_FIELD_SYS_VERSION = 3184

# 稳定版本过滤：变体(+xxx)、测试版(.crashN)、无 debian 修订号
EXCLUDE_TOKENS = ('+', '.crash')
VERSION_PARTS_RE = re.compile(r'^\d+(\.\d+)*$')


def compute_weeks(start_date: str, end_date: str):
    """按自然周（周一~周日）分割日期范围"""
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    monday = start - timedelta(days=start.weekday())
    weeks = []
    while monday <= end:
        sunday = monday + timedelta(days=6)
        w_start = max(monday, start)
        w_end = min(sunday, end)
        weeks.append((w_start.strftime('%Y-%m-%d'), w_end.strftime('%Y-%m-%d')))
        monday += timedelta(days=7)
    return weeks


def run(cmd, **kwargs):
    """跑子进程，失败时抛错带命令上下文"""
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run([str(c) for c in cmd], **kwargs)
    if result.returncode != 0:
        raise RuntimeError(f"命令失败 (exit={result.returncode}): {' '.join(str(c) for c in cmd)}")
    return result


def download_week(package, sys_version, start, end, download_dir):
    """调用 download_metabase_csv.sh 下载一周 DB10 明细，返回 CSV 路径"""
    cmd = [
        "bash", str(DOWNLOAD_SCRIPT),
        "--sys-version", str(sys_version),
        "--start-date", start,
        "--end-date", end,
        "--output-dir", str(download_dir),
        "--file-date", f"{start.replace('-', '')}_{end.replace('-', '')}",
        package, "all", "crash",
    ]
    env = os.environ.copy()
    # Metabase 是内网服务，去掉代理
    for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
        env.pop(k, None)
    run(cmd, env=env)

    # 取最新的 CSV
    csvs = sorted(download_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not csvs:
        raise RuntimeError(f"下载完成但未生成 CSV: {download_dir}")
    return csvs[0]


def _strip_proxy_from_env():
    """Metabase 是内网服务，去掉代理环境变量"""
    for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
        os.environ.pop(k, None)


def _load_metabase_summary_account():
    """从 accounts.json 加载 DB9 (metabase_summary) 账号"""
    if not ACCOUNTS_PATH.exists():
        raise RuntimeError(f"找不到 accounts.json: {ACCOUNTS_PATH}")
    with open(ACCOUNTS_PATH) as f:
        a = json.load(f)
    mb = a.get('metabase_summary', {})
    if not mb.get('url') or not mb.get('account', {}).get('username'):
        raise RuntimeError("accounts.json 缺少 metabase_summary 配置（url/account.username/account.password）")
    return mb['url'], mb['account']['username'], mb['account']['password']


def _metabase_login(base_url, username, password):
    """POST /api/session 拿 session id"""
    payload = json.dumps({'username': username, 'password': password}).encode('utf-8')
    req = urllib.request.Request(
        f"{base_url}/api/session",
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))['id']


def _metabase_query(base_url, session_id, query_payload):
    """POST /api/dataset 执行查询"""
    payload = json.dumps(query_payload).encode('utf-8')
    req = urllib.request.Request(
        f"{base_url}/api/dataset",
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'X-Metabase-Session': session_id,
        },
        method='POST',
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))


def download_summary_week(package, sys_version, start, end, output_csv):
    """从 DB9 table 182 下载一周崩溃汇总（按版本预聚合），落盘原始 CSV

    返回 (csv_path, row_count)。返回字段含: 应用版本/崩溃主机数/崩溃率(万分之)/崩溃次数。
    """
    _strip_proxy_from_env()
    base_url, username, password = _load_metabase_summary_account()
    session_id = _metabase_login(base_url, username, password)

    period = f"{start.replace('-', '')}-{end.replace('-', '')}"
    query = {
        'database': 9,
        'type': 'query',
        'query': {
            'source-table': 182,
            'filter': ['and',
                ['=', ['field', DB9_FIELD_PACKAGE, None], package],
                ['=', ['field', DB9_FIELD_PERIOD, None], period],
                ['=', ['field', DB9_FIELD_SYS_VERSION, None], str(sys_version)],
            ],
        },
    }
    data = _metabase_query(base_url, session_id, query)
    cols = [c['display_name'] for c in data['data']['cols']]
    rows = data['data']['rows']

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        writer.writerows(rows)

    return output_csv, len(rows)


def split_by_version(input_csv, output_dir):
    """调用 split_by_version.py 分类"""
    run([sys.executable, str(SPLIT_SCRIPT), "-i", str(input_csv), "-o", str(output_dir)])


def pick_latest_stable(stats_csv, target_version=None):
    """从 _version_statistics.csv 选取最新稳定版本

    排除：含 '+', '.crash' 的变体/测试版；无 '-' debian 修订号的；'EMPTY'。
    剩余按语义版本号排序取最大。
    """
    candidates = []
    with open(stats_csv) as f:
        for row in csv.DictReader(f):
            v = row['Version']
            if v == 'EMPTY' or '-' not in v:
                continue
            if any(tok in v for tok in EXCLUDE_TOKENS):
                continue
            main = v.split('-')[0]
            if not VERSION_PARTS_RE.match(main):
                continue
            parts = tuple(int(x) for x in main.split('.'))
            candidates.append((v, row['File'], int(row['Count']), parts))

    if target_version:
        for v, fp, cnt, _ in candidates:
            if v == target_version:
                return v, fp, cnt
        # 即使被排除规则过滤，用户显式指定也允许（只要存在于原始数据）
        with open(stats_csv) as f:
            for row in csv.DictReader(f):
                if row['Version'] == target_version:
                    return target_version, row['File'], int(row['Count'])
        raise RuntimeError(f"目标版本 {target_version} 不在 {stats_csv} 中")

    if not candidates:
        return None, None, 0
    candidates.sort(key=lambda x: x[3])
    v, fp, cnt, _ = candidates[-1]
    return v, fp, cnt


def cluster(input_csv, output_file):
    """调用 stack_analyzer.py 聚类"""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    run([sys.executable, str(ANALYZE_SCRIPT),
         "-i", str(input_csv),
         "-o", str(output_file),
         "-c", "StackInfo"])


def main():
    parser = argparse.ArgumentParser(
        description="崩溃堆栈聚类分析流程 (按周独立闭环，适用任意 deb 包)")
    parser.add_argument("--package", required=True,
                        help="包名 (如 dde-file-manager / dde-dock / dde-control-center)")
    parser.add_argument("--sys-version", required=True, help="系统版本号 (如 1075)")
    parser.add_argument("--start-date", required=True, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--workspace", default=None,
                        help="工作目录 (默认: data/workspace_<package>_<日期范围>/)")
    parser.add_argument("--target-version", default=None,
                        help="指定聚类的版本号 (默认: 每周自动判定最新稳定版本)")
    parser.add_argument("--skip-download", action="store_true",
                        help="跳过下载，复用 1_download/ 下已有的周数据 (开发调试用)")
    args = parser.parse_args()

    start_compact = args.start_date.replace('-', '')
    end_compact = args.end_date.replace('-', '')
    workspace = Path(args.workspace) if args.workspace else (
        SCRIPT_DIR.parent / "data" / f"workspace_{args.package}_{start_compact}_{end_compact}"
    )
    workspace.mkdir(parents=True, exist_ok=True)
    download_dir = workspace / "1_download"
    download_dir.mkdir(parents=True, exist_ok=True)

    weeks = compute_weeks(args.start_date, args.end_date)

    print("=" * 44)
    print(f"崩溃堆栈聚类分析: {args.package} (按周独立闭环)")
    print("=" * 44)
    print(f"系统版本: {args.sys_version}")
    print(f"日期范围: {args.start_date} ~ {args.end_date}")
    print(f"工作目录: {workspace}")
    if args.target_version:
        print(f"聚类目标版本: {args.target_version} (手动指定)")
    else:
        print("聚类目标版本: 每周自动判定最新稳定版本")
    if args.skip_download:
        print("注意: --skip-download 已启用，复用现有 1_download/ 数据")
    print(f"\n覆盖 {len(weeks)} 个自然周:")
    for ws, we in weeks:
        print(f"  {ws} ~ {we}")
    print()

    success_total = 0
    week_summaries = []

    for idx, (ws, we) in enumerate(weeks, 1):
        week_tag = f"{ws.replace('-', '')}_{we.replace('-', '')}"
        print("#" * 44)
        print(f"# 周 [{idx}/{len(weeks)}]: {ws} ~ {we}")
        print("#" * 44)

        # 步骤 1: 下载（或复用）DB10 明细 + DB9 汇总
        expected_csv = download_dir / f"{args.package}_ALL_crash_{week_tag}.csv"
        expected_summary = download_dir / f"{args.package}_summary_{week_tag}.csv"
        print(f"--- 步骤 1/3: 数据准备 ({week_tag}) ---")
        if args.skip_download and expected_csv.exists():
            print(f"  复用 DB10: {expected_csv}")
            week_csv = expected_csv
        else:
            week_csv = download_week(args.package, args.sys_version, ws, we, download_dir)
            if week_csv != expected_csv:
                print(f"  警告: 期望 {expected_csv.name}, 实际 {week_csv.name}")
        line_count = sum(1 for _ in open(week_csv)) - 1
        print(f"  DB10 明细: {week_csv} ({line_count} 行)")

        # DB9 汇总（按版本预聚合，与 DB10 同周并列落盘）
        if args.skip_download and expected_summary.exists():
            print(f"  复用 DB9:  {expected_summary}")
        else:
            try:
                summary_csv, summary_rows = download_summary_week(
                    args.package, args.sys_version, ws, we, expected_summary)
                print(f"  DB9 汇总:  {summary_csv} ({summary_rows} 行)")
            except Exception as e:
                print(f"  警告: DB9 汇总下载失败，跳过: {e}")

        # 步骤 2: 按版本分类
        print(f"\n--- 步骤 2/3: 按版本分类 ({week_tag}) ---")
        split_dir = workspace / "2_split_by_version" / week_tag
        split_by_version(week_csv, split_dir)

        # 步骤 3: 选取目标版本 + 聚类
        print(f"\n--- 步骤 3/3: 选取目标版本 + 聚类 ({week_tag}) ---")
        stats_csv = split_dir / "_version_statistics.csv"
        latest_ver, target_csv, count = pick_latest_stable(stats_csv, args.target_version)
        if latest_ver is None:
            print(f"  警告: 周 {week_tag} 无稳定版本，跳过聚类\n")
            week_summaries.append({
                'week': week_tag, 'version': '', 'count': 0,
                'status': 'Skipped', 'file': '',
            })
            continue

        if args.target_version:
            print(f"  目标版本 (手动指定): {latest_ver} ({count} 条)")
        else:
            print(f"  目标版本 (自动判定): {latest_ver} ({count} 条)")

        output_file = workspace / "3_version_analysis_results" / week_tag / latest_ver / f"analysis_{latest_ver}.csv"
        print(f"  聚类中...")
        try:
            cluster(Path(target_csv), output_file)
            status = "Success"
            success_total += 1
        except RuntimeError as e:
            print(f"  警告: 聚类失败: {e}")
            status = "Failed"

        # 周级汇总
        analysis_dir = workspace / "3_version_analysis_results" / week_tag
        week_summary_file = analysis_dir / "_week_summary.csv"
        with open(week_summary_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Week', 'Version', 'Record Count', 'Analysis Status', 'Analysis File'])
            writer.writerow([week_tag, latest_ver, count, status, str(output_file)])
        week_summaries.append({
            'week': week_tag, 'version': latest_ver, 'count': count,
            'status': status, 'file': str(output_file),
        })
        print(f"  周汇总: {week_summary_file}\n")

    # 全局汇总
    print("=" * 44)
    print("流程完成")
    print("=" * 44)
    print(f"覆盖 {len(weeks)} 周，成功聚类 {success_total} 个周目标")
    print(f"工作目录: {workspace}")
    print(f"  - 原始数据: {download_dir}")
    print(f"  - 版本分类: {workspace}/2_split_by_version/<周>/")
    print(f"  - 聚类结果: {workspace}/3_version_analysis_results/<周>/<版本>/")

    analysis_root = workspace / "3_version_analysis_results"
    analysis_root.mkdir(parents=True, exist_ok=True)
    global_summary = analysis_root / "_summary_report.csv"
    with open(global_summary, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Week', 'Version', 'Record Count', 'Analysis Status', 'Analysis File'])
        for row in week_summaries:
            writer.writerow([row['week'], row['version'], row['count'], row['status'], row['file']])
    print(f"全局汇总: {global_summary}")

    # 跨周 hash 趋势：按 Crash Hash 聚合各周占比，按最新一周降序
    import importlib.util
    trend_script = SCRIPT_DIR / "build_hash_trend.py"
    if trend_script.exists():
        spec = importlib.util.spec_from_file_location("build_hash_trend", trend_script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        print("\n--- 跨周 hash 趋势汇总 ---")
        mod.build(analysis_root)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
跨周崩溃 hash 趋势汇总。

扫描 3_version_analysis_results/<周>/<版本>/analysis_<version>.csv，按 Crash Hash
聚合各周占比，生成 _hash_trend_by_week.csv（按最新一周占比降序）。

设计要点：
- 不区分版本号，所有周的 analysis CSV 统一按周聚合（周列由其所在目录名决定）。
- 同一个 hash 在单周 CSV 内若出现多行（上游聚类产生的相似类代表样本经清洗后
  内容一致），占比/count 求和合并，避免漏算。
- Cleaned Stack 列取该 hash 下 count 最大一行的 Cleaned Stack (No Addr) 内容
  （去地址/偏移后的栈，保留换行）。
- 排序键为最新一周的占比降序，便于定位当前最突出的问题。

用法：
    python3 build_hash_trend.py --analysis-root <3_version_analysis_results 目录>
    python3 build_hash_trend.py --workspace <workspace 目录>   # 自动定位
"""
import argparse
import csv
import os
import sys
import glob


def collect_weeks(analysis_root):
    """按周目录(形如 YYYYMMDD_YYYYMMDD)收集其下所有 analysis_*.csv。

    返回 [(week_label, [csv_path, ...]), ...]，按周目录名升序。
    一个周目录下可能有多版本 analysis CSV（历史多周数据），全部纳入该周。
    """
    weeks = []
    for entry in sorted(os.listdir(analysis_root)):
        week_dir = os.path.join(analysis_root, entry)
        if not os.path.isdir(week_dir):
            continue
        # 周目录名形如 20260511_20260517；放宽校验，只要含下划线即视为周目录
        if '_' not in entry:
            continue
        csvs = sorted(glob.glob(os.path.join(week_dir, '*', 'analysis_*.csv')))
        if csvs:
            weeks.append((entry, csvs))
    return weeks


def build(analysis_root, output_file=None, verbose=True):
    weeks = collect_weeks(analysis_root)
    if not weeks:
        if verbose:
            print(f"[build_hash_trend] 未在 {analysis_root} 下找到任何 analysis_*.csv", file=sys.stderr)
        return None

    labels = [w for w, _ in weeks]
    n = len(weeks)

    # hash -> {"pct":[...], "cnt":[...], "full":"", "full_cnt":0}
    agg = {}

    for i, (week, csvs) in enumerate(weeks):
        week_cnt_total = 0
        seen_rows = 0
        for csv_path in csvs:
            with open(csv_path, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for r in reader:
                    h = (r.get('Crash Hash') or '').strip()
                    if not h:
                        continue
                    try:
                        cnt = int(r.get('Count') or 0)
                    except ValueError:
                        cnt = 0
                    try:
                        pct = float((r.get('Percentage') or '0').rstrip('%'))
                    except ValueError:
                        pct = 0.0
                    cleaned = r.get('Cleaned Stack (No Addr)') or ''
                    seen_rows += 1
                    week_cnt_total += cnt
                    if h not in agg:
                        agg[h] = {'pct': [0.0] * n, 'cnt': [0] * n, 'full': '', 'full_cnt': 0}
                    agg[h]['pct'][i] += pct
                    agg[h]['cnt'][i] += cnt
                    if cnt > agg[h]['full_cnt']:
                        agg[h]['full_cnt'] = cnt
                        agg[h]['full'] = cleaned
        if verbose:
            print(f"[build_hash_trend] {week}: {len(csvs)} 个版本CSV, {seen_rows} 数据行, count合计 {week_cnt_total}")

    rows = list(agg.items())
    # 按最新一周占比降序
    rows.sort(key=lambda kv: -kv[1]['pct'][-1])

    if output_file is None:
        output_file = os.path.join(analysis_root, '_hash_trend_by_week.csv')
    with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['Crash Hash'] + [f'{lab} %' for lab in labels] + ['Cleaned Stack'])
        for h, d in rows:
            writer.writerow([h] + [f'{p:.2f}' for p in d['pct']] + [d['full']])

    if verbose:
        print(f"[build_hash_trend] 已生成: {output_file}")
        print(f"[build_hash_trend] 共 {len(rows)} 个精确 hash, 按 {labels[-1]} 占比降序")
    return output_file


def main():
    ap = argparse.ArgumentParser(description='跨周崩溃 hash 趋势汇总')
    ap.add_argument('--analysis-root', help='3_version_analysis_results 目录路径')
    ap.add_argument('--workspace', help='workspace 目录（自动定位其 3_version_analysis_results）')
    ap.add_argument('-o', '--output', help='输出 CSV 路径（默认 analysis_root/_hash_trend_by_week.csv）')
    args = ap.parse_args()

    if args.analysis_root:
        analysis_root = args.analysis_root
    elif args.workspace:
        analysis_root = os.path.join(args.workspace, '3_version_analysis_results')
    else:
        ap.error('请提供 --analysis-root 或 --workspace')

    if not os.path.isdir(analysis_root):
        print(f'错误: 目录不存在 {analysis_root}', file=sys.stderr)
        sys.exit(1)

    out = build(analysis_root, output_file=args.output)
    if not out:
        sys.exit(1)


if __name__ == '__main__':
    main()

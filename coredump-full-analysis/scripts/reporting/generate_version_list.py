#!/usr/bin/env python3
"""
从统计数据生成版本清单
从 crash_statistics.json 中提取版本信息，生成 version_list.txt
"""

import json
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Tuple


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='从统计数据生成版本清单',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  python3 generate_version_list.py package_crash_statistics.json version_list.txt
  python3 generate_version_list.py stats.json list.txt --min-crash-count 10
  python3 generate_version_list.py stats.json list.txt --sort-by total
        '''
    )
    parser.add_argument(
        'stats_file',
        help='统计数据文件路径 (package_crash_statistics.json)'
    )
    parser.add_argument(
        'output_file',
        help='输出文件路径 (version_list.txt)'
    )
    parser.add_argument(
        '--min-crash-count',
        type=int,
        default=5,
        help='最小崩溃次数阈值（默认: 5）'
    )
    parser.add_argument(
        '--sort-by',
        choices=['total', 'unique', 'version'],
        default='total',
        help='排序方式: total(总崩溃数), unique(唯一崩溃数), version(版本号)'
    )
    parser.add_argument(
        '--reverse',
        action='store_true',
        help='反向排序'
    )
    parser.add_argument(
        '--high-threshold',
        type=int,
        default=50,
        help='高优先级阈值（默认: 50）'
    )
    parser.add_argument(
        '--medium-threshold',
        type=int,
        default=20,
        help='中优先级阈值（默认: 20）'
    )

    return parser.parse_args()


def generate_version_list(stats_file: Path, output_file: Path, min_count: int,
                          sort_by: str = 'total', reverse: bool = False,
                          high_threshold: int = 50, medium_threshold: int = 20) -> Tuple[int, int, int]:
    """
    生成版本清单文件

    Args:
        stats_file: 统计数据文件路径
        output_file: 输出文件路径
        min_count: 最小崩溃次数阈值
        sort_by: 排序方式
        reverse: 是否反向排序
        high_threshold: 高优先级阈值
        medium_threshold: 中优先级阈值

    Returns:
        (总版本数, 过滤后版本数, 总崩溃数)
    """
    # 读取统计数据
    if not stats_file.exists():
        print(f"错误: 统计数据文件不存在: {stats_file}")
        return 0, 0, 0

    with open(stats_file, 'r', encoding='utf-8') as f:
        stats = json.load(f)

    # 提取版本信息
    by_version = stats.get('by_version', {})
    if not by_version:
        print("错误:统计数据中未找到版本信息")
        return 0, 0, 0

    # 转换为列表
    versions_list: List[Dict] = []
    for version, data in by_version.items():
        if isinstance(data, dict):
            total_crashes = data.get('total_crashes', 0)
            unique_crashes = data.get('unique_crashes', 0)
        else:
            total_crashes = int(data or 0)
            unique_crashes = 0

        versions_list.append({
            'version': version,
            'total_crashes': total_crashes,
            'unique_crashes': unique_crashes
        })

    # 排序
    sort_key_map = {
        'total': 'total_crashes',
        'unique': 'unique_crashes',
        'version': 'version'
    }
    sort_key = sort_key_map.get(sort_by, 'total_crashes')
    reverse_sort = reverse if sort_by == 'version' else not reverse

    versions_list.sort(key=lambda x: x[sort_key], reverse=reverse_sort)

    # 确定优先级并过滤
    filtered_versions: List[Dict] = []

    for version_data in versions_list:
        count = version_data['total_crashes']

        if count < min_count:
            continue

        # 确定优先级
        if count >= high_threshold:
            priority = 'high'
        elif count >= medium_threshold:
            priority = 'medium'
        else:
            priority = 'low'

        version_data['priority'] = priority
        filtered_versions.append(version_data)

    # 生成输出文件
    with open(output_file, 'w', encoding='utf-8') as f:
        # 文件头
        f.write("# 版本清单: 版本号|崩溃次数|优先级\n")
        f.write(f"# 生成时间: {Path(__file__).stat().st_mtime}\n")
        f.write(f"# 优先级定义:\n")
        f.write(f"#   high   >= {high_threshold} 次\n")
        f.write(f"#   medium {medium_threshold}-{high_threshold-1} 次\n")
        f.write(f"#   low    {medium_threshold-1}-{min_count} 次\n")
        f.write(f"# 最小崩溃次数阈值: {min_count}\n")
        f.write(f"# 排序方式: {sort_by}\n")
        f.write("\n")

        # 版本列表
        for version_data in filtered_versions:
            f.write(f"{version_data['version']}|{version_data['total_crashes']}|{version_data['priority']}\n")

    # 统计信息
    total_versions = len(versions_list)
    filtered_count = len(filtered_versions)
    total_crashes = sum(v['total_crashes'] for v in filtered_versions)

    # 统计各类优先级的数量
    high_count = sum(1 for v in filtered_versions if v['priority'] == 'high')
    medium_count = sum(1 for v in filtered_versions if v['priority'] == 'medium')
    low_count = sum(1 for v in filtered_versions if v['priority'] == 'low')

    # 打印摘要
    print("\n" + "=" * 80)
    print("版本清单生成统计")
    print("=" * 80)
    print(f"总版本数: {total_versions}")
    print(f"过滤后版本数 (崩溃次数 >= {min_count}): {filtered_count}")
    print(f"过滤掉版本数: {total_versions - filtered_count}")
    print(f"总崩溃次数: {total_crashes}")
    print()

    print("优先级分布:")
    print(f"  🔴 高优先级 (>= {high_threshold} 次): {high_count} 个版本")
    print(f"  🟡 中优先级 ({medium_threshold}-{high_threshold-1} 次): {medium_count} 个版本")
    print(f"  🟢 低优先级 ({min_count}-{medium_threshold-1} 次): {low_count} 个版本")
    print()

    # 显示前10个版本
    print(f"前10个版本 (按{sort_by}排序):")
    print(f"{'序号':<4} {'版本号':<25} {'总崩溃次数':<10} {'唯一崩溃数':<10} {'优先级':<10}")
    print("-" * 70)
    for i, version_data in enumerate(filtered_versions[:10], 1):
        priority_icon = "🔴" if version_data['priority'] == 'high' else \
                       "🟡" if version_data['priority'] == 'medium' else "🟢"
        print(f"{i:<4} {version_data['version']:<25} "
              f"{version_data['total_crashes']:<10} {version_data['unique_crashes']:<10} "
              f"{version_data['priority']:<10} {priority_icon}")

    print("=" * 80)
    print(f"版本清单已保存到: {output_file}")

    return total_versions, filtered_count, total_crashes


def main():
    """主函数"""
    args = parse_args()

    stats_file = Path(args.stats_file)
    output_file = Path(args.output_file)

    print("=" * 80)
    print("版本清单生成工具")
    print("=" * 80)
    print(f"输入文件: {stats_file}")
    print(f"输出文件: {output_file}")

    # 生成版本清单
    total, filtered, crash_count = generate_version_list(
        stats_file,
        output_file,
        min_count=args.min_crash_count,
        sort_by=args.sort_by,
        reverse=args.reverse,
        high_threshold=args.high_threshold,
        medium_threshold=args.medium_threshold
    )

    if filtered == 0:
        print("\n警告: 没有版本满足崩溃次数阈值要求")
        print(f"建议降低最小崩溃次数阈值（当前: {args.min_crash_count}）")
        sys.exit(1)

    print("\n✅ 完成!")


if __name__ == '__main__':
    main()

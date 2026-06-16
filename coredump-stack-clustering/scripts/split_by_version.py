#!/usr/bin/env python3
"""
按 Version 列分类 CSV 文件
融合自 crash-analysis skill 的 split_by_version.py
"""
import csv
import os
from pathlib import Path
from collections import defaultdict


def split_csv_by_version(input_file, output_dir=None, tag=None):
    """按 Version 列分类 CSV 文件

    tag: 输出目录下的子目录名，用于按时期区分分类结果（如 '20260511_20260517'）
    """
    print(f"正在读取文件: {input_file}")

    version_data = defaultdict(list)
    header = None
    version_index = None

    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)

            try:
                version_index = header.index('Version')
                print(f"找到 Version 列，索引: {version_index}")
            except ValueError:
                print("错误: CSV 中没有 'Version' 列")
                print(f"可用列: {header}")
                return None

            total_rows = 0
            for row in reader:
                total_rows += 1
                if len(row) > version_index:
                    version = row[version_index].strip()
                    if not version:
                        version = "EMPTY"
                else:
                    version = "EMPTY"
                version_data[version].append(row)

            print(f"总行数: {total_rows} (不含表头)")

    except Exception as e:
        print(f"读取文件失败: {e}")
        return None

    if output_dir is None:
        output_dir = Path(input_file).parent / "split_by_version_output"
    else:
        output_dir = Path(output_dir)
    if tag:
        output_dir = output_dir / tag
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n找到 {len(version_data)} 个不同版本:")
    sorted_versions = sorted(version_data.keys(), key=lambda x: (x == "EMPTY", x))
    for version in sorted_versions:
        count = len(version_data[version])
        print(f"  - {version}: {count} 行")

    print(f"\n开始分类并保存文件...")
    stats = []

    for version in sorted_versions:
        rows = version_data[version]

        safe_version = version.replace('/', '_').replace('\\', '_')
        safe_version = safe_version.replace(':', '_').replace(' ', '_')
        safe_version = safe_version.replace('|', '_').replace('"', '_')
        safe_version = safe_version.replace('<', '_').replace('>', '_')

        if safe_version == "EMPTY":
            output_file = output_dir / "version_EMPTY.csv"
        else:
            output_file = output_dir / f"version_{safe_version}.csv"

        try:
            with open(output_file, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(header)
                writer.writerows(rows)

            stats.append({
                'version': version,
                'count': len(rows),
                'file': str(output_file)
            })
            print(f"  Version {version}: {len(rows)} 行 -> {output_file}")
        except Exception as e:
            print(f"  保存失败 {output_file}: {e}")

    # 保存统计信息
    stats_file = output_dir / "_version_statistics.csv"
    with open(stats_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Version', 'Count', 'File'])
        for stat in stats:
            writer.writerow([stat['version'], stat['count'], stat['file']])

    print(f"\n分类完成!")
    print(f"- 创建了 {len(stats)} 个分类文件")
    print(f"- 输出目录: {output_dir}")
    return output_dir


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='按 Version 列分类 CSV 文件')
    parser.add_argument('-i', '--input', type=str, required=True, help='输入 CSV 文件路径')
    parser.add_argument('-o', '--output-dir', type=str, default=None, help='输出目录 (默认: 输入文件同目录)')
    parser.add_argument('-t', '--tag', type=str, default=None, help='输出子目录名，用于按时期区分 (如 20260511_20260517)')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"错误: 文件 '{args.input}' 不存在")
        exit(1)

    result = split_csv_by_version(args.input, args.output_dir, tag=args.tag)
    if result:
        print(str(result))

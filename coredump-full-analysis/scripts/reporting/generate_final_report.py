#!/usr/bin/env python3
"""
生成最终报告脚本
汇总所有版本的分析结果，生成最终结论报告
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
import argparse


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='生成最终汇总报告',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  python3 generate_final_report.py --package dde-session-ui --workspace /path/to/workspace
        '''
    )
    parser.add_argument(
        '--package',
        required=True,
        help='包名'
    )
    parser.add_argument(
        '--workspace',
        required=True,
        help='工作目录'
    )
    parser.add_argument(
        '--output-dir',
        help='输出目录（默认: workspace/final_report）'
    )
    parser.add_argument(
        '--start-date',
        help='开始日期'
    )
    parser.add_argument(
        '--end-date',
        help='结束日期'
    )

    return parser.parse_args()


def clean_version(version: str) -> str:
    """清理版本号"""
    version = re.sub(r'^1:', '', version)
    version = re.sub(r'-\d+$', '', version)
    return version


def load_version_analyses(workspace: Path, package: str) -> List[Dict]:
    """加载所有版本的分析结果"""
    # 新目录结构: 5.崩溃分析/<package>/version_xxx/
    analysis_dir = workspace / '5.崩溃分析' / package
    versions = []

    if not analysis_dir.exists():
        print(f"警告: 分析目录不存在: {analysis_dir}")
        return versions

    # 遍历所有版本目录
    for version_dir in sorted(analysis_dir.glob('version_*')):
        analysis_file = version_dir / 'analysis.json'

        if not analysis_file.exists():
            continue

        try:
            with open(analysis_file, 'r', encoding='utf-8') as f:
                analysis = json.load(f)
                versions.append(analysis)
        except Exception as e:
            print(f"警告: 无法读取 {analysis_file}: {e}")

    return versions


def load_version_list(workspace: Path, package: str) -> List[Dict]:
    """加载版本清单"""
    version_list_file = workspace / '2.数据筛选' / 'version_list.txt'

    versions = []
    if not version_list_file.exists():
        print(f"警告: 版本清单不存在: {version_list_file}")
        return versions

    with open(version_list_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            parts = line.split('|')
            if len(parts) >= 2:
                version = parts[0].strip()
                count = int(parts[1].strip()) if parts[1].strip().isdigit() else 0
                priority = parts[2].strip() if len(parts) >= 3 else 'medium'

                versions.append({
                    'version': version,
                    'count': count,
                    'priority': priority
                })

    return versions


def calculate_trend(versions: List[Dict]) -> Dict:
    """计算崩溃趋势"""
    if len(versions) < 2:
        return {'trend': 'insufficient_data'}

    # 按版本号排序（假设是数字版本）
    try:
        # 提取版本号主部分进行比较
        def version_key(v):
            ver = clean_version(v['version'])
            parts = re.findall(r'\d+', ver)
            return tuple(int(p) for p in parts) if parts else (0,)

        sorted_versions = sorted(versions, key=version_key)
    except:
        sorted_versions = versions

    # 比较首尾版本
    first = sorted_versions[0]
    last = sorted_versions[-1]

    # 从summary中获取总崩溃次数
    first_count = first.get('summary', {}).get('total_crash_records', 0)
    last_count = last.get('summary', {}).get('total_crash_records', 0)

    if last_count > first_count * 1.5:
        trend = 'increasing'
    elif last_count < first_count * 0.5:
        trend = 'decreasing'
    else:
        trend = 'stable'

    return {
        'trend': trend,
        'first_version': first.get('version'),
        'first_count': first_count,
        'last_version': last.get('version'),
        'last_count': last_count,
        'change_percent': ((last_count - first_count) / first_count * 100) if first_count > 0 else 0
    }


def aggregate_statistics(versions: List[Dict]) -> Dict:
    """汇总统计信息"""
    total_versions = len(versions)
    total_unique_crashes = sum(v.get('summary', {}).get('unique_crashes', 0) for v in versions)
    total_crash_records = sum(v.get('summary', {}).get('total_crash_records', 0) for v in versions)
    total_fixable = sum(v.get('summary', {}).get('fixable_count', 0) for v in versions)
    total_non_fixable = sum(v.get('summary', {}).get('non_fixable_count', 0) for v in versions)
    total_uncertain = sum(v.get('summary', {}).get('uncertain_count', 0) for v in versions)

    # 计算整体修复率
    total_assessable = total_fixable + total_non_fixable + total_uncertain
    fix_rate = (total_fixable / total_assessable * 100) if total_assessable > 0 else 0

    # 按信号类型汇总
    signal_counts = {}
    for version in versions:
        for signal, count in version.get('by_signal', {}).items():
            signal_counts[signal] = signal_counts.get(signal, 0) + count

    return {
        'total_versions_analyzed': total_versions,
        'total_unique_crashes': total_unique_crashes,
        'total_crash_records': total_crash_records,
        'total_fixable': total_fixable,
        'total_non_fixable': total_non_fixable,
        'total_uncertain': total_uncertain,
        'overall_fix_rate': round(fix_rate, 1),
        'by_signal': signal_counts
    }


def generate_markdown_report(package: str, versions: List[Dict], version_list: List[Dict],
                            statistics: Dict, trend: Dict, output_dir: Path,
                            start_date: str = None, end_date: str = None) -> Path:
    """生成Markdown格式的最终报告"""
    report_file = output_dir / 'final_conclusion.md'

    with open(report_file, 'w', encoding='utf-8') as f:
        # 标题
        f.write(f"# {package} 崩溃分析最终报告\n\n")
        f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        # 日期范围（如果有）
        if start_date or end_date:
            f.write(f"**日期范围**: {start_date or '未知'} 至 {end_date or '未知'}\n\n")

        # 执行摘要
        f.write("## 执行摘要\n\n")

        # 总体统计
        f.write("### 总体统计\n\n")
        stats = statistics
        f.write(f"- **分析的版本数**: {stats['total_versions_analyzed']}\n")
        f.write(f"- **唯一崩溃数**: {stats['total_unique_crashes']}\n")
        f.write(f"- **总崩溃记录数**: {stats['total_crash_records']}\n")
        f.write(f"- **可修复崩溃**: {stats['total_fixable']}\n")
        f.write(f"- **不可修复崩溃**: {stats['total_non_fixable']}\n")
        f.write(f"- **需人工判断**: {stats['total_uncertain']}\n")
        f.write(f"- **整体修复率**: {stats['overall_fix_rate']}%\n\n")

        # 趋势分析
        f.write("### 趋势分析\n\n")
        if trend['trend'] == 'increasing':
            f.write("⚠️ **警告**: 崩溃呈上升趋势\n\n")
            f.write(f"- 早期版本 {trend['first_version']}: {trend['first_count']} 次崩溃\n")
            f.write(f"- 最新版本 {trend['last_version']}: {trend['last_count']} 次崩溃\n")
            f.write(f"- 变化: {trend['change_percent']:.1f}% (增加)\n\n")
        elif trend['trend'] == 'decreasing':
            f.write("✅ **良好**: 崩溃呈下降趋势\n\n")
            f.write(f"- 早期版本 {trend['first_version']}: {trend['first_count']} 次崩溃\n")
            f.write(f"- 最新版本 {trend['last_version']}: {trend['last_count']} 次崩溃\n")
            f.write(f"- 变化: {trend['change_percent']:.1f}% (减少)\n\n")
        else:
            f.write("ℹ️ **稳定**: 崩溃数量保持稳定\n")
            f.write(f"- 分析版本范围内的崩溃数量相对稳定\n\n")

        # 按信号类型统计
        f.write("### 按信号类型统计\n\n")
        f.write("| 信号类型 | 次数 | 占比 |\n")
        f.write("|---------|------|------|\n")

        total_signals = sum(stats['by_signal'].values())
        for signal, count in sorted(stats['by_signal'].items(), key=lambda x: -x[1]):
            percent = (count / total_signals * 100) if total_signals > 0 else 0
            signal_desc = {
                'SIGSEGV': '段错误',
                'SIGABRT': '主动终止',
                'SIGBUS': '总线错误',
                'SIGFPE': '浮点异常'
            }.get(signal, signal)
            f.write(f"| {signal_desc} ({signal}) | {count} | {percent:.1f}% |\n")

        f.write("\n")

        # 版本详细分析
        f.write("## 版本分析结果\n\n")
        f.write("| 版本 | 唯一崩溃 | 总次数 | 可修复 | 不可修复 | 需人工判断 | 修复率 |\n")
        f.write("|------|---------|--------|--------|----------|------------|--------|\n")

        for version in sorted(versions, key=lambda v: v.get('version', '')):
            summary = version.get('summary', {})
            f.write(f"| {version['version']} | ")
            f.write(f"{summary.get('unique_crashes', 0)} | ")
            f.write(f"{summary.get('total_crash_records', 0)} | ")
            f.write(f"{summary.get('fixable_count', 0)} | ")
            f.write(f"{summary.get('non_fixable_count', 0)} | ")
            f.write(f"{summary.get('uncertain_count', 0)} | ")
            f.write(f"{summary.get('fix_rate', '0%')} |\n")

        f.write("\n")

        # 优先级版本
        if version_list:
            f.write("## 优先版本分析\n\n")

            high_priority = [v for v in version_list if v.get('priority') == 'high']
            if high_priority:
                f.write("### 高优先级版本（崩溃次数 ≥ 50）\n\n")
                for vp in high_priority[:5]:  # 最多显示5个
                    # 查找对应的分析结果
                    version_analysis = next((v for v in versions if v.get('version') == vp['version']), None)
                    if version_analysis:
                        summary = version_analysis.get('summary', {})
                        version_dir = version_analysis.get('version_dir') or clean_version(vp['version']).replace('.', '_')
                        f.write(f"**{vp['version']}** ({vp['count']} 次崩溃)\n")
                        f.write(f"- 可修复: {summary.get('fixable_count', 0)}\n")
                        f.write(f"- 不可修复: {summary.get('non_fixable_count', 0)}\n")
                        f.write(f"- 分析报告: `5.崩溃分析/{package}/version_{version_dir}/analysis_report.md`\n\n")

            medium_priority = [v for v in version_list if v.get('priority') == 'medium']
            if medium_priority:
                f.write(f"### 中优先级版本（崩溃次数 20-49）\n\n")
                f.write(f"共 {len(medium_priority)} 个中优先级版本\n\n")

        # 主要崩溃类型分析
        f.write("## 主要崩溃类型分析\n\n")

        # 找出最常见的可修复崩溃
        fixable_crashes = {}
        for version in versions:
            for crash in version.get('crashes', []):
                if crash.get('fixable') is True:
                    key_frame = crash.get('key_frame') or {}
                    symbol = crash.get('app_layer_symbol') or key_frame.get('symbol') or crash.get('pattern_name') or 'unknown'
                    key = (crash.get('signal', ''), symbol)
                    fixable_crashes[key] = fixable_crashes.get(key, 0) + crash.get('count', 1)

        if fixable_crashes:
            f.write("### 可修复崩溃（Top 5）\n\n")
            f.write("| 信号 | 函数 | 次数 |\n")
            f.write("|------|------|------|\n")

            for (signal, symbol), count in sorted(fixable_crashes.items(), key=lambda x: -x[1])[:5]:
                f.write(f"| {signal} | `{symbol[:30]}` | {count} |\n")
            f.write("\n")

        # 修复建议
        f.write("## 修复建议\n\n")

        if stats['total_fixable'] > 0:
            f.write("### 可按优先级处理的崩溃\n\n")
            f.write("以下类型的崩溃可以通过在应用代码中添加检查和错误处理来修复：\n\n")
            f.write("1. **空指针解引用**\n")
            f.write("   - 添加指针非空检查\n")
            f.write("   - 在使用前验证对象有效性\n\n")
            f.write("2. **缓冲区溢出**\n")
            f.write("   - 添加数组/容器边界检查\n")
            f.write("   - 使用安全的字符串操作函数\n\n")
            f.write("3. **释放后使用**\n")
            f.write("   - 使用智能指针管理内存\n")
            f.write("   - 释放后立即置NULL\n\n")
        else:
            f.write("当前没有识别到可修复的崩溃模式。\n\n")

        if stats['total_non_fixable'] > 0:
            f.write("### 需要防护处理的崩溃\n\n")
            f.write("以下类型的崩溃位于系统库或第三方库中，需要在应用层面进行防护：\n\n")
            f.write("1. **第三方库崩溃**\n")
            f.write("   - 添加错误处理和try-catch块\n")
            f.write("   - 设置合理的超时和重试机制\n\n")
            f.write("2. **系统调用失败**\n")
            f.write("   - 检查系统调用的返回值\n")
            f.write("   - 处理可能的错误码\n\n")

        # 总结
        f.write("## 总结\n\n")

        if trend['trend'] == 'decreasing':
            f.write("✅ 整体情况良好：崩溃数量呈下降趋势，表示之前的问题修复工作有效。\n\n")
            f.write("建议继续当前的修复策略，并关注新增功能的稳定性测试。\n\n")
        elif trend['trend'] == 'increasing':
            f.write("⚠️ 需要关注：崩溃数量呈上升趋势，建议：\n\n")
            f.write("1. 优先处理高崩溃频率版本中的可修复崩溃\n")
            f.write("2. 加强代码审查和单元测试\n")
            f.write("3. 考虑引入更严格的静态分析工具\n\n")
        else:
            f.write("ℹ️ 稳定期：崩溃数量相对稳定。\n\n")
            f.write("建议持续监控，定期进行代码健康检查。\n\n")

        # 详细报告位置
        f.write("## 详细报告\n\n")
        f.write(f"所有版本的详细分析报告位于: `{output_dir.parent / '5.崩溃分析'}/`\n\n")
        f.write("每个版本的分析目录包含：\n")
        f.write("- `analysis.json` - 原始分析数据\n")
        f.write("- `analysis_report.md` - 详细的Markdown报告\n")
        f.write("- `fixes/` - 可修复崩溃的补丁建议\n")
        f.write("- `issues/` - 不可修复崩溃的问题文档\n\n")

        # Gerrit提交信息
        gerrit_dir = output_dir.parent / '5.崩溃分析' / 'gerrit'
        if gerrit_dir.exists():
            gerrit_commits = list(gerrit_dir.glob('commit_*.json'))
            if gerrit_commits:
                f.write(f"## Gerrit提交\n\n")
                f.write(f"已创建 {len(gerrit_commits)} 个Gerrit提交\n\n")

        f.write("---\n\n")
        f.write(f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")

    return report_file


def generate_json_summary(package: str, versions: List[Dict], version_list: List[Dict],
                          statistics: Dict, trend: Dict, output_dir: Path,
                          start_date: str = None, end_date: str = None) -> Path:
    """生成JSON格式的摘要"""
    summary_file = output_dir / 'summary_statistics.json'

    version_summaries = []
    for version in versions:
        version_summaries.append({
            'version': version.get('version'),
            'version_clean': version.get('version_clean'),
            'unique_crashes': version.get('summary', {}).get('unique_crashes', 0),
            'total_crash_records': version.get('summary', {}).get('total_crash_records', 0),
            'fixable_count': version.get('summary', {}).get('fixable_count', 0),
            'non_fixable_count': version.get('summary', {}).get('non_fixable_count', 0),
            'uncertain_count': version.get('summary', {}).get('uncertain_count', 0),
            'fix_rate': version.get('summary', {}).get('fix_rate', '0%')
        })

    summary = {
        'metadata': {
            'package': package,
            'analysis_time': datetime.now().isoformat(),
            'total_versions_in_list': len(version_list),
            'total_versions_analyzed': len(versions),
            'date_range': {
                'start': start_date,
                'end': end_date
            }
        },
        'trend_analysis': trend,
        'crash_statistics': statistics,
        'versions': version_summaries,
        'by_signal': statistics['by_signal'],
        'high_priority_versions': [v for v in version_list if v.get('priority') == 'high'],
        'recommendations': {
            'should_investigate': trend['trend'] == 'increasing',
            'fixable_crash_ratio': statistics['overall_fix_rate'],
            'top_signals': sorted(statistics['by_signal'].items(), key=lambda x: -x[1])[:3]
        }
    }

    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return summary_file


def main():
    """主函数"""
    args = parse_args()

    print("=" * 80)
    print("生成最终汇总报告")
    print("=" * 80)
    print(f"包名: {args.package}")
    print(f"工作目录: {args.workspace}")
    print()

    workspace = Path(args.workspace)

    # 确定输出目录
    output_dir = Path(args.output_dir) if args.output_dir else workspace / 'final_report'
    output_dir.mkdir(parents=True, exist_ok=True)

    # 加载分析结果
    print("加载分析结果...")
    versions = load_version_analyses(workspace, args.package)
    print(f"  找到 {len(versions)} 个已分析的版本")

    # 加载版本清单
    print("加载版本清单...")
    version_list = load_version_list(workspace, args.package)
    print(f"  清单中共有 {len(version_list)} 个版本")

    if not versions and not version_list:
        print("错误: 没有找到任何分析结果或版本清单")
        print("请先运行 analyze_crash_loop.sh 进行分析")
        return 1

    # 计算统计
    print("计算统计信息...")
    statistics = aggregate_statistics(versions)

    # 计算趋势
    if versions:
        print("分析趋势...")
        trend = calculate_trend(versions)
    else:
        trend = {'trend': 'insufficient_data'}

    print()
    print("=== 统计摘要 ===")
    print(f"分析的版本数: {statistics['total_versions_analyzed']}")
    print(f"唯一崩溃数: {statistics['total_unique_crashes']}")
    print(f"总崩溃记录数: {statistics['total_crash_records']}")
    print(f"可修复: {statistics['total_fixable']}")
    print(f"不可修复: {statistics['total_non_fixable']}")
    print(f"需人工判断: {statistics['total_uncertain']}")
    print(f"修复率: {statistics['overall_fix_rate']}%")
    print(f"趋势: {trend.get('trend', 'N/A')}")
    print()

    # 生成报告
    print("生成报告...")
    md_report = generate_markdown_report(
        args.package, versions, version_list,
        statistics, trend, output_dir,
        args.start_date, args.end_date
    )

    json_summary = generate_json_summary(
        args.package, versions, version_list,
        statistics, trend, output_dir,
        args.start_date, args.end_date
    )

    print(f"Markdown报告: {md_report}")
    print(f"JSON摘要: {json_summary}")
    print()
    print("✅ 最终报告生成完成!")

    return 0


if __name__ == '__main__':
    exit(main())

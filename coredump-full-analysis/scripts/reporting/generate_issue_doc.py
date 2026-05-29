#!/usr/bin/env python3
"""
生成问题文档脚本
为不可修复的崩溃生成详细的问题文档
"""

import json
import re
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='生成不可修复崩溃的问题文档',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  python3 generate_issue_doc.py --package dde-session-ui --version 1:5.9.6-1 --workspace /path/to/workspace
        '''
    )
    parser.add_argument(
        '--package',
        required=True,
        help='包名'
    )
    parser.add_argument(
        '--version',
        required=True,
        help='版本号'
    )
    parser.add_argument(
        '--workspace',
        required=True,
        help='工作目录'
    )

    return parser.parse_args()


def clean_version(version: str) -> str:
    """清理版本号"""
    version = re.sub(r'^1:', '', version)
    version = re.sub(r'-\d+$', '', version)
    return version


def markdown_escape(text: str) -> str:
    """转义Markdown特殊字符"""
    if not text:
        return ''
    # 转义: * _ ` [ ] ( ) # + - . !
    for char in '*\\`[]()#+-.!':
        text = text.replace(char, f'\\{char}')
    return text


def format_crash_details(crash: Dict) -> str:
    """格式化崩溃详情"""
    details = []

    # 基本信息
    details.append(f"**崩溃ID**: `{crash['id'][:50]}...`")
    details.append(f"**发生次数**: {crash.get('count', 1)}")
    details.append(f"**信号类型**: {crash.get('signal', 'N/A')}")

    if crash.get('signal_desc'):
        details.append(f"**信号说明**: {crash['signal_desc']}")

    # 应用层信息
    app_symbol = crash.get('app_layer_symbol') or 'N/A'
    details.append(f"**应用层函数**: `{markdown_escape(app_symbol)}`")

    app_library = crash.get('app_layer_library') or 'N/A'
    details.append(f"**应用层库**: `{app_library}`")

    # 关键帧信息
    if crash.get('key_frame'):
        key_frame = crash['key_frame']
        details.append(f"**关键帧**: 帧 #{key_frame['index']} `{markdown_escape(key_frame['symbol'])}` in `{key_frame['library']}`")

    # 不可修复原因
    if crash.get('fixable') is False and crash.get('fix_reason'):
        details.append(f"**不可修复原因**: {crash['fix_reason']}")

    # 崩溃描述
    if crash.get('description'):
        desc = crash['description'][:500]  # 限制长度
        details.append(f"**描述**: {markdown_escape(desc)}")

    # 系统版本信息
    if crash.get('sys_v_number'):
        details.append(f"**系统版本**: {crash['sys_v_number']}")

    return '\n'.join(details)


def format_stack_traces(crash: Dict) -> str:
    """格式化堆栈跟踪"""
    stack_info = crash.get('stack_info', '')
    if not stack_info:
        return "暂无堆栈信息"

    frames = stack_info.strip().split('\n')
    formatted_frames = []

    for frame in frames[:30]:  # 限制为前30帧
        formatted_frames.append(f"    {frame}")

    return '\n'.join(formatted_frames)


def generate_issue_content(crash: Dict, package: str, version: str) -> str:
    """生成问题文档内容"""
    crash_id_short = crash['id'][:10]

    content = f"# 崩溃问题文档: {crash_id_short}\n\n"
    content += f"**包名**: {package}\n\n"
    content += f"**版本**: {version}\n\n"

    # 基本信息
    content += "## 基本信息\n\n"
    content += format_crash_details(crash)
    content += "\n\n"

    # 崩溃详情
    content += "## 崩溃详情\n\n"
    if crash.get('description'):
        content += f"{markdown_escape(crash['description'])}\n\n"

    # 堆栈跟踪
    content += "## 堆栈跟踪\n\n"
    content += "```\n"
    content += format_stack_traces(crash)
    content += "```\n\n"

    # 分析结论
    content += "## 分析结论\n\n"
    if crash.get('fix_reason'):
        content += f"**原因**: {crash['fix_reason']}\n\n"

    content += "此崩溃位于系统库或第三方库中，在应用层面直接修复的难度较大。\n\n"

    # 关键帧分析
    if crash.get('key_frame'):
        key_frame = crash['key_frame']
        content += "## 关键帧分析\n\n"
        content += f"- **帧号**: #{key_frame['index']}\n"
        content += f"- **函数**: `{markdown_escape(key_frame['symbol'])}`\n"
        content += f"- **库**: `{key_frame['library']}`\n\n"

    # 建议处理方式
    content += "## 建议处理方式\n\n"

    # 根据信号类型给出建议
    signal = crash.get('signal', '')
    if signal == 'SIGSEGV':
        content += "1. **参数验证**: 检查应用代码中传递给库的参数是否正确\n"
        content += "   - 指针非空检查\n"
        content += "   - 数组边界检查\n\n"
        content += "2. **错误处理**: 添加对库函数返回值的检查\n"
        content += "   - 处理可能的错误码\n"
        content += "   - 设置超时和重试机制\n\n"
    elif signal == 'SIGABRT':
        content += "1. **assert检查**: 检查调用的库函数是否有前置条件\n"
        content += "   - 确保对象已正确初始化\n"
        content += "   - 验证状态机有效性\n\n"
        content += "2. **内存管理**: 检查对象生命周期\n"
        content += "   - 避免重复释放\n"
        content += "   - 确保析构顺序正确\n\n"
    elif signal == 'SIGBUS':
        content += "1. **数据对齐**: 检查传递给库的数据结构\n"
        content += "   - 确保内存对齐正确\n"
        content += "   - 使用pack属性控制结构体布局\n\n"
    else:
        content += "1. **日志记录**: 添加更详细的日志以定位问题\n"
        content += "2. **边界检查**: 添加输入参数验证\n"
        content += "3. **异常捕获**: 使用try-catch捕获可能的异常\n\n"

    # 通用建议
    content += "3. **上游反馈**: 如需上游修复，需要提供以下信息\n"
    content += "   - 完整的崩溃堆栈\n"
    content += "   - 可复现的测试用例\n"
    content += "   - 系统和库的版本信息\n\n"

    # 联系信息
    content += "## 联系信息\n\n"
    content += "如需进一步分析或协助，请联系崩溃分析团队。\n\n"

    content += "---\n\n"
    content += f"*文档生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n"

    return content


def generate_summary_index(package: str, version: str, output_dir: Path, issues: List[Dict]) -> str:
    """生成问题摘要索引"""
    total_issues = len(issues)
    total_count = sum(c.get('count', 1) for c in issues)

    content = f"# {package} 版本 {version} - 不可修复崩溃问题清单\n\n"
    content += f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    content += "---\n\n"

    content += "## 统计摘要\n\n"
    content += f"- **问题总数**: {total_issues}\n"
    content += f"- **崩溃总次数**: {total_count}\n\n"

    # 按信号类型统计
    signal_counts = {}
    for crash in issues:
        sig = crash.get('signal', 'UNKNOWN')
        signal_counts[sig] = signal_counts.get(sig, 0) + crash.get('count', 1)

    if signal_counts:
        content += "## 按信号类型分类\n\n"
        content += "| 信号类型 | 次数 |\n"
        content += "|---------|------|\n"
        for sig, count in sorted(signal_counts.items(), key=lambda x: -x[1]):
            content += f"| {sig} | {count} |\n"
        content += "\n"

    # 问题列表
    content += "## 问题列表\n\n"
    for i, crash in enumerate(issues, 1):
        crash_id_short = crash['id'][:10]
        doc_file = f"issue_{crash_id_short}.md"
        signal = crash.get('signal', 'N/A')
        count = crash.get('count', 1)
        reason = crash.get('fix_reason', '未知原因')[:50]

        content += f"### {i}. {crash_id_short}\n\n"
        content += f"- **信号**: {signal}\n"
        content += f"- **次数**: {count}\n"
        content += f"- **原因**: {reason}\n"
        content += f"- **文档**: [{doc_file}]({doc_file})\n\n"

    return content


def main():
    """主函数"""
    args = parse_args()

    print("=" * 80)
    print("生成不可修复崩溃的问题文档")
    print("=" * 80)
    print(f"包名: {args.package}")
    print(f"版本: {args.version}")
    print(f"工作目录: {args.workspace}")
    print()

    # 清理版本号
    version_clean = clean_version(args.version)
    version_dir = version_clean.replace('.', '_').replace('+', '_').replace('-', '_')

    # 读取分析结果
    analysis_file = Path(args.workspace) / '5.崩溃分析' / f'version_{version_dir}' / 'analysis.json'

    if not analysis_file.exists():
        print(f"错误: 分析文件不存在: {analysis_file}")
        print("请先运行 analyze_crash_per_version.py 进行崩溃分析")
        return 1

    with open(analysis_file, 'r', encoding='utf-8') as f:
        analysis = json.load(f)

    # 筛选不可修复的崩溃
    non_fixable_crashes = [c for c in analysis.get('crashes', []) if c.get('fixable') is False]

    if not non_fixable_crashes:
        print("没有不可修复的崩溃，无需生成问题文档")
        return 0

    # 输出目录
    output_dir = Path(args.workspace) / '5.崩溃分析' / f'version_{version_dir}' / 'issues'
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"找到 {len(non_fixable_crashes)} 个不可修复的崩溃")
    print()

    # 生成每个崩溃的问题文档
    for crash in non_fixable_crashes:
        crash_id_short = crash['id'][:10]
        doc_file = output_dir / f"issue_{crash_id_short}.md"

        content = generate_issue_content(crash, args.package, args.version)

        with open(doc_file, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"  生成文档: {doc_file.name}")

    # 生成汇总索引
    index_file = output_dir / 'issues_index.md'
    summary = generate_summary_index(args.package, args.version, output_dir, non_fixable_crashes)

    with open(index_file, 'w', encoding='utf-8') as f:
        f.write(summary)

    print()
    print(f"汇总索引: issues_index.md")
    print()
    print("✅ 问题文档生成完成!")

    return 0


if __name__ == '__main__':
    exit(main())

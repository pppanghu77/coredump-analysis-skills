#!/usr/bin/env python3
"""
dde-file-manager 崩溃堆栈分析器
融合自 crash-analysis skill 的 stack_analyzer.py

对分类后的每版本数据进行堆栈聚类，按问题领域归类，生成：
- analysis_{version}.csv         每个崩溃类型的详细分析
- analysis_{version}_keyword_stats.csv  按领域的统计汇总
"""
import re
import csv
import os
import sys
from collections import defaultdict
from difflib import SequenceMatcher
import multiprocessing as mp
import time
from pathlib import Path


# dde-file-manager 专属关键词与问题类型映射（按优先级）
PRIORITY_PATTERNS = [
    ('deepin_platform_plugin', 'deepin_platform_plugin问题'),
    ('(deleted)', '(deleted)问题'),
    ('Splitter', 'Splitter导致的dfmplugin_workspace析构问题'),
    ('getFileDisplayName', 'dfmplugin_workspace::getFileDisplayNam问题'),
    ('dfmio', 'dfm-io问题'),
    ('Thumbnail', '缩略图处理问题'),
    ('removePersistentIndex', '文件视图析构问题'),
    ('dfmplugin_workspace', '文管工作区问题'),
    ('libdfm-base', '文管base工作区问题'),
    ('FileView', '文件视图相关问题'),
]

KEYWORD_TO_TYPE = {k: v for k, v in PRIORITY_PATTERNS}


def extract_stack_traces(file_content):
    """从文本内容提取所有堆栈"""
    pattern = r'("Stack trace of thread \d+:.*?)(?="Stack trace of thread|\Z)'
    traces = re.findall(pattern, file_content, re.DOTALL)
    return [trace.strip().strip('"') for trace in traces if trace.strip()]


def get_stack_signature(trace):
    """获取堆栈特征签名，忽略地址"""
    lines = trace.split('\n')
    signature = []
    for line in lines[1:]:
        parts = line.strip().split()
        if len(parts) >= 2:
            func_and_lib = ' '.join(parts[2:])
            if func_and_lib and func_and_lib != 'n/a':
                signature.append(func_and_lib)
    return '\n'.join(signature)


def are_similar_stacks(stack1, stack2, threshold=0.9):
    """判断两个堆栈是否相似"""
    sig1 = get_stack_signature(stack1)
    sig2 = get_stack_signature(stack2)
    if sig1 == sig2:
        return True
    similarity = SequenceMatcher(None, sig1, sig2).ratio()
    return similarity >= threshold


def compare_trace_with_class(args):
    trace, class_representative = args
    return are_similar_stacks(class_representative, trace)


def classify_stacks(traces, processes=None, num_processes=None):
    """并行堆栈分类"""
    if num_processes is None:
        num_processes = mp.cpu_count()

    print(f"使用 {min(num_processes, len(traces))} 个核心进行分类...")

    classifications = defaultdict(list)
    process_classifications = defaultdict(list)

    if traces:
        classifications[0].append(traces[0])
        if processes:
            process_classifications[0].append(processes[0])

    with mp.Pool(processes=num_processes) as pool:
        for i, trace in enumerate(traces[1:], 1):
            if i % 100 == 0:
                print(f"  已处理 {i}/{len(traces)-1} 个堆栈...")

            found_match = False
            class_reps = [existing[0] for existing in classifications.values()]
            compare_args = [(trace, rep) for rep in class_reps]

            if compare_args:
                similarities = pool.map(compare_trace_with_class, compare_args)
                for class_id, is_similar in enumerate(similarities):
                    if is_similar:
                        classifications[class_id].append(trace)
                        if processes:
                            process_classifications[class_id].append(processes[i])
                        found_match = True
                        break

            if not found_match:
                new_id = len(classifications)
                classifications[new_id].append(trace)
                if processes:
                    process_classifications[new_id].append(processes[i])

    return classifications, process_classifications


def guess_crash_reason(stack_trace):
    """推测崩溃原因 - 按优先级匹配"""
    lines = stack_trace.split('\n')[1:]
    for keyword, reason in PRIORITY_PATTERNS:
        for line in lines[:20]:
            if keyword.lower() in line.lower():
                return reason
    return '未能确定具体原因'


def read_stack_from_csv(csv_file, stack_column='StackInfo', exe_column='Exe'):
    """从 CSV 读取堆栈和进程信息"""
    traces = []
    processes = []
    print(f"从 CSV 读取 {stack_column} 列...")

    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        if stack_column not in reader.fieldnames:
            raise ValueError(f"CSV 中未找到 '{stack_column}' 列。可用: {', '.join(reader.fieldnames)}")

        has_exe = exe_column in reader.fieldnames
        for row in reader:
            stack_info = row[stack_column]
            if stack_info and stack_info.strip():
                traces.append(stack_info.strip())
                processes.append(row.get(exe_column, 'Unknown') if has_exe else 'Unknown')

    print(f"读取了 {len(traces)} 条堆栈")
    return traces, processes


def write_analysis_results(classifications, output_file, process_classifications=None):
    """写入分析结果 CSV"""
    crashes = []

    for class_id, traces in classifications.items():
        sample_trace = traces[0]
        summary = '\n'.join(sample_trace.split('\n')[1:6])
        suspected_reason = guess_crash_reason(sample_trace)

        # 进程频次统计
        process_stats = ''
        if process_classifications and class_id in process_classifications:
            proc_list = process_classifications[class_id]
            proc_counts = defaultdict(int)
            for proc in proc_list:
                pname = proc.split('/')[-1] if proc else 'Unknown'
                proc_counts[pname] += 1
            sorted_procs = sorted(proc_counts.items(), key=lambda x: x[1], reverse=True)
            process_stats = '; '.join([f"{n}({c})" for n, c in sorted_procs])

        # 收集最多 5 个堆栈样本
        all_traces_info = []
        for trace in traces[:5]:
            all_traces_info.append(trace)
        all_traces_str = "\n\n====================\n\n".join(all_traces_info)

        crash_info = {
            'type': f'Type {class_id + 1}',
            'count': len(traces),
            'summary': summary,
            'reason': suspected_reason,
            'process_stats': process_stats,
            'full_trace': sample_trace,
            'all_traces': all_traces_str
        }
        crashes.append(crash_info)

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow([
            'Crash Type', 'Count', 'Stack Summary', 'Suspected Reason',
            'Process Stats', 'Full Stack Trace', 'All Traces (Max 5)', 'Notes'
        ])
        for crash in crashes:
            writer.writerow([
                crash['type'], crash['count'], crash['summary'],
                crash['reason'], crash['process_stats'],
                crash['full_trace'], crash['all_traces'], ''
            ])

    known = sum(1 for c in crashes if c['reason'] != '未能确定具体原因')
    print(f"  分类: {len(crashes)} 种类型, 已知: {known}, 未知: {len(crashes) - known}")
    print(f"  已写入: {output_file}")

    # 生成关键词统计
    stats_file = output_file.replace('.csv', '_keyword_stats.csv')
    write_keyword_stats(classifications, stats_file, process_classifications)

    return crashes


def write_keyword_stats(classifications, output_file, process_classifications=None):
    """生成按领域的统计表"""
    reason_stats = defaultdict(int)
    reason_processes = defaultdict(list)
    unknown_count = 0
    unknown_processes = []
    total_crashes = 0

    for class_id, traces in classifications.items():
        sample_trace = traces[0]
        suspected_reason = guess_crash_reason(sample_trace)
        trace_count = len(traces)
        total_crashes += trace_count

        procs = process_classifications.get(class_id, []) if process_classifications else []

        if suspected_reason == '未能确定具体原因':
            unknown_count += trace_count
            unknown_processes.extend(procs)
        else:
            reason_stats[suspected_reason] += trace_count
            reason_processes[suspected_reason].extend(procs)

    reason_to_keyword = {v: k for k, v in KEYWORD_TO_TYPE.items()}

    def format_proc_stats(process_list):
        proc_counts = defaultdict(int)
        for proc in process_list:
            pname = proc.split('/')[-1] if proc else 'Unknown'
            proc_counts[pname] += 1
        sorted_procs = sorted(proc_counts.items(), key=lambda x: x[1], reverse=True)
        total = len(process_list) or 1
        return '; '.join([f"{n}({c}, {c/total*100:.1f}%)" for n, c in sorted_procs])

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(['Keyword', 'Issue Type', 'Total Count', 'Percentage', 'Process Stats'])

        sorted_stats = sorted(reason_stats.items(), key=lambda x: x[1], reverse=True)
        for reason, count in sorted_stats:
            keyword = reason_to_keyword.get(reason, 'Unknown')
            percentage = f"{count / total_crashes * 100:.2f}%"
            writer.writerow([keyword, reason, count, percentage,
                             format_proc_stats(reason_processes[reason])])

        if unknown_count > 0:
            writer.writerow(['Unknown', '未能确定具体原因', unknown_count,
                             f"{unknown_count / total_crashes * 100:.2f}%",
                             format_proc_stats(unknown_processes)])

        all_procs = []
        for procs in reason_processes.values():
            all_procs.extend(procs)
        all_procs.extend(unknown_processes)
        writer.writerow(['Total', '全部问题', total_crashes, '100.00%',
                         format_proc_stats(all_procs)])

    print(f"  关键词统计: {output_file}")


def analyze_csv(input_path, output_dir):
    """对单个 CSV 进行堆栈分析"""
    traces, processes = read_stack_from_csv(input_path)

    if not traces:
        print("  警告: 无堆栈数据，跳过")
        return None

    if len(traces) > 50:
        classifications, proc_classes = classify_stacks(traces, processes)
    else:
        print("  使用串行分类...")
        # fallback 串行
        classifications = defaultdict(list)
        proc_classes = defaultdict(list)
        if traces:
            classifications[0].append(traces[0])
            if processes:
                proc_classes[0].append(processes[0])
        for i, trace in enumerate(traces[1:], 1):
            found = False
            for cid, existing in classifications.items():
                if are_similar_stacks(existing[0], trace):
                    classifications[cid].append(trace)
                    if processes:
                        proc_classes[cid].append(processes[i])
                    found = True
                    break
            if not found:
                nid = len(classifications)
                classifications[nid].append(trace)
                if processes:
                    proc_classes[nid].append(processes[i])

    os.makedirs(output_dir, exist_ok=True)
    base_name = Path(input_path).stem
    output_file = os.path.join(output_dir, f"analysis_{base_name}.csv")
    return write_analysis_results(classifications, output_file, proc_classes)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='dde-file-manager 堆栈分析器')
    parser.add_argument('-i', '--input', type=str, required=True, help='输入 CSV 文件路径')
    parser.add_argument('-o', '--output', type=str, default='analysis_results.csv', help='输出文件路径')
    parser.add_argument('-c', '--column', type=str, default='StackInfo', help='堆栈列名 (默认: StackInfo)')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"错误: 文件 '{args.input}' 不存在")
        sys.exit(1)

    start_time = time.time()

    traces, processes = read_stack_from_csv(args.input, args.column)
    if not traces:
        print("错误: 未找到任何堆栈信息")
        sys.exit(1)

    if len(traces) > 50:
        classifications, proc_classes = classify_stacks(traces, processes)
    else:
        classifications = defaultdict(list)
        proc_classes = defaultdict(list)
        if traces:
            classifications[0].append(traces[0])
            if processes:
                proc_classes[0].append(processes[0])
        for i, trace in enumerate(traces[1:], 1):
            found = False
            for cid, existing in classifications.items():
                if are_similar_stacks(existing[0], trace):
                    classifications[cid].append(trace)
                    if processes:
                        proc_classes[cid].append(processes[i])
                    found = True
                    break
            if not found:
                nid = len(classifications)
                classifications[nid].append(trace)
                if processes:
                    proc_classes[nid].append(processes[i])

    print(f"分类为 {len(classifications)} 种类型")

    output_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(output_dir, exist_ok=True)
    write_analysis_results(classifications, args.output, proc_classes)

    elapsed = time.time() - start_time
    print(f"总耗时: {elapsed:.2f} 秒")

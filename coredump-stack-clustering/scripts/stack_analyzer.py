#!/usr/bin/env python3
"""
dde-file-manager 崩溃堆栈分析器
融合自 crash-analysis skill 的 stack_analyzer.py

对分类后的每版本数据进行堆栈聚类，生成：
- analysis_{version}.csv         每个崩溃类型的详细分析（含百分比）
"""
import hashlib
import re
import csv
import os
import sys
from collections import defaultdict
from difflib import SequenceMatcher
import multiprocessing as mp
import time
from pathlib import Path


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


def are_similar_stacks(stack1, stack2, threshold=0.75):
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


def clean_stack_trace(trace):
    """去掉堆栈中的线程号、帧号、虚拟地址和偏移量，保留函数名和库信息"""
    import re as _re
    lines = trace.split('\n')
    cleaned = []
    for line in lines:
        # 去掉线程号 (如 "Thread 12345" 或 "thread 42")
        line = _re.sub(r'[Tt]hread\s+\d+', '', line)
        # 去掉帧号 (如 "#0 " 或 "#123 ")
        line = _re.sub(r'#\d+\s*', '', line)
        # 去掉 0x 开头的十六进制地址
        line = _re.sub(r'0x[0-9a-fA-F]+', '', line)
        # 去掉 +0x 偏移量
        line = _re.sub(r'\+0x[0-9a-fA-F]+', '', line)
        # 去掉单独的 +数字 偏移
        line = _re.sub(r'\+\d+', '', line)
        # 压缩多余空格
        line = _re.sub(r'\s+', ' ', line).strip()
        cleaned.append(line)
    return '\n'.join(cleaned)


# 噪声库：跨版本 hash 时跳过这些帧，避免公共库帧导致过度分裂
NOISE_LIBS = ['libc.so', 'libc-', 'libstdc++', 'libgcc_s', 'n/a', 'linux-vdso']


def stable_hash(clean_trace, top_n=None):
    """对完整 cleaned stack 全部帧做 hash，实现跨版本稳定且精确的追踪。

    设计要点：
    - clean_stack_trace 已统一去除线程号/帧号/十六进制地址/偏移，剩余的
      "函数名 + 库路径"序列本身就是崩溃的稳定特征，可直接参与 hash。
    - 不再额外过滤 NOISE_LIBS：早期为避免公共库帧导致过度分裂才过滤，但
      clean 后已无地址偏移，过滤纯属多余；更严重的是对"符号缺失(n/a 占满)
      的崩溃"，过滤会掏空整栈，导致完全不同的崩溃塌缩成同一个 hash
      （实测 b3a43a1512f8 曾把 26 种不同栈误并为 1 个，趋势严重失真）。
    - top_n：保留参数以兼容旧调用；默认 None 表示用全部帧（不截断）。
    - 极端空栈回退用原始 cleaned 文本，避免空 hash。
    """
    lines = [ln for ln in clean_trace.split('\n') if ln.strip()]
    if top_n is not None:
        lines = lines[:top_n]
    text = '\n'.join(lines) if lines else (clean_trace[:200] or '_empty_')
    return hashlib.sha256(text.encode()).hexdigest()[:12]


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
        clean_trace = clean_stack_trace(sample_trace)
        type_hash = stable_hash(clean_trace)

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
            'type': type_hash,
            'count': len(traces),
            'summary': summary,
            'process_stats': process_stats,
            'full_trace': sample_trace,
            'clean_trace': clean_trace,
            'all_traces': all_traces_str
        }
        crashes.append(crash_info)

    # 按数量降序排列
    crashes.sort(key=lambda c: c['count'], reverse=True)

    total = sum(c['count'] for c in crashes)

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow([
            'Crash Hash', 'Count', 'Percentage', 'Stack Summary',
            'Process Stats', 'Full Stack Trace', 'Cleaned Stack (No Addr)',
            'All Traces (Max 5)', 'Notes'
        ])
        for crash in crashes:
            percentage = f"{crash['count'] / total * 100:.2f}%"
            writer.writerow([
                crash['type'], crash['count'], percentage, crash['summary'],
                crash['process_stats'],
                crash['full_trace'], crash['clean_trace'],
                crash['all_traces'], ''
            ])

    print(f"  分类: {len(crashes)} 种类型")
    print(f"  已写入: {output_file}")

    return crashes


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

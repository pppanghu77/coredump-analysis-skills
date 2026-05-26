#!/usr/bin/env python3
"""dde-clipboard cluster-level automatic fix plans and actions."""

from pathlib import Path
from typing import Dict

from auto_fix_types import CrashCluster, FixPlan, FixResult
from fixers.common import apply_replacements, file_contains_all


def get_fix_specs() -> Dict[str, Dict]:
    return {}


def build_fix_plan_for_cluster(cluster: CrashCluster) -> FixPlan:
    # All known dde-clipboard crash patterns occur in system libraries
    # (Qt/XCB), with no safe application-layer fix point.
    # Every cluster falls through to conservative analysis.
    return FixPlan(
        cluster_id=cluster.cluster_id,
        action="record_conservative_analysis_only",
        confidence="low",
        target_files=[],
        commit_subject=f"[coredump-analysis] analyze: {cluster.title}",
        root_cause=(
            f"{cluster.title} 已完成自动聚类。"
            "dde-clipboard 的可修复崩溃均发生在系统库（Qt XCB / libX11 / atspi）中，"
            "应用层没有安全的直接修复点。"
        ),
        fix_description="记录自动分析结果，不修改源码。",
        influence="请结合该根因簇的代表堆栈继续验证，建议向上游 Qt/XCB 或系统层排查。",
    )


def is_fix_present(code_dir: Path, plan: FixPlan) -> bool:
    return False


def apply_fix_plan(code_dir: Path, plan: FixPlan) -> FixResult:
    if is_fix_present(code_dir, plan):
        return FixResult(plan.cluster_id, plan.action, False, "local source already contains equivalent fix", plan.target_files)
    return record_conservative_analysis_only(code_dir, plan)


def record_conservative_analysis_only(_code_dir: Path, plan: FixPlan) -> FixResult:
    del _code_dir
    return FixResult(plan.cluster_id, plan.action, False, "no safe local source edit for this cluster", [])

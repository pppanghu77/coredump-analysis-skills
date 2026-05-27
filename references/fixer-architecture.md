# Auto-Fix Pipeline Architecture & Coverage

Analysis of `auto_fix_submit.py`, `cluster_crashes.py`, and the package fixer modules. Captures what currently produces real Gerrit commits, what only produces analysis-report fallback commits, and where the dispatcher still has coverage gaps.

## Pipeline Flow

```text
analyze_crash_complete.sh (step 6)
  └─ auto_fix_submit.py --package X --version V --workspace W
       │
       ├─ Has cluster fixer? (fixers/<pkg>.py with build_fix_plan_for_cluster + apply_fix_plan)
       │   ├─ YES → run_cluster_auto_fix()
       │   │         ├─ cluster_crashes(package, crashes) → list of CrashCluster
       │   │         ├─ For each cluster:
       │   │         │   ├─ build_fix_plan_for_cluster(cluster) → FixPlan
       │   │         │   ├─ apply_fix_plan(code_dir, plan) → FixResult
       │   │         │   │   ├─ is_fix_present() → if already fixed locally, skip edit
       │   │         │   │   └─ apply_<action>() or record_conservative_analysis_only()
       │   │         │   ├─ If FixResult.changed → create_commit(build_cluster_commit_message(...))
       │   │         │   └─ If !changed → record as analysis_only
       │   │         ├─ If any cluster commit was created → push_to_gerrit()
       │   │         ├─ If no cluster produced code changes but fixable clusters exist:
       │   │         │     generate coredump-analysis-report.md → commit → push_to_gerrit
       │   │         └─ Save auto_fix_clusters_result.json
       │   │
       │   └─ NO → spec-based path
       │             ├─ get_fix_specs(package) → {pattern: spec, ...}
       │             ├─ For each fixable crash:
       │             │   ├─ resolve_fix_spec_for_crash(specs, crash)
       │             │   ├─ Check fixed_commits against target branch
       │             │   ├─ If already fixed → already_fixed
       │             │   ├─ If has auto_fixer=cherry_pick_known_fix → queue preferred commit
       │             │   └─ Else → manual_required
       │             ├─ Cherry-pick unique preferred commits → push_to_gerrit
       │             ├─ If no auto-fix applied but fixable crashes exist:
       │             │     generate coredump-analysis-report.md → commit → push_to_gerrit
       │             └─ Save auto_fix_result.json
       │
       └─ Result:
            cluster path → {auto_fixed, analysis_only, submitted, analysis_report?}
            spec path    → {already_fixed, auto_fixed, manual_required, submitted, analysis_report?}
```

## Dispatcher Gate: Cluster Path Wins First

This is the most important current behavior in `auto_fix_submit.py`:

- if a package has both `get_package_fix_plan_builder(package)` and `get_package_fix_applier(package)`, the script enters `run_cluster_auto_fix(...)`
- after the cluster path finishes, `main()` returns immediately
- the spec-based path below it is not executed for that package in the same run

Practical consequence:
- packages with cluster fixers do not currently benefit from `get_fix_specs()` inside the normal `auto_fix_submit.py` dispatcher
- `dde-launcher` still defines a substantial `get_fix_specs()` table, but its normal automation path is currently the cluster path, not the spec path

So when evaluating effective coverage, distinguish between:
- metadata that exists in fixer modules
- behavior that is actually reachable through the current dispatcher

## Two Execution Modes

### Path A: Cluster-Level Fixers

Packages with `fixers/<pkg>.py` exporting both `build_fix_plan_for_cluster` and `apply_fix_plan` use deterministic cluster handling.

Current cluster-fixer packages:
- `dde-dock`
- `dde-launcher`
- `dde-control-center`
- `dde-clipboard`
- `dde-polkit-agent`
- `startdde`

`cluster_crashes.py` classifies crashes with `KNOWN_CLUSTER_RULES`, then falls back to a generated key like `<signal>-<symbol>` for unmatched cases.

### Path B: Spec-Level Fixers

Packages without a cluster fixer use `get_fix_specs()`.

Current state:
- `fixers/common.py:get_fix_specs()` returns `{}`
- most packages still have no package-specific spec rules
- this path only becomes effective when a package does not hit the cluster-fixer gate and also provides explicit spec rules
- today this is a relatively narrow path compared with cluster handling

## Current Fixer Coverage

### Cluster Rules

`cluster_crashes.py` currently defines **24 deterministic cluster rules**.

Coverage areas include:
- D-Bus lifecycle crashes
- Qt object lifetime / event-loop crashes
- X11/XCB connection crashes
- updater watcher cleanup families
- qsocketnotifier / qscroller / qmenu / qhash / pixmap-cache families
- atspi / native-event-filter / deepin platform plugin related crashes

### Package Coverage Snapshot

| Package | Has Cluster Fixer | Effective Current Behavior |
|---------|-------------------|----------------------------|
| dde-dock | Yes | 6 concrete code-changing fix plans + conservative fallback |
| dde-launcher | Yes | Cluster path is conservative analysis-only; `get_fix_specs()` exists but is not used by the normal dispatcher while cluster fixer entry points are present |
| dde-control-center | Yes | 2 explicit code-changing plan entries that converge to one edit action + conservative fallback |
| dde-clipboard | Yes | Conservative analysis-only for all clusters |
| dde-polkit-agent | Yes | Conservative analysis-only for all clusters |
| startdde | Yes | Conservative analysis-only for all clusters |
| Other packages | No | Depend on spec path; most currently have no registered fix specs |

### Concrete Cluster Fixers

#### dde-dock

`fixers/dde_dock.py` currently maps 6 cluster keys to code edits:
1. `appitem-dbus-property-read`
2. `pluginlistview-qscroller-dtor`
3. `dock-context-menu-qwindow-dtor`
4. `xrecord-x11-io-error`
5. `dock-application-notify-cast`
6. `speed-plugin-update-tip`

Unmatched dock clusters fall back to `record_conservative_analysis_only`.

#### dde-control-center

`fixers/dde_control_center.py` currently has 5 explicit cluster entries:
- `updater-dbus-pending-watchers-crash` → code-changing fixer
- `updater-dbus-watchers-dtor` → code-changing fixer
- `dmainwindow-dtor-crash` → conservative
- `dbus-disconnect-notify-crash` → conservative
- `wallpaper-provider-dtor` → conservative

Both updater watcher keys converge to the same edit action: `apply_updater_dbus_watcher_cleanup`.

Important nuance:
- `cluster_crashes.py` also defines a broad cluster key named `updater-dbus-pending-watchers-wide`
- that key name does not currently have a dedicated explicit entry in `fixers/dde_control_center.py`
- therefore it falls through to the package default conservative fallback unless the crash also matches one of the explicitly handled updater keys

#### dde-launcher

`fixers/dde_launcher.py` exports both cluster plans and a large `get_fix_specs()` table, but under the current dispatcher these serve uneven roles:

- cluster plans are the effective path in normal runs
- those cluster plans are intentionally conservative for Qt/libdbus/XCB/system-library crashes
- `get_fix_specs()` contains many `cherry_pick_known_fix` mappings for known upstream fixes
- however those spec mappings are not normally reached while the package still satisfies the cluster-fixer gate in `auto_fix_submit.py`

So the codebase contains launcher spec knowledge, but the normal dispatcher currently behaves as conservative cluster analysis plus analysis-report fallback.

#### Conservative-Only Packages

`dde-clipboard`, `dde-polkit-agent`, and `startdde` currently route every cluster to `record_conservative_analysis_only` because known fixable crashes are considered to occur in system libraries or lack a safe application-layer edit point.

## Analysis Report Fallback

A key behavior change is that "no safe code edit" no longer means "no Gerrit output".

`auto_fix_submit.py` now generates and submits `coredump-analysis-report.md` when:

1. Cluster path:
   - `auto_fixed` is empty
   - `analysis_only` is non-empty
   - there are fixable clusters worth recording

2. Spec path:
   - `auto_fixed` is empty
   - `manual_required` is non-empty
   - `fixable_crashes` is non-empty

This ensures fixable-but-non-mechanical crashes still produce a review artifact in Gerrit for human follow-up.

## Gerrit Commit Subject Rule

All crash-analysis-related Gerrit commit subjects should carry the `[coredump-analysis]` prefix.

Verified current behavior:
- cluster-fixer `FixPlan.commit_subject` values in
  - `fixers/dde_dock.py`
  - `fixers/dde_launcher.py`
  - `fixers/dde_control_center.py`
  - `fixers/dde_clipboard.py`
  - `fixers/dde_polkit_agent.py`
  - `fixers/startdde.py`
  all include `[coredump-analysis]`
- fallback analysis-report commits generated in `auto_fix_submit.py` use a subject beginning with:
  - `[coredump-analysis] <package> v<version>: add crash analysis report`
- `deep_auto_fix.py` generates commit messages beginning with:
  - `[coredump-analysis] fix: ...`

Important distinction:
- `generate_gerrit_web_report.py` only reads and displays `commit_subject`; it does not generate commit titles itself

## Why "Fixable" May Still Not Mean "Auto-Patched"

Common reasons:
1. crash matched a cluster rule, but that cluster only has conservative handling
2. crash reached a package with a cluster fixer, so package `get_fix_specs()` metadata was bypassed by the dispatcher
3. crash reached the spec path, but no package `get_fix_specs()` exists
4. spec exists, but no supported `auto_fixer` was registered for the matched case
5. spec exists with `cherry_pick_known_fix`, but preferred commit is absent or cherry-pick conflicts
6. crash is fixable at analysis level, but a safe local source edit cannot be determined automatically

So the current system should be understood as:
- `fixable` = likely actionable root cause
- `auto_fixed` = a safe deterministic code edit or successful cherry-pick action exists
- otherwise fallback = submit analysis report instead of silently dropping it

## Coverage Gap Framing

Do not treat "generated Gerrit change" as a single bucket.

Current interpretation should distinguish:
- real code-changing auto-fix commits
- cherry-pick based auto-fix commits
- analysis-report fallback commits

A package may still produce useful Gerrit output even when every cluster is conservative, but that does not mean a real source-code crash fix was submitted.

## Highest-Value Expansion Directions

1. decide whether cluster-fixer packages such as `dde-launcher` should also be allowed to consume `get_fix_specs()` in the normal dispatcher
2. add an explicit mapping for `updater-dbus-pending-watchers-wide` if it is intended to reuse the updater watcher cleanup path
3. expand package-specific `get_fix_specs()` for packages that currently have neither cluster fixers nor usable spec rules
4. convert repeated conservative cluster families into safe mechanical fixers where source edit points become stable
5. continue growing `KNOWN_CLUSTER_RULES` so more crashes land in meaningful root-cause buckets
6. keep reporting/metrics separated into:
   - code edits applied
   - cherry-picks applied
   - analysis-only report submissions

## Detection Commands

```bash
# Check cluster rule count
python3 - <<'PY'
import ast, pathlib
p = pathlib.Path('coredump-full-analysis/scripts/cluster_crashes.py')
mod = ast.parse(p.read_text(encoding='utf-8'))
for node in mod.body:
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if getattr(t, 'id', None) == 'KNOWN_CLUSTER_RULES':
                print(len(node.value.elts))
PY

# Inspect whether a package has cluster fixer entry points
grep -n 'build_fix_plan_for_cluster\|apply_fix_plan\|get_fix_specs' \
  coredump-full-analysis/scripts/fixers/*.py

# Check whether analysis report fallback exists
grep -n 'coredump-analysis-report\|analysis_report' \
  coredump-full-analysis/scripts/auto_fix_submit.py

# Check current commit-subject prefix coverage
grep -RFn '\[coredump-analysis\]' \
  coredump-full-analysis/scripts/fixers \
  coredump-full-analysis/scripts/auto_fix_submit.py \
  coredump-full-analysis/scripts/deep_auto_fix.py
```

# Automatic Deep-Dive Policy

Session update: expanded enhanced-analysis deep-dive behavior from "uncertain only" to a broader automatic trigger policy, and raised default addr2line depth.

## Code locations

- `coredump-full-analysis/scripts/analyze_crash_complete.sh`
- `coredump-full-analysis/scripts/analyze_crash_per_version.py`
- `coredump-full-analysis/scripts/enhanced_analysis.py`

## New defaults

- `ADDR2LINE_MAX_FRAMES` shell default: `300`
- `--addr2line-max-frames` CLI default: `300`
- `EnhancedAnalyzer(..., max_addr2line_frames=300)` default: `300`
- automatic second-pass deep dive therefore uses at least `max(300*2, 200) = 600` frames

## Trigger policy

Automatic second-pass deep dive now runs when any of these are true:

1. `crash['fixable'] == 'uncertain'`
2. app-layer signal is present:
   - non-empty `app_layer_symbol`, or
   - package-owned `key_frame.symbol`, or
   - package-owned `key_frame.library`
3. high-frequency crash:
   - `int(crash.get('count') or 0) >= 3`

## New helpers

Implemented in `enhanced_analysis.py`:

- `_has_app_layer_signal(crash)`
- `_get_deep_dive_reasons(crash)`
- `_run_targeted_deep_dive(crash, frames, base_a2l, reasons)`

## Reporting changes

Markdown reports now use:
- `自动二次深挖`

instead of:
- `uncertain 二次深挖`

because second-pass deep dive is no longer restricted to uncertain crashes.

## New degradation markers

- `deep_dive_exhausted`
- `deep_dive_no_gain`

These supersede the old `uncertain_deep_dive_*` naming.

## Validation performed in session

- `python3 -m py_compile enhanced_analysis.py analyze_crash_per_version.py` passed
- grep verification confirmed the new defaults, trigger helpers, and report wording
- real regression runs validated the behavior on `dde-launcher 5.7.25.1` and `dde-dock 5.9.1`

## Operational implication

This increases analysis cost but improves the chance of converting high-frequency Qt/DBus/XCB/app-layer stacks into source-owned, patchable findings without requiring manual reruns.

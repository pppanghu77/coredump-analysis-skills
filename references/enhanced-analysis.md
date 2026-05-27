# Enhanced Analysis — Techniques, Pitfalls & Design Decisions

Detailed reference for `coredump-full-analysis/scripts/enhanced_analysis.py` and its integration.

## 1. Addr2Line Resolution

### DWARF Corruption (UOS Universal Problem)

UOS dbgsym packages have **corrupted DWARF debug sections**. Every addr2line invocation against a UOS dbgsym produces:

```
addr2line: DWARF error: section .debug_info is larger than its filesize!
```

This means addr2line can demangle the function name but **cannot resolve file:line**. The output becomes:
```
func_name 于 ??:?
```

### Chinese Locale Handling

On UOS systems, addr2line outputs Chinese locale:
- `于 ??:?` instead of `at ??:?`
- The parser must handle both. In `enhanced_analysis.py`, the regex matches `于` as a separator.

### Partial Resolution Workaround

When addr2line returns only a function name (no file:line), the system falls back to **source code search**:

1. Demangle the function name to get the qualified name (e.g., `PluginListView::rowsInserted`)
2. Search the source repo for that exact qualified name using grep
3. **Priority order**: `.cpp` definition files > `.h` header files
4. Read surrounding source context from the matched file
5. Mark frame as `partial_with_source` instead of just `partial`

### Source Search Strategy

Always search the **qualified name** first (e.g., `PluginListView::rowsInserted`), not just the method name (`rowsInserted`). A simple method name matches too many files — headers, tests, mocks, unrelated classes.

```python
# WRONG: simple grep for function name alone
# "rowsInserted" matches too many files (headers, tests, mocks)

# RIGHT: search qualified name first
grep -rn "PluginListView::rowsInserted" source_dir/

# Then try class-only if qualified name finds nothing
grep -rn "rowsInserted" source_dir/ --include="*.cpp"
```

**Key decision**: Always prefer `.cpp` over `.h`. A function defined in a `.cpp` file is more useful for blame/context than a declaration in a header.

### find(1) Locale Pitfall

Running `find` with `-type f` on UOS with non-C locale produces garbled error messages. Fix:

```python
env = os.environ.copy()
env['LC_ALL'] = 'C'  # Must set for find commands
```

## 2. Binary File Resolution

### Search Order

`BinaryResolver` looks for library files in this order:

1. Exact path from stack frame (e.g., `/usr/lib/dde-dock/plugins/libeye-comfort-mode.so`)
2. Standard system paths: `/usr/lib/`, `/usr/lib/x86_64-linux-gnu/`
3. Package-specific plugin paths (e.g., `/usr/lib/dde-dock/plugins/`)
4. Debug files via build-id: `/usr/lib/debug/.build-id/XX/YYYYYY.debug`
5. If a build-id is available, also try debuginfod

### Plugin Libraries

DDE plugins live in non-standard paths:
- `/usr/lib/dde-dock/plugins/*.so`
- `/usr/lib/dde-control-center/plugins/*.so`
- `/usr/lib/dde-launcher/plugins/*.so`

These are **not** in standard `LD_LIBRARY_PATH` or dpkg-tracked paths. The resolver has hardcoded search paths for known plugin directories.

### Build-ID Path Format

```
/usr/lib/debug/.build-id/ab/cdef1234567890abcdef1234567890abcdef1234.debug
                              ^^ first 2 hex chars  ^^ rest
```

## 3. Git Blame / Log Analysis

### Applicable Frames

Git analysis runs on frames with status `ok` (full resolution with line number) OR `partial_with_source` (function name matched to source file).

For `partial_with_source` frames, the analyzer must **find the function definition line** within the matched source file. This uses a grep for the function/class-qualified name and returns the first match line number.

### Git Blame Output Format

```
9fa42306 (chujiaqi@uniontech.com 2025-09-15 14:23:01 +0800 123) PluginListView::rowsInserted(...)
```

Format: `<commit_hash> (<author> <date> <line_number>) <line_content>`

### Git Log Output

For the blamed commit, `git log -1 --format=...` extracts:
- Commit hash
- Author
- Date
- Commit message (subject line)

## 4. Objdump Disassembly

### Trigger Condition

Objdump only runs when the original analysis has identified a `key_frame`. Without knowing which frame is the crash point, disassembly is meaningless.

## 7. Frame Window and Deep-Stack Coverage

Enhanced addr2line resolution is no longer hardcoded to the first 20 frames. The frame window is now configurable via `--addr2line-max-frames <n>` and currently defaults to **300** in `analyze_crash_complete.sh` / `analyze_crash_per_version.py`.

Use a higher value when:
- the meaningful app-layer frame is buried deep under Qt / GLib / signal / event-loop frames
- the first 20 frames are all wrapper/system frames
- you are diagnosing crashes with repeated dispatcher / callback nesting

## 8. Partial Resolution Is Still Actionable

On UOS, full file:line resolution often fails because DWARF is corrupted, but `partial_with_source` (function name + source file found by qualified-name search) is still valuable. Treat it as a usable source hit, not as a failed analysis.

Updated behavior:
- `partial_with_source` now counts as a usable source frame for fixability improvement
- enhanced analysis should continue root-cause inference when only `partial_with_source` is available
- do not require `status == ok` exclusively before trying source-based heuristics

## 9. Degradation Reasons Must Be Surfaced

When enhanced analysis cannot go deeper, record **why** instead of silently falling back. Current per-crash degradation reasons include:
- `no_parsed_frames`
- `no_addr2line_results`
- `library_not_found`
- `missing_frame_offset`
- `addr2line_timeout`
- `addr2line_error`
- `addr2line_unresolved`
- `source_context_unavailable`
- `no_resolved_source_frames`
- `objdump_not_available`
- `git_analysis_unavailable`
- `debuginfod_unavailable`
- `llm_analysis_unavailable`

Check these fields first when a report looks "shallow".

### Output Format

8 instructions before + the target instruction + 8 instructions after:

```
0x00007f8a1b2c3d40:  48 8b 45 f8          mov    -0x8(%rbp),%rax
0x00007f8a1b2c3d44:  48 89 c7             mov    %rax,%rdi   <- crash at this offset
0x00007f8a1b2c3d47:  e8 00 00 00 00       call   ...
```

## 5. Debuginfod Client

### How It Works

Sends HTTP GET to known debuginfod servers with the build-id:

```
https://debuginfod.ubuntu.com/buildid/<build-id>/debuginfo
```

### Known Servers

1. `https://debuginfod.ubuntu.com` — Ubuntu packages
2. `https://debuginfod.debian.net` — Debian packages

UOS packages have unique build-ids not found on Ubuntu/Debian servers, so debuginfod typically returns 404 for UOS. But it's useful when a crash involves a standard system library.

## 6. LLM Stack Analysis

### When It Runs

LLM stack analysis remains an optional late-stage aid for crashes that still need extra reasoning after the deterministic passes. It is independent from the automatic second-pass deep dive trigger policy. Requires an LLM API key configured in the environment.

### What It Does

Sends the full stack trace to an LLM with a structured prompt asking for:
1. Root cause classification (null deref, use-after-free, double-free, etc.)
2. Which frame is most likely the crash point
3. Suggested fix approach
4. Confidence level

### Result Integration

If LLM returns high confidence (>0.7), the crash's `fixable` status is upgraded from `uncertain` to a specific pattern.

## Key Environment Constraints

| Tool | Available | Notes |
|------|-----------|-------|
| `addr2line` | Yes | Via binutils, handles Chinese locale |
| `objdump` | Yes | Via binutils |
| `readelf` | Yes | Via binutils |
| `eu-addr2line` | No | Not installed (elfutils) |
| `debuginfod-find` | No | Not installed (elfutils) |
| `git` | Yes | Required for blame/log |
| `python3 requests` | Yes | For debuginfod HTTP |

## Stack Frame Parsing

Raw StackInfo format:
```
#0 0x7f8a1b2c3d4e symbol_name (libname.so + 0xOFFSET)
```

Parsing regex extracts:
- Frame number (`#0`)
- Address (`0x7f8a1b2c3d4e`)
- Symbol name (`symbol_name`, may be mangled)
- Library name (`libname.so`)
- Offset (`0xOFFSET`)

The offset is used for addr2line: `addr2line -e <binary> -C -f <hex_offset>`

## Automated Fixability Improvement

The enhanced analyzer can upgrade crash fixability assessment:

| Before | After | Trigger |
|--------|-------|---------|
| `uncertain` | `fixable` (null_deref) | Source context shows null pointer access pattern |
| `uncertain` | `fixable` (use_after_free) | Source context shows dangling pointer usage |
| `uncertain` | `manual_required` | LLM analysis with low confidence |

This reduces the number of crashes requiring manual review.

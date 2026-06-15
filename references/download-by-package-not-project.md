# Download by package name, not project name

Durable workflow rule confirmed by user:
- Crash-data download from Metabase must always filter by package name.
- Do not substitute the Gerrit project name into the download step.

Why this matters
- The analysis pipeline may use `project:package` mappings in `packages.txt`.
- Those mappings serve two different purposes:
  1. package name → Metabase crash-data filter
  2. project name → source checkout / Gerrit branch operations
- Mixing them causes incorrect or empty crash-data retrieval.

Correct handling
- Download step: use package name only.
- Source checkout / branch logic: may still use project mapping.

Examples
- `go-lib:golang-github-linuxdeepin-go-lib-dev`
  - download with `golang-github-linuxdeepin-go-lib-dev`
  - checkout project `go-lib`
- `base/lightdm:lightdm`
  - download with `lightdm`
  - checkout project `base/lightdm`

Audit hint
- When reviewing a failed or suspicious full-analysis run, inspect whether the download command used the package token or the project token.
- If a run appears to fetch the wrong dataset for mapped entries, verify the handoff between `packages.txt` parsing and the Metabase download invocation first.

For one-project-many-packages entries such as `deepin-kde/kwin:kwin-x11,kwin-wayland`, apply the rule independently to each package on the right-hand side: download crash data with `kwin-x11` / `kwin-wayland`, download deb/dbgsym with `kwin-x11` / `kwin-wayland`, and use `deepin-kde/kwin` only for source checkout and Gerrit-side operations.

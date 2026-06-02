#!/usr/bin/env python3
"""
Skill Packager - Creates distributable .skill files from skill folders

Usage:
    # Package all coredump skills
    python3 package_skills.py --all

    # Package specific skill
    python3 package_skills.py coredump-data-download

    # Package to custom output directory
    python3 package_skills.py coredump-crash-analysis --output /path/to/output

    # List available skills
    python3 package_skills.py --list
"""

import fnmatch
import sys
import zipfile
from pathlib import Path
from typing import Optional


# Patterns to exclude when packaging skills
EXCLUDE_DIRS = {"__pycache__", "node_modules", ".git", ".claude"}
EXCLUDE_GLOBS = {"*.pyc", "*.pyo", "*.db", "*.sqlite"}
EXCLUDE_FILES = {".DS_Store", "accounts.json", "*.log", "download.log"}

# Skill directories to package
COREDUMP_SKILLS = [
    "coredump-data-download",
    "coredump-data-filter",
    "coredump-code-management",
    "coredump-package-management",
    "coredump-crash-analysis",
    "coredump-full-analysis",
]

# Additional components to bundle
BUNDLE_COMPONENTS = [
    "agent",
    "package_skills.py",
    "install_skill.py",
]


def should_exclude(rel_path: Path) -> bool:
    """Check if a path should be excluded from packaging."""
    parts = rel_path.parts
    if any(part in EXCLUDE_DIRS for part in parts):
        return True
    name = rel_path.name
    if name in EXCLUDE_FILES:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_GLOBS)


def validate_skill(skill_path: Path) -> tuple:
    """Validate skill folder has required structure."""
    if not skill_path.exists():
        return False, f"Skill folder not found: {skill_path}"
    if not skill_path.is_dir():
        return False, f"Path is not a directory: {skill_path}"
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return False, f"SKILL.md not found in {skill_path}"
    return True, "Valid skill structure"


def get_skill_info(skill_path: Path) -> dict:
    """Extract skill name and description from SKILL.md."""
    skill_md = skill_path / "SKILL.md"
    info = {"name": skill_path.name, "description": "", "version": "1.0.0"}
    try:
        content = skill_md.read_text(encoding="utf-8")
        # Parse YAML frontmatter
        if content.startswith("---"):
            end = content.find("---", 3)
            if end > 0:
                frontmatter = content[3:end]
                for line in frontmatter.split("\n"):
                    if line.startswith("name:"):
                        info["name"] = line.split(":", 1)[1].strip()
                    elif line.startswith("description:"):
                        info["description"] = line.split(":", 1)[1].strip()
    except Exception as e:
        print(f"  Warning: Could not parse SKILL.md: {e}")
    return info


def package_skill(skill_path: Path, output_dir: Optional[Path] = None) -> Optional[Path]:
    """
    Package a single skill folder into a .skill file.

    Args:
        skill_path: Path to the skill folder
        output_dir: Optional output directory

    Returns:
        Path to the created .skill file, or None if error
    """
    skill_path = Path(skill_path).resolve()

    # Validate
    valid, message = validate_skill(skill_path)
    if not valid:
        print(f"  ❌ {message}")
        return None
    print(f"  ✅ {message}")

    # Get skill info
    info = get_skill_info(skill_path)
    print(f"  📝 Skill: {info['name']}")
    print(f"  📄 Description: {info['description'][:50]}..." if info['description'] else "  📄 Description: (none)")

    # Determine output location
    skill_name = skill_path.name
    if output_dir:
        output_path = Path(output_dir).resolve()
        output_path.mkdir(parents=True, exist_ok=True)
    else:
        output_path = skill_path.parent

    skill_filename = output_path / f"{skill_name}.skill"

    # Create the .skill file (zip format)
    try:
        file_count = 0
        with zipfile.ZipFile(skill_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path in skill_path.rglob('*'):
                if not file_path.is_file():
                    continue
                arcname = file_path.relative_to(skill_path.parent)
                if should_exclude(arcname):
                    continue
                zipf.write(file_path, arcname)
                file_count += 1

        size_kb = skill_filename.stat().st_size / 1024
        print(f"  ✅ Packaged {file_count} files → {skill_filename.name} ({size_kb:.1f} KB)")
        return skill_filename

    except Exception as e:
        print(f"  ❌ Error creating .skill file: {e}")
        return None


def package_all_skills(base_dir: Path, output_dir: Optional[Path] = None) -> list:
    """Package all coredump skills."""
    results = []
    for skill_name in COREDUMP_SKILLS:
        skill_path = base_dir / skill_name
        if skill_path.exists():
            print(f"\n📦 Packaging {skill_name}...")
            result = package_skill(skill_path, output_dir)
            results.append((skill_name, result))
        else:
            print(f"\n⚠️  Skill not found: {skill_name}")
            results.append((skill_name, None))
    return results


def package_bundle(base_dir: Path, output_dir: Optional[Path] = None) -> Optional[Path]:
    """
    Package everything (all skills + agent + tools) as a single .skill bundle.

    This creates a complete distribution that includes:
    - All 6 skills
    - The agent (coredump-analysis-agent.md)
    - Packaging tools (package_skills.py, install_skill.py)
    - Run scripts (run_analysis_*.sh)
    - Documentation (README.md)
    """
    bundle_name = "coredump-analysis-skills-bundle"
    output_path = output_dir or base_dir
    bundle_file = output_path / f"{bundle_name}.skill"

    # Additional files to include in bundle
    BUNDLE_EXTRA_FILES = [
        "README.md",
        "run_analysis_agent.sh",
        "run_analysis_cron.sh",
        "accounts.json",  # Template (user should edit after install)
    ]

    print(f"\n📦 Creating complete bundle: {bundle_name}")
    print(f"   Includes: 6 skills + agent + scripts + docs")

    try:
        file_count = 0
        with zipfile.ZipFile(bundle_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Package all skills
            for skill_name in COREDUMP_SKILLS:
                skill_path = base_dir / skill_name
                if not skill_path.exists():
                    print(f"  ⚠️  Skipping {skill_name} (not found)")
                    continue
                for file_path in skill_path.rglob('*'):
                    if not file_path.is_file():
                        continue
                    arcname = file_path.relative_to(base_dir)
                    if should_exclude(arcname):
                        continue
                    zipf.write(file_path, arcname)
                    file_count += 1

            # Package agent
            agent_path = base_dir / "agent"
            if agent_path.exists():
                for file_path in agent_path.rglob('*'):
                    if not file_path.is_file():
                        continue
                    arcname = file_path.relative_to(base_dir)
                    zipf.write(file_path, arcname)
                    file_count += 1

            # Package tools
            for tool in ["package_skills.py", "install_skill.py"]:
                tool_path = base_dir / tool
                if tool_path.exists():
                    zipf.write(tool_path, Path(tool))
                    file_count += 1

            # Package extra files (scripts, docs, config template)
            for fname in BUNDLE_EXTRA_FILES:
                fpath = base_dir / fname
                if fpath.exists():
                    zipf.write(fpath, Path(fname))
                    file_count += 1

        size_kb = bundle_file.stat().st_size / 1024
        print(f"  ✅ Bundled {file_count} files → {bundle_name}.skill ({size_kb:.1f} KB)")
        return bundle_file

    except Exception as e:
        print(f"  ❌ Error creating bundle: {e}")
        return None


def list_skills(base_dir: Path):
    """List all available coredump skills."""
    print("\n📦 Available Coredump Skills:")
    print("=" * 60)
    for skill_name in COREDUMP_SKILLS:
        skill_path = base_dir / skill_name
        if skill_path.exists():
            info = get_skill_info(skill_path)
            status = "✅" if (skill_path / "SKILL.md").exists() else "❌"
            print(f"  {status} {skill_name}")
            print(f"     Name: {info['name']}")
            if info['description']:
                desc = info['description'][:55] + "..." if len(info['description']) > 55 else info['description']
                print(f"     Desc: {desc}")
        else:
            print(f"  ❌ {skill_name} (not found)")
    print()


def main():
    # base_dir is the project root (where this script is located)
    base_dir = Path(__file__).parent.resolve()
    output_dir = None

    # Parse arguments
    args = sys.argv[1:]

    if "--list" in args:
        list_skills(base_dir)
        sys.exit(0)

    if "--bundle" in args:
        # Package everything as a single bundle
        output_dir = None
        if "--output" in args:
            idx = args.index("--output")
            output_dir = Path(args[idx + 1]) if idx + 1 < len(args) else None
        result = package_bundle(base_dir, output_dir)
        sys.exit(0 if result else 1)

    if "--all" in args:
        # Package all skills
        output_dir = None
        if "--output" in args:
            idx = args.index("--output")
            output_dir = Path(args[idx + 1]) if idx + 1 < len(args) else None
        print(f"📦 Packaging all coredump skills from: {base_dir}")
        if output_dir:
            print(f"   Output directory: {output_dir}")
        results = package_all_skills(base_dir, output_dir)

        # Summary
        print("\n" + "=" * 60)
        print("📊 Packaging Summary:")
        success = sum(1 for _, r in results if r)
        total = len(results)
        print(f"   Success: {success}/{total}")

        for skill_name, result in results:
            status = "✅" if result else "❌"
            print(f"   {status} {skill_name}")

        sys.exit(0 if success == total else 1)

    if len(args) == 0:
        # No arguments, show help
        print(__doc__)
        print("\n📦 Available skills:")
        for s in COREDUMP_SKILLS:
            print(f"   - {s}")
        sys.exit(1)

    # Package specific skill(s)
    skill_name = args[0]
    output_dir = None
    if "--output" in args:
        idx = args.index("--output")
        output_dir = Path(args[idx + 1]) if idx + 1 < len(args) else None

    skill_path = base_dir / skill_name
    if not skill_path.exists():
        print(f"❌ Skill not found: {skill_name}")
        print(f"   Available skills: {', '.join(COREDUMP_SKILLS)}")
        sys.exit(1)

    print(f"📦 Packaging {skill_name}...")
    result = package_skill(skill_path, output_dir)
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()

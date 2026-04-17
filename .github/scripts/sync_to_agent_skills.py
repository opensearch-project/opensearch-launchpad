#!/usr/bin/env python3
"""Sync opensearch-launchpad skills to opensearch-agent-skills.

Usage: python3 sync_to_agent_skills.py <source_root> <target_root>

All content is identical between repos. The only transformations are:
  - Path references: references/knowledge/ → launchpad/, references/aws-* → aws/*, etc.
  - ui.py: SEARCH_UI_STATIC_DIR points to scripts/ui/ instead of shared/ui/
  - UI assets live at scripts/ui/ instead of shared/ui/
  - Test imports use "opensearch-skills" instead of "opensearch-launchpad"
  - test_agent_skills_standalone_assets.py is maintained separately (not synced)
"""

import shutil
import sys
from pathlib import Path


# Path replacement map for SKILL.md
SKILL_MD_REPLACEMENTS = [
    ("name: opensearch-launchpad", "name: opensearch-skills"),
    (
        "The `opensearch-launchpad` repository cloned locally",
        "The `opensearch-skills` skill directory available locally",
    ),
    ("references/knowledge/", "launchpad/"),
    ("references/observability/", "observability/"),
    ("references/cli-reference.md", "cli-reference.md"),
    ("references/aws-reference.md", "aws/reference.md"),
    ("references/aws-domain-", "aws/domain-"),
    ("references/aws-serverless-", "aws/serverless-"),
]

# Path replacement map for aws md internal links
AWS_MD_REPLACEMENTS = [
    ("(aws-domain-", "(domain-"),
    ("(aws-serverless-", "(serverless-"),
]

# ui.py replacements
UI_PY_REPLACEMENTS = [
    (
        'SEARCH_UI_STATIC_DIR = Path(__file__).resolve().parents[4] / "shared" / "ui"',
        'SEARCH_UI_STATIC_DIR = _SCRIPT_DIR / "ui"',
    ),
    (
        "Make sure you cloned the full opensearch-launchpad repository.",
        "Make sure you have the full opensearch-skills skill directory.",
    ),
]

# Test file replacements
TEST_REPLACEMENTS = [
    (
        '"skills" / "opensearch-launchpad" / "scripts"',
        '"skills" / "opensearch-skills" / "scripts"',
    ),
    (
        "skills/opensearch-launchpad/scripts/lib/",
        "skills/opensearch-skills/scripts/lib/",
    ),
]


def copy_and_replace(src: Path, dst: Path, replacements: list[tuple[str, str]]) -> None:
    """Copy a file, applying text replacements."""
    text = src.read_text()
    for old, new in replacements:
        text = text.replace(old, new)
    dst.write_text(text)


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <source_root> <target_root>")
        sys.exit(1)

    src = Path(sys.argv[1]).resolve()
    tgt = Path(sys.argv[2]).resolve()

    src_skill = src / "skills" / "opensearch-launchpad"
    tgt_skill = tgt / "skills" / "opensearch-skills"
    src_scripts = src_skill / "scripts"
    tgt_scripts = tgt_skill / "scripts"

    # 1. scripts/lib/* — direct copy
    print("=== scripts/lib ===")
    for f in sorted((src_scripts / "lib").glob("*.py")):
        shutil.copy2(f, tgt_scripts / "lib" / f.name)
        print(f"  {f.name}")

    # 2. Patch ui.py
    print("=== patch ui.py ===")
    ui_py = tgt_scripts / "lib" / "ui.py"
    text = ui_py.read_text()
    for old, new in UI_PY_REPLACEMENTS:
        text = text.replace(old, new)
    ui_py.write_text(text)
    print("  done")

    # 3. scripts root files — direct copy
    print("=== scripts root ===")
    for name in ["opensearch_ops.py", "start_opensearch.sh"]:
        shutil.copy2(src_scripts / name, tgt_scripts / name)
        print(f"  {name}")

    # 4. sample_data — direct copy
    print("=== sample_data ===")
    shutil.copy2(
        src_scripts / "sample_data" / "imdb.title.basics.tsv",
        tgt_scripts / "sample_data" / "imdb.title.basics.tsv",
    )
    print("  imdb.title.basics.tsv")

    # 5. UI assets (shared/ui/ → scripts/ui/)
    print("=== UI assets ===")
    for name in ["app.jsx", "index.html", "styles.css"]:
        shutil.copy2(src / "shared" / "ui" / name, tgt_scripts / "ui" / name)
        print(f"  {name}")

    # 6. Knowledge md (references/knowledge/ → launchpad/)
    print("=== knowledge md ===")
    for f in sorted((src_skill / "references" / "knowledge").glob("*.md")):
        shutil.copy2(f, tgt_skill / "launchpad" / f.name)
        print(f"  {f.name}")

    # 7. Observability md
    print("=== observability md ===")
    for f in sorted((src_skill / "references" / "observability").glob("*.md")):
        shutil.copy2(f, tgt_skill / "observability" / f.name)
        print(f"  {f.name}")

    # 8. AWS md — copy with link rewrites
    print("=== aws md ===")
    for f in sorted((src_skill / "references").glob("aws-*.md")):
        target_name = f.name.removeprefix("aws-")
        copy_and_replace(f, tgt_skill / "aws" / target_name, AWS_MD_REPLACEMENTS)
        print(f"  {f.name} → aws/{target_name}")

    # 9. CLI reference — direct copy
    print("=== cli-reference ===")
    shutil.copy2(src_skill / "references" / "cli-reference.md", tgt_skill / "cli-reference.md")
    print("  cli-reference.md")

    # 10. SKILL.md — copy with path rewrites
    print("=== SKILL.md ===")
    copy_and_replace(src_skill / "SKILL.md", tgt_skill / "SKILL.md", SKILL_MD_REPLACEMENTS)
    print("  done")

    # 11. Tests — copy with path rewrites (skip standalone_assets)
    print("=== tests ===")
    skip = {"test_agent_skills_standalone_assets.py"}
    for f in sorted((src / "tests").glob("test_agent_skills_*.py")):
        if f.name in skip:
            print(f"  {f.name} (SKIPPED)")
            continue
        copy_and_replace(f, tgt / "tests" / f.name, TEST_REPLACEMENTS)
        print(f"  {f.name}")

    print("\n=== SYNC COMPLETE ===")


if __name__ == "__main__":
    main()

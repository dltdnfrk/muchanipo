import re


def test_muchanipo_skill_references_existing_python_scripts(repo_root):
    skill_text = (repo_root / "skills/muchanipo.md").read_text(encoding="utf-8")
    script_paths = sorted(set(re.findall(r"python3?\s+(src/[^\s`\"']+\.py)", skill_text)))

    assert script_paths
    missing = [path for path in script_paths if not (repo_root / path).exists()]
    assert missing == []

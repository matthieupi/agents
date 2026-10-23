"""Shared utilities; adapted for OpenCode V2 path-derived IDs."""

from pathlib import Path
import re
import yaml


def parse_skill_md(skill_path: Path) -> tuple[str, str, str]:
    """Return (path-derived ID, description, full content), parsing real YAML."""
    content = (skill_path / 'SKILL.md').read_text()
    match = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)', content, re.S)
    if not match:
        raise ValueError('SKILL.md requires YAML frontmatter for description evaluation')
    metadata = yaml.safe_load(match.group(1))
    if not isinstance(metadata, dict) or not isinstance(metadata.get('description'), str):
        raise ValueError('SKILL.md requires a string description for discovery')
    if not metadata['description'].strip():
        raise ValueError('Description must not be empty')
    return skill_path.absolute().name, metadata['description'], content

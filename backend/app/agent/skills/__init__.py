"""仅内置白名单技能，导入时读取，请求期间不阻塞文件I/O."""

from pathlib import Path

from app.schemas.agent_skill import LoadedSkill, SkillName, SkillSection

SKILLS_VERSION = "v7"
_ROOT = Path(__file__).parent
_VERSIONS: dict[SkillName, str] = {
    "fund-analysis": "1.4.0",
    "portfolio-diagnosis": "1.0.0",
    "fund-allocation": "1.0.0",
    "sector-analysis": "1.0.0",
    "stock-analysis": "1.0.0",
}
_SECTIONS: dict[SkillSection, str] = {"instructions": "SKILL.md", "evidence": "references/evidence.md"}
_RESOURCES: dict[tuple[SkillName, SkillSection], str] = {
    (name, section): (_ROOT / name / filename).read_text(encoding="utf-8")
    for name in _VERSIONS
    for section, filename in _SECTIONS.items()
}


def read_skill(skill_name: SkillName, section: SkillSection) -> LoadedSkill:
    """固定映射，无法路径穿越或载入外部网页、脚本."""
    return LoadedSkill(
        name=skill_name,
        version=_VERSIONS[skill_name],
        section=section,
        content=_RESOURCES[(skill_name, section)],
        available_sections=["instructions", "evidence"],
    )

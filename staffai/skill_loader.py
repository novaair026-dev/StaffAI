"""技能加载器：扫描员工技能目录，两阶段加载技能描述"""

from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Skill:
    """
    一个员工技能的定义。

    初始加载时只读取简要描述（省 token），
    详细描述通过 ensure_detail_loaded() 懒加载。
    """
    name: str           # 技能名称（= 目录名）
    brief: str          # 员工技能简要描述
    detail: str = ""    # 员工技能详细描述（懒加载）
    dir_path: Path = None
    _detail_loaded: bool = field(default=False, repr=False)

    def ensure_detail_loaded(self):
        """
        按需加载详细描述。

        只在第一次调用时读取文件，后续调用直接返回。
        """
        if self._detail_loaded:
            return

        if self.dir_path:
            detail_file = self.dir_path / "员工技能详细描述"
            if detail_file.exists():
                self.detail = detail_file.read_text(encoding="utf-8").strip()

        self._detail_loaded = True

    def build_worker_system_prompt(self) -> str:
        """
        组装员工的完整 system prompt（第二阶段使用）。

        会自动触发详细描述的懒加载。

        Returns:
            包含角色定义、详细描述、命令输出格式的 system prompt
        """
        self.ensure_detail_loaded()

        parts = [f"你是「{self.name}」员工。"]

        if self.detail:
            parts.append(f"\n{self.detail}")

        parts.append(
            "\n当你需要执行操作时，请将 Shell 命令用以下格式输出：\n"
            "```shell\n<要执行的命令>\n```\n"
            "核心系统会提取并执行该命令，然后把执行结果反馈给你。"
        )

        return "\n".join(parts)


def load_all_skills(skills_dir: Path) -> dict[str, Skill]:
    """
    扫描员工技能目录，加载所有技能。

    第一阶段：只读取「员工技能简要描述」文件（轻量），
    「员工技能详细描述」在实际使用时才懒加载。

    Args:
        skills_dir: 员工技能目录的路径

    Returns:
        {技能名称: Skill} 字典
    """
    skills = {}

    if not skills_dir.exists():
        return skills

    for skill_path in sorted(skills_dir.iterdir()):
        # 跳过非目录和隐藏目录
        if not skill_path.is_dir():
            continue
        if skill_path.name.startswith("."):
            continue

        # 只读取简要描述（轻量加载）
        brief_file = skill_path / "员工技能简要描述"
        if not brief_file.exists():
            continue

        brief = brief_file.read_text(encoding="utf-8").strip()

        skill = Skill(
            name=skill_path.name,
            brief=brief,
            dir_path=skill_path,
        )
        skills[skill.name] = skill

    return skills


def build_skill_summary(skills: dict[str, Skill]) -> str:
    """
    构建技能摘要列表，供调度中枢第一阶段使用。

    只包含技能名和简要描述，不含详细描述，节省 token。

    Args:
        skills: 技能字典

    Returns:
        格式化的技能列表文本，如：
        1. 发送通知文本 — 有在Mac上面推送想要推送的通知。
        2. 朗读文本 — 将一段需要朗读的自然段落文本在Mac上面朗读。
    """
    lines = []
    for i, (name, skill) in enumerate(skills.items(), 1):
        lines.append(f"{i}. {name} — {skill.brief}")
    return "\n".join(lines)

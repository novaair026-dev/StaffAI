"""配置管理器：加载和校验 config.yaml"""

import yaml
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class LLMConfig:
    """大模型配置"""
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 4096


@dataclass
class ShellConfig:
    """Shell 执行器安全配置"""
    whitelist: list[str] = field(default_factory=list)
    blacklist: list[str] = field(default_factory=list)
    timeout: int = 30


@dataclass
class WebConfig:
    """Web 界面配置"""
    host: str = "127.0.0.1"
    port: int = 7860
    share: bool = False


@dataclass
class AppConfig:
    """应用全局配置"""
    llm: LLMConfig = field(default_factory=LLMConfig)
    shell: ShellConfig = field(default_factory=ShellConfig)
    web: WebConfig = field(default_factory=WebConfig)
    skills_dir: str = "员工技能目录"


def load_config(config_path: Path | None = None) -> AppConfig:
    """
    加载配置文件，缺失字段使用默认值。

    Args:
        config_path: 配置文件路径，默认为项目根目录的 config.yaml

    Returns:
        AppConfig 配置对象

    Raises:
        FileNotFoundError: 配置文件不存在时抛出
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yaml"

    if not config_path.exists():
        raise FileNotFoundError(
            f"配置文件不存在: {config_path}\n"
            f"请复制 config.example.yaml 为 config.yaml 并填写你的 API Key"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    llm_data = raw.get("llm", {})
    shell_data = raw.get("shell", {})
    web_data = raw.get("web", {})

    return AppConfig(
        llm=LLMConfig(**llm_data),
        shell=ShellConfig(**shell_data),
        web=WebConfig(**web_data),
        skills_dir=raw.get("skills_dir", "员工技能目录"),
    )

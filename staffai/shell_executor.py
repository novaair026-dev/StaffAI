"""Shell 执行器：命令执行 + 白名单/黑名单安全策略"""

import subprocess
from enum import Enum
from dataclasses import dataclass
from staffai.config_manager import ShellConfig


class CommandVerdict(Enum):
    """命令安全判定结果"""
    ALLOW_AUTO = "auto"          # 白名单命令，自动执行
    NEEDS_CONFIRM = "confirm"    # 需要老板确认
    DENY = "deny"                # 黑名单，拒绝执行


@dataclass
class ExecutionResult:
    """命令执行结果"""
    command: str
    returncode: int
    stdout: str
    stderr: str
    success: bool

    @property
    def output(self) -> str:
        """返回合并后的输出文本"""
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(f"[stderr] {self.stderr}")
        if not parts:
            return "(执行成功，无输出)" if self.success else f"(命令失败，退出码: {self.returncode})"
        return "\n".join(parts)


class ShellExecutor:
    """
    Shell 命令执行器。

    四层安全判定流程：
    1. 黑名单拦截 → 永远拒绝
    2. 全局白名单检查 → 自动执行
    3. 技能命令匹配 → 自动执行
    4. 请求老板确认
    """

    def __init__(self, config: ShellConfig):
        self.whitelist = config.whitelist
        self.blacklist = config.blacklist
        self.timeout = config.timeout

    def judge(self, command: str, skill_commands: list[str] | None = None) -> CommandVerdict:
        """
        判定一个命令的执行策略。

        Args:
            command: 要执行的 Shell 命令
            skill_commands: 当前技能声明的可用命令前缀列表

        Returns:
            CommandVerdict 枚举值
        """
        command_stripped = command.strip()

        # 第一层：黑名单检查 — 命中则永远拒绝
        for pattern in self.blacklist:
            if pattern in command_stripped:
                return CommandVerdict.DENY

        # 第二层：全局白名单检查 — 命中则自动执行
        for prefix in self.whitelist:
            if command_stripped.startswith(prefix):
                return CommandVerdict.ALLOW_AUTO

        # 第三层：当前技能的可用命令检查 — 命中则自动执行
        if skill_commands:
            for cmd_prefix in skill_commands:
                if command_stripped.startswith(cmd_prefix.strip()):
                    return CommandVerdict.ALLOW_AUTO

        # 第四层：需要老板确认
        return CommandVerdict.NEEDS_CONFIRM

    def execute(self, command: str) -> ExecutionResult:
        """
        执行 Shell 命令并返回结果。

        Args:
            command: 要执行的 Shell 命令

        Returns:
            ExecutionResult 包含退出码、标准输出、标准错误
        """
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            return ExecutionResult(
                command=command,
                returncode=result.returncode,
                stdout=result.stdout.strip(),
                stderr=result.stderr.strip(),
                success=(result.returncode == 0),
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                command=command,
                returncode=-1,
                stdout="",
                stderr=f"命令执行超时（{self.timeout}秒）",
                success=False,
            )
        except Exception as e:
            return ExecutionResult(
                command=command,
                returncode=-1,
                stdout="",
                stderr=f"执行异常: {str(e)}",
                success=False,
            )

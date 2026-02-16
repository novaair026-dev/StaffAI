"""调度中枢：两阶段调度 + 多员工协作"""

import re
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from staffai.llm_client import LLMClient
from staffai.skill_loader import Skill, load_all_skills, build_skill_summary
from staffai.shell_executor import ShellExecutor, CommandVerdict
from staffai.config_manager import AppConfig


# ──────────────────────────────────────────────
# 调度中枢的 system prompt 模板
# ──────────────────────────────────────────────

DISPATCH_SYSTEM_PROMPT = """\
你是 StaffAI 调度中枢，负责理解老板的需求并分配给合适的 AI 员工。

当前可用员工列表：
{skill_summary}

规则：
- 分析老板的需求，判断需要哪个（或哪几个）员工来完成
- 如果需要多个员工，按执行顺序排列
- 如果不需要任何员工（普通聊天、问答等），返回空任务列表
- 必须严格用 JSON 格式返回决策，不要输出其他内容

返回格式：
{{"tasks": [{{"skill": "技能名称", "instruction": "分配给该员工的具体指令"}}]}}

示例1 - 需要一个员工：
{{"tasks": [{{"skill": "朗读文本", "instruction": "朗读以下内容：明天下午3点开会"}}]}}

示例2 - 需要多个员工：
{{"tasks": [{{"skill": "发送通知文本", "instruction": "发送通知提醒3点开会"}}, {{"skill": "朗读文本", "instruction": "朗读：3点开会"}}]}}

示例3 - 不需要员工（普通对话）：
{{"tasks": []}}
"""

DIRECT_CHAT_SYSTEM_PROMPT = """\
你是 StaffAI，一人公司老板的 AI 助手。请友好、简洁地与老板对话。
"""


@dataclass
class PendingCommand:
    """等待老板确认的命令"""
    command: str
    skill_name: str


@dataclass
class ChatSession:
    """一次对话会话的状态"""
    session_id: str
    history: list[dict] = field(default_factory=list)
    pending_command: PendingCommand | None = None
    current_skill: Skill | None = None  # 当前正在执行的技能（用于确认回调）


class StaffAICore:
    """
    StaffAI 调度中枢。

    两阶段工作流：
    1. 调度决策：用技能名+简要描述（省 token）让 LLM 判断需要哪些员工
    2. 员工执行：加载被选中员工的详细描述，调用 LLM 生成并执行 Shell 命令
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.llm = LLMClient(config.llm)
        self.executor = ShellExecutor(config.shell)

        # 计算技能目录的绝对路径
        self._skills_dir = Path(__file__).parent.parent / config.skills_dir
        self.skills = load_all_skills(self._skills_dir)

        # 会话管理
        self.sessions: dict[str, ChatSession] = {}

    def reload_skills(self):
        """重新加载技能目录（热重载，无需重启）"""
        self.skills = load_all_skills(self._skills_dir)

    def create_session(self) -> str:
        """创建新的对话会话，返回 session_id"""
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = ChatSession(session_id=session_id)
        return session_id

    def chat(self, session_id: str, user_input: str):
        """
        核心对话循环。

        生成器函数，yield 不同类型的事件：
        - ("text", "...")           流式文本回复
        - ("dispatch", "...")       调度信息（选中了哪些员工）
        - ("skill_start", "...")    某员工开始执行
        - ("command_auto", "...")   自动执行的命令
        - ("command_confirm", "..") 需确认的命令
        - ("command_deny", "...")   被拒绝的命令
        - ("command_result", "..") 命令执行结果

        Args:
            session_id: 会话 ID
            user_input: 老板的输入

        Yields:
            (event_type, event_data) 元组
        """
        session = self.sessions.get(session_id)
        if not session:
            yield ("text", "会话不存在，请刷新页面重试。")
            return

        # 如果有待确认的命令，处理确认回复
        if session.pending_command:
            yield from self._handle_confirmation(session, user_input)
            return

        # 记录用户消息到历史
        session.history.append({"role": "user", "content": user_input})

        # ========== 第一阶段：调度决策 ==========
        dispatch_result = self._dispatch(user_input)

        # 不需要任何员工 → 直接对话
        if not dispatch_result["tasks"]:
            yield from self._direct_chat(session, user_input)
            return

        # 显示调度信息
        skill_names = [t["skill"] for t in dispatch_result["tasks"]]
        yield ("dispatch", "、".join(skill_names))

        # ========== 第二阶段：逐个员工执行 ==========
        all_results = []

        for task in dispatch_result["tasks"]:
            skill_name = task["skill"]
            instruction = task["instruction"]

            # 检查技能是否存在
            if skill_name not in self.skills:
                yield ("text", f"\n找不到员工「{skill_name}」，跳过。\n")
                continue

            skill = self.skills[skill_name]
            yield ("skill_start", skill_name)

            # 懒加载详细描述，组装员工 system prompt
            worker_prompt = skill.build_worker_system_prompt()

            # 调用 LLM 让员工执行任务
            worker_messages = [
                {"role": "system", "content": worker_prompt},
                {"role": "user", "content": instruction},
            ]

            # 流式获取员工回复
            full_response = ""
            for chunk in self.llm.chat_stream(worker_messages):
                full_response += chunk
                yield ("text", chunk)

            # 提取并执行 Shell 命令
            commands = self._extract_commands(full_response)

            for cmd in commands:
                verdict = self.executor.judge(cmd)

                if verdict == CommandVerdict.DENY:
                    yield ("command_deny", cmd)
                    all_results.append(f"[{skill_name}] 命令被安全策略拒绝: {cmd}")

                elif verdict == CommandVerdict.ALLOW_AUTO:
                    yield ("command_auto", cmd)
                    result = self.executor.execute(cmd)
                    yield ("command_result", result.output)
                    all_results.append(f"[{skill_name}] 执行: {cmd} → {result.output}")

                elif verdict == CommandVerdict.NEEDS_CONFIRM:
                    # 设置待确认状态，暂停执行
                    session.pending_command = PendingCommand(
                        command=cmd, skill_name=skill_name
                    )
                    session.current_skill = skill
                    yield ("command_confirm", cmd)
                    # 将已有结果记录到历史
                    if all_results:
                        session.history.append({
                            "role": "assistant",
                            "content": "\n".join(all_results),
                        })
                    return  # 暂停，等待老板确认

        # 记录执行结果到对话历史
        if all_results:
            session.history.append({
                "role": "assistant",
                "content": "\n".join(all_results),
            })

    def _dispatch(self, user_input: str) -> dict:
        """
        第一阶段：调度决策。

        构建只含技能名+简要描述的轻量 prompt，
        让 LLM 判断需要哪些员工。

        Args:
            user_input: 老板的原始输入

        Returns:
            {"tasks": [{"skill": "技能名", "instruction": "指令"}, ...]}
        """
        skill_summary = build_skill_summary(self.skills)

        if not skill_summary:
            # 没有任何技能，直接返回空
            return {"tasks": []}

        system_prompt = DISPATCH_SYSTEM_PROMPT.format(skill_summary=skill_summary)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]

        response = self.llm.chat(messages)

        # 解析 JSON 响应
        try:
            # 尝试从响应中提取 JSON
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                # 验证格式
                if "tasks" in result and isinstance(result["tasks"], list):
                    # 过滤掉不存在的技能
                    result["tasks"] = [
                        t for t in result["tasks"]
                        if isinstance(t, dict) and "skill" in t and "instruction" in t
                    ]
                    return result
        except (json.JSONDecodeError, ValueError):
            pass

        # 解析失败，返回空任务列表（降级为直接对话）
        return {"tasks": []}

    def _direct_chat(self, session: ChatSession, user_input: str):
        """
        不需要员工技能时，作为普通 AI 助手直接对话。

        Args:
            session: 当前会话
            user_input: 老板的输入

        Yields:
            ("text", chunk) 流式文本
        """
        messages = [
            {"role": "system", "content": DIRECT_CHAT_SYSTEM_PROMPT},
        ]
        # 加入对话历史（最近的记录）
        messages.extend(session.history[-20:])

        full_response = ""
        for chunk in self.llm.chat_stream(messages):
            full_response += chunk
            yield ("text", chunk)

        session.history.append({"role": "assistant", "content": full_response})

    def _handle_confirmation(self, session: ChatSession, user_input: str):
        """
        处理老板对待确认命令的回复。

        Args:
            session: 当前会话
            user_input: 老板的回复

        Yields:
            事件元组
        """
        pending = session.pending_command
        session.pending_command = None
        session.current_skill = None

        # 判断是否同意
        affirmative_words = {"y", "yes", "是", "确认", "执行", "好", "ok", "同意", "可以", "好的"}
        is_confirmed = user_input.strip().lower() in affirmative_words

        if is_confirmed:
            yield ("command_auto", pending.command)
            result = self.executor.execute(pending.command)
            yield ("command_result", result.output)
            session.history.append({
                "role": "assistant",
                "content": f"[{pending.skill_name}] 已确认执行: {pending.command}\n结果: {result.output}",
            })
        else:
            yield ("text", f"已取消执行命令: `{pending.command}`")
            session.history.append({
                "role": "assistant",
                "content": f"[{pending.skill_name}] 老板取消了命令: {pending.command}",
            })

    def _extract_commands(self, text: str) -> list[str]:
        """
        从 LLM 回复中提取 shell 代码块中的命令。

        支持 ```shell、```bash、```sh 三种标记。

        Args:
            text: LLM 的回复文本

        Returns:
            提取到的命令列表
        """
        pattern = r'```(?:shell|bash|sh)\n(.*?)```'
        matches = re.findall(pattern, text, re.DOTALL)

        commands = []
        for match in matches:
            for line in match.strip().split("\n"):
                line = line.strip()
                # 跳过空行和注释行
                if line and not line.startswith("#"):
                    commands.append(line)

        return commands

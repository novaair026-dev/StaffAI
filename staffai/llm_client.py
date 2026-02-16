"""LLM 客户端：OpenAI 兼容 API 统一封装"""

from openai import OpenAI
from staffai.config_manager import LLMConfig


class LLMClient:
    """
    OpenAI 兼容 API 统一客户端。

    支持所有兼容 OpenAI API 格式的服务商：
    OpenAI、DeepSeek、通义千问、Moonshot 等，
    只需修改 base_url 和 api_key 即可切换。
    """

    def __init__(self, config: LLMConfig):
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self.model = config.model
        self.temperature = config.temperature
        self.max_tokens = config.max_tokens

    def chat(
        self,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """
        发送聊天请求，返回助手回复文本。

        用于调度决策等需要完整回复的场景。

        Args:
            messages: 对话消息列表，格式如
                [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
            temperature: 生成温度，None 时使用配置默认值
            max_tokens: 最大输出长度，None 时使用配置默认值

        Returns:
            助手回复的文本内容
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature if temperature is not None else self.temperature,
            max_tokens=max_tokens or self.max_tokens,
        )
        return response.choices[0].message.content

    def chat_stream(
        self,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        """
        流式聊天，逐片段 yield 返回。

        用于 Gradio 界面逐字显示回复。

        Args:
            messages: 对话消息列表
            temperature: 生成温度
            max_tokens: 最大输出长度

        Yields:
            每个文本片段（chunk）
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature if temperature is not None else self.temperature,
            max_tokens=max_tokens or self.max_tokens,
            stream=True,
        )
        for chunk in response:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

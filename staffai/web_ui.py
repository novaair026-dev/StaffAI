"""Gradio Web 界面：单栏聊天，AI 自动调度员工"""

import gradio as gr
from staffai.core import StaffAICore
from staffai.config_manager import load_config


def create_app() -> gr.Blocks:
    """创建 Gradio 应用"""

    config = load_config()
    core = StaffAICore(config)

    # 启动时创建一个默认会话
    default_session_id = core.create_session()

    with gr.Blocks(
        title="StaffAI - 你的一人公司 AI 员工",
    ) as app:

        # 状态
        session_id = gr.State(value=default_session_id)

        gr.Markdown("# StaffAI - 你的一人公司 AI 员工")
        gr.Markdown("直接说出你的需求，AI 会自动安排合适的员工来帮你完成。")

        # 对话窗口
        chatbot = gr.Chatbot(
            label="对话",
            height=550,
        )

        # 命令确认区域（默认隐藏）
        with gr.Row(visible=False) as confirm_row:
            confirm_display = gr.Code(
                label="以下命令需要老板确认",
                language="shell",
                interactive=False,
            )
            with gr.Column(scale=0, min_width=120):
                confirm_btn = gr.Button("✅ 确认执行", variant="primary")
                reject_btn = gr.Button("❌ 取消", variant="stop")

        # 输入区域
        with gr.Row():
            user_input = gr.Textbox(
                placeholder="告诉 AI 员工你需要什么...",
                label="",
                scale=4,
                lines=1,
            )
            send_btn = gr.Button("发送", variant="primary", scale=0)

        # ─────── 交互逻辑 ───────

        def on_send(sid, user_msg, chat_history):
            """发送消息"""
            if not user_msg.strip():
                yield sid, chat_history, "", gr.update(visible=False), ""
                return

            # 添加用户消息
            chat_history = chat_history + [
                {"role": "user", "content": user_msg}
            ]

            assistant_text = ""

            for event_type, event_data in core.chat(sid, user_msg):

                if event_type == "text":
                    assistant_text += event_data
                    display = chat_history + [
                        {"role": "assistant", "content": assistant_text}
                    ]
                    yield sid, display, "", gr.update(visible=False), ""

                elif event_type == "dispatch":
                    assistant_text += f"📋 **调度员工：{event_data}**\n\n"
                    display = chat_history + [
                        {"role": "assistant", "content": assistant_text}
                    ]
                    yield sid, display, "", gr.update(visible=False), ""

                elif event_type == "skill_start":
                    assistant_text += f"\n---\n**【{event_data}】员工执行中：**\n\n"
                    display = chat_history + [
                        {"role": "assistant", "content": assistant_text}
                    ]
                    yield sid, display, "", gr.update(visible=False), ""

                elif event_type == "command_auto":
                    assistant_text += f"\n> ✅ 自动执行命令: `{event_data}`\n"
                    display = chat_history + [
                        {"role": "assistant", "content": assistant_text}
                    ]
                    yield sid, display, "", gr.update(visible=False), ""

                elif event_type == "command_result":
                    assistant_text += f"```\n{event_data}\n```\n"
                    display = chat_history + [
                        {"role": "assistant", "content": assistant_text}
                    ]
                    yield sid, display, "", gr.update(visible=False), ""

                elif event_type == "command_deny":
                    assistant_text += f"\n> 🚫 命令被安全策略拒绝: `{event_data}`\n"
                    display = chat_history + [
                        {"role": "assistant", "content": assistant_text}
                    ]
                    yield sid, display, "", gr.update(visible=False), ""

                elif event_type == "command_confirm":
                    # 暂停，显示确认面板
                    display = chat_history + [
                        {"role": "assistant", "content": assistant_text}
                    ]
                    yield sid, display, "", gr.update(visible=True), event_data
                    return

            # 最终结果
            final = chat_history + [
                {"role": "assistant", "content": assistant_text}
            ]
            yield sid, final, "", gr.update(visible=False), ""

        def on_confirm(sid, chat_history):
            """老板确认执行命令"""
            return _process_confirmation(sid, "是", chat_history)

        def on_reject(sid, chat_history):
            """老板取消执行命令"""
            return _process_confirmation(sid, "否", chat_history)

        def _process_confirmation(sid, answer, chat_history):
            """处理确认/拒绝"""
            result_text = ""
            for event_type, event_data in core.chat(sid, answer):
                if event_type == "text":
                    result_text += event_data
                elif event_type == "command_auto":
                    result_text += f"\n> ✅ 执行命令: `{event_data}`\n"
                elif event_type == "command_result":
                    result_text += f"```\n{event_data}\n```\n"

            if result_text:
                chat_history = chat_history + [
                    {"role": "assistant", "content": result_text}
                ]

            return sid, chat_history, gr.update(visible=False), ""

        # ─────── 事件绑定 ───────

        send_btn.click(
            on_send,
            inputs=[session_id, user_input, chatbot],
            outputs=[session_id, chatbot, user_input, confirm_row, confirm_display],
        )

        user_input.submit(
            on_send,
            inputs=[session_id, user_input, chatbot],
            outputs=[session_id, chatbot, user_input, confirm_row, confirm_display],
        )

        confirm_btn.click(
            on_confirm,
            inputs=[session_id, chatbot],
            outputs=[session_id, chatbot, confirm_row, confirm_display],
        )

        reject_btn.click(
            on_reject,
            inputs=[session_id, chatbot],
            outputs=[session_id, chatbot, confirm_row, confirm_display],
        )

    return app


def launch():
    """启动 StaffAI Web 界面"""
    config = load_config()
    app = create_app()
    app.launch(
        server_name=config.web.host,
        server_port=config.web.port,
        share=config.web.share,
        theme=gr.themes.Soft(),
        css="""
        .command-confirm {
            border: 2px solid #ff9800;
            border-radius: 8px;
            padding: 12px;
            margin: 8px 0;
            background: #fff8e1;
        }
        """,
    )

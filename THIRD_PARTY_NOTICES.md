# Third-party notices

本项目源码以仓库根目录 `LICENSE` 中的许可证发布。依赖、模型和外部资产仍受各自许可证和使用条款约束，不能因为本项目使用它们就自动获得再分发权。

当前主要组件包括：

- Python：FastAPI、Pydantic、Requests、OpenAI SDK、LangGraph、Streamlit、PaddlePaddle、PaddleOCR、OpenCV、NumPy、Pandas、OpenPyXL。
- 前端：Vue 3、Vue Router、Pinia、Element Plus、ECharts、Axios、Vite、Nginx。
- 检索模型：BAAI/bge-small-zh-v1.5（仅在启用混合检索并按模型条款取得权重后使用）。
- 可选外部服务：DeepSeek 复核接口、阿里云百炼 Qwen VL OCR。启用这些服务会将相应字段或票据内容发送到服务商，使用者需自行完成合规评估。

发布前请根据实际 lockfile 和镜像清单补充精确版本、许可证链接和模型权重来源。未经确认授权的课程材料、内部制度文档和业务数据不属于本项目开源资产。

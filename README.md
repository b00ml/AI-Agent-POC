# AI Expense Audit POC

制造企业报销人机协同审核系统的 Agent 应用开发学习项目。

项目围绕两个硬约束设计：业务数据默认留在本地，AI 只提供审核意见，最终放行由人工完成。系统用确定性规则处理全量单据，用 RAG 和可选 LLM 复核处理复杂或分歧场景，并把证据、预算、失败降级和人工终审作为可测试的工程契约。

> English summary: An agent-assisted expense audit POC built with Python, FastAPI, Vue 3, LangGraph, local OCR, and hybrid retrieval. The public demo runs entirely on synthetic fixtures without ERP or external model credentials.

## 5 分钟 Demo

要求：Docker Desktop，约 2 GB 可用磁盘。Demo 不需要 ERP、API Key、外部 LLM 或 PaddleOCR 模型下载。

```bash
docker compose -f docker-compose.demo.yml up --build
```

打开 <http://localhost:5173>。页面会自动连接本地合成 ERP，包含 6 条报销单、重复发票、超标伙食、高铁舱位、未知城市和缺附件等边界案例。

停止 Demo：

```bash
docker compose -f docker-compose.demo.yml down -v
```

Demo 的 API 健康检查：<http://localhost:8000/api/health>。

## 系统架构

```text
Vue 3 (5173)
  -> FastAPI (8000)
      -> job/repository/application services
          -> M2 rules + optional LLM review + LangGraph investigation
          -> M3 invoice anomaly audit
          -> M4 bank reconciliation
          -> ERP adapter or in-process synthetic demo adapter
```

核心决策边界：

- 规则引擎对每个选中单据执行全量审核，是确定性基线；
- LLM 是第二意见，和规则结论不一致时只能进入 `FLAG`；
- 调查工具只读，证据必须回溯到工具返回；
- `adjudicate` 只能向人工关注方向推进，不能自动放行；
- 最终改变 ERP 审核意见的动作由人工终审触发。

详细设计见 [docs/architecture.md](docs/architecture.md) 和 [docs/agent-workflow.md](docs/agent-workflow.md)。

## 功能范围

### M2 差旅报销审核

- 住宿、伙食、市内交通、长途舱位、发票抬头/税号、金额、重复报销、加班打车审批、缺附件和科目归集规则；
- 支持 `APPROVE`、`REJECT`、`FLAG` 三种结果；
- 批量任务有进度、取消、失败清单和结果持久化；
- 可选 LangGraph 管线：规则审核 -> LLM 复核 -> 有限调查 -> 人工终审。

### M3 发票稽核

- 重复发票、购方抬头/税号、税率、连号、供应商重复档案和风险画像；
- 异常项支持 AI 复核和人工确认。

### M4 银行对账

- CSV 解析、客户别名、金额容差、一笔多票和按原因分类的待认领清单；
- Demo 使用 `data/demo/bank_transactions.csv`，真实 ERP 应收台账属于可选自托管集成。

## 目录

```text
core/                 规则、OCR、RAG、LLM、Agent 工具和工作流
backend/              FastAPI 路由、服务、任务和持久化
frontend/             Vue 3 + Element Plus 主界面
data/demo/            公开合成 fixture（无真实企业数据）
tools/                评测、Prompt 回归和发布检查
tests/unit/           核心单测和契约测试
docs/                 架构、Agent 工作流、评测和工程踩坑
```

## 真实 ERP 集成（可选）

真实 ERP 适配使用 `core/client.py` 的开放平台客户端，需要调用方自行提供地址和最小权限 Key。公开 Demo 不需要这些配置：

```bash
cp .env.example .env
docker compose up -d --build
```

不要把真实 Key 写入代码、issue、日志、截图或 Git 历史。

## 本地开发

```bash
python -m venv .venv
.venv\\Scripts\\activate                 # Windows
pip install -r requirements.txt -r backend/requirements.txt
python -m pytest
python -m ruff check .

cd frontend
npm install
npm run build
```

本地运行 Demo 适配器时设置 `DEMO_MODE=1`；PowerShell 使用 `$env:DEMO_MODE="1"`。

## 评测证据

评测脚本和结果口径见 [docs/evaluation.md](docs/evaluation.md)。当前已验证：

- 公开合成 Demo：M2 6 条单据可复现规则结果，M3 可识别重复发票和票面问题，M4 可完成匹配与待认领分类；
- 公开样例规则评测与困难集门禁；
- 注入鲁棒性评测：对抗文本不能静默放行；
- RAG 50 条标注集：keyword Recall@8 = 0.78，hybrid Recall@8 = 1.00；
- 最近本地环境的混合检索延迟约 1 秒/查询，实际值受 CPU、模型缓存和配置影响，不能脱离环境宣称固定延迟。

运行：

```bash
python -m pytest
python tools/eval_retrieval.py --mode both
python tools/eval_hard_set.py --gate
python tools/eval_injection.py
python tools/prompt_regression.py
python tools/public_release_check.py
```

## 明确限制

这是学习用途 POC，不是生产财务系统：

- 没有生产级身份认证、RBAC、SSO、多租户和托管密钥系统；
- 没有持久化消息队列、HA worker、完整数据库迁移和跨实例调度；
- 浏览器连接 ERP 的方式仍属于 POC 边界，生产部署应由后端安全托管凭据；
- 默认 Demo 使用合成数据，任何真实数据接入前都必须自行完成合规和授权评估；
- Windows Docker bind mount 下 SQLite WAL 曾出现数据库文件打开异常，这是已知部署限制。

## 文档与开源规范

- [安全策略](SECURITY.md)
- [贡献指南](CONTRIBUTING.md)
- [数据发布说明](data/README.md)
- [第三方声明](THIRD_PARTY_NOTICES.md)
- [工程踩坑与修复](docs/engineering-lessons.md)

## License

代码使用 [MIT License](LICENSE)。依赖、模型权重、课程材料和外部服务仍受各自许可证与使用条款约束。

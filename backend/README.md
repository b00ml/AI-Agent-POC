# 启衡精密 AI 财务审核 - 后端

基于 FastAPI 的企业级财务审核系统后端 API。

## 技术栈

- Python 3.12
- FastAPI
- Uvicorn
- Pydantic

## 快速开始

### 本地开发

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker 部署

```bash
cd .. && docker compose build qiheng-api
docker compose up -d qiheng-api
```

## API 文档

启动后访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- 健康检查: http://localhost:8000/api/health

## 路由说明

| 前缀 | 模块 | 说明 |
|------|------|------|
| `/api/erp` | ERP 模块 | ERP 连接和报销单加载 |
| `/api/m2` | M2 模块 | 合规审核、OCR 识别、人工复核 |
| `/api/m3` | M3 模块 | 异常检测和风险扫描 |
| `/api/m4` | M4 模块 | 银行对账 |
| `/api/settings` | 设置模块 | 系统配置、AI 复核助手开关（llm-review） |

## 目录结构

```
backend/
├── app/
│   ├── main.py          # FastAPI 入口
│   ├── routers/         # 路由模块
│   └── schemas/         # Pydantic 模型
├── requirements.txt
├── Dockerfile
└── README.md
```

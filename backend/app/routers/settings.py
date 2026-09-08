"""
系统设置路由
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

class SettingsUpdate(BaseModel):
    ocrEngine: str = "paddle"
    dashscopeApiKey: Optional[str] = None
    qihengApiKey: Optional[str] = None

@router.get("")
async def get_settings():
    """获取当前设置"""
    import os
    return {
        "ocrEngine": os.getenv("OCR_ENGINE", "paddle"),
        "dashscopeConfigured": bool(os.getenv("DASHSCOPE_API_KEY")),
        "qihengConfigured": bool(os.getenv("QIHENG_API_KEY")),
        "version": "2.0.0",
    }

@router.put("")
async def update_settings(req: SettingsUpdate):
    """更新设置（当前仅内存模式）"""
    return {"status": "updated", "ocrEngine": req.ocrEngine}


@router.get("/llm-review")
async def get_llm_review():
    """查询 AI 复核助手状态"""
    import os
    from core.llm_reviewer import is_llm_review_enabled
    return {
        "enabled": is_llm_review_enabled(),
        "model": os.environ.get("LLM_REVIEW_MODEL", "deepseek-v4-flash"),
        "keyConfigured": bool(os.environ.get("LLM_REVIEW_API_KEY")),
    }


class LLMReviewUpdate(BaseModel):
    enabled: bool = False


@router.put("/llm-review")
async def update_llm_review(req: LLMReviewUpdate):
    """开关 AI 复核助手（进程内生效，下次审核即用）"""
    import os
    os.environ["LLM_REVIEW_ENABLED"] = "1" if req.enabled else "0"
    return {
        "status": "updated",
        "enabled": req.enabled,
        "model": os.environ.get("LLM_REVIEW_MODEL", "deepseek-v4-flash"),
        "keyConfigured": bool(os.environ.get("LLM_REVIEW_API_KEY")),
        "note": "规则引擎与 AI 复核结论不一致时自动转 FLAG 提请人工复核",
    }

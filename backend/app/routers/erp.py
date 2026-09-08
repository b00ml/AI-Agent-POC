"""
ERP 连接和报销单加载路由
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

class ConnectRequest(BaseModel):
    api_url: str
    api_key: str

@router.post("/connect")
def connect_erp(req: ConnectRequest):
    """验证 ERP API Key 并建立连接"""
    try:
        from core.client import QihengClient
        client = QihengClient(api_key=req.api_key, base_url=req.api_url)
        me = client.me()
        return {"status": "connected", "message": "连接成功", "user": me}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"连接失败: {str(e)}")

@router.get("/claims")
def list_claims(
    api_url: str = Query(...),
    api_key: str = Query(...),
    status: Optional[str] = Query(None),
    limit: int = Query(20),
    cursor: Optional[str] = Query(None),
):
    """分页加载待审报销单列表"""
    try:
        from core.client import QihengClient
        client = QihengClient(api_key=api_key, base_url=api_url)
        response = client.expense_claims_list(status=status, limit=limit, cursor=cursor)
        return {
            "items": response.get("data", []),
            "hasMore": response.get("hasMore", False),
            "nextCursor": response.get("nextCursor"),
            "limit": limit,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/claims/{claim_id}")
def get_claim(
    claim_id: str,
    api_url: str = Query(...),
    api_key: str = Query(...),
):
    """获取单笔报销单详情"""
    try:
        from core.client import QihengClient
        client = QihengClient(api_key=api_key, base_url=api_url)
        detail = client.expense_claims_get(claim_id)
        return detail
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/attachments/{attachment_id}/content")
def get_attachment_content(
    attachment_id: str,
    api_url: Optional[str] = Query(None),
    api_key: Optional[str] = Query(None),
):
    """代理下载票据附件图片（供前端 <img> 展示，票据不出浏览器→后端→ERP 链路）"""
    import os
    try:
        from core.client import QihengClient
        client = QihengClient(
            api_key=api_key or os.environ.get("QIHENG_API_KEY"),
            base_url=api_url or os.environ.get("QIHENG_BASE_URL"),
        )
        content = client.attachments_content(attachment_id)
        info = client.attachments_get(attachment_id)
        mime = info.get("mimeType", "image/jpeg")
        return Response(content=content, media_type=mime)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"附件下载失败: {str(e)}")


@router.get("/claims/{claim_id}/ocr-fields")
def get_claim_ocr_fields(
    claim_id: str,
    api_url: Optional[str] = Query(None),
    api_key: Optional[str] = Query(None),
):
    """
    返回该报销单各附件的 OCR 购方抬头/税号（读取本地 OCR 缓存，不重复识别）
    及公司真实名称/税号，供前端三栏比对。
    """
    import os
    import json
    from pathlib import Path
    try:
        from core.client import QihengClient
        from data.config import COMPANY_NAME, COMPANY_TAX_NO
        client = QihengClient(
            api_key=api_key or os.environ.get("QIHENG_API_KEY"),
            base_url=api_url or os.environ.get("QIHENG_BASE_URL"),
        )
        detail = client.expense_claims_get(claim_id)

        repo_root = Path(__file__).resolve().parents[3]
        cache_dir = repo_root / "output" / "cache"
        ocr_map = {}
        for name in ("ocr_all_paddle.json", "ocr_samples_paddle.json",
                     "ocr_all_qwen.json", "ocr_samples_qwen.json"):
            path = cache_dir / name
            if not path.exists():
                continue
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for attach_id, fields in data.items():
                if isinstance(fields, dict):
                    ocr_map.setdefault(attach_id, {}).update({
                        "buyerName": fields.get("buyerName") or "",
                        "buyerTaxNo": fields.get("buyerTaxNo") or "",
                    })

        fields = {}
        for line in detail.get("lines", []):
            att = line.get("attachment") or {}
            if att and att.get("id"):
                fields[att["id"]] = ocr_map.get(att["id"], {})

        return {
            "claimId": claim_id,
            "companyName": COMPANY_NAME,
            "companyTaxNo": COMPANY_TAX_NO,
            "fields": fields,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

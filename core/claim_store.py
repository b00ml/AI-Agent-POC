"""
全量报销单数据存取层

职责：
1. 通过开放平台 API 拉取全量报销单详情（含历史单，用于跨单查重）
2. 本地 JSON 缓存（output/cache/all_claims.json），避免重复拉取
3. 构建发票（code/no -> [claimId]）全量索引
"""

import os
import json
from typing import List, Dict

from core.client import QihengClient, QihengError
from core.logger import get_logger

logger = get_logger("claim_store")

DEFAULT_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "output", "cache", "all_claims.json",
)


def _normalize_key(code: str, no: str) -> str:
    """发票索引键：去空白后拼接"""
    return f"{str(code or '').strip()}/{str(no or '').strip()}"


def fetch_all_claims(client: QihengClient, cache_file: str = DEFAULT_CACHE_FILE,
                     use_cache: bool = True, force: bool = False,
                     progress: bool = True) -> List[dict]:
    """
    拉取全量报销单详情（所有状态）。

    首次执行会对全部报销单（约 6000 张）逐单 GET 详情，约需 10-15 分钟；
    之后命中本地缓存秒回。force=True 强制刷新。
    """
    # Demo fixtures are intentionally isolated from self-hosted ERP caches.
    if getattr(client, "is_demo", False):
        use_cache = False
        force = True
    if use_cache and not force and os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    os.makedirs(os.path.dirname(cache_file), exist_ok=True)

    claims = []
    for i, claim in enumerate(client.expense_claims_iterate(), 1):
        try:
            detail = client.expense_claims_get(claim["id"])
            claims.append(detail)
        except QihengError as e:
            logger.warning(f"  x 获取 {claim['id']} 详情失败: {e.message}")
        if progress and i % 300 == 0:
            logger.info(f"  已拉取 {i} 单详情...")

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(claims, f, ensure_ascii=False)

    logger.info(f"全量报销单详情已缓存: {cache_file} ({len(claims)} 单)")
    return claims


def build_invoice_index(claims: List[dict]) -> Dict[str, List[str]]:
    """
    构建全量发票索引：invoiceCode/invoiceNo -> [claimId, ...]
    """
    index: Dict[str, List[str]] = {}
    for claim in claims:
        claim_id = claim.get("id", "")
        for line in claim.get("lines", []):
            invoice = line.get("invoice")
            if not invoice:
                continue
            key = _normalize_key(invoice.get("invoiceCode", ""), invoice.get("invoiceNo", ""))
            if not key or key == "/":
                continue
            if key not in index:
                index[key] = []
            if claim_id not in index[key]:
                index[key].append(claim_id)
    return index


def load_invoice_index(client: QihengClient, cache_file: str = DEFAULT_CACHE_FILE,
                       use_cache: bool = True, force: bool = False) -> Dict[str, List[str]]:
    """加载（或构建）全量发票索引"""
    claims = fetch_all_claims(client, cache_file=cache_file, use_cache=use_cache, force=force)
    return build_invoice_index(claims)

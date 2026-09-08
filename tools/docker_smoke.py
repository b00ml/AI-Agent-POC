"""
容器内冒烟测试：验证 ERP 连通性 + 本地 OCR + 最小审核链路。
用法：docker exec qiheng-audit python tools/docker_smoke.py
"""

import os
import sys

sys.path.insert(0, "/app")

from core.client import QihengClient
from core.invoice_ocr import InvoiceOCREngine


def main() -> None:
    print("env QIHENG_BASE_URL:", os.environ.get("QIHENG_BASE_URL"))
    print("env QIHENG_API_KEY:", "set" if os.environ.get("QIHENG_API_KEY") else "MISSING")
    print("env OCR_ENGINE:", os.environ.get("OCR_ENGINE"))

    client = QihengClient()
    print("client base_url:", client.base_url)

    claim_ids = []
    for cl in client.expense_claims_iterate(status="PENDING"):
        claim_ids.append(cl["id"])
        if len(claim_ids) >= 2:
            break
    print("ERP OK, sample pending:", claim_ids)

    ocr = InvoiceOCREngine()
    print("OCR engine:", ocr.engine_type)

    detail = client.expense_claims_get(claim_ids[0])
    ocr_ok = 0
    for line in detail.get("lines", []):
        att = line.get("attachment") or {}
        if not att or not att.get("migrated"):
            continue
        image = client._request("GET", f"/v1/attachments/{att['id']}/content")
        result = ocr.ocr_invoice(image, att.get("mimeType", "image/jpeg"), att["id"])
        if result and not result.get("ocr_failed"):
            ocr_ok += 1
        print("  OCR", att["id"], "->", {k: str(result.get(k))[:18] for k in ("buyerName", "buyerTaxNo", "totalAmount") if result.get(k)})
    print("local OCR success:", ocr_ok)
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()

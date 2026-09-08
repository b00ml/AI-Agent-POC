"""M2 详情页「审核结果」合并页签验证：规则结果 + AI 复核 + 审批建议。"""

import os
import requests
from playwright.sync_api import sync_playwright

API_URL = "http://host.docker.internal:8081"
API_KEY = os.environ.get("QIHENG_API_KEY", "")
BASE = "http://localhost:8000"


def main() -> None:
    # 先通过后端开启 AI 复核
    requests.put(BASE + "/api/settings/llm-review", json={"enabled": True}, timeout=15)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto("http://localhost:5173", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1200)
        dlg = page.locator(".el-dialog input").all()
        if dlg:
            dlg[0].fill(API_URL)
            dlg[1].fill(API_KEY)
        page.locator("button:has-text('验证并连接')").first.click()
        page.wait_for_timeout(2500)

        # 勾选第 1 单并批量审核
        page.locator(".el-table__row .el-checkbox").first.click()
        page.wait_for_timeout(500)
        page.locator("button:has-text('批量审核')").first.click()
        print("已点击批量审核，等待 AI 复核（约 30-60s）...")
        page.wait_for_timeout(60000)

        # 打开详情 → 审核结果页签
        page.locator(".claim-no-link").first.click()
        page.wait_for_timeout(3500)
        tabs = page.locator(".tab-btn").all_inner_texts()
        print("页签:", [t.strip() for t in tabs])
        page.locator("button:has-text('审核结果')").first.click()
        page.wait_for_timeout(1200)
        body = page.inner_text("body")
        print("含 '规则匹配结果':", "规则匹配结果" in body)
        print("含 'AI 审核结果':", "AI 审核结果" in body)
        print("含 '审批建议':", "审批建议" in body)
        print("含 '与规则一致/分歧':", ("与规则一致" in body) or ("与规则分歧" in body))
        print("含 '存疑复核':", "存疑复核" in body)
        page.screenshot(path=os.path.join(os.path.dirname(__file__), "screenshots", "e2e", "14_m2_result.png"), full_page=True)
        print("控制台错误:", len(errors))
        for e in errors[:8]:
            print("  ", e[:160])
        browser.close()
    requests.put(BASE + "/api/settings/llm-review", json={"enabled": False}, timeout=15)


if __name__ == "__main__":
    main()

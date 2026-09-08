"""M3 页面缓存秒开验证"""

import os
import time
from playwright.sync_api import sync_playwright

API_URL = "http://host.docker.internal:8081"
API_KEY = os.environ.get("QIHENG_API_KEY", "")


def main() -> None:
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

        t0 = time.time()
        page.locator(".nav-item:has-text('M3 异常检测')").first.click()
        page.wait_for_timeout(5000)
        body = page.inner_text("body")
        print("M3 页面加载耗时:", round(time.time() - t0, 1), "s")
        print("含 重复发票(组):", "重复发票(组)" in body)
        print("含 异常总数:", "异常总数" in body)
        print("含 最近一次扫描结果:", "最近一次扫描结果" in body)
        print("含 开始全量扫描:", "开始全量扫描" in body)
        print("控制台错误:", len(errors))
        for e in errors[:8]:
            print("  ", e[:160])
        browser.close()


if __name__ == "__main__":
    main()

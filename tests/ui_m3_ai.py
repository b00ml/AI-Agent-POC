"""M3 AI 复核展示验证：徽章 + 弹窗 AI 意见"""

import os
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

        page.locator(".nav-item:has-text('M3 异常检测')").first.click()
        page.wait_for_timeout(5000)
        body = page.inner_text("body")
        print("含 AI复核按钮:", "AI 复核异常" in body)
        print("含 AI确认 徽章:", "AI确认" in body)
        print("含 AI存疑 徽章:", "AI存疑" in body)

        rows = page.locator(".result-item.clickable").all()
        opened = False
        for i in range(min(60, len(rows))):
            rows[i].click()
            page.wait_for_timeout(1200)
            db = page.inner_text("body")
            if "AI 复核意见" in db:
                print("弹窗含 AI 复核意见: True")
                idx = db.find("AI 复核意见")
                print("  意见片段:", db[idx:idx + 120].replace("\n", " "))
                opened = True
                break
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
        print("找到带 AI 意见的异常:", opened)
        print("控制台错误:", len(errors))
        for e in errors[:8]:
            print("  ", e[:160])
        browser.close()


if __name__ == "__main__":
    main()

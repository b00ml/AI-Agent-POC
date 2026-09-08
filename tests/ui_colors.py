"""快速断言：通过绿/驳回红/存疑黄 的配色是否正确"""

import os
from playwright.sync_api import sync_playwright

API_URL = "http://host.docker.internal:8081"
API_KEY = os.environ.get("QIHENG_API_KEY", "")


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto("http://localhost:5173", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        dlg = page.locator(".el-dialog input").all()
        if dlg:
            dlg[0].fill(API_URL)
            dlg[1].fill(API_KEY)
        page.locator("button:has-text('验证并连接')").first.click()
        page.wait_for_timeout(3000)

        # 统计卡：通过/驳回/存疑 颜色
        cards = page.locator(".stats-cards .stat-card").all()
        print("统计卡数量:", len(cards))
        for c in cards:
            label = c.inner_text().strip().splitlines()[-1]
            color = c.evaluate("el => getComputedStyle(el).getPropertyValue('--card-color').trim()")
            print(f"  卡[{label}] --card-color={color}")

        # 详情页人工复核按钮颜色
        page.locator(".claim-no-link").first.click()
        page.wait_for_timeout(3500)
        page.locator("button:has-text('人工复核')").first.click()
        page.wait_for_timeout(800)
        btns = page.locator(".decision-btn").all()
        for b in btns:
            label = b.inner_text().strip().splitlines()[-1]
            color = b.evaluate("el => getComputedStyle(el).getPropertyValue('--decision-color').trim()")
            print(f"  复核按钮[{label}] --decision-color={color}")

        # 违规标签颜色
        page.locator("button:has-text('违规检测')").first.click()
        page.wait_for_timeout(800)
        tags = page.locator(".violations-panel .el-tag").all()
        for t in tags[:3]:
            cls = t.get_attribute("class") or ""
            print(f"  违规标签 class={cls}")
        browser.close()


if __name__ == "__main__":
    main()

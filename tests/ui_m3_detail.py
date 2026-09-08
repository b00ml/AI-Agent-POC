"""M3 异常详情下钻验证：点开重复发票，弹窗显示两张发票信息与截图"""

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

        # 点开第一组重复发票
        dup_row = page.locator(".result-item.clickable").first
        print("重复行存在:", dup_row.count() > 0)
        if dup_row.count() > 0:
            dup_row.click()
            page.wait_for_timeout(1500)
            body = page.inner_text("body")
            print("弹窗含 '发票代码/号码':", "发票代码/号码" in body)
            print("弹窗含 '购方名称':", "购方名称" in body)
            print("弹窗含 '判断依据':", "判断依据" in body)
            cards = page.locator(".invoice-detail-card").all()
            print("弹窗发票卡片数:", len(cards))
            imgs = page.locator(".invoice-img").all()
            print("弹窗图片数:", len(imgs))
            no_imgs = page.locator(".no-img").all()
            print("无影像提示数:", len(no_imgs))
            page.screenshot(path=os.path.join(os.path.dirname(__file__), "screenshots", "e2e", "12_m3_detail.png"))
            # 关闭弹窗，找一组可加载影像的重复发票
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
            rows = page.locator(".result-item.clickable").all()
            found_img = False
            for idx in range(min(10, len(rows))):
                rows[idx].click()
                page.wait_for_timeout(1200)
                imgs = page.locator(".invoice-img").all()
                ok = 0
                for img in imgs:
                    dim = img.evaluate("el => ({w: el.naturalWidth, h: el.naturalHeight})")
                    if dim["w"] > 0:
                        ok += 1
                print(f"第 {idx + 1} 组重复：图片 {len(imgs)} 张，可加载 {ok} 张")
                if ok > 0:
                    found_img = True
                    page.screenshot(path=os.path.join(os.path.dirname(__file__), "screenshots", "e2e", "13_m3_detail_img.png"))
                    break
                page.keyboard.press("Escape")
                page.wait_for_timeout(600)
            print("找到可加载影像的重复组:", found_img)
        print("控制台错误:", len(errors))
        for e in errors[:8]:
            print("  ", e[:160])
        browser.close()


if __name__ == "__main__":
    main()

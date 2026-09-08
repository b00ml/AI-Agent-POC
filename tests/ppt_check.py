"""解决方案 PPT 渲染验证：页数、版式、关键文案、截图。"""

import os
from playwright.sync_api import sync_playwright

DECK = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "doc", "solution_ppt", "index.html",
)
SHOT_DIR = os.path.join(os.path.dirname(__file__), "screenshots", "ppt")


def main() -> None:
    os.makedirs(SHOT_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 810})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto("file:///" + DECK.replace("\\", "/"), wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2500)

        sections = page.locator("section.slide").count()
        print("slide 数量:", sections)
        layouts = page.locator("section.slide").evaluate_all(
            "els => els.map(e => e.getAttribute('data-layout') + ':' + (e.getAttribute('data-animate')||''))"
        )
        print("版式序列:", layouts)

        html = page.content()
        print("HTML 含 [必填]:", "[必填]" in html)
        print("标题:", page.title())

        # 第 1 页截图 + 文案
        page.screenshot(path=os.path.join(SHOT_DIR, "01.png"))
        body = page.inner_text("body")
        print("封面含标题:", "让 AI 先读票" in body)

        # 逐页截图（ArrowRight 翻页）
        for i in range(1, sections):
            page.keyboard.press("ArrowRight")
            page.wait_for_timeout(1100)
            page.screenshot(path=os.path.join(SHOT_DIR, f"{i+1:02d}.png"))

        # 回到关键页抽查
        for _ in range(sections):
            page.keyboard.press("ArrowLeft")
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(1100)
        body = page.inner_text("body")
        print("现状/目标页含 'AI 预筛':", "AI 预筛" in body)
        for _ in range(8):
            page.keyboard.press("ArrowRight")
        page.wait_for_timeout(1100)
        body = page.inner_text("body")
        print("收尾页含 'TAKEAWAYS':", "TAKEAWAYS" in body)
        print("控制台错误:", len(errors))
        for e in errors[:8]:
            print("  ", e[:160])
        browser.close()


if __name__ == "__main__":
    main()

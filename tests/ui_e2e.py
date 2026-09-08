"""
前端 E2E 自测脚本（Playwright）

覆盖：连接 → 加载待审单 → 批量审核 → 详情（票据图片/OCR/违规/AI建议/人工复核）
     → M3 扫描 → M4 对账 → 设置（AI 复核开关）

用法：python tests/ui_e2e.py
"""

import os
import json

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5173"
API_URL = "http://host.docker.internal:8081"
API_KEY = os.environ.get("QIHENG_API_KEY", "")
SHOT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tests", "screenshots", "e2e")


def log(msg: str) -> None:
    print(f"[E2E] {msg}", flush=True)


def main() -> None:
    os.makedirs(SHOT_DIR, exist_ok=True)
    issues = []
    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(f"PAGEERROR: {e}"))

        # 1. 首页
        page.goto(BASE, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        page.screenshot(path=os.path.join(SHOT_DIR, "01_home.png"), full_page=True)
        log("首页标题: " + page.title())
        log("页面包含 'M2 合规审核': " + str("M2 合规审核" in page.content()))

        # 侦察：找出输入框与按钮
        inputs = page.locator("input").all()
        log(f"输入框数量: {len(inputs)}")
        for i, inp in enumerate(inputs[:6]):
            ph = inp.get_attribute("placeholder") or ""
            log(f"  input[{i}] placeholder={ph}")
        btns = page.locator("button").all()
        log(f"按钮: {[ (b.inner_text() or '').strip()[:20] for b in btns[:10] ]}")

        # 2. 连接（弹窗通常已自动打开）
        dialog_inputs = page.locator(".el-dialog input").all()
        if dialog_inputs:
            dialog_inputs[0].fill(API_URL)
            if len(dialog_inputs) > 1:
                dialog_inputs[1].fill(API_KEY)
        else:
            page.locator("button:has-text('连接 ERP')").first.click()
            page.wait_for_timeout(800)
            dialog_inputs = page.locator(".el-dialog input").all()
            if dialog_inputs:
                dialog_inputs[0].fill(API_URL)
                if len(dialog_inputs) > 1:
                    dialog_inputs[1].fill(API_KEY)
        page.screenshot(path=os.path.join(SHOT_DIR, "02_connect_dialog.png"))
        page.locator("button:has-text('验证并连接')").first.click()
        page.wait_for_timeout(2500)
        page.screenshot(path=os.path.join(SHOT_DIR, "03_after_connect.png"))
        body = page.inner_text("body")
        log("连接后页面含 '总单数': " + str("总单数" in body))
        if "连接失败" in body:
            issues.append("连接失败")

        # 3. 等待待审单加载（loadAll 300）
        page.wait_for_timeout(3000)
        body = page.inner_text("body")
        log("待审单加载后含 300: " + str("300" in body))

        # 4. 勾选前 3 单批量审核（el-table 复选列）
        checked = 0
        for i in range(3):
            cb = page.locator(".el-table__row .el-checkbox").nth(i)
            if cb.count() > 0:
                cb.click()
                checked += 1
        log(f"已勾选 {checked} 单")
        audit_btn = page.locator("button:has-text('批量审核')").first
        if audit_btn.count() > 0:
            audit_btn.click()
            log("已点击批量审核，等待完成（OCR+审核，约 30-60s）...")
            page.wait_for_timeout(60000)
        page.screenshot(path=os.path.join(SHOT_DIR, "04_after_audit.png"))
        body = page.inner_text("body")
        log("审核后页面含 '通过'/'驳回': " + str(("通过" in body) or ("驳回" in body)))

        # 5. 打开第一单详情
        link = page.locator(".claim-no-link").first
        if link.count() > 0:
            link.click()
            page.wait_for_timeout(4000)
        page.screenshot(path=os.path.join(SHOT_DIR, "05_detail.png"), full_page=True)
        body = page.inner_text("body")
        log("详情页含 '费用明细': " + str("费用明细" in body))
        log("详情页含 '票据图片': " + str("票据图片" in body))
        log("详情页含 '购方名称': " + str("购方名称" in body))

        # 票据图片是否真实加载
        img = page.locator(".invoice-image img").first
        if img.count() > 0:
            try:
                img.wait_for(timeout=8000)
                src = img.get_attribute("src")
                log(f"票据图片 img src: {src}")
                natural = img.evaluate("el => ({w: el.naturalWidth, h: el.naturalHeight})")
                log(f"图片实际尺寸: {natural}")
                if natural["w"] <= 0:
                    issues.append("票据图片未加载（naturalWidth=0）")
            except Exception as e:
                issues.append(f"票据图片加载失败: {str(e)[:100]}")
        else:
            issues.append("详情页未找到票据图片元素")

        # 6. 违规检测页签
        tab = page.locator("button:has-text('违规检测')").first
        if tab.count() > 0:
            tab.click()
            page.wait_for_timeout(800)
        page.screenshot(path=os.path.join(SHOT_DIR, "06_violations.png"))

        # 7. AI 建议页签
        tab = page.locator("button:has-text('AI 建议')").first
        if tab.count() > 0:
            tab.click()
            page.wait_for_timeout(800)
        page.screenshot(path=os.path.join(SHOT_DIR, "07_ai_advice.png"))

        # 8. 人工复核页签
        tab = page.locator("button:has-text('人工复核')").first
        if tab.count() > 0:
            tab.click()
            page.wait_for_timeout(800)
            # 选择驳回并提交
            reject_btn = page.locator("button:has-text('驳回')").first
            if reject_btn.count() > 0:
                reject_btn.click()
                submit_btn = page.locator("button:has-text('提交审核决定')").first
                if submit_btn.count() > 0:
                    submit_btn.click()
                    page.wait_for_timeout(3000)
        page.screenshot(path=os.path.join(SHOT_DIR, "08_review.png"))
        body = page.inner_text("body")
        log("复核提交后含 '回写': " + str("回写" in body))

        # 9. M3 页面
        page.goto(BASE + "/m3", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        page.screenshot(path=os.path.join(SHOT_DIR, "09_m3.png"))
        body = page.inner_text("body")
        log("M3 含 '开始全量扫描': " + str("开始全量扫描" in body))

        # 10. M4 页面
        page.goto(BASE + "/m4", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        page.screenshot(path=os.path.join(SHOT_DIR, "10_m4.png"))
        body = page.inner_text("body")
        log("M4 含 '开始对账': " + str("开始对账" in body))

        # 11. 设置页 AI 复核开关
        page.goto(BASE + "/settings", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        body = page.inner_text("body")
        log("设置页含 'AI 复核助手': " + str("AI 复核助手" in body))
        switch = page.locator(".el-switch").first
        if switch.count() > 0:
            switch.click()
            page.wait_for_timeout(1500)
            log("AI 复核开关已点击")
            switch.click()
            page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(SHOT_DIR, "11_settings.png"))

        browser.close()

    log("=" * 50)
    log(f"控制台错误 {len(console_errors)} 条:")
    for e in console_errors[:15]:
        log("  " + e[:200])
    log(f"问题清单 {len(issues)} 条:")
    for it in issues:
        log("  - " + it)
    with open(os.path.join(SHOT_DIR, "e2e_report.json"), "w", encoding="utf-8") as f:
        json.dump({"consoleErrors": console_errors, "issues": issues}, f, ensure_ascii=False, indent=2)
    log("报告已保存: " + os.path.join(SHOT_DIR, "e2e_report.json"))


if __name__ == "__main__":
    main()

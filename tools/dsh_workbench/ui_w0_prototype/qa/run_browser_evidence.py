"""W0 原创页面浏览器验收。只校验演示交互；不宣称宿主/真实服务已验收。"""
from __future__ import annotations
import argparse
import hashlib
import http.server
from pathlib import Path
import threading
from typing import Optional
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        pass


def run(output: Path, browser_path: Optional[str] = None) -> None:
    output.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, executable_path=browser_path) if browser_path else pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1380, "height": 850}, device_scale_factor=1)
            exceptions = []
            page.on("pageerror", lambda error: exceptions.append(str(error)))
            page.goto("http://127.0.0.1:{}/".format(server.server_port), wait_until="networkidle")
            assert page.locator("[data-page]").count() == 5
            page.get_by_role("button", name="进入项目详情").click()
            assert page.locator("#detail-tabs button").count() == 10

            page.get_by_label("投产日期").select_option("B12")
            page.get_by_label("需求", exact=True).select_option("R1")
            page.get_by_label("系统版本").select_option("V2")
            assert page.get_by_label("SST", exact=True).locator("option").all_text_contents() == ["全部 SST", "S3 · 审批系统"]
            page.get_by_label("SST", exact=True).select_option("S3")
            for title in ["项目概览", "质量任务", "需求", "测试用例", "缺陷", "里程碑", "报告", "知识", "会议纪要", "门禁"]:
                page.locator("#detail-tabs button").get_by_text(title, exact=True).click()
                assert "S3" in page.locator("#scope-echo").inner_text(), title
            page.locator("#detail-tabs button").get_by_text("需求", exact=True).click()
            page.screenshot(path=str(output / "wb-c-w0-scope-ten-sections.png"), full_page=True)

            page.get_by_label("需求", exact=True).select_option("R3")
            assert "待拆分 SST" in page.locator("#scope-status").inner_text()
            page.get_by_label("投产日期").select_option("B19")
            assert page.get_by_label("需求", exact=True).input_value() == ""
            assert page.get_by_label("SST", exact=True).input_value() == ""
            page.get_by_role("button", name="查看当前分区能力").click()
            assert "尚未接入正式业务 API" in page.locator("#detail-error").inner_text()

            page.get_by_role("button", name="切换主题").click()
            assert "dark" in page.locator("body").get_attribute("class")
            page.get_by_role("button", name="返回项目看板").click()
            assert page.locator(".stage").count() == 6
            page.get_by_role("button", name="新建项目／迭代").click()
            assert page.locator("#board-error").is_visible()
            page.screenshot(path=str(output / "wb-c-w0-six-stage-board.png"), full_page=True)
            page.get_by_role("button", name="DSH 测试对话").click()
            page.locator("#chat-message").fill("测试消息")
            page.get_by_role("button", name="发送").click()
            assert "未发送" in page.locator("#chat-error").inner_text()
            page.get_by_role("button", name="QA Skill 安装").click()
            page.get_by_role("button", name="安装技能").click()
            assert page.locator("#skill-error").is_visible()
            page.get_by_role("button", name="日历排期").click()
            page.get_by_role("button", name="新建日程").click()
            assert page.locator("#calendar-error").is_visible()
            page.get_by_role("button", name="测试首页").click()
            page.locator("#search").fill("登录策略")
            assert "关联匹配" in page.locator("#global-message").inner_text()
            page.get_by_role("button", name="收起侧栏").click()
            assert page.locator(".shell").get_attribute("class") == "shell collapsed"
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(output / "wb-c-w0-mobile.png"), full_page=True)
            assert not exceptions, exceptions
            browser.close()
    finally:
        server.shutdown()
    for file in sorted(output.glob("wb-c-w0-*.png")):
        print("{} SHA256={} bytes={}".format(file.name, hashlib.sha256(file.read_bytes()).hexdigest(), file.stat().st_size))
    print("W0_BROWSER_PROBE_PASS: six-page identity, ten sections, Scope, errors, dark theme and mobile")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("wb-c-w0-browser-evidence"))
    parser.add_argument("--chrome")
    options = parser.parse_args()
    run(options.output, options.chrome)

# -*- coding: utf-8 -*-
"""前端快速巡检：登录后逐页渲染，抓控制台报错与截图（开发期工具）"""
import io
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("FQ_BASE", "http://127.0.0.1:8019")
SHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "reports", "screenshots")
os.makedirs(SHOTS, exist_ok=True)

PAGES = [
    ("dashboard", "供应链驾驶舱"), ("suppliers", "供应商档案"), ("materials", "物料主数据"),
    ("requisitions", "请购单"), ("rfqs", "询价比价"), ("orders", "采购订单"),
    ("receipts", "收货质检"), ("stock", "库存台账"), ("stockops", "库存作业"),
    ("invoices", "结算付款"), ("reports", "报表分析"), ("integration", "集成中心"),
    ("settings", "基础设置"), ("logs", "操作日志"),
]


def launch(p):
    for kw in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
        try:
            return p.chromium.launch(**kw)
        except Exception:
            continue
    raise RuntimeError("没有可用的 Chromium / Edge 浏览器")


def main():
    errs = []
    with sync_playwright() as p:
        b = launch(p)
        ctx = b.new_context(viewport={"width": 1440, "height": 960})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append("console[%s] %s" % (m.type, m.text))
              if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append("pageerror %s" % e))
        pg.goto(BASE + "/login.html")
        pg.fill("#u", "admin")
        pg.fill("#p", "admin123")
        pg.click("#btn")
        pg.wait_for_url("**/index.html", timeout=15000)
        pg.wait_for_timeout(1200)
        for route, title in PAGES:
            pg.goto(BASE + "/index.html#" + route)
            pg.wait_for_timeout(1100)
            txt = pg.inner_text("#view")
            empty = len(txt.strip()) < 20 or "加载中" in txt
            bad = "页面渲染失败" in txt
            print("%-14s %-10s chars=%-6d %s" % (route, title, len(txt), "FAIL" if (empty or bad) else "ok"))
            pg.screenshot(path=os.path.join(SHOTS, "ui_%s.png" % route), full_page=False)
        b.close()
    if errs:
        print("\n--- 前端错误 %d 条 ---" % len(errs))
        for e in errs[:40]:
            print(" ·", e[:300])
        return 1
    print("\n前端巡检通过，无控制台错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())

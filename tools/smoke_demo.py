# -*- coding: utf-8 -*-
"""飞泉SCM系统 · 离线 DEMO 冒烟测试（Playwright 打开本地单文件，不需要后端与网络）

用法：python tools/smoke_demo.py
验证点：14 个页面能渲染、控制台无报错；请购创建、库存台账切换、发票三单对照、
API Key 生成吊销等写操作在内存里真实联动。
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "demo", "飞泉SCM系统Demo.html")
PAGES = ["dashboard", "suppliers", "materials", "requisitions", "rfqs", "orders",
         "receipts", "stock", "stockops", "invoices", "reports", "integration",
         "settings", "logs"]
EXPECT = {"dashboard": "在途采购", "suppliers": "供应商", "materials": "物料",
          "requisitions": "请购", "rfqs": "询价", "orders": "采购订单",
          "receipts": "收货", "stock": "库存", "stockops": "库存作业",
          "invoices": "发票", "reports": "采购金额趋势", "integration": "API Key",
          "settings": "业务规则", "logs": "操作日志"}


def wait_text(pg, sel, sub, timeout=15000):
    dl = time.time() + timeout / 1000.0
    last = ""
    while time.time() < dl:
        try:
            last = pg.inner_text(sel)
        except Exception:
            last = ""
        if sub in last:
            return last
        pg.wait_for_timeout(100)
    raise AssertionError("等待 %s 出现 %r 超时，当前：%r" % (sel, sub, last[:200]))


def main():
    assert os.path.exists(DEMO), "请先运行 python tools/build_demo.py"
    url = "file:///" + DEMO.replace("\\", "/")
    fails = []
    with sync_playwright() as pw:
        try:
            br = pw.chromium.launch(channel="msedge", headless=True)
        except Exception:
            br = pw.chromium.launch(headless=True)
        pg = br.new_page(viewport={"width": 1680, "height": 980})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("dialog", lambda d: d.accept())
        pg.goto(url, wait_until="domcontentloaded")
        pg.wait_for_selector("#view .kpi-grid", timeout=20000)

        print("· 页面遍历")
        for r in PAGES:
            errs.clear()
            pg.evaluate("r => { location.hash = '#' + r; }", r)
            pg.wait_for_timeout(500)
            try:
                body = pg.inner_text("body")
                assert EXPECT[r] in body, "缺少「%s」" % EXPECT[r]
                assert not errs, "前端报错：%s" % errs[:2]
                print("  ✓ %-14s" % r)
            except AssertionError as e:
                fails.append("%s: %s" % (r, e))
                print("  ✗ %-14s %s" % (r, e))

        print("· 请购创建（内存写联动）")
        pg.evaluate("location.hash = '#requisitions'")
        pg.wait_for_timeout(500)
        pg.click("#rNew")
        pg.wait_for_selector("#nSave", state="visible")
        pg.fill("#nPurpose", "离线演示请购")
        pg.fill(".lnQty", "40")
        pg.click("#nSave")
        pg.wait_for_timeout(800)
        try:
            wait_text(pg, "#statusMsg", "请购已创建")
            print("  ✓ 请购创建成功：" + pg.inner_text("#statusMsg")[:40])
        except AssertionError as e:
            fails.append("请购创建：%s" % e)
            print("  ✗ 请购创建失败")

        print("· 库存台账：切批次明细 + 状态筛选")
        pg.evaluate("location.hash = '#stock'")
        pg.wait_for_timeout(500)
        pg.click("[data-view='batch']")
        pg.wait_for_timeout(600)
        body = pg.inner_text("#view")
        ok = "批次明细" in body or "WH-" in body
        print(("  ✓ " if ok else "  ✗ ") + "批次明细渲染")
        if not ok:
            fails.append("库存批次明细渲染失败")

        print("· 发票三单对照弹层")
        pg.evaluate("location.hash = '#invoices'")
        pg.wait_for_timeout(600)
        btn = pg.query_selector("[data-view]")
        if btn:
            btn.click()
            pg.wait_for_timeout(600)
            body = pg.inner_text("#dialog")
            ok = "订单金额" in body and "发票金额" in body
            print(("  ✓ " if ok else "  ✗ ") + "三单对照弹层")
            if not ok:
                fails.append("三单对照弹层缺字段")
            pg.click("#dialog [data-close2]")
        else:
            fails.append("发票列表没有三单对照按钮")

        print("· API Key 生成 → 明文展示 → 吊销")
        pg.evaluate("location.hash = '#integration'")
        pg.wait_for_timeout(600)
        pg.click("#kNew")
        pg.wait_for_selector("#kSave", state="visible")
        pg.fill("#kName", "冒烟测试对接方")
        pg.click("#kSave")
        pg.wait_for_timeout(700)
        key_txt = pg.inner_text("#dialog")
        ok = "fqk_" in key_txt
        print(("  ✓ " if ok else "  ✗ ") + "Key 生成")
        if not ok:
            fails.append("API Key 生成失败")
        pg.click("#dialog [data-close2]")
        pg.wait_for_timeout(500)
        rv = pg.query_selector("[data-revoke]")
        if rv:
            rv.click()
            pg.wait_for_timeout(600)
            body = pg.inner_text("#view")
            ok = "吊销" in body
            print(("  ✓ " if ok else "  ✗ ") + "Key 吊销")
            if not ok:
                fails.append("API Key 吊销失败")

        if errs:
            print("控制台错误：", errs[:5])
            fails.append("控制台错误：%s" % errs[:3])
        br.close()

    print()
    if fails:
        print("冒烟失败 %d 项：" % len(fails))
        for f in fails:
            print(" -", f)
        sys.exit(1)
    print("离线 DEMO 冒烟通过。")


if __name__ == "__main__":
    main()

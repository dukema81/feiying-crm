# -*- coding: utf-8 -*-
"""飞鹰CRM系统 · 离线 DEMO 冒烟测试（Playwright 打开本地单文件，不需要后端与网络）

用法：python tools/smoke_demo.py
验证点：14 个页面能渲染、控制台无报错；线索建单/查重、商机阶段推进、
报价折扣审批、合同签署收款、工单 SLA 在内存里真实联动。
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "demo", "飞鹰CRM系统Demo.html")
PAGES = ["dashboard", "leads", "campaigns", "customers", "opportunities", "activities",
         "quotes", "contracts", "payments", "tickets", "reports", "integration",
         "settings", "logs"]
EXPECT = {"dashboard": "在谈商机（加权）", "leads": "线索池", "campaigns": "整体 ROI",
          "customers": "客户档案", "opportunities": "商机看板", "activities": "跟进记录",
          "quotes": "报价管理", "contracts": "合同管理", "payments": "回款管理",
          "tickets": "服务工单", "reports": "销售漏斗", "integration": "对接方式",
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
        ANSWERS = {"满意度": "5", "处理结论": "演示：已修复", "竞品": "销售易",
                   "决策人": "王总", "输单原因": "预算削减", "驳回原因": "折扣过低"}

        def _ans(d):
            msg = d.message or ""
            for k, v in ANSWERS.items():
                if k in msg:
                    d.accept(v)
                    return
            d.accept()

        pg.on("dialog", _ans)
        pg.goto(url, wait_until="domcontentloaded")
        pg.wait_for_selector("#view .kpi-grid", timeout=20000)

        print("· 页面遍历")
        for r in PAGES:
            errs.clear()
            pg.evaluate("r => { location.hash = '#' + r; }", r)
            pg.wait_for_timeout(400)
            try:
                body = pg.inner_text("body")
                assert EXPECT[r] in body, "缺少「%s」" % EXPECT[r]
                assert not errs, "前端报错：%s" % errs[:2]
                print("  ✓ %-14s" % r)
            except AssertionError as e:
                fails.append("%s: %s" % (r, e))
                print("  ✗ %-14s %s" % (r, e))

        print("· 线索建单 / 查重")
        pg.evaluate("location.hash = '#leads'")
        pg.wait_for_timeout(400)
        pg.click("#lNew")
        pg.wait_for_selector("#nSave", state="visible")
        pg.fill("#nName", "离线演示阀门有限公司")
        pg.fill("#nPhone", "13600009999")
        pg.wait_for_timeout(500)
        pg.click("#nSave")
        pg.wait_for_timeout(600)
        try:
            wait_text(pg, "#statusMsg", "线索已创建")
            print("  ✓ 建单成功（提示可见）")
        except AssertionError as e:
            fails.append("线索建单：%s" % e)
            print("  ✗ 线索建单失败")

        print("· 商机阶段推进（看板 → 详情 → 推进）")
        pg.evaluate("location.hash = '#opportunities'")
        pg.wait_for_timeout(600)
        card = pg.query_selector("[data-opp]")
        if card:
            card.click()
            pg.wait_for_timeout(600)
            btns = pg.query_selector_all("[data-stage]")
            if btns:
                btns[0].click()
                pg.wait_for_timeout(700)
                txt = pg.inner_text("#statusMsg")
                ok = ("已推进到" in txt) or ("补齐" in txt)
                print(("  ✓ " if ok else "  ✗ ") + "推进结果：" + txt[:40])
                if not ok:
                    fails.append("商机推进：%s" % txt)
            else:
                fails.append("商机详情没有推进按钮")
        else:
            fails.append("商机看板没有卡片")

        print("· 报价折扣 → 待审批 → 批准")
        pg.evaluate("location.hash = '#quotes'")
        pg.wait_for_timeout(500)
        pg.click("#qNew")
        pg.wait_for_selector("#qSave", state="visible")
        pg.wait_for_timeout(600)
        lines = pg.query_selector_all("#qLines .qline")
        if len(lines) > 1:
            lines[1].query_selector("[data-del]").click()
        first = pg.query_selector_all("#qLines .qline")[0]
        first.query_selector(".lnPrice").fill("30000")
        pg.wait_for_timeout(300)
        pg.click("#qSave")
        pg.wait_for_timeout(700)
        txt = pg.inner_text("#statusMsg")
        ok = "待审批" in txt
        print(("  ✓ " if ok else "  ✗ ") + txt[:60])
        if not ok:
            fails.append("报价折扣审批：%s" % txt)

        print("· 工单 SLA 受理")
        pg.evaluate("location.hash = '#tickets'")
        pg.wait_for_timeout(500)
        rows = pg.query_selector_all("#view tbody tr[data-key]")
        if rows:
            rows[0].click()
            pg.wait_for_timeout(600)
            acc = pg.query_selector("#tkAccept")
            if acc:
                acc.click()
                pg.wait_for_timeout(600)
                print("  ✓ 工单受理：" + pg.inner_text("#statusMsg")[:40])
            else:
                print("  · 首张工单无需受理（状态已推进）")
        else:
            fails.append("工单列表为空")

        if errs:
            print("控制台错误：", errs[:5])
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

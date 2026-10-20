# -*- coding: utf-8 -*-
"""飞泉 SCM · 端到端 UI 测试：14 个页面渲染 + 关键交互流程（Playwright）"""
import os

import pytest

pytestmark = pytest.mark.e2e

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "reports", "screenshots")
os.makedirs(SHOTS, exist_ok=True)

PAGES = [
    ("dashboard", "供应链驾驶舱"), ("suppliers", "供应商档案"), ("materials", "物料主数据"),
    ("requisitions", "请购单"), ("rfqs", "询价比价"), ("orders", "采购订单"),
    ("receipts", "收货质检"), ("stock", "库存台账"), ("stockops", "库存作业"),
    ("invoices", "结算付款"), ("reports", "报表分析"), ("integration", "集成中心"),
    ("settings", "基础设置"), ("logs", "操作日志"),
]

CONSOLE_ERRORS = []


def _launch(p):
    for kw in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
        try:
            return p.chromium.launch(**kw)
        except Exception:
            continue
    pytest.skip("本机没有可用的 Chromium / Edge 浏览器")


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = _launch(p)
        yield b
        b.close()


@pytest.fixture(scope="module")
def page(browser, e2e):
    ctx = browser.new_context(viewport={"width": 1440, "height": 960})
    pg = ctx.new_page()
    pg.on("console", lambda m: CONSOLE_ERRORS.append("%s: %s" % (m.type, m.text))
          if m.type == "error" else None)
    pg.on("pageerror", lambda e: CONSOLE_ERRORS.append("pageerror: %s" % e))
    pg.on("dialog", lambda d: d.accept())
    pg.goto(e2e.base + "/login.html")
    pg.fill("#u", "admin")
    pg.fill("#p", "admin123")
    pg.click("#btn")
    pg.wait_for_url("**/index.html", timeout=20000)
    pg.wait_for_timeout(1200)
    yield pg
    ctx.close()


def _open(pg, e2e, route, wait=1100):
    pg.goto(e2e.base + "/index.html#" + route)
    pg.wait_for_timeout(wait)


def _view_text(pg):
    return pg.inner_text("#view")


# ------------------------------------------------------------ 用例
def test_shell_and_title(page):
    assert "飞泉 SCM" in page.title()
    assert page.locator("#tree a").count() >= 14


def test_dashboard_kpis(page, e2e):
    _open(page, e2e, "dashboard")
    txt = _view_text(page)
    assert "在途采购" in txt and "缺料预警" in txt and "待办与预警" in txt
    page.screenshot(path=os.path.join(SHOTS, "e2e_dashboard.png"))


def test_all_pages_render(page, e2e):
    bad = []
    for route, title in PAGES:
        _open(page, e2e, route)
        txt = _view_text(page)
        if len(txt.strip()) < 20 or "页面渲染失败" in txt or "加载中…" in txt:
            bad.append(route)
        page.screenshot(path=os.path.join(SHOTS, "e2e_%s.png" % route))
    assert not bad, "以下页面渲染异常：%s" % ", ".join(bad)


def test_supplier_360_dialog(page, e2e):
    _open(page, e2e, "suppliers")
    page.locator("#view tbody tr[data-key]").first.click()
    page.wait_for_timeout(900)
    assert "资质" in page.inner_text("#dialog") or "绩效" in page.inner_text("#dialog")
    page.screenshot(path=os.path.join(SHOTS, "e2e_supplier_360.png"))
    page.click("#dialog [data-close]")


def test_create_requisition_ui(page, e2e):
    _open(page, e2e, "requisitions")
    page.click("#rNew")
    page.wait_for_timeout(400)
    page.fill("#nPurpose", "端到端测试请购")
    page.fill(".lnQty", "30")
    page.click("#nSave")
    page.wait_for_timeout(1000)
    assert "端到端测试请购" in _view_text(page) or "PR" in _view_text(page)
    page.screenshot(path=os.path.join(SHOTS, "e2e_req_created.png"))


def test_stock_batch_view_and_filter(page, e2e):
    _open(page, e2e, "stock")
    page.click("[data-view='batch']")
    page.wait_for_timeout(900)
    txt = _view_text(page)
    assert "批次" in txt and ("WH-" in txt or "仓库" in txt)
    page.click("[data-state='待补货']")
    page.wait_for_timeout(700)
    page.screenshot(path=os.path.join(SHOTS, "e2e_stock_batch.png"))


def test_stockops_tabs(page, e2e):
    _open(page, e2e, "stockops")
    for tab, hint in (("transfers", "调拨"), ("stocktakes", "盘点"), ("adjust", "调整"),
                      ("moves", "流水")):
        page.click("[data-tab='%s']" % tab)
        page.wait_for_timeout(700)
        assert hint in _view_text(page)
    page.screenshot(path=os.path.join(SHOTS, "e2e_stockops.png"))


def test_invoice_triple_match_dialog(page, e2e):
    _open(page, e2e, "invoices")
    btns = page.locator("[data-view]")
    if btns.count() == 0:
        pytest.skip("没有发票数据")
    btns.first.click()
    page.wait_for_timeout(800)
    txt = page.inner_text("#dialog")
    assert "订单金额" in txt and "收货金额" in txt and "发票金额" in txt
    page.screenshot(path=os.path.join(SHOTS, "e2e_invoice_match.png"))
    page.click("#dialog [data-close2]")


def test_reports_modules(page, e2e):
    _open(page, e2e, "reports", wait=1400)
    txt = _view_text(page)
    for m in ("采购金额趋势", "物料类别", "供应商绩效", "库存周转", "准时率", "价格波动",
              "应付账龄"):
        assert m in txt, m
    assert page.locator("#view svg").count() >= 2
    page.screenshot(path=os.path.join(SHOTS, "e2e_reports.png"))


def test_integration_key_lifecycle(page, e2e):
    _open(page, e2e, "integration")
    page.click("#kNew")
    page.wait_for_timeout(400)
    page.fill("#kName", "端到端测试对接")
    page.click("#kSave")
    page.wait_for_timeout(800)
    key_text = page.inner_text("#dialog")
    assert "fqk_" in key_text and "我已保存" in key_text
    page.click("#dialog [data-close2]")
    page.wait_for_timeout(600)
    page.screenshot(path=os.path.join(SHOTS, "e2e_integration_key.png"))
    # 吊销刚建的 Key（confirm 自动接受）
    page.locator("[data-revoke]").first.click()
    page.wait_for_timeout(800)
    assert "吊销" in _view_text(page)


def test_settings_and_logs(page, e2e):
    _open(page, e2e, "settings")
    assert "业务规则" in _view_text(page) and "用户与角色" in _view_text(page)
    _open(page, e2e, "logs")
    assert "操作日志" in _view_text(page)
    page.screenshot(path=os.path.join(SHOTS, "e2e_logs.png"))


def test_non_admin_sees_locked_integration(page, e2e):
    # 用仓管账号在独立标签页验证权限锁定
    ctx = page.context
    pg2 = ctx.new_page()
    pg2.goto(e2e.base + "/login.html")
    pg2.evaluate("localStorage.clear()")
    pg2.reload()
    pg2.fill("#u", "sunlei")
    pg2.fill("#p", "fe@2026")
    pg2.click("#btn")
    pg2.wait_for_url("**/index.html", timeout=20000)
    pg2.goto(e2e.base + "/index.html#integration")
    pg2.wait_for_timeout(1000)
    assert "管理员" in pg2.inner_text("#view")
    pg2.close()


def test_no_console_errors():
    assert not CONSOLE_ERRORS, "前端控制台错误：%s" % " | ".join(CONSOLE_ERRORS[:10])

# -*- coding: utf-8 -*-
"""飞鹰 CRM · 端到端 UI 测试（Playwright + Edge/Chromium headless，16 项）

覆盖：登录与驾驶舱、14 个功能页遍历、线索建单/查重提示/跟进/转客户、
客户 360 六标签、商机阶段闸口推进、报价折扣审批与发送、合同签署与收款、
工单 SLA 全流程（受理/解决/关闭评价）、报表 6 标签、市场 ROI、
集成中心 API Key 与 Webhook、规则启停、会话失效跳转、非管理员集成锁定。
"""
import os
import sys
import time

import pytest
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
SHOT_DIR = os.path.join(ROOT, "reports", "screenshots")

PAGES = ["dashboard", "leads", "campaigns", "customers", "opportunities", "activities",
         "quotes", "contracts", "payments", "tickets", "reports", "integration",
         "settings", "logs"]

_EXPECT = {
    "dashboard": "在谈商机（加权）", "leads": "线索池", "campaigns": "整体 ROI",
    "customers": "客户档案", "opportunities": "商机看板", "activities": "跟进记录",
    "quotes": "报价管理", "contracts": "合同管理", "payments": "回款管理",
    "tickets": "服务工单", "reports": "销售漏斗", "integration": "API Key",
    "settings": "业务规则", "logs": "操作日志",
}

# window.prompt / confirm 的自动应答（按提示语包含的关键字匹配）
ANSWERS = {
    "处理结论": "已定位原因并修复，请客户验证",
    "满意度": "5",
    "竞品": "销售易",
    "决策人": "王建国 信息总监",
    "赢单要点": "价格与服务优于竞品",
    "输单原因": "预算被削减，选择自研",
    "驳回原因": "折扣过低，需再谈",
    "终止原因": "客户项目终止",
    "无效原因": "预算不足，暂无采购计划",
    "分配": "liuyang",
    "回复内容": "已收到，正在排查",
}


def _ans(dlg):
    msg = dlg.message or ""
    for k, v in ANSWERS.items():
        if k in msg:
            dlg.accept(v)
            return
    dlg.accept()


@pytest.fixture(scope="session")
def browser_ctx(e2e):
    with sync_playwright() as p:
        try:
            br = p.chromium.launch(channel="msedge", headless=True)
        except Exception:
            br = p.chromium.launch(headless=True)
        ctx = br.new_context(viewport={"width": 1680, "height": 980})
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append(m.text)
              if m.type == "error" and "status of 4" not in m.text else None)
        pg.on("dialog", _ans)
        pg._base = e2e.base.rstrip("/") + "/"
        yield pg, errors
        br.close()


@pytest.fixture()
def page_ctx(browser_ctx, request):
    pg, errors = browser_ctx
    errors.clear()
    yield pg, errors
    try:
        os.makedirs(SHOT_DIR, exist_ok=True)
        name = request.node.name
        name = name[5:] if name.startswith("test_") else name
        pg.screenshot(path=os.path.join(SHOT_DIR, "e2e-%s.png" % name), full_page=True)
    except Exception:
        pass


# ------------------------------------------------------------------ 工具
def wait_until(pg, cond, timeout=20000, desc=""):
    dl = time.time() + timeout / 1000.0
    while time.time() < dl:
        try:
            if cond():
                return True
        except Exception:
            pass
        pg.wait_for_timeout(120)
    raise AssertionError("等待条件超时：%s" % (desc or cond))


def wait_text(pg, sel, sub, timeout=20000):
    dl = time.time() + timeout / 1000.0
    last = ""
    while time.time() < dl:
        try:
            last = pg.inner_text(sel)
        except Exception:
            last = ""
        if sub in last:
            return last
        pg.wait_for_timeout(120)
    raise AssertionError("等待 %s 出现 %r 超时，当前内容：%r" % (sel, sub, last[:300]))


def mask_on(pg):
    el = pg.query_selector("#mask")
    return bool(el) and "on" in (el.get_attribute("class") or "")


def wait_dialog(pg, sub, timeout=20000):
    """等弹层打开且正文含指定文本（F.closeDialog 不清空内容，必须同时判 mask）。"""
    dl = time.time() + timeout / 1000.0
    last = ""
    while time.time() < dl:
        if mask_on(pg):
            try:
                last = pg.inner_text("#dialog")
            except Exception:
                last = ""
            if sub in last:
                return last
        pg.wait_for_timeout(120)
    raise AssertionError("等待对话框出现 %r 超时，当前内容：%r" % (sub, last[:300]))


def wait_closed(pg, timeout=20000):
    wait_until(pg, lambda: not mask_on(pg), timeout, "弹层关闭")


def row_keys(pg):
    return [tr.get_attribute("data-key") for tr in pg.query_selector_all("#view tbody tr[data-key]")]


def wait_row(pg, key, timeout=20000):
    wait_until(pg, lambda: key in row_keys(pg), timeout, "列表出现 %s" % key)


def open_row(pg, key, dlg_sub, timeout=20000):
    """点击 data-key == key 的行并等详情弹层（表格会重绘致元素 detach，故循环重试）。"""
    dl = time.time() + timeout / 1000.0
    while time.time() < dl:
        tr = pg.query_selector('#view tbody tr[data-key="%s"]' % key)
        if tr:
            try:
                tr.click(timeout=3000)
            except Exception:
                pg.wait_for_timeout(120)
                continue
            return wait_dialog(pg, dlg_sub)
        pg.wait_for_timeout(120)
    raise AssertionError("未找到 data-key=%s 的表格行" % key)


def login_as(pg, base, username, password=None):
    password = password or ("admin123" if username == "admin" else "fe@2026")
    pg.goto(base + "login.html", wait_until="domcontentloaded")
    pg.evaluate("() => { try { localStorage.clear(); sessionStorage.clear(); } catch (e) {} }")
    pg.reload(wait_until="domcontentloaded")
    pg.wait_for_selector("#u", timeout=15000)
    pg.fill("#u", username)
    pg.fill("#p", password)
    pg.click("#btn")
    pg.wait_for_url("**/index.html*", timeout=20000)
    pg.wait_for_selector("#view .panel, #view .kpi-grid", timeout=20000)


def login(pg, base):
    login_as(pg, base, "admin")


def nav(pg, base, route, errors):
    pg.goto(base + "index.html#" + route, wait_until="domcontentloaded")
    pg.reload(wait_until="domcontentloaded")
    pg.wait_for_selector("#view .panel, #view .kpi-grid", timeout=20000)
    errors.clear()


def search(pg, kw_sel, kw, btn_sel):
    pg.fill(kw_sel, kw)
    pg.click(btn_sel)


# ------------------------------------------------------------------ 用例
def test_login_and_dashboard(page_ctx):
    pg, errors = page_ctx
    login(pg, pg._base)
    body = pg.inner_text("body")
    assert "销售驾驶舱" in body
    for k in ("在谈商机（加权）", "本月签约", "赢单率", "逾期应收", "待处理工单", "客户 / 在跟线索"):
        assert k in body, "驾驶舱缺少 KPI：%s" % k
    assert "销售漏斗（按金额）" in body and "近 6 个月签约趋势" in body
    assert errors == []


def test_all_pages_traverse(page_ctx):
    pg, errors = page_ctx
    login(pg, pg._base)
    for r in PAGES:
        nav(pg, pg._base, r, errors)
        body = pg.inner_text("body")
        assert _EXPECT[r] in body, "%s 缺少关键文案「%s」" % (r, _EXPECT[r])
        assert len(body) > 300, "%s 内容过少" % r
        assert errors == [], "%s 有前端错误：%s" % (r, errors)


def test_lead_create_dup_hint_and_follow(page_ctx, e2e):
    pg, errors = page_ctx
    e2e.login("admin")
    login(pg, pg._base)
    nav(pg, pg._base, "leads", errors)

    name = "UI 建单阀门" + str(int(time.time()) % 100000)
    pg.click("#lNew")
    wait_dialog(pg, "新建线索")
    pg.fill("#nName", name)
    pg.fill("#nContact", "周工")
    pg.fill("#nPhone", "13600001234")
    pg.fill("#nBudget", "680000")
    pg.select_option("#nSource", "展会")
    pg.click("#nContact")
    wait_text(pg, "#dupHint", "未发现重复")

    with pg.expect_response(lambda r: r.url.endswith("/api/leads")
                            and r.request.method == "POST") as info:
        pg.click("#nSave")
    body = info.value.json()["data"]
    no = body["no"]
    assert no.startswith("LD2026"), "单号规则不符：%s" % no
    assert body["grade"] == "A", "68 万预算 + 展会来源应为 A 级，实际 %s" % body["grade"]
    wait_closed(pg)
    wait_text(pg, "#statusMsg", "线索已创建")

    search(pg, "#fKw", name, "#btnSearch")
    wait_row(pg, no)
    text = open_row(pg, no, no)
    assert "跟进时间线" in text and "等级 A" in text

    pg.click("#ldFollow")
    wait_dialog(pg, "写跟进")
    pg.fill("#fSub", "首次电话沟通")
    pg.fill("#fCon", "确认预算与决策链，客户希望 11 月完成选型")
    pg.fill("#fNext", "下周发送方案")
    pg.click("#fSave")
    wait_closed(pg)
    wait_text(pg, "#statusMsg", "跟进已记录")
    assert e2e.ok("GET", "/api/leads/" + no)["activities"], "跟进应落库"
    assert errors == []


def test_lead_convert_to_customer(page_ctx, e2e):
    pg, errors = page_ctx
    e2e.login("admin")
    name = "UI 转客户机械" + str(int(time.time()) % 100000)
    lead = e2e.ok("POST", "/api/leads", {"name": name, "phone": "13600002222",
                                         "contact": "李经理", "source": "官网表单",
                                         "budget": 260000, "owner": "liuyang"})
    assert lead["status"] == "跟进中"

    login(pg, pg._base)
    nav(pg, pg._base, "leads", errors)
    search(pg, "#fKw", name, "#btnSearch")
    wait_row(pg, lead["no"])
    open_row(pg, lead["no"], lead["no"])
    pg.click("#ldConvert")
    text = wait_dialog(pg, "客户 360", timeout=25000)
    assert "在谈商机" in text and "累计回款" in text
    detail = e2e.ok("GET", "/api/leads/" + lead["no"])
    assert detail["status"] == "已转客户" and detail["convertedCustomer"]
    pg.click("[data-close5]")            # 关掉客户 360 弹层
    wait_closed(pg)
    assert errors == []


def test_customer_create_and_360_tabs(page_ctx, e2e):
    pg, errors = page_ctx
    e2e.login("admin")
    login(pg, pg._base)
    nav(pg, pg._base, "customers", errors)

    name = "UI 新建客户" + str(int(time.time()) % 100000)
    pg.click("#cNew")
    wait_dialog(pg, "新建客户")
    pg.fill("#kName", name)
    pg.fill("#kPhone", "13700003333")
    pg.fill("#kCredit", "500000")
    with pg.expect_response(lambda r: r.url.endswith("/api/customers")
                            and r.request.method == "POST") as info:
        pg.click("#kSave")
    code = info.value.json()["data"]["code"]
    assert code.startswith("C-")
    wait_closed(pg)

    search(pg, "#cKw", name, "#cSearch")
    wait_row(pg, code)
    text = open_row(pg, code, "客户 360")
    for k in ("在谈商机", "已签合同", "累计回款", "逾期应收", "未结工单", "满意度"):
        assert k in text, "客户 360 缺少指标：%s" % k
    tabs = [b.inner_text() for b in pg.query_selector_all("#cTabs button")]
    assert tabs == ["联系人", "商机", "报价", "合同", "工单", "时间线"], tabs

    # 六个标签逐个点开，内容区要跟着换
    markers = {1: "商机", 2: "报价单", 3: "合同", 4: "优先级"}
    for idx, marker in markers.items():
        pg.click('#cTabs button[data-tab="%d"]' % idx)
        wait_text(pg, "#cTabBody", marker)
    pg.click('#cTabs button[data-tab="0"]')
    wait_text(pg, "#cTabBody", "姓名")
    assert e2e.ok("GET", "/api/customers/" + code)["code"] == code
    pg.click("[data-close5]")
    wait_closed(pg)
    assert errors == []


def test_opportunity_stage_gate_advance(page_ctx, e2e):
    pg, errors = page_ctx
    e2e.login("admin")
    code = e2e.ok("GET", "/api/customers?pageSize=1")["list"][0]["code"]
    opp = e2e.ok("POST", "/api/opportunities",
                 {"name": "UI 阶段推进商机" + str(int(time.time()) % 100000),
                  "customerCode": code, "amount": 460000, "expectCloseDate": "2026-12-31",
                  "decisionMaker": "王建国 信息总监", "competitor": ""})
    assert opp["stage"] == "初步接触" and opp["probability"] == 0.1

    login(pg, pg._base)
    nav(pg, pg._base, "opportunities", errors)
    search(pg, "#oKw", opp["no"], "#oSearch")
    pg.click("#vList")
    wait_row(pg, opp["no"])
    text = open_row(pg, opp["no"], "阶段闸口")
    assert "可进入" in text and "缺 " in text, "闸口应同时展示可进入与缺失项"

    pg.click('[data-stage="需求确认"]')
    wait_closed(pg)
    wait_text(pg, "#statusMsg", "已推进到「需求确认」")
    got = e2e.ok("GET", "/api/opportunities/" + opp["no"])
    assert got["stage"] == "需求确认" and got["probability"] == 0.25
    assert got["stageLogs"], "阶段轨迹应留痕"

    # 跨级推进 + 闸口拦截：直接推到商务谈判（缺竞品→补录后成功）
    pg.click("#vBoard")
    wait_until(pg, lambda: pg.query_selector('[data-opp="%s"]' % opp["no"]) is not None,
               desc="看板出现商机卡片")
    pg.click('[data-opp="%s"]' % opp["no"])
    wait_dialog(pg, "阶段闸口")
    pg.click('[data-stage="商务谈判"]')          # prompt 自动补竞品与决策人
    wait_closed(pg)
    wait_text(pg, "#statusMsg", "商务谈判")
    got = e2e.ok("GET", "/api/opportunities/" + opp["no"])
    assert got["stage"] == "商务谈判" and got["competitor"]
    assert errors == []


def test_quote_discount_approval_flow(page_ctx, e2e):
    pg, errors = page_ctx
    e2e.login("admin")
    login(pg, pg._base)
    nav(pg, pg._base, "quotes", errors)

    pg.click("#qNew")
    wait_dialog(pg, "新建报价")
    wait_until(pg, lambda: len(pg.query_selector_all("#qLines .qline")) >= 2,
               desc="报价明细行加载")
    lines = pg.query_selector_all("#qLines .qline")
    lines[1].query_selector("[data-del]").click()       # 只留一行，折扣口径清晰
    first = pg.query_selector_all("#qLines .qline")[0]
    first.query_selector(".lnQty").fill("1")
    first.query_selector(".lnPrice").fill("30000")      # 标准价 4.8 万 → 折扣 37.5%（超 15% 审批线）
    wait_text(pg, "#qCalc", "超审批线")

    with pg.expect_response(lambda r: r.url.endswith("/api/quotes")
                            and r.request.method == "POST") as info:
        pg.click("#qSave")
    created = info.value.json()["data"]
    assert created["status"] == "待审批", "超阈值应进入待审批，实际 %s" % created["status"]
    assert created["discountPct"] > 15
    wait_closed(pg)

    search(pg, "#qKw", created["no"], "#qSearch")
    wait_row(pg, created["no"])
    text = open_row(pg, created["no"], created["no"])
    assert "审批线" in text and "折扣率" in text

    pg.click("#qApprove")
    wait_closed(pg)
    wait_text(pg, "#statusMsg", "已批准")
    got = e2e.ok("GET", "/api/quotes/" + created["no"])
    assert got["status"] == "已批准" and got["approverName"]

    # 批准后才能发送、再标记客户接受
    open_row(pg, created["no"], created["no"])
    pg.click("#qSend")
    wait_closed(pg)
    wait_until(pg, lambda: e2e.ok("GET", "/api/quotes/" + created["no"])["status"] == "已发送",
               desc="报价已发送")
    open_row(pg, created["no"], created["no"])
    pg.click("#qAccept")
    wait_closed(pg)
    wait_until(pg, lambda: e2e.ok("GET", "/api/quotes/" + created["no"])["status"] == "已接受",
               desc="报价被客户接受")
    assert errors == []


def test_contract_sign_and_payment(page_ctx, e2e):
    pg, errors = page_ctx
    e2e.login("admin")
    login(pg, pg._base)
    nav(pg, pg._base, "contracts", errors)

    pg.click("#tNew")
    wait_dialog(pg, "新建合同")
    pg.fill("#tTitle", "UI 签署回款合同")
    pg.fill("#tAmount", "120000")
    pg.select_option("#tTerms", "5-5")
    with pg.expect_response(lambda r: r.url.endswith("/api/contracts")
                            and r.request.method == "POST") as info:
        pg.click("#tSave")
    no = info.value.json()["data"]["no"]
    assert no.startswith("CT2026"), "合同号规则不符：%s" % no
    wait_closed(pg)

    search(pg, "#tKw", no, "#tSearch")
    wait_row(pg, no)
    text = open_row(pg, no, no)
    assert "5-5" in text and "回款计划" in text
    plans = e2e.ok("GET", "/api/contracts/" + no)["plans"]
    assert len(plans) == 2 and abs(sum(p["amount"] for p in plans) - 120000) < 0.01

    pg.click("#ctSign")
    wait_closed(pg)
    wait_text(pg, "#statusMsg", "合同已签署")
    assert e2e.ok("GET", "/api/contracts/" + no)["status"] in ("已签署", "执行中")

    open_row(pg, no, no)
    pg.click("#ctPay")
    wait_dialog(pg, "登记收款")
    pg.fill("#pAmount", "60000")
    with pg.expect_response(lambda r: r.url.endswith("/api/payments")
                            and r.request.method == "POST") as pay:
        pg.click("#pSave")
    body = pay.value.json()["data"]
    assert abs(body["amount"] - 60000) < 0.01
    wait_closed(pg)
    wait_text(pg, "#statusMsg", "已登记收款")

    got = e2e.ok("GET", "/api/contracts/" + no)
    assert abs(got["paidAmount"] - 60000) < 0.01 and abs(got["unpaidAmount"] - 60000) < 0.01
    assert got["payments"] and got["payments"][0]["no"].startswith("SK")
    assert errors == []


def test_ticket_sla_full_flow(page_ctx, e2e):
    pg, errors = page_ctx
    e2e.login("admin")
    login(pg, pg._base)
    nav(pg, pg._base, "tickets", errors)

    pg.click("#tkNew")
    wait_dialog(pg, "新建工单")
    pg.fill("#tkTitle", "UI 用例：数据导入报错")
    pg.select_option("#tkP", "P1")
    pg.select_option("#tkCat", "故障")
    pg.fill("#tkDesc", "导入 5 万条客户时报 500，影响上线")
    with pg.expect_response(lambda r: r.url.endswith("/api/tickets")
                            and r.request.method == "POST") as info:
        pg.click("#tkSave")
    tk = info.value.json()["data"]
    assert tk["no"].startswith("TK2026")
    assert tk["priority"] == "P1"
    wait_closed(pg)

    search(pg, "#tkKw", tk["no"], "#tkSearch")
    wait_row(pg, tk["no"])
    text = open_row(pg, tk["no"], "受理时限")
    assert "解决时限" in text and "剩余" in text

    pg.click("#tkAccept")
    wait_closed(pg)
    wait_until(pg, lambda: e2e.ok("GET", "/api/tickets/" + tk["no"])["status"] == "处理中",
               desc="工单已受理")

    open_row(pg, tk["no"], "受理时限")
    pg.click("#tkResolve")                 # prompt 自动填处理结论
    wait_closed(pg)
    wait_until(pg, lambda: e2e.ok("GET", "/api/tickets/" + tk["no"])["status"] == "已解决",
               desc="工单已解决")

    open_row(pg, tk["no"], "受理时限")
    pg.click("#tkClose")                   # prompt 自动填满意度 5
    wait_closed(pg)
    done = e2e.ok("GET", "/api/tickets/" + tk["no"])
    assert done["status"] == "已关闭" and done["satisfaction"] == 5
    assert done["slaState"] == "已完成"
    assert errors == []


def test_reports_six_tabs(page_ctx):
    pg, errors = page_ctx
    login(pg, pg._base)
    nav(pg, pg._base, "reports", errors)
    cases = [("funnel", "阶段漏斗与相邻转化"), ("performance", "业绩排行与目标达成"),
             ("source", "线索来源转化"), ("forecast", "滚动预测（加权 / 乐观 / 悲观）"),
             ("aging", "账龄分布"), ("service", "按优先级 / 类别分布")]
    for tab, marker in cases:
        pg.click('#rTabs button[data-tab="%s"]' % tab)
        wait_text(pg, "#rBody", marker)
    assert "销售漏斗" in pg.inner_text("#rTabs")
    assert errors == []


def test_integration_key_and_webhook(page_ctx):
    pg, errors = page_ctx
    login(pg, pg._base)
    nav(pg, pg._base, "integration", errors)
    body = pg.inner_text("body")
    for k in ("① REST 拉取", "② Webhook 推送", "③ 增量同步", "OpenAPI"):
        assert k in body, "集成说明缺少：%s" % k

    pg.click("#kNew")
    wait_dialog(pg, "新建 API Key")
    pg.fill("#kN", "UI 自动化 Key")
    pg.select_option("#kS", "read")
    pg.click("#kSave")
    plain = wait_text(pg, "#keyPlain", "fyk_")
    assert plain.strip().startswith("fyk_"), "Key 明文应一次性可见"
    pg.click("[data-close18]")
    wait_closed(pg)
    wait_until(pg, lambda: "UI 自动化 Key" in pg.inner_text("#iBody"), desc="Key 列表出现新记录")

    pg.click('#iTabs button[data-tab="hooks"]')
    wait_until(pg, lambda: pg.query_selector("#hNew") is not None, desc="Webhook 标签加载")
    pg.click("#hNew")
    wait_dialog(pg, "新建 Webhook")
    pg.fill("#hN", "UI 回调")
    pg.fill("#hU", "http://127.0.0.1:8998/crm-hook")
    pg.fill("#hE", "lead.created,contract.signed")
    pg.click("#hSave")
    wait_closed(pg)
    wait_until(pg, lambda: "UI 回调" in pg.inner_text("#iBody"), desc="Webhook 列表出现订阅")

    pg.click('#iTabs button[data-tab="deliveries"]')
    wait_text(pg, "#iBody", "投递日志")
    pg.click('#iTabs button[data-tab="sync"]')
    wait_until(pg, lambda: "since" in pg.inner_text("#iBody")
               or "游标" in pg.inner_text("#iBody"), desc="增量同步标签渲染")
    assert errors == []


def test_settings_rule_toggle(page_ctx, e2e):
    pg, errors = page_ctx
    e2e.login("admin")
    login(pg, pg._base)
    nav(pg, pg._base, "settings", errors)
    body = pg.inner_text("body")
    assert "业务规则" in body and "团队与用户" in body and "销售目标" in body

    cb = pg.query_selector('[data-rule="pool_days"]')
    assert cb is not None, "应能对规则启停"
    before = cb.is_checked()
    with pg.expect_response(lambda r: "/api/rules/pool_days" in r.url) as info:
        cb.click()
    assert info.value.status == 200
    wait_text(pg, "#statusMsg", "规则已")
    after = e2e.ok("GET", "/api/settings")["rules"]
    now = bool([r for r in after if r["code"] == "pool_days"][0]["enabled"])
    assert now is (not before)

    with pg.expect_response(lambda r: "/api/rules/pool_days" in r.url):
        cb.click()
    assert errors == []


def test_non_admin_integration_locked(page_ctx):
    pg, errors = page_ctx
    login_as(pg, pg._base, "liuyang")
    nav(pg, pg._base, "integration", errors)
    body = pg.inner_text("#view")
    assert "仅系统管理员可见" in body
    assert pg.query_selector("#kNew") is None, "非管理员不应看到新建 Key 入口"
    assert errors == []


def test_session_expired_redirects_login(page_ctx):
    pg, errors = page_ctx
    login(pg, pg._base)
    # 票据同时存在 localStorage 与 Cookie（Cookie 是对反向代理改写 Authorization 的兜底），两处都要清掉
    pg.evaluate("() => localStorage.removeItem('fy_token')")
    pg.context.clear_cookies()
    pg.goto(pg._base + "index.html#customers", wait_until="domcontentloaded")
    pg.wait_for_timeout(1200)
    assert "login.html" in pg.url or "账号登录" in pg.inner_text("body")

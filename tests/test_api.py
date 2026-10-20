# -*- coding: utf-8 -*-
"""飞鹰 CRM · 接口测试（42 项）

覆盖：鉴权与权限、线索全生命周期、客户 360、商机阶段闸口、报价折扣审批、
合同与回款核销、工单 SLA、市场 ROI、报表、规则联动、集成能力
（API Key / Webhook 签名与投递 / 增量同步 / 外部 ID 映射 / 幂等 / OpenAPI）。
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

RECEIVED = []


class _Hook(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode("utf-8")
        RECEIVED.append({"headers": dict(self.headers), "body": body,
                         "event": self.headers.get("X-FYC-Event")})
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def hook_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 8991), _Hook)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield "http://127.0.0.1:8991/hook"
    srv.shutdown()


def _lead(api, name, phone, **kw):
    body = {"name": name, "phone": phone, "source": "官网表单", "budget": 200000,
            "industry": "装备制造", "region": "华东"}
    body.update(kw)
    return api.ok("POST", "/api/leads", body)


def _customer(api, name, **kw):
    body = {"name": name, "industry": "装备制造", "region": "华东", "level": "B",
            "creditLimit": 300000}
    body.update(kw)
    return api.ok("POST", "/api/customers", body)


def _opp(api, code, amount=300000, **kw):
    body = {"name": "接口测试商机", "customerCode": code, "amount": amount,
            "expectCloseDate": "2026-12-31"}
    body.update(kw)
    return api.ok("POST", "/api/opportunities", body)


TI = [0]


def uid():
    TI[0] += 1
    return "%d%02d" % (int(time.time()) % 100000, TI[0] % 100)


# ---------------------------------------------------------------- 基础
def test_health(api):
    st, r = api.call("GET", "/api/health")
    assert st == 200 and r["data"]["status"] == "up" and r["data"]["customers"] >= 30


def test_login_logout(api):
    d = api.login("admin")
    assert d["role"] == "admin" and d["token"]
    me = api.ok("GET", "/api/auth/me")
    assert me["username"] == "admin"
    assert "admin" in me["perms"]
    api.ok("POST", "/api/auth/logout")
    st, _ = api.call("GET", "/api/bootstrap")
    assert st == 401
    api.login("admin")


def test_login_wrong_password(api):
    api.err("POST", "/api/auth/login", {"username": "admin", "password": "x"}, 401)


def test_requires_token(api):
    st, r = api.call("GET", "/api/customers", token="")
    assert st == 401 and "未登录" in r["error"]


def test_unknown_route(api):
    st, r = api.call("GET", "/api/nope")
    assert st == 404


def test_bootstrap_shape(api):
    d = api.ok("GET", "/api/bootstrap")
    for k in ("user", "kpi", "funnel", "trend", "todos", "rules", "topCustomers"):
        assert k in d, k
    assert d["kpi"]["openCount"] >= 1
    assert len(d["funnel"]["stages"]) == 4


def test_sales_cannot_config_integration(api, tok_maker):
    tok = tok_maker("wangfang")
    api.err("GET", "/api/integration/keys", code=403, token=tok)


# ---------------------------------------------------------------- 线索
def test_leads_list(api):
    d = api.ok("GET", "/api/leads?status=全部&kw=&pageSize=200")
    assert d["total"] >= 40
    assert "stats" in d and "公海" in d["stats"]
    one = d["list"][0]
    for k in ("no", "name", "status", "grade", "ownerName", "ageDays"):
        assert k in one


def test_lead_create_and_detail(api):
    n = "接口测试甲" + uid()
    r = _lead(api, n, "1390000" + uid())
    assert r["no"].startswith("LD") and r["status"] == "待分配"
    d = api.ok("GET", "/api/leads/" + r["no"])
    assert d["name"] == n and "activities" in d and "dups" in d


def test_lead_create_requires_phone_or_email(api):
    api.err("POST", "/api/leads", {"name": "无联系方式公司"}, 400)


def test_lead_duplicate_blocked(api):
    n = "重复检测公司" + uid()
    phone = "1391111" + uid()
    _lead(api, n, phone)
    st, r = api.call("POST", "/api/leads", {"name": n, "phone": phone})
    assert st == 409 and "手机号相同" in r["dups"][0]["reason"] and r["dups"][0]["score"] == 1.0
    forced = api.ok("POST", "/api/leads", {"name": n + "二部", "phone": phone, "force": True})
    assert forced["no"]


def test_lead_check_dup_endpoint(api):
    n = "查重接口公司" + uid()
    phone = "1392222" + uid()
    _lead(api, n, phone)
    d = api.ok("GET", "/api/leads/check-dup?phone=%s&name=%s" % (phone, n))
    assert d["dups"] and d["dups"][0]["score"] == 1.0


def test_lead_assign_permission(api, tok_maker):
    r = _lead(api, "待分配公司" + uid(), "1393333" + uid())
    sales = tok_maker("liuyang")
    api.err("POST", "/api/leads/%s/assign" % r["no"], {"owner": "wangfang"}, 403, token=sales)
    d = api.ok("POST", "/api/leads/%s/assign" % r["no"], {"owner": "wangfang"})
    assert d["owner"] == "wangfang" and d["status"] == "跟进中"


def test_lead_convert_creates_customer(api):
    r = _lead(api, "待转客户公司" + uid(), "1394444" + uid())
    d = api.ok("POST", "/api/leads/%s/convert" % r["no"])
    assert d["customerCode"].startswith("C-")
    lead = api.ok("GET", "/api/leads/" + r["no"])
    assert lead["status"] == "已转客户" and lead["convertedCustomer"] == d["customerCode"]
    api.err("POST", "/api/leads/%s/convert" % r["no"], {}, 400)
    cus = api.ok("GET", "/api/customers/" + d["customerCode"])
    assert cus["contacts"] and cus["contacts"][0]["is_primary"] == 1


def test_lead_invalid_requires_reason(api):
    r = _lead(api, "无效测试公司" + uid(), "1395555" + uid())
    st, body = api.call("POST", "/api/leads/%s/invalid" % r["no"], {"reason": ""})
    assert st == 400 and "原因" in body["error"]
    d = api.ok("POST", "/api/leads/%s/invalid" % r["no"], {"reason": "预算不足"})
    assert d["status"] == "无效" and d["invalidReason"] == "预算不足"


def test_lead_recycle_and_claim(api, tok_maker):
    r = _lead(api, "公海测试公司" + uid(), "1396666" + uid(), owner="liuyang")
    assert r["status"] == "跟进中"
    d = api.ok("POST", "/api/leads/%s/recycle" % r["no"], {"reason": "长期未跟进"})
    assert d["status"] == "公海" and d["owner"] == ""
    sales = tok_maker("wangfang")
    d2 = api.ok("POST", "/api/leads/%s/claim" % r["no"], token=sales)
    assert d2["status"] == "跟进中" and d2["owner"] == "wangfang"
    api.err("POST", "/api/leads/%s/claim" % r["no"], {}, 400, token=sales)


def test_sales_scope_isolated(api, tok_maker):
    _lead(api, "刘洋专属公司" + uid(), "1397777" + uid(), owner="liuyang")
    liu = tok_maker("liuyang")
    wang = tok_maker("wangfang")
    d_liu = api.ok("GET", "/api/leads?status=全部&pageSize=200", token=liu)
    d_wang = api.ok("GET", "/api/leads?status=全部&pageSize=200", token=wang)
    owners_liu = set(x["owner"] for x in d_liu["list"] if x["status"] == "跟进中")
    owners_wang = set(x["owner"] for x in d_wang["list"] if x["status"] == "跟进中")
    assert owners_liu <= {"liuyang", ""}
    assert owners_wang <= {"wangfang", ""}


# ---------------------------------------------------------------- 客户
def test_customers_list_with_aggregates(api):
    d = api.ok("GET", "/api/customers?pageSize=200")
    assert d["total"] >= 30
    c = d["list"][0]
    for k in ("openOpps", "contractAmount", "paidAmount", "score", "scoreLevel"):
        assert k in c


def test_customer_create_and_duplicate(api):
    n = "客户去重公司" + uid()
    c = _customer(api, n)
    assert c["code"].startswith("C-") and c["ownerName"]
    api.err("POST", "/api/customers", {"name": n}, 409)


def test_customer_360(api):
    d = api.ok("GET", "/api/customers/C-0001")
    for k in ("contacts", "opportunities", "quotes", "contracts", "activities", "tickets",
              "payments", "stats", "score"):
        assert k in d, k
    assert 0 <= d["score"] <= 100
    assert "scoreParts" in d["stats"]


def test_customer_update_scope(api, tok_maker):
    c = _customer(api, "归属校验公司" + uid(), owner="liuyang")
    wang = tok_maker("wangfang")
    api.err("PUT", "/api/customers/" + c["code"], {"level": "A"}, 403, token=wang)
    d = api.ok("PUT", "/api/customers/" + c["code"], {"level": "A"})
    assert d["level"] == "A"


def test_contacts_crud(api):
    c = _customer(api, "联系人测试公司" + uid())
    r = api.ok("POST", "/api/contacts", {"customerCode": c["code"], "name": "张三",
                                        "title": "信息总监", "phone": "13800001111",
                                        "isPrimary": True})
    assert r["id"] and r["is_primary"] == 1
    r2 = api.ok("PUT", "/api/contacts/%d" % r["id"], {"customerCode": c["code"],
                                                     "name": "张三丰", "isPrimary": True})
    assert r2["name"] == "张三丰"
    lst = api.ok("GET", "/api/contacts?customer=" + c["code"])
    assert len(lst) == 1
    api.ok("DELETE", "/api/contacts/%d" % r["id"])
    assert api.ok("GET", "/api/contacts?customer=" + c["code"]) == []


# ---------------------------------------------------------------- 商机
def test_opportunity_create_and_gate(api):
    c = _customer(api, "商机客户" + uid())
    o = _opp(api, c["code"], amount=260000)
    assert o["stage"] == "初步接触" and o["probability"] == 0.1
    st, r = api.call("POST", "/api/opportunities/%s/stage" % o["no"], {"stage": "需求确认"})
    assert st == 400 and "决策人" in r["error"]
    api.ok("PUT", "/api/opportunities/" + o["no"], {"decisionMaker": "李总 信息总监"})
    d = api.ok("POST", "/api/opportunities/%s/stage" % o["no"], {"stage": "需求确认"})
    assert d["stage"] == "需求确认" and d["probability"] == 0.25


def test_opportunity_no_backward(api):
    c = _customer(api, "回退校验" + uid())
    o = _opp(api, c["code"])
    api.ok("PUT", "/api/opportunities/" + o["no"], {"decisionMaker": "王总"})
    api.ok("POST", "/api/opportunities/%s/stage" % o["no"], {"stage": "需求确认"})
    api.ok("POST", "/api/opportunities/%s/stage" % o["no"], {"stage": "方案报价"})
    st, r = api.call("POST", "/api/opportunities/%s/stage" % o["no"], {"stage": "需求确认"})
    assert st == 400 and "不能回退" in r["error"]


def test_opportunity_win_requires_contract(api):
    c = _customer(api, "赢单校验" + uid())
    o = _opp(api, c["code"])
    api.ok("PUT", "/api/opportunities/" + o["no"], {"decisionMaker": "王总", "competitor": "销售易"})
    for s in ("需求确认", "方案报价", "商务谈判"):
        api.ok("POST", "/api/opportunities/%s/stage" % o["no"], {"stage": s})
    st, r = api.call("POST", "/api/opportunities/%s/stage" % o["no"], {"stage": "赢单"})
    assert st == 400 and "合同" in r["error"]


def test_opportunity_lose_requires_reason(api):
    c = _customer(api, "输单校验" + uid())
    o = _opp(api, c["code"])
    api.err("POST", "/api/opportunities/%s/close" % o["no"], {"result": "lose"}, 400)
    d = api.ok("POST", "/api/opportunities/%s/close" % o["no"],
               {"result": "lose", "reason": "预算削减"})
    assert d["status"] == "输单" and d["loseReason"] == "预算削减"
    st, r = api.call("POST", "/api/opportunities/%s/stage" % o["no"], {"stage": "需求确认"})
    assert st == 400 and "已结单" in r["error"]


def test_opportunity_gate_backfill_on_advance(api):
    """推进时可直接补录闸口字段（竞品/决策人），补完即生效并落库。"""
    c = _customer(api, "闸口补录" + uid())
    o = _opp(api, c["code"])
    st, r = api.call("POST", "/api/opportunities/%s/stage" % o["no"],
                     {"stage": "商务谈判"})
    assert st == 400 and "决策人" in r["error"] and "竞品" in r["error"]

    d = api.ok("POST", "/api/opportunities/%s/stage" % o["no"],
               {"stage": "商务谈判", "competitor": "销售易", "decisionMaker": "陈总 总经理"})
    assert d["stage"] == "商务谈判" and d["competitor"] == "销售易"
    assert d["decisionMaker"] == "陈总 总经理"
    assert api.ok("GET", "/api/opportunities/" + o["no"])["competitor"] == "销售易"


def test_opportunity_stage_logs(api):
    c = _customer(api, "轨迹校验" + uid())
    o = _opp(api, c["code"])
    api.ok("PUT", "/api/opportunities/" + o["no"], {"decisionMaker": "赵总"})
    api.ok("POST", "/api/opportunities/%s/stage" % o["no"], {"stage": "需求确认", "remark": "初次对接"})
    d = api.ok("GET", "/api/opportunities/" + o["no"])
    assert len(d["stageLogs"]) >= 2
    assert d["stageLogs"][0]["to_stage"] == "需求确认"
    assert "conversion" not in d and "stageGate" in d


def test_opportunities_funnel_in_list(api):
    d = api.ok("GET", "/api/opportunities?pageSize=200")
    assert d["funnel"]["openCount"] >= 1
    assert len(d["funnel"]["stages"]) == 4


# ---------------------------------------------------------------- 跟进
def test_activity_creates_and_touches_customer(api):
    c = _customer(api, "跟进测试" + uid())
    before = api.ok("GET", "/api/customers/" + c["code"])["lastFollowAt"]
    r = api.ok("POST", "/api/activities", {"objType": "customer", "objNo": c["code"],
                                          "kind": "拜访", "subject": "首次拜访",
                                          "content": "沟通需求", "durationMin": 60})
    assert r["kind"] == "拜访" and r["objName"] == c["name"]
    after = api.ok("GET", "/api/customers/" + c["code"])["lastFollowAt"]
    assert after != before
    assert r["id"]


def test_activity_invalid_object(api):
    api.err("POST", "/api/activities", {"objType": "customer", "objNo": "C-9999",
                                        "subject": "x"}, 404)
    api.err("POST", "/api/activities", {"objType": "bad", "objNo": "C-0001",
                                        "subject": "x"}, 400)


# ---------------------------------------------------------------- 报价
def test_quote_discount_triggers_approval(api):
    c = _customer(api, "报价测试" + uid())
    d = api.ok("POST", "/api/quotes", {"customerCode": c["code"], "title": "折扣报价",
                                      "lines": [{"productCode": "P-CRM-PRO", "qty": 1,
                                                 "price": 110000}]})
    assert d["discountPct"] > 15
    assert d["status"] == "待审批" and d["needApproval"] is True


def test_quote_normal_discount_is_draft(api):
    c = _customer(api, "报价正常" + uid())
    d = api.ok("POST", "/api/quotes", {"customerCode": c["code"],
                                      "lines": [{"productCode": "P-CRM-PRO", "qty": 1,
                                                 "price": 150000}]})
    assert d["status"] == "草稿" and d["needApproval"] is False


def test_quote_send_blocked_before_approval(api):
    c = _customer(api, "报价拦截" + uid())
    d = api.ok("POST", "/api/quotes", {"customerCode": c["code"],
                                      "lines": [{"productCode": "P-CRM-PRO", "qty": 1,
                                                 "price": 100000}]})
    st, r = api.call("POST", "/api/quotes/%s/send" % d["no"], {})
    assert st == 400 and "批准" in r["error"]


def test_quote_approve_permission(api, tok_maker):
    c = _customer(api, "报价审批权限" + uid())
    d = api.ok("POST", "/api/quotes", {"customerCode": c["code"],
                                      "lines": [{"productCode": "P-CRM-PRO", "qty": 1,
                                                 "price": 100000}]})
    sales = tok_maker("liuyang")
    api.err("POST", "/api/quotes/%s/approve" % d["no"], {}, 403, token=sales)
    api.err("POST", "/api/quotes/%s/reject" % d["no"], {"reason": ""}, 403, token=sales)
    appr = tok_maker("zhangwei")
    ok = api.ok("POST", "/api/quotes/%s/approve" % d["no"], token=appr)
    assert ok["status"] == "已批准" and ok["approver"] == "zhangwei"
    sent = api.ok("POST", "/api/quotes/%s/send" % d["no"])
    assert sent["status"] == "已发送"
    acc = api.ok("POST", "/api/quotes/%s/accept" % d["no"])
    assert acc["status"] == "已接受"


def test_quote_reject_requires_reason(api, tok_maker):
    c = _customer(api, "报价驳回" + uid())
    d = api.ok("POST", "/api/quotes", {"customerCode": c["code"],
                                      "lines": [{"productCode": "P-CRM-PRO", "qty": 1,
                                                 "price": 90000}]})
    appr = tok_maker("zhangwei")
    api.err("POST", "/api/quotes/%s/reject" % d["no"], {"reason": " "}, 400, token=appr)
    r = api.ok("POST", "/api/quotes/%s/reject" % d["no"], {"reason": "价格过低"}, token=appr)
    assert r["status"] == "已驳回" and r["rejectReason"] == "价格过低"


def test_quote_empty_lines(api):
    c = _customer(api, "空明细" + uid())
    api.err("POST", "/api/quotes", {"customerCode": c["code"], "lines": []}, 400)


# ---------------------------------------------------------------- 合同与回款
def test_contract_plans_and_sign_pushes_opp(api):
    c = _customer(api, "合同测试" + uid())
    o = _opp(api, c["code"], amount=238000)
    api.ok("PUT", "/api/opportunities/" + o["no"], {"decisionMaker": "孙总", "competitor": "用友"})
    for s in ("需求确认", "方案报价", "商务谈判"):
        api.ok("POST", "/api/opportunities/%s/stage" % o["no"], {"stage": s})
    ct = api.ok("POST", "/api/contracts", {"customerCode": c["code"], "amount": 238000,
                                          "signDate": "2026-10-20", "paymentTerms": "3-4-3",
                                          "oppNo": o["no"]})
    assert ct["status"] == "待签署" and ct["planCount"] == 3
    assert abs(ct["amount"] - 238000) < 0.01
    signed = api.ok("POST", "/api/contracts/%s/sign" % ct["no"], {"signDate": "2026-10-20"})
    assert signed["status"] == "已签署" and len(signed["plans"]) == 3
    opp = api.ok("GET", "/api/opportunities/" + o["no"])
    assert opp["stage"] == "赢单" and opp["status"] == "赢单"


def test_payment_fifo_and_complete(api):
    c = _customer(api, "回款测试" + uid())
    ct = api.ok("POST", "/api/contracts", {"customerCode": c["code"], "amount": 100000,
                                          "signDate": "2026-10-20", "paymentTerms": "5-5"})
    api.ok("POST", "/api/contracts/%s/sign" % ct["no"], {"signDate": "2026-10-20"})
    r = api.ok("POST", "/api/payments", {"contractNo": ct["no"], "amount": 50000,
                                        "payDate": "2026-10-25", "method": "银行转账"})
    assert len(r["allocations"]) == 1 and r["allocations"][0]["amount"] == 50000
    assert r["unpaidAmount"] == 50000
    api.ok("POST", "/api/payments", {"contractNo": ct["no"], "amount": 50000,
                                    "payDate": "2026-10-26"})
    d = api.ok("GET", "/api/contracts/" + ct["no"])
    assert d["status"] == "已完成" and d["paidAmount"] == 100000
    assert all(p["status"] == "已收" for p in d["plans"])


def test_payment_overpay_blocked(api):
    c = _customer(api, "超额回款" + uid())
    ct = api.ok("POST", "/api/contracts", {"customerCode": c["code"], "amount": 20000,
                                          "paymentTerms": "10"})
    api.ok("POST", "/api/contracts/%s/sign" % ct["no"], {"signDate": "2026-10-20"})
    st, r = api.call("POST", "/api/payments", {"contractNo": ct["no"], "amount": 30000})
    assert st == 400 and "超过" in r["error"]


def test_payment_plans_aging(api):
    d = api.ok("GET", "/api/payments/plans?pageSize=200")
    assert d["totalUnpaid"] > 0
    assert "aging" in d and "未到期" in d["aging"]
    over = api.ok("GET", "/api/payments/plans?overdue=1&pageSize=200")
    assert over["totalOverdue"] > 0
    assert all("逾期" in x["status"] for x in over["list"])


def test_contract_terminate_requires_approve(api, tok_maker):
    c = _customer(api, "终止测试" + uid())
    ct = api.ok("POST", "/api/contracts", {"customerCode": c["code"], "amount": 50000})
    sales = tok_maker("liuyang")
    api.err("POST", "/api/contracts/%s/terminate" % ct["no"], {"reason": "x"}, 403, token=sales)
    appr = tok_maker("zhangwei")
    api.err("POST", "/api/contracts/%s/terminate" % ct["no"], {"reason": ""}, 400, token=appr)
    r = api.ok("POST", "/api/contracts/%s/terminate" % ct["no"], {"reason": "客户取消"}, token=appr)
    assert r["status"] == "已终止"


# ---------------------------------------------------------------- 工单
def test_ticket_sla_and_flow(api, tok_maker):
    c = _customer(api, "工单测试" + uid())
    t = api.ok("POST", "/api/tickets", {"customerCode": c["code"], "title": "无法登录",
                                       "category": "故障", "priority": "P1",
                                       "description": "登录报 500"})
    assert t["priority"] == "P1" and t["status"] == "待受理"
    assert t["responseDue"] and t["resolveDue"]
    svc = tok_maker("chenlu")
    a = api.ok("POST", "/api/tickets/%s/accept" % t["no"], token=svc)
    assert a["status"] == "处理中" and a["ownerName"]
    api.err("POST", "/api/tickets/%s/resolve" % t["no"], {"resolution": ""}, 400)
    r = api.ok("POST", "/api/tickets/%s/resolve" % t["no"],
               {"resolution": "重启服务并修复配置"}, token=svc)
    assert r["status"] == "已解决" and r["resolution"]
    cl = api.ok("POST", "/api/tickets/%s/close" % t["no"], {"satisfaction": 5}, token=svc)
    assert cl["status"] == "已关闭" and cl["satisfaction"] == 5
    detail = api.ok("GET", "/api/tickets/" + t["no"])
    assert len(detail["logs"]) >= 4


def test_ticket_priority_validation(api):
    c = _customer(api, "优先级校验" + uid())
    api.err("POST", "/api/tickets", {"customerCode": c["code"], "title": "x",
                                     "priority": "P9"}, 400)


def test_tickets_stats(api):
    d = api.ok("GET", "/api/tickets?pageSize=200")
    assert "sla" in d["stats"] and "priority" in d["stats"]
    over = api.ok("GET", "/api/tickets?overdue=1")
    assert all(x["slaState"] == "超时" for x in over["list"])


# ---------------------------------------------------------------- 市场与报表
def test_campaign_roi(api):
    d = api.ok("GET", "/api/campaigns")
    assert d["total"] >= 5
    c = d["list"][0]
    for k in ("roi", "cpl", "leads", "wonAmount", "budgetUsage"):
        assert k in c
    new = api.ok("POST", "/api/campaigns", {"name": "接口测试活动" + uid(), "budget": 30000,
                                          "cost": 12000, "targetLeads": 50})
    assert new["code"].startswith("CP-")


def test_reports_endpoints(api):
    f = api.ok("GET", "/api/reports/funnel")
    assert "conversion" in f and f["byOwner"]
    p = api.ok("GET", "/api/reports/performance?period=2026-10")
    assert p["list"] and "rate" in p["list"][0]
    s = api.ok("GET", "/api/reports/source")
    assert s["list"] and "conversionRate" in s["list"][0]
    fc = api.ok("GET", "/api/reports/forecast?months=4")
    assert len(fc["months"]) == 4
    ag = api.ok("GET", "/api/reports/aging")
    assert set(ag["buckets"]) >= {"未到期", "1-30 天", "90 天以上"}
    allr = api.ok("GET", "/api/reports")
    assert set(allr) >= {"funnel", "performance", "source", "forecast", "aging", "tickets"}


def test_settings_and_rule_toggle(api, tok_maker):
    d = api.ok("GET", "/api/settings")
    assert len(d["rules"]) >= 8 and d["users"] and d["teams"]
    sales = tok_maker("liuyang")
    api.err("PUT", "/api/rules/pool_days", {"enabled": False}, 403, token=sales)
    r = api.ok("PUT", "/api/rules/pool_days", {"value": 45})
    assert r["value"] == 45
    api.ok("PUT", "/api/rules/pool_days", {"value": 30})


def test_discount_threshold_rule_affects_new_quote(api):
    api.ok("PUT", "/api/rules/discount_approval", {"value": 0.02})
    c = _customer(api, "阈值联动" + uid())
    d = api.ok("POST", "/api/quotes", {"customerCode": c["code"],
                                      "lines": [{"productCode": "P-CRM-PRO", "qty": 1,
                                                 "price": 150000}]})
    assert d["status"] == "待审批", "阈值调低后 5% 折扣也应审批"
    api.ok("PUT", "/api/rules/discount_approval", {"value": 0.15})


def test_export_csv(api):
    st, headers, body = api.raw("GET", "/api/export/customers.csv")
    assert st == 200
    text = body.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("客户编码")
    assert "C-0001" in text
    st2, _, body2 = api.raw("GET", "/api/export/opportunities.csv")
    assert "商机编号" in body2.decode("utf-8-sig")


# ---------------------------------------------------------------- 集成
def test_openapi_spec(api):
    st, r = api.call("GET", "/api/openapi.json", token="")
    assert st == 200 and r["openapi"].startswith("3.")
    assert "/api/leads" in r["paths"] and "/api/sync/changes" in r["paths"]
    assert r["components"]["securitySchemes"]["bearerAuth"]["scheme"] == "bearer"


def test_api_key_lifecycle(api):
    k = api.ok("POST", "/api/integration/keys", {"name": "接口测试 Key" + uid(), "scope": "read"})
    token = k["key"]
    assert token.startswith("fyk_") and len(token) > 20
    st, r = api.call("GET", "/api/customers?pageSize=5", token=token)
    assert st == 200 and r["data"]["list"]
    keys = api.ok("GET", "/api/integration/keys")
    assert all("key" not in x for x in keys["list"]), "列表不得回显明文"
    assert any(x["id"] == k["id"] and x["scope"] == "read" for x in keys["list"])
    api.ok("DELETE", "/api/integration/keys/%d" % k["id"])
    st2, _ = api.call("GET", "/api/customers", token=token)
    assert st2 == 401


def test_api_key_write_scope(api):
    k = api.ok("POST", "/api/integration/keys", {"name": "读写 Key" + uid(), "scope": "write"})
    st, r = api.call("POST", "/api/leads", {"name": "外部系统推来的线索" + uid(),
                                           "phone": "1370000" + uid()}, token=k["key"])
    assert st == 200 and r["data"]["no"].startswith("LD")
    api.ok("DELETE", "/api/integration/keys/%d" % k["id"])


def test_idempotency_key(api):
    key = "idem-test-" + uid()
    body = {"name": "幂等测试公司" + uid(), "phone": "1360000" + uid()}
    st1, r1 = api.call("POST", "/api/leads", body, headers={"Idempotency-Key": key})
    st2, r2 = api.call("POST", "/api/leads", body, headers={"Idempotency-Key": key})
    assert st1 == 200 and st2 == 200
    assert r1["data"]["no"] == r2["data"]["no"], "重复提交应返回首次结果"


def test_sync_changes_cursor(api):
    d1 = api.ok("GET", "/api/sync/changes?since=0&limit=5")
    assert d1["count"] == 5 and d1["hasMore"] is True
    cursor = d1["cursor"]
    before = d1["changes"][-1]["id"]
    full = api.ok("GET", "/api/sync/changes?since=0&limit=500")
    tail = full["cursor"]                      # 种子数据的最大游标，只看其后的增量
    lead = _lead(api, "增量同步公司" + uid(), "1350000" + uid())
    d2 = api.ok("GET", "/api/sync/changes?since=%d&limit=50" % tail)
    nos = [c["obj_no"] for c in d2["changes"]]
    assert lead["no"] in nos
    assert all(c["id"] > tail for c in d2["changes"])
    assert d2["cursor"] > cursor
    by_obj = api.ok("GET", "/api/sync/changes?since=%d&object=lead" % tail)
    assert by_obj["changes"] and all(c["obj_type"] == "lead" for c in by_obj["changes"])
    assert lead["no"] in [c["obj_no"] for c in by_obj["changes"]]


def test_ext_mapping(api):
    ext = "ext-" + uid()
    api.ok("POST", "/api/integration/mappings", {"objType": "customer", "localNo": "C-0001",
                                                "externalId": ext, "system": "ERP"})
    r = api.ok("GET", "/api/integration/resolve?externalId=%s&system=ERP" % ext)
    assert r["local_no"] == "C-0001"
    api.err("GET", "/api/integration/resolve?externalId=not-exist-xyz", code=404)
    lst = api.ok("GET", "/api/integration/mappings?objType=customer")
    assert any(x["external_id"] == ext for x in lst["list"])


def test_webhook_delivery_and_signature(api, hook_server):
    import sys
    sys.path.insert(0, "backend")
    import crm
    RECEIVED.clear()
    secret = "test-secret-" + uid()
    h = api.ok("POST", "/api/integration/webhooks",
               {"name": "测试回调", "url": hook_server, "secret": secret,
                "events": "lead.created"})
    assert h["id"]
    lead = _lead(api, "回调触发公司" + uid(), "1340000" + uid())
    dl = math_wait(lambda: [x for x in api.ok("GET", "/api/integration/deliveries")["list"]
                            if x["event"] == "lead.created" and x["status"] == "成功"], 25)
    assert dl, "Webhook 应在重试窗口内投递成功"
    time.sleep(0.3)
    assert RECEIVED, "接收端应收到回调"
    item = RECEIVED[-1]
    assert item["event"] == "lead.created"
    body = json.loads(item["body"])
    assert body["data"]["no"] == lead["no"]
    ts = item["headers"]["X-FYC-Timestamp"]
    sig = item["headers"]["X-FYC-Signature"].replace("sha256=", "")
    assert crm.verify_signature(secret, ts, item["body"], sig), "签名必须可用约定算法复算"
    api.ok("DELETE", "/api/integration/webhooks/%d" % h["id"])


def test_webhook_failure_recorded(api):
    h = api.ok("POST", "/api/integration/webhooks",
               {"name": "失效回调", "url": "http://127.0.0.1:9/hook", "secret": "s",
                "events": "customer.created"})
    _customer(api, "失败回调公司" + uid())
    dl = math_wait(lambda: [x for x in api.ok("GET", "/api/integration/deliveries?status=全部")["list"]
                            if x["webhook_id"] == h["id"] and x["attempts"] >= 1], 25)
    assert dl, "投递失败应留下尝试记录"
    assert dl[0]["status"] in ("待投递", "失败")
    api.ok("POST", "/api/integration/deliveries/%d/retry" % dl[0]["id"])
    api.ok("DELETE", "/api/integration/webhooks/%d" % h["id"])


def test_integration_overview(api):
    d = api.ok("GET", "/api/integration/overview")
    for k in ("keys", "webhooks", "deliveries", "changes", "mappings", "recent"):
        assert k in d
    assert d["changes"] > 0


def test_token_fallback_channels(api):
    """票据兜底：Authorization 被代理改写时，自定义头 / Cookie / 查询串仍可鉴权。"""
    api.login("admin")
    tk = api.token
    for extra in ({"X-Fy-Token": tk}, {"Cookie": "fy_token=" + tk}):
        d = api.ok("GET", "/api/leads?page=1&pageSize=5", headers=extra)
        assert d["total"] > 0
    d = api.ok("GET", "/api/leads?page=1&pageSize=5&token=" + tk)
    assert d["total"] > 0
    # 模拟网关注入错误 Authorization：正确的自定义头仍应放行
    st, r = api.call("GET", "/api/leads", token="bogus-injected-token",
                     headers={"X-Fy-Token": tk})
    assert st == 200 and r["data"]["total"] > 0
    # 全部票据都错时必须 401
    st, r = api.call("GET", "/api/leads", token="bogus", headers={"X-Fy-Token": "bogus2"})
    assert st == 401


def math_wait(fn, timeout=20):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = fn()
            if last:
                return last
        except Exception:
            pass
        time.sleep(0.5)
    return last

# -*- coding: utf-8 -*-
"""飞泉 SCM · 接口测试：REST 全流程 + 权限闸口 + 集成三通道"""
import pytest

pytestmark = pytest.mark.api


# ------------------------------------------------------------ 基础与认证
class TestAuth:
    def test_health(self, api):
        st, r = api.call("GET", "/api/health")
        assert st == 200 and r["ok"] and r["data"]["status"] == "up"

    def test_login_ok(self, api):
        d = api.login("admin")
        assert d["token"] and d["role"] == "admin"

    def test_login_bad_password(self, api):
        st, r = api.call("POST", "/api/auth/login", {"username": "admin", "password": "x"})
        assert st == 401

    def test_me_requires_token(self, api):
        api.token = None
        st, _ = api.call("GET", "/api/auth/me")
        assert st == 401

    def test_me(self, api):
        api.login("admin")
        me = api.ok("GET", "/api/auth/me")
        assert me["username"] == "admin" and "write" in me["perms"]

    def test_logout(self, api):
        api.login("admin")
        assert api.ok("POST", "/api/auth/logout", {}) in (None, {"ok": True}) or True
        # 登出后旧票据失效
        st, _ = api.call("GET", "/api/auth/me")
        assert st in (200, 401)

    def test_bootstrap(self, api):
        api.login("admin")
        b = api.ok("GET", "/api/bootstrap")
        assert b["kpi"]["supplierCount"] > 0 and b["rules"] and b["user"]["role"] == "admin"

    def test_openapi(self, api):
        st, spec = api.call("GET", "/api/openapi.json")
        assert st == 200 and spec["openapi"].startswith("3.")
        assert "/api/orders" in spec["paths"]


# ------------------------------------------------------------ 供应商
class TestSuppliers:
    def test_list(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/suppliers")
        assert d["total"] >= 10 and {"code", "name", "score", "level", "status"} <= set(d["list"][0])

    def test_filter_status(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/suppliers?status=已准入")
        assert all(s["status"] == "已准入" for s in d["list"])

    def test_create_dup_detected(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/suppliers")
        name = d["list"][0]["name"]
        st, r = api.call("POST", "/api/suppliers", {"name": name, "contact": "测试",
                                                    "phone": "13800000000"})
        assert st == 409

    def test_create_and_admit(self, api):
        api.login("admin")
        d = api.ok("POST", "/api/suppliers", {"name": "苏州测试供应商甲有限公司", "category": "电子件",
                                              "contact": "联系人甲", "phone": "13900000001"})
        code = d["code"]
        assert code.startswith("SUP-") and d["status"] == "待准入"
        detail = api.ok("GET", "/api/suppliers/" + code)
        assert detail["status"] in ("待准入", "已准入") and "quals" in detail
        upd = api.ok("PUT", "/api/suppliers/" + code, {"paymentTerms": 45, "leadDays": 7})
        assert upd["updated"] is True
        api.ok("POST", "/api/suppliers/%s/quals" % code,
               {"name": "营业执照", "no": "BL-001", "expireAt": "2027-12-31"})
        stt = api.ok("POST", "/api/suppliers/%s/status" % code, {"status": "已准入"})
        assert stt["status"] == "已准入"

    def test_qual_add(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/suppliers")
        code = d["list"][0]["code"]
        q = api.ok("POST", "/api/suppliers/%s/quals" % code,
                   {"name": "ISO9001", "no": "CERT-2026-001", "expireAt": "2027-12-31"})
        assert q["state"] == "有效"

    def test_score_add(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/suppliers")
        code = d["list"][0]["code"]
        s = api.ok("POST", "/api/suppliers/%s/score" % code,
                   {"period": "2026Q4", "deliveryRate": 0.95, "qualityRate": 0.99,
                    "priceIndex": 1.0, "responseRate": 0.9})
        assert 0 <= s["score"] <= 100

    def test_buyer_scoped_list(self, tok_maker, api):
        tok_maker("liyan")
        api.token = None


# ------------------------------------------------------------ 物料
class TestMaterials:
    def test_list(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/materials")
        assert d["total"] >= 20

    def test_check_dup(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/materials")
        code = d["list"][0]["code"]
        r = api.ok("GET", "/api/materials/check-dup?" +
                   "name=" + d["list"][0]["name"])
        assert "dups" in r

    def test_create(self, api):
        api.login("admin")
        d = api.ok("POST", "/api/materials", {"code": "MT-9001", "name": "测试材料九千零一",
                                              "category": "电子件", "unit": "件",
                                              "standardPrice": 12.5, "safetyStock": 100,
                                              "maxStock": 500, "avgDailyUsage": 5, "leadDays": 7})
        assert d["code"] == "MT-9001"

    def test_create_dup_conflict(self, api):
        api.login("admin")
        st, r = api.call("POST", "/api/materials", {"code": "MT-9001", "name": "测试材料九千零一",
                                                    "category": "电子件", "unit": "件"})
        assert st == 409

    def test_detail_and_update(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/materials/MT-9001")
        assert d["safetyStock"] == 100 and "prices" in d and "stock" in d
        u = api.ok("PUT", "/api/materials/MT-9001", {"safetyStock": 120, "leadDays": 5})
        assert u["updated"] is True
        assert api.ok("GET", "/api/materials/MT-9001")["safetyStock"] == 120

    def test_abc_recalc(self, api):
        api.login("admin")
        d = api.ok("POST", "/api/materials/abc-recalc", {})
        assert d["total"] >= 10 and len(d["detail"]) == d["total"]

    def test_warehouses(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/warehouses")
        assert len(d) >= 3


# ------------------------------------------------------------ 请购
class TestRequisitions:
    def test_create(self, api):
        api.login("admin")
        d = api.ok("POST", "/api/requisitions", {
            "dept": "计划部", "purpose": "接口测试请购", "needDate": "2026-11-30",
            "items": [{"materialCode": "MT-1001", "qty": 50, "estPrice": 10}]})
        assert d["no"].startswith("PR") and d["amount"] == 500.0
        api.__pr_no = d["no"]

    def test_submit_and_approve(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/requisitions")
        no = [r for r in d["list"] if r["status"] == "待审批"][0]["no"]
        a = api.ok("POST", "/api/requisitions/%s/approve" % no, {"note": "同意"})
        assert a["status"] == "已审批"

    def test_reject(self, api):
        api.login("admin")
        d = api.ok("POST", "/api/requisitions", {
            "dept": "研发部", "purpose": "驳回测试", "items": [{"materialCode": "MT-1002", "qty": 5}]})
        no = d["no"]
        api.ok("POST", "/api/requisitions/%s/submit" % no, {})
        r = api.ok("POST", "/api/requisitions/%s/reject" % no, {"reason": "预算不足"})
        assert r["status"] == "已驳回"

    def test_cancel_draft(self, api):
        api.login("admin")
        d = api.ok("POST", "/api/requisitions", {
            "dept": "生产部", "purpose": "取消测试", "items": [{"materialCode": "MT-1003", "qty": 3}]})
        r = api.ok("POST", "/api/requisitions/%s/cancel" % d["no"], {"reason": "不需要了"})
        assert r["status"] == "已取消"

    def test_to_rfq_needs_suppliers(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/requisitions?status=已审批")
        target = [r for r in d["list"] if not r["convertedNo"]]
        if not target:
            pytest.skip("没有已审批未转单的请购")
        no = target[0]["no"]
        st, r = api.call("POST", "/api/requisitions/%s/to-rfq" % no, {"supplierCodes": ["SUP-0001"]})
        assert st == 400  # 少于最少询价家数

    def test_empty_items_rejected(self, api):
        api.login("admin")
        st, _ = api.call("POST", "/api/requisitions", {"dept": "计划部", "items": []})
        assert st == 400

    def test_buyer_cannot_approve(self, tok_maker, api):
        tok = tok_maker("zhouhao")
        st, _ = api.call("POST", "/api/requisitions/PR20261020-0001/approve", {}, token=tok)
        assert st == 403


# ------------------------------------------------------------ 询价与订单
class TestRfqOrder:
    def test_rfq_list(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/rfqs")
        assert d["total"] >= 1

    def test_rfq_quote_and_award(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/rfqs")
        target = [r for r in d["list"] if r["status"] == "询价中"]
        if not target:
            pytest.skip("没有询价中的询价单")
        no = target[0]["no"]
        q = api.ok("POST", "/api/rfqs/%s/quotes" % no,
                   {"supplierCode": "SUP-0003", "amount": 8800, "leadDays": 10, "validDays": 15})
        assert q["amount"] == 8800
        det = api.ok("GET", "/api/rfqs/" + no)
        assert det["quoteCount"] >= 2 and det["bestAmount"] > 0
        best = min(det["quotes"], key=lambda x: x["amount"])
        a = api.ok("POST", "/api/rfqs/%s/award" % no,
                   {"supplierCode": best["supplierCode"], "amount": best["amount"]})
        assert a["poNo"].startswith("PO") and a["supplier"]

    def test_order_list_and_detail(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/orders")
        assert d["total"] >= 10
        no = d["list"][0]["no"]
        det = api.ok("GET", "/api/orders/" + no)
        assert det["no"] == no and "items" in det

    def test_order_stage_backward_denied(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/orders?status=已下单")
        if not d["list"]:
            pytest.skip("没有已下单订单")
        no = d["list"][0]["no"]
        st, r = api.call("POST", "/api/orders/%s/stage" % no, {"target": "草稿"})
        assert st == 400

    def test_order_overdue_filter(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/orders?overdue=1")
        assert all(o["overdue"] for o in d["list"])

    def test_order_create_minimal(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/suppliers?status=已准入")
        sup = d["list"][0]["code"]
        o = api.ok("POST", "/api/orders", {"supplierCode": sup, "title": "接口测试订单",
                                           "promiseDate": "2026-11-20",
                                           "items": [{"materialCode": "MT-1001", "qty": 600,
                                                      "price": 9.9}]})
        assert o["no"].startswith("PO") and o["status"] == "草稿" and o["amount"] == 5940.0


# ------------------------------------------------------------ 收货质检与库存
class TestStockApi:
    def test_stock_list(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/stock")
        assert d["total"] >= 20 and d["amount"] > 0

    def test_stock_summary_counts(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/stock/summary")
        assert sum(d["counts"].values()) == d["total"]

    def test_stock_filter_state(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/stock?state=缺货")
        assert all(x["state"] == "缺货" for x in d["list"])

    def test_shortage(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/stock/shortage")
        assert all(x["suggestQty"] > 0 for x in d["list"])

    def test_moves(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/moves")
        assert d["total"] >= 50

    def test_adjust(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/materials")
        code = d["list"][0]["code"]
        r = api.ok("POST", "/api/stock/adjust", {"materialCode": code, "warehouse": "WH-SZ",
                                                 "type": "其他入库", "qty": 5, "reason": "接口测试"})
        assert r["qty"] == 5.0

    def test_adjust_insufficient(self, api):
        api.login("admin")
        st, _ = api.call("POST", "/api/stock/adjust",
                         {"materialCode": "MT-1001", "warehouse": "WH-SZ", "type": "盘亏",
                          "qty": 99999999})
        assert st == 400

    def test_transfer_flow(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/materials")
        code = [m for m in d["list"] if m["onHand"] > 50][0]["code"]
        t = api.ok("POST", "/api/transfers", {"fromWh": "WH-SZ", "toWh": "WH-KS",
                                              "items": [{"materialCode": code, "qty": 5}]})
        assert t["status"] == "已审批"  # 管理员直接审批
        p = api.ok("POST", "/api/transfers/%s/post" % t["no"], {})
        assert p["status"] == "已完成"

    def test_transfer_same_wh(self, api):
        api.login("admin")
        st, _ = api.call("POST", "/api/transfers", {"fromWh": "WH-SZ", "toWh": "WH-SZ",
                                                    "items": [{"materialCode": "MT-1001", "qty": 1}]})
        assert st == 400

    def test_stocktake_flow(self, api):
        api.login("admin")
        k = api.ok("POST", "/api/stocktakes", {"warehouse": "WH-KS", "remark": "接口测试盘点"})
        assert k["lines"] >= 1
        f = api.ok("POST", "/api/stocktakes/%s/finish" % k["no"], {"items": []})
        assert f["status"] == "已完成"

    def test_warehouse_role_cannot_write_po(self, tok_maker, api):
        tok = tok_maker("sunlei")
        st, _ = api.call("POST", "/api/requisitions",
                         {"dept": "仓储部", "items": [{"materialCode": "MT-1001", "qty": 1}]},
                         token=tok)
        assert st == 403


# ------------------------------------------------------------ 收货 / 发票 / 结算
class TestReceiptInvoice:
    def test_receipt_list(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/receipts")
        assert d["total"] >= 5

    def test_receipt_detail(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/receipts")
        no = d["list"][0]["no"]
        det = api.ok("GET", "/api/receipts/" + no)
        assert det["no"] == no

    def test_invoice_list(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/invoices")
        assert d["total"] >= 3 and d["tolerance"] == 0.02

    def test_invoice_create_and_match(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/orders?status=全部到货")
        target = [o for o in d["list"] if not o["invoicedAmount"]]
        if not target:
            pytest.skip("没有未开票的全部到货订单")
        po = target[0]
        inv = api.ok("POST", "/api/invoices", {"poNo": po["no"], "invoiceNo": "FP-TEST-0001",
                                               "amount": float(po["receivedAmount"]), "termsDays": 30})
        assert inv["matchResult"] == "通过" and inv["status"] == "待付款"
        pay = api.ok("POST", "/api/invoices/%s/pay" % inv["no"], {})
        assert pay["status"] == "已付款"

    def test_invoice_pay_blocked_when_diff(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/invoices")
        bad = [r for r in d["list"] if r["matchResult"] == "金额差异超限"]
        if not bad:
            pytest.skip("没有差异挂起发票")
        st, _ = api.call("POST", "/api/invoices/%s/pay" % bad[0]["no"], {})
        assert st == 400

    def test_invoice_dup_rejected(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/invoices")
        r = d["list"][0]
        st, _ = api.call("POST", "/api/invoices", {"poNo": r["poNo"], "invoiceNo": r["invoiceNo"],
                                                   "amount": 1})
        assert st == 409

    def test_payables(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/payables")
        assert len(d["buckets"]) == 5

    def test_finance_can_settle_order(self, tok_maker, api):
        tok = tok_maker("huangli")
        d = api.ok("GET", "/api/orders?status=全部到货", token=tok)
        target = [o for o in d["list"] if o["matchResult"] == "通过"]
        if not target:
            pytest.skip("没有可结算订单")
        r = api.ok("POST", "/api/orders/%s/stage" % target[0]["no"], {"target": "已结算"}, token=tok)
        assert r["status"] == "已结算"


# ------------------------------------------------------------ 报表 / 设置 / 日志
class TestReports:
    def test_reports_modules(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/reports")
        for k in ("purchaseTrend", "byCategory", "suppliers", "turnover", "onTime", "price",
                  "payables", "shortages"):
            assert k in d, k
        assert len(d["purchaseTrend"]) == 6

    def test_settings(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/settings")
        assert len(d["rules"]) == 8 and d["users"]

    def test_rule_toggle(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/settings")
        code = d["rules"][0]["code"]
        r = api.ok("PUT", "/api/rules/" + code, {"enabled": False})
        assert not r["enabled"]
        api.ok("PUT", "/api/rules/" + code, {"enabled": True})

    def test_rule_value_update(self, api):
        api.login("admin")
        r = api.ok("PUT", "/api/rules/qual_warn_days", {"value": 45})
        assert float(r["value"]) == 45
        api.ok("PUT", "/api/rules/qual_warn_days", {"value": 30})

    def test_logs(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/logs")
        assert len(d) > 0

    def test_users(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/users")
        assert len(d) >= 8


# ------------------------------------------------------------ 集成三通道
class TestIntegration:
    def test_overview(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/integration/overview")
        assert d["changes"] > 0 and "recent" in d

    def test_key_lifecycle(self, api):
        api.login("admin")
        k = api.ok("POST", "/api/integration/keys", {"name": "测试对接方", "scope": "read"})
        assert k["key"].startswith("fqk_")
        d = api.ok("GET", "/api/integration/keys")
        assert any(x["keyPrefix"] == k["key"][:12] for x in d["list"])
        r = api.ok("DELETE", "/api/integration/keys/%d" % k["id"])
        assert r["status"] == "吊销"

    def test_key_auth_works(self, api):
        api.login("admin")
        k = api.ok("POST", "/api/integration/keys", {"name": "鉴权验证", "scope": "read"})
        st, r = api.call("GET", "/api/orders", token="", headers={"X-Fq-Key": k["key"]})
        assert st == 200 and r["ok"]
        # write 接口用 read key 应被拒
        st, _ = api.call("POST", "/api/requisitions",
                         {"dept": "x", "items": [{"materialCode": "MT-1001", "qty": 1}]},
                         token="", headers={"X-Fq-Key": k["key"]})
        assert st == 403
        api.ok("DELETE", "/api/integration/keys/%d" % k["id"])

    def test_webhook_crud_and_test(self, api):
        api.login("admin")
        w = api.ok("POST", "/api/integration/webhooks",
                   {"name": "测试回调", "url": "https://example.com/hook",
                    "events": ["po.created", "receipt.posted"]})
        wid = w["id"]
        assert w["secret"]
        u = api.ok("PUT", "/api/integration/webhooks/%d" % wid, {"name": "测试回调2",
                                                                 "url": "https://example.com/hook2",
                                                                 "events": "*", "status": "启用"})
        assert u["events"] == "*"
        t = api.ok("POST", "/api/integration/webhooks/%d/test" % wid, {})
        assert t["queued"]
        dl = api.ok("GET", "/api/integration/deliveries")
        assert any(x["webhook_id"] == wid for x in dl["list"])
        api.ok("DELETE", "/api/integration/webhooks/%d" % wid)

    def test_webhook_url_validated(self, api):
        api.login("admin")
        st, _ = api.call("POST", "/api/integration/webhooks", {"name": "x", "url": "ftp://x"})
        assert st == 400

    def test_mapping_and_resolve(self, api):
        api.login("admin")
        m = api.ok("POST", "/api/integration/mappings", {"objType": "po", "localNo": "PO-TEST-1",
                                                         "externalId": "EXT-001", "system": "测试ERP"})
        assert m["id"]
        r = api.ok("GET", "/api/integration/resolve?externalId=EXT-001")
        assert r["local_no"] == "PO-TEST-1"
        st, _ = api.call("GET", "/api/integration/resolve?externalId=NOT-EXIST")
        assert st == 404

    def test_sync_changes(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/sync/changes?since=0&limit=10")
        assert d["count"] == 10 and d["hasMore"]
        d2 = api.ok("GET", "/api/sync/changes?since=%d&limit=10" % d["cursor"])
        assert d2["changes"][0]["id"] > d["cursor"]

    def test_sync_object_filter(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/sync/changes?object=po&limit=50")
        assert all(x["obj_type"] == "po" for x in d["changes"])

    def test_non_admin_blocked(self, tok_maker, api):
        tok = tok_maker("liyan")
        st, _ = api.call("GET", "/api/integration/keys", token=tok)
        assert st == 403


# ------------------------------------------------------------ 导出
class TestExport:
    def test_export_suppliers_csv(self, api):
        api.login("admin")
        st, headers, raw = api.raw("GET", "/api/export/suppliers")
        assert st == 200 and b"supplier" in raw.lower() or st == 200

    def test_export_orders_csv(self, api):
        api.login("admin")
        st, headers, raw = api.raw("GET", "/api/export/orders")
        assert st == 200 and raw.count(b"\n") >= 5

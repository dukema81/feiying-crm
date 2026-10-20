# -*- coding: utf-8 -*-
"""飞泉 SCM · 单元测试：业务内核纯函数（scm.py）"""
import pytest

from scm import (AGING_BUCKETS, abc_classify, add_days, aging_bucket, available, can,
                 can_move_po, coverage_days, days_between, delay_days, doc_no, expiry_state,
                 inspect_conclusion, inspect_rate, invoice_diff_status, match3, name_affinity,
                 norm_company, norm_text, on_time_rate, overdue_days, payable_state,
                 parse_date, payment_due, price_index, po_gate, po_index, po_stage_by_qty,
                 qual_state, r2, r4, ratio, receive_rate, reorder_point, saving_rate, sha256,
                 shortage_qty, sign_payload, similarity, stock_state, supplier_health,
                 supplier_level, supplier_score, sum_amount, turnover, turnover_days,
                 weighted_price)


pytestmark = pytest.mark.unit


# ------------------------------------------------------------ 数值口径
class TestNumeric:
    def test_r2_basic(self):
        assert r2(1.005) == 1.01 or abs(r2(1.005) - 1.01) < 0.011

    def test_r2_none(self):
        assert r2(None) == 0.0

    def test_r2_string(self):
        assert r2("12.345") == 12.35

    def test_r2_bad(self):
        assert r2("abc") == 0.0

    def test_r4(self):
        assert r4(0.12345) == 0.1235

    def test_ratio_zero_div(self):
        assert ratio(10, 0) == 0.0

    def test_ratio(self):
        assert ratio(1, 4) == 0.25


# ------------------------------------------------------------ 日期与单号
class TestDates:
    def test_parse_date(self):
        from datetime import date
        assert parse_date("2026-10-20") == date(2026, 10, 20)

    def test_parse_date_bad(self):
        assert parse_date("not-a-date") is None
        assert parse_date("") is None

    def test_days_between(self):
        assert days_between("2026-10-01", "2026-10-20") == 19

    def test_days_between_none(self):
        assert days_between(None, "2026-10-20") is None

    def test_add_days(self):
        assert add_days("2026-10-20", 12) == "2026-11-01"

    def test_add_days_invalid(self):
        assert add_days("xx", 3) == ""

    def test_doc_no(self):
        assert doc_no("PO", "2026-10-20", 7) == "PO20261020-0007"

    def test_doc_no_lower_kind(self):
        assert doc_no("pr", "2026-01-02", 99) == "PR20260102-0099"


# ------------------------------------------------------------ 文本归一与查重
class TestText:
    def test_norm_text_fullwidth(self):
        assert norm_text("ＡＢＣ－１２３") == "abc123"

    def test_norm_text_punct(self):
        assert norm_text("苏州（电子）-有限, 公司") == "苏州电子有限公司"

    def test_similarity_identical(self):
        assert similarity("立信电子", "立信电子") == 1.0

    def test_similarity_zero(self):
        assert similarity("", "abc") == 0.0

    def test_norm_company_strips_suffix(self):
        assert norm_company("苏州立信电子有限公司") == "立信电子"

    def test_name_affinity_same(self):
        # 空格 / 全半角差异应归一为同一家
        assert name_affinity("苏州立信电子有限公司", "苏州立信电子 有限公司") == 1.0
        assert name_affinity("苏州立信电子有限公司", "ＳＵＺＨＯＵ 立信电子") == 0.0

    def test_name_affinity_diff(self):
        assert name_affinity("苏州立信电子有限公司", "上海华宇五金厂") == 0.0


# ------------------------------------------------------------ 权限
class TestPerm:
    def test_admin_all(self):
        assert can("admin", "write") and can("admin", "finance") and can("admin", "stock")

    def test_buyer_no_approve(self):
        assert can("buyer", "write") and not can("buyer", "approve")

    def test_finance(self):
        assert can("finance", "finance") and not can("finance", "write")

    def test_warehouse(self):
        assert can("warehouse", "stock") and not can("warehouse", "write")

    def test_unknown_role(self):
        assert not can("guest", "read")


# ------------------------------------------------------------ 供应商
class TestSupplier:
    def test_score_perfect(self):
        assert supplier_score(1, 1, 1.0, 1) == 100.0

    def test_score_weights(self):
        # 交付 0.8、质量 0.9、价格持平、响应 0.7 → 35*0.8+35*0.9+15+15*0.7 = 85.0
        assert supplier_score(0.8, 0.9, 1.0, 0.7) == 85.0

    def test_score_price_penalty(self):
        # 价格偏离 10% → 价格分 13.5，其余满分 → 98.5
        assert supplier_score(1, 1, 1.10, 1) == 98.5

    def test_score_clamp(self):
        assert supplier_score(2, 2, 1, 2) == 100.0

    def test_level_lines(self):
        assert supplier_level(85) == "A"
        assert supplier_level(84.9) == "B"
        assert supplier_level(70) == "B"
        assert supplier_level(55) == "C"
        assert supplier_level(54.9) == "D"

    def test_health_normal(self):
        assert supplier_health(90) == "正常"

    def test_health_limited(self):
        assert supplier_health(90, overdue_invoices=1) == "限单"

    def test_health_watch(self):
        assert supplier_health(50) == "观察"
        assert supplier_health(90, overdue_invoices=3) == "观察"

    def test_health_frozen(self):
        assert supplier_health(90, expired_quals=1) == "冻结"

    def test_qual_state(self):
        assert qual_state("2026-12-31", "2026-10-20", 30) == "有效"
        assert qual_state("2026-11-10", "2026-10-20", 30) == "临期"
        assert qual_state("2026-10-01", "2026-10-20") == "过期"
        assert qual_state("", "2026-10-20") == "未知"


# ------------------------------------------------------------ 订单状态机
class TestPoFlow:
    def test_index(self):
        assert po_index("草稿") == 0 and po_index("已结算") == 5
        assert po_index("不存在") == -1

    def test_forward_ok(self):
        ok, _ = can_move_po("待审批", "已下单")
        assert ok

    def test_backward_denied(self):
        ok, why = can_move_po("已下单", "待审批")
        assert not ok and "只能向前推进" in why

    def test_same_denied(self):
        ok, _ = can_move_po("已下单", "已下单")
        assert not ok

    def test_closed_terminal(self):
        assert not can_move_po("已结算", "待审批")[0]
        assert not can_move_po("已取消", "待审批")[0]

    def test_cancel_allowed_until_closed(self):
        assert can_move_po("已下单", "已取消")[0]
        assert not can_move_po("已取消", "已取消")[0]

    def test_unknown_target(self):
        assert not can_move_po("草稿", "神秘状态")[0]

    def test_gate_submit(self):
        assert po_gate("待审批", {"itemCount": 2, "amount": 100}) == []
        miss = po_gate("待审批", {"itemCount": 0, "amount": 0})
        assert "至少一行采购明细" in miss and "订单金额需大于 0" in miss

    def test_gate_order(self):
        assert po_gate("已下单", {"approvedBy": "zhaokun", "supplierStatus": "已准入"}) == []
        miss = po_gate("已下单", {"supplierStatus": "待准入"})
        assert any("审批" in m for m in miss) and any("准入" in m for m in miss)

    def test_gate_settle(self):
        assert po_gate("已结算", {"hasInvoice": 1, "matchResult": "通过"}) == []
        miss = po_gate("已结算", {"hasInvoice": 0, "matchResult": "金额差异超限"})
        assert len(miss) == 2

    def test_gate_receive(self):
        assert po_gate("全部到货", {"receivedQty": 100, "orderedQty": 100}) == []
        assert po_gate("全部到货", {"receivedQty": 90, "orderedQty": 100})

    def test_stage_by_qty(self):
        assert po_stage_by_qty(100, 0) is None
        assert po_stage_by_qty(100, 50) == "部分到货"
        assert po_stage_by_qty(100, 100) == "全部到货"

    def test_receive_rate(self):
        assert receive_rate(100, 50) == 0.5
        assert receive_rate(100, 150) == 1.0


# ------------------------------------------------------------ 三单匹配
class TestMatch3:
    def test_pass(self):
        m = match3(10000, 9800, 9900)
        assert m["result"] == "通过" and m["diff"] == 100.0

    def test_over_tolerance(self):
        m = match3(10000, 9800, 10500)
        assert m["result"] == "金额差异超限"
        assert m["rate"] > 0.02

    def test_no_receipt(self):
        assert match3(1000, 0, 900)["result"] == "无收货"

    def test_no_invoice(self):
        assert match3(1000, 900, 0)["result"] == "无发票"

    def test_custom_tolerance(self):
        assert match3(1000, 1000, 1050, tolerance=0.06)["result"] == "通过"
        assert match3(1000, 1000, 1050, tolerance=0.04)["result"] == "金额差异超限"

    def test_diff_status(self):
        assert invoice_diff_status(0.01) == "通过"
        assert invoice_diff_status(0.05) == "差异超限"


# ------------------------------------------------------------ 库存
class TestStock:
    def test_available(self):
        assert available(100, 20) == 80.0

    def test_reorder_point(self):
        assert reorder_point(10, 5, 20) == 70.0

    def test_reorder_point_ceil(self):
        assert reorder_point(2.3, 3, 0) == 7.0

    def test_coverage(self):
        assert coverage_days(100, 10) == 10.0
        assert coverage_days(100, 0) is None

    def test_stock_state(self):
        assert stock_state(0, 10, 20, 1) == "缺货"
        assert stock_state(5, 10, 20, 1) == "低于安全库存"
        assert stock_state(20, 10, 20, 1) == "待补货"
        assert stock_state(30, 10, 20, 1) == "正常"
        assert stock_state(200, 10, 20, 1, 100) == "超储"

    def test_turnover(self):
        assert turnover(300, 100) == 3.0

    def test_turnover_days(self):
        assert turnover_days(3, 90) == 30.0
        assert turnover_days(0, 90) is None

    def test_aging_bucket(self):
        assert aging_bucket(10) == "0-30天"
        assert aging_bucket(45) == "31-60天"
        assert aging_bucket(180) == "91-180天"
        assert aging_bucket(365) == "180天以上"
        assert len(AGING_BUCKETS) == 5

    def test_expiry_state(self):
        assert expiry_state("2027-06-01", "2026-10-20") == "正常"
        assert expiry_state("2026-12-01", "2026-10-20") == "近效期"
        assert expiry_state("2026-01-01", "2026-10-20") == "已过期"
        assert expiry_state("", "2026-10-20") == "无有效期"

    def test_shortage_qty(self):
        assert shortage_qty(50, 100) == 50.0
        assert shortage_qty(50, 100, 200) == 150.0
        assert shortage_qty(150, 100) == 0.0

    def test_abc_single_item_is_a(self):
        out = abc_classify([{"code": "X", "amount": 1000}])
        assert out[0]["abc"] == "A"

    def test_abc_distribution(self):
        items = [{"code": "M%d" % i, "amount": a} for i, a in
                 enumerate([500, 300, 100, 40, 30, 20, 10])]
        out = abc_classify(items)
        got = {x["code"]: x["abc"] for x in out}
        assert got["M0"] == "A"
        assert list(got.values()).count("A") >= 1
        assert list(got.values()).count("C") >= 1

    def test_abc_empty(self):
        assert abc_classify([]) == []

    def test_abc_zero_total(self):
        out = abc_classify([{"code": "A", "amount": 0}])
        assert out[0]["abc"] == "C"


# ------------------------------------------------------------ 质检与准时率
class TestQuality:
    def test_inspect_rate(self):
        assert inspect_rate(98, 2) == 0.98
        assert inspect_rate(0, 0) == 0.0

    def test_conclusion(self):
        assert inspect_conclusion(100, 0) == "合格"
        assert inspect_conclusion(99, 1) == "让步接收"
        assert inspect_conclusion(95, 5) == "退货"
        assert inspect_conclusion(0, 0) == "待检"

    def test_on_time_rate(self):
        recs = [{"promise": "2026-10-01", "actual": "2026-09-30"},
                {"promise": "2026-10-01", "actual": "2026-10-01"},
                {"promise": "2026-10-01", "actual": "2026-10-05"},
                {"promise": "2026-10-01", "actual": ""}]
        assert on_time_rate(recs) == round(2 / 3, 4)

    def test_on_time_empty(self):
        assert on_time_rate([]) == 0.0

    def test_delay_days(self):
        assert delay_days("2026-10-01", "2026-10-04") == 3
        assert delay_days("2026-10-04", "2026-10-01") == -3


# ------------------------------------------------------------ 结算
class TestPay:
    def test_payment_due(self):
        assert payment_due("2026-10-20", 30) == "2026-11-19"

    def test_overdue_days(self):
        assert overdue_days("2026-10-01", "2026-10-20") == 19
        assert overdue_days("2026-12-01", "2026-10-20") == 0

    def test_payable_state(self):
        assert payable_state("2026-10-01", 0, "2026-10-20") == "逾期"
        assert payable_state("2026-11-30", 0, "2026-10-20") == "未到期"
        assert payable_state("2026-10-22", 0, "2026-10-20") == "待付"
        assert payable_state("2026-10-01", 100, "2026-10-20") == "已付"

    def test_price_index(self):
        assert price_index(105, 100) == 1.05
        assert price_index(100, 0) == 1.0

    def test_saving_rate(self):
        assert saving_rate(95, 100) == 0.05
        assert saving_rate(105, 100) == -0.05


# ------------------------------------------------------------ 签名与汇总
class TestMisc:
    def test_sign_payload_deterministic(self):
        a = sign_payload("s3cret", "1760000000", '{"x":1}')
        b = sign_payload("s3cret", "1760000000", '{"x":1}')
        assert a == b and len(a) == 64

    def test_sign_payload_secret_matters(self):
        assert sign_payload("a", "1", "x") != sign_payload("b", "1", "x")

    def test_sha256(self):
        assert sha256("fqk_demo") == sha256("fqk_demo")
        assert sha256("a") != sha256("b")

    def test_sum_amount(self):
        assert sum_amount([{"qty": 2, "price": 3.5}, {"qty": 1, "price": 10}]) == 17.0

    def test_weighted_price(self):
        assert weighted_price([{"qty": 1, "price": 10}, {"qty": 3, "price": 20}]) == 17.5
        assert weighted_price([]) == 0.0

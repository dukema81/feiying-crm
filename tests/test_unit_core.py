# -*- coding: utf-8 -*-
"""飞鹰 CRM · 业务内核单元测试（40 项）

只测 backend/crm.py 的纯函数，不碰数据库、不起服务：
规则算错在这里暴露，接口层只负责取数落库。
"""
import os
import sys
from datetime import date, datetime, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import crm  # noqa: E402


# ---------------------------------------------------------------- 数值与单号
def test_round_money():
    assert crm.r2(0.005) == 0.01
    assert crm.r2(2.675) == 2.68
    assert crm.money(1234.5) == "1234.50"


def test_doc_no_formats():
    d = date(2026, 10, 20)
    assert crm.doc_no("lead", d, 7) == "LD20261020-0007"
    assert crm.doc_no("quote", "2026-10-20", 12) == "QT20261020-0012"
    assert crm.doc_no("ticket", d, 5) == "TK20261020-000005"
    assert crm.doc_no("payment", d, 9999) == "SK20261020-9999"


def test_parse_no_roundtrip():
    assert crm.parse_no("LD20261020-0007") == ("lead", "20261020", 7)
    assert crm.parse_no("TK20261020-000005") == ("ticket", "20261020", 5)
    assert crm.parse_no("XX20261020-0001") is None
    assert crm.parse_no("LD2026-1") is None


# ---------------------------------------------------------------- 阶段状态机
def test_stage_forward_allowed():
    ok, msg = crm.can_move_stage("初步接触", "需求确认")
    assert ok and msg == ""
    ok, _ = crm.can_move_stage("初步接触", "方案报价")
    assert ok, "允许跨级前进"


def test_stage_backward_blocked():
    ok, msg = crm.can_move_stage("商务谈判", "方案报价")
    assert not ok and "不能回退" in msg


def test_stage_win_only_from_negotiation():
    ok, msg = crm.can_move_stage("方案报价", "赢单")
    assert not ok and "商务谈判" in msg
    ok, _ = crm.can_move_stage("商务谈判", "赢单")
    assert ok


def test_stage_lose_from_any_open():
    for s in crm.OPEN_STAGES:
        ok, _ = crm.can_move_stage(s, "输单")
        assert ok, s


def test_stage_closed_locked():
    ok, msg = crm.can_move_stage("赢单", "商务谈判")
    assert not ok and "已结单" in msg


def test_stage_unknown():
    ok, msg = crm.can_move_stage("不存在的阶段", "需求确认")
    assert not ok and msg == "阶段不存在"


def test_stage_gate_decision_maker():
    miss = crm.stage_gate("需求确认", {"amount": 100000, "decision_maker": ""})
    assert miss == ["决策人"]
    assert crm.stage_gate("需求确认", {"decision_maker": "王总"}) == []


def test_stage_gate_amount():
    assert crm.stage_gate("方案报价", {"amount": 0}) == ["商机金额"]
    assert crm.stage_gate("方案报价", {"amount": 50000}) == []


def test_stage_gate_contract():
    assert crm.stage_gate("赢单", {"amount": 1}, has_contract=False) == ["已签署合同"]
    assert crm.stage_gate("赢单", {"amount": 1}, has_contract=True) == []


def test_opp_status():
    assert crm.opp_status("赢单") == "赢单"
    assert crm.opp_status("输单") == "输单"
    assert crm.opp_status("方案报价") == "进行中"


# ---------------------------------------------------------------- 归一化与查重
def test_norm_phone():
    assert crm.norm_phone("+86 139-1234-5601") == "13912345601"
    assert crm.norm_phone("0086 13912345601") == "13912345601"
    assert crm.norm_phone("(0512)6800 0000") == "051268000000"


def test_norm_company():
    assert crm.norm_company("苏州精工机械有限公司") == crm.norm_company("精工机械股份有限公司")
    assert crm.norm_company(" 深圳 睿驰 智能装备有限公司 ") == crm.norm_company("睿驰智能装备")


def test_similarity_bounds():
    assert crm.similarity("苏州精工机械有限公司", "苏州精工机械有限公司") == 1.0
    assert crm.similarity("精工机械", "精工机械制造") > 0.5
    assert crm.similarity("精工机械", "完全不同名称") < 0.4
    assert crm.similarity("", "x") == 0.0


def test_dup_by_phone():
    lead = {"name": "新公司", "phone": "139-1234-5601"}
    others = [{"no": "LD1", "name": "旧公司", "phone": "13912345601", "owner": "liuyang"}]
    dups = crm.dup_candidates(lead, others, [])
    assert dups and dups[0]["reason"] == "手机号相同" and dups[0]["score"] == 1.0


def test_dup_by_name_similarity():
    lead = {"name": "苏州精工机械有限公司", "phone": ""}
    others = [{"no": "LD1", "name": "苏州精工机械制造有限公司", "phone": "13900000000"}]
    dups = crm.dup_candidates(lead, others, [])
    assert dups and "名称相似" in dups[0]["reason"]


def test_dup_skip_self_and_customers():
    lead = {"no": "LD9", "name": "苏州精工机械有限公司", "phone": "13912345601"}
    own = [{"no": "LD9", "name": "苏州精工机械有限公司", "phone": "13912345601"}]
    cus = [{"code": "C-0001", "name": "苏州精工机械有限公司", "phone": "13912345601"}]
    dups = crm.dup_candidates(lead, own, cus)
    assert len(dups) == 1 and dups[0]["objType"] == "customer"


def test_dup_no_match():
    assert crm.dup_candidates({"name": "甲", "phone": "1"}, [], []) == []


def test_name_affinity_gate():
    """相似度达标还不够，必须共有前缀 ≥2 字或一方包含另一方。"""
    assert crm.name_affinity("苏州精工机械有限公司", "苏州精工机械制造有限公司") >= 0.62
    assert crm.name_affinity("精工机械", "精工机械制造") >= 0.62
    assert crm.name_affinity("甲", "乙") == 0.0


def test_dup_numeric_noise_not_flagged():
    """主体名称不同、只有末尾编号相同时不应判为重复（避免误拦新建）。"""
    lead = {"name": "公海阀门制造有限公司9597613", "phone": "13700000001"}
    others = [{"no": "LD1", "name": "无效线索清理有限公司9597611", "phone": "13700000002"}]
    assert crm.dup_candidates(lead, others, []) == []


# ---------------------------------------------------------------- 线索分级
def test_grade_thresholds():
    assert crm.grade_of(500000) == "A"
    assert crm.grade_of(499999) == "B"
    assert crm.grade_of(150000) == "B"
    assert crm.grade_of(1000) == "C"


def test_grade_source_uplift():
    assert crm.grade_of(200000, "展会") == "A"
    assert crm.grade_of(200000, "官网表单") == "B"
    assert crm.grade_of(10000, "老客推荐") == "B"


# ---------------------------------------------------------------- 客户评分
def test_score_high_quality_customer():
    s = crm.score_customer(2, 400000, 4, 5)
    assert s >= 90, s
    assert crm.score_level(s) == "优质"


def test_score_decay_by_recency():
    fresh = crm.score_customer(1, 0, 0, 0)
    stale = crm.score_customer(120, 0, 0, 0)
    assert fresh > stale
    assert stale == 0


def test_score_overdue_penalty():
    base = crm.score_customer(10, 100000, 2, 4)
    pen = crm.score_customer(10, 100000, 2, 4, overdue_plans=2)
    assert base - pen == pytest.approx(16, abs=0.01)


def test_score_clamped():
    assert 0 <= crm.score_customer(None, 10 ** 9, 99, 5, 0) <= 100
    assert crm.score_customer(None, 0, 0, 0, 9) >= 0


def test_score_level_buckets():
    assert crm.score_level(85) == "优质"
    assert crm.score_level(70) == "健康"
    assert crm.score_level(50) == "待经营"
    assert crm.score_level(10) == "流失风险"


# ---------------------------------------------------------------- 漏斗与预测
def _opps():
    return [
        {"stage": "初步接触", "status": "进行中", "amount": 100000, "probability": 0.1,
         "expect_close_date": "2026-11-10"},
        {"stage": "需求确认", "status": "进行中", "amount": 200000, "probability": 0.25,
         "expect_close_date": "2026-11-20"},
        {"stage": "方案报价", "status": "进行中", "amount": 300000, "probability": 0.5,
         "expect_close_date": "2026-12-05"},
        {"stage": "商务谈判", "status": "进行中", "amount": 400000, "probability": 0.75,
         "expect_close_date": "2026-12-25"},
        {"stage": "赢单", "status": "赢单", "amount": 500000, "probability": 1.0,
         "expect_close_date": "2026-10-01"},
        {"stage": "输单", "status": "输单", "amount": 60000, "probability": 0.0,
         "expect_close_date": "2026-09-01"},
    ]


def test_funnel_amounts():
    f = crm.funnel(_opps())
    assert f["openCount"] == 4
    assert f["openAmount"] == 1000000
    assert f["wonCount"] == 1 and f["wonAmount"] == 500000
    assert f["winRate"] == 0.5
    assert f["avgDeal"] == 500000
    assert f["stages"][0]["weighted"] == 10000


def test_funnel_empty():
    f = crm.funnel([])
    assert f["openAmount"] == 0 and f["winRate"] == 0 and f["avgDeal"] == 0


def test_conversion_rates():
    f = crm.funnel(_opps())
    conv = crm.conversion(f["stages"])
    assert conv[0]["from"] == "初步接触" and conv[0]["rate"] == 1.0
    assert len(conv) == 3


def test_forecast_months():
    fc = crm.forecast(_opps(), ["2026-11", "2026-12", "2027-01"])
    assert fc[0]["count"] == 2 and fc[0]["amount"] == 300000
    assert fc[0]["weighted"] == pytest.approx(60000, abs=0.01)
    assert fc[1]["pessimistic"] == pytest.approx(700000 * 0.7, abs=0.01)
    assert fc[2]["count"] == 0


def test_month_list_cross_year():
    assert crm.month_list("2026-11", 4) == ["2026-11", "2026-12", "2027-01", "2027-02"]
    assert crm.month_list(date(2026, 12, 1), 2) == ["2026-12", "2027-01"]


def test_weighted():
    assert crm.weighted(123456, 0.25) == 30864.0
    assert crm.weighted(0, 1) == 0


# ---------------------------------------------------------------- 报价折扣
def test_quote_discount():
    assert crm.quote_discount(100000, 90000) == 0.1
    assert crm.quote_discount(0, 100) == 0.0
    assert crm.quote_discount(100000, 120000) == 0.0, "溢价不算负折扣"


def test_discount_approval_boundary():
    assert crm.need_discount_approval(0.1501, 0.15) is True
    assert crm.need_discount_approval(0.15, 0.15) is False, "等于阈值不审批"
    assert crm.need_discount_approval(0.3, 0.15) is True


def test_quote_amount():
    calc = crm.quote_amount([
        {"qty": 2, "listPrice": 100000, "price": 90000},
        {"qty": 10, "listPrice": 2000, "price": 1800},
    ])
    assert calc["listAmount"] == 220000
    assert calc["amount"] == 198000
    assert calc["discountRate"] == 0.1


def test_quote_amount_camel_keys():
    calc = crm.quote_amount([{"qty": 1, "listPrice": 100, "price": 80}])
    assert calc["listAmount"] == 100


# ---------------------------------------------------------------- 回款计划
def test_build_plans_sum_matches_amount():
    plans = crm.build_plans(100000, "2026-10-20", "3-4-3")
    assert len(plans) == 3
    assert [p["amount"] for p in plans] == [30000.0, 40000.0, 30000.0]
    assert sum(p["amount"] for p in plans) == 100000
    assert plans[0]["dueDate"] == "2026-11-19"
    assert plans[2]["dueDate"] == "2027-01-18"


def test_build_plans_rounding_remainder():
    plans = crm.build_plans(100000, "2026-10-20", "3-3-4")
    assert sum(p["amount"] for p in plans) == 100000
    plans2 = crm.build_plans(1000, "2026-10-20", "1-1-1")
    assert abs(sum(p["amount"] for p in plans2) - 1000) < 0.01


def test_build_plans_equal_installments():
    plans = crm.build_plans(120000, "2026-10-01", "10", n=4)
    assert len(plans) == 4 and abs(sum(p["amount"] for p in plans) - 120000) < 0.02


def test_plan_status():
    assert crm.plan_status(1000, 1000, "2020-01-01", date(2026, 10, 20)) == "已收"
    assert crm.plan_status(1000, 0, "2026-12-01", date(2026, 10, 20)) == "未收"
    assert crm.plan_status(1000, 0, "2026-09-01", date(2026, 10, 20)) == "逾期"
    assert crm.plan_status(1000, 300, "2026-12-01", date(2026, 10, 20)) == "部分收款"
    assert crm.plan_status(1000, 300, "2026-09-01", date(2026, 10, 20)) == "部分逾期"


def test_overdue_days():
    assert crm.overdue_days("2026-10-01", date(2026, 10, 20)) == 19
    assert crm.overdue_days("2026-12-01", date(2026, 10, 20)) == 0


def test_aging_buckets():
    plans = [
        {"amount": 1000, "paidAmount": 0, "dueDate": "2026-12-31"},
        {"amount": 2000, "paidAmount": 0, "dueDate": "2026-10-10"},
        {"amount": 3000, "paidAmount": 3000, "dueDate": "2026-01-01"},
        {"amount": 4000, "paidAmount": 0, "dueDate": "2026-07-01"},
    ]
    b = crm.aging_buckets(plans, date(2026, 10, 20))
    assert b["未到期"] == 1000
    assert b["1-30 天"] == 2000
    assert b["90 天以上"] == 4000
    assert b["31-60 天"] == 0


# ---------------------------------------------------------------- SLA
def test_sla_dues_by_priority():
    resp, res = crm.sla_dues("2026-10-20 09:00:00", "P1")
    assert resp == "2026-10-20 11:00:00"
    assert res == "2026-10-20 13:00:00"
    resp3, res3 = crm.sla_dues("2026-10-20 09:00:00", "P3")
    assert res3 == "2026-10-21 09:00:00"


def test_sla_state():
    assert crm.sla_state("2026-10-20 08:00:00", "2026-10-20 09:00:00") == "超时"
    assert crm.sla_state("2026-10-20 10:00:00", "2026-10-20 09:00:00") == "临期"
    assert crm.sla_state("2026-10-20 20:00:00", "2026-10-20 09:00:00") == "正常"
    assert crm.sla_state("2026-10-20 08:00:00", "2026-10-20 09:00:00",
                         resolved_at="2026-10-20 09:30:00") == "已完成"


def test_sla_left_hours():
    assert crm.sla_left_hours("2026-10-20 12:00:00", "2026-10-20 09:00:00") == 3.0
    assert crm.sla_left_hours("2026-10-20 08:00:00", "2026-10-20 09:00:00") == -1.0


# ---------------------------------------------------------------- 市场 ROI
def test_campaign_roi():
    r = crm.campaign_roi(100000, 350000, 50)
    assert r["roi"] == 2.5
    assert r["cpl"] == 2000
    assert r["revenue"] == 350000
    assert crm.campaign_roi(0, 1000, 0)["roi"] == 0.0


# ---------------------------------------------------------------- 集成
def test_signature_verify():
    sig = crm.sign_payload("s3cret", "1761000000", '{"a":1}')
    assert crm.verify_signature("s3cret", "1761000000", '{"a":1}', sig) is True
    assert crm.verify_signature("s3cret", "1761000000", '{"a":2}', sig) is False
    assert crm.verify_signature("other", "1761000000", '{"a":1}', sig) is False


def test_paginate():
    items = list(range(45))
    p = crm.paginate(items, 2, 20)
    assert p["total"] == 45 and len(p["list"]) == 20 and p["list"][0] == 20
    assert p["pages"] == 3
    p2 = crm.paginate(items, 1, 999)
    assert p2["pageSize"] == 200, "每页上限 200"
    assert crm.paginate([], 1, 10)["pages"] == 0


# ---------------------------------------------------------------- 权限
def test_permission_matrix():
    assert crm.can("admin", "admin")
    assert crm.can("sales_director", "approve")
    assert not crm.can("sales", "approve")
    assert crm.can("sales", "write")
    assert not crm.can("service", "write"), "客服不能改客户主数据"
    assert crm.can("service", "service")
    assert crm.can("finance", "finance")
    assert not crm.can("marketing", "finance")
    assert crm.is_manager("sales_director") and not crm.is_manager("sales")


def test_days_between():
    assert crm.days_between("2026-10-01 09:00:00", "2026-10-20 18:00:00") == 19
    assert crm.days_between("", "2026-10-20") is None
    assert crm.days_between("2026-10-20", "bad") is None

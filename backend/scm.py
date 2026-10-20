# -*- coding: utf-8 -*-
"""飞泉 SCM · 业务内核（纯函数，无 IO / 无 SQL，可直接单元测试）

设计原则
- 所有「口径」都收敛到这里：供应商评级、采购订单状态机与闸口、三单匹配、
  库存状态与补货点、ABC 分类、周转与库龄、到货及时率、付款到期。
- 不做任何数据库访问，也不读环境变量；服务层只负责取数与落库。
- 金额一律四舍五入到分（r2），比率保留 4 位（r4），避免浮点噪声穿透到界面。
"""
import hashlib
import hmac
import json
import math
import re
import unicodedata
from datetime import date, datetime, timedelta

# ---------------------------------------------------------------- 角色与权限
ROLE_LABEL = {
    "admin": "系统管理员",
    "purchase_director": "采购总监",
    "buyer": "采购专员",
    "planner": "计划员",
    "warehouse": "仓库主管",
    "quality": "质检员",
    "finance": "财务专员",
}

# read 全域读 / write 建单改单 / approve 审批定价 / stock 库存作业 / finance 结算付款
_PERM = {
    "admin": {"read", "write", "approve", "stock", "finance", "admin"},
    "purchase_director": {"read", "write", "approve", "finance"},
    "buyer": {"read", "write"},
    "planner": {"read", "write"},
    "warehouse": {"read", "stock"},
    "quality": {"read", "stock"},
    "finance": {"read", "finance", "approve"},
}


def can(role, perm):
    return perm in _PERM.get(role, set())


# ---------------------------------------------------------------- 基础口径
def r2(v):
    try:
        return round(float(v or 0) + 1e-9, 2)
    except (TypeError, ValueError):
        return 0.0


def r4(v):
    try:
        return round(float(v or 0) + 1e-12, 4)
    except (TypeError, ValueError):
        return 0.0


def ratio(a, b):
    a, b = float(a or 0), float(b or 0)
    return r4(a / b) if b else 0.0


def parse_date(text):
    if not text:
        return None
    if isinstance(text, date):
        return text
    try:
        return datetime.strptime(str(text)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_time(text):
    if not text:
        return None
    s = str(text).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(fmt) + 2].strip(), fmt)
        except ValueError:
            continue
    return None


def days_between(a, b):
    """b - a 的天数（a、b 可以是日期或 yyyy-mm-dd 字符串）。"""
    da, db_ = parse_date(a), parse_date(b)
    if not da or not db_:
        return None
    return (db_ - da).days


def add_days(text, n):
    d = parse_date(text)
    if not d:
        return ""
    return (d + timedelta(days=int(n))).isoformat()


def doc_no(kind, d, seq):
    """单号：PR20261020-0001。kind 为 2~4 位大写字母前缀，seq 为当日流水。"""
    day = parse_date(d) or date.today()
    return "%s%s-%04d" % (str(kind).upper(), day.strftime("%Y%m%d"), int(seq))


def norm_text(s):
    """NFKC 归一（全角转半角）、去标点与空白、转小写，用于编码/名称比对。"""
    if not s:
        return ""
    t = unicodedata.normalize("NFKC", str(s)).lower()
    return re.sub(r"[\s\-_/\\.,，。、;；:：()（）\[\]【】\"'`]+", "", t)


def similarity(a, b):
    """最长公共子串长度 ÷ 较长串长度，0~1。"""
    x, y = norm_text(a), norm_text(b)
    if not x or not y:
        return 0.0
    if x == y:
        return 1.0
    if len(x) > len(y):
        x, y = y, x
    best = 0
    prev = [0] * (len(x) + 1)
    for ch in y:
        cur = [0] * (len(x) + 1)
        for i, cx in enumerate(x, 1):
            if cx == ch:
                cur[i] = prev[i - 1] + 1
                if cur[i] > best:
                    best = cur[i]
        prev = cur
    return r4(best / float(len(y)))


COMPANY_SUFFIX = ("股份有限公司", "有限责任公司", "有限公司", "集团", "公司", "厂", "商行", "经营部")
CITY_PREFIX = ("苏州", "上海", "无锡", "常州", "南京", "杭州", "宁波", "深圳", "东莞", "广州", "北京",
               "天津", "青岛", "合肥", "武汉", "成都", "重庆", "西安", "厦门", "昆山", "太仓")


def norm_company(name):
    t = norm_text(name)
    for suf in COMPANY_SUFFIX:
        t = t.replace(norm_text(suf), "")
    for city in CITY_PREFIX:
        if t.startswith(norm_text(city)):
            t = t[len(norm_text(city)):]
            break
    return t


def name_affinity(a, b, threshold=0.62):
    """供应商名是否「像同一家」：相似度达标，且共有前缀 ≥2 字或一方完整包含另一方。"""
    sim = similarity(a, b)
    if sim < threshold:
        return 0.0
    x, y = norm_company(a), norm_company(b)
    short, long = (x, y) if len(x) <= len(y) else (y, x)
    if short and short in long:
        return sim
    pre = 0
    for u, v in zip(x, y):
        if u != v:
            break
        pre += 1
    return sim if pre >= 2 else 0.0


# ---------------------------------------------------------------- 供应商
SUP_LEVELS = ["A", "B", "C", "D"]


def supplier_score(delivery_rate, quality_rate, price_index, response_rate):
    """供应商综合分（0~100）。

    delivery_rate  交付及时率 0~1      权重 35
    quality_rate   到货合格率 0~1      权重 35
    price_index    价格指数（本厂价 ÷ 市场均价，1.0 为持平）权重 15：
                   |index-1| 每偏离 1% 扣 1 分，最多扣满 15 分
    response_rate  协同响应达标率 0~1  权重 15
    """
    delivery = max(0.0, min(1.0, float(delivery_rate or 0)))
    quality = max(0.0, min(1.0, float(quality_rate or 0)))
    response = max(0.0, min(1.0, float(response_rate or 0)))
    idx = float(price_index or 1.0)
    price_score = max(0.0, 1.0 - abs(idx - 1.0) * 1.0) if idx > 0 else 0.0
    price_score = min(1.0, price_score)
    return r2(100.0 * (0.35 * delivery + 0.35 * quality + 0.15 * price_score + 0.15 * response))


def supplier_level(score):
    s = float(score or 0)
    if s >= 85:
        return "A"
    if s >= 70:
        return "B"
    if s >= 55:
        return "C"
    return "D"


def supplier_health(score, overdue_invoices=0, expired_quals=0):
    """供应商可用性判定：分数低、证件过期、有逾期发票都会降级。"""
    if expired_quals:
        return "冻结"
    if float(score or 0) < 55 or int(overdue_invoices or 0) >= 3:
        return "观察"
    if int(overdue_invoices or 0) > 0:
        return "限单"
    return "正常"


def qual_state(expire_date, today_str, warn_days=30):
    """资质有效状态：有效 / 临期（warn_days 内到期）/ 过期 / 未知。"""
    left = days_between(today_str, expire_date)
    if left is None:
        return "未知"
    if left < 0:
        return "过期"
    if left <= int(warn_days):
        return "临期"
    return "有效"


# ---------------------------------------------------------------- 采购订单状态机
PO_FLOW = ["草稿", "待审批", "已下单", "部分到货", "全部到货", "已结算"]
PO_CLOSED = {"已结算", "已取消"}


def po_index(stage):
    return PO_FLOW.index(stage) if stage in PO_FLOW else -1


def can_move_po(cur, target):
    """只能前进，不能回退；已结算/已取消为终态。"""
    if cur in PO_CLOSED:
        return False, "订单已%s，不可变更" % ("结算" if cur == "已结算" else "取消")
    if target == "已取消":
        return True, ""
    if target not in PO_FLOW:
        return False, "未知状态：%s" % target
    if cur not in PO_FLOW:
        return False, "当前状态异常：%s" % cur
    if po_index(target) <= po_index(cur):
        return False, "采购订单只能向前推进（当前 %s，目标 %s）" % (cur, target)
    return True, ""


def po_gate(target, ctx, tolerance=0.02):
    """阶段闸口：返回缺失项清单（空列表表示可推进）。

    ctx 键：itemCount、amount、supplierStatus、approvedBy、orderedQty、
            receivedQty、matchResult、hasInvoice
    """
    miss = []
    if target == "待审批":
        if int(ctx.get("itemCount") or 0) <= 0:
            miss.append("至少一行采购明细")
        if float(ctx.get("amount") or 0) <= 0:
            miss.append("订单金额需大于 0")
    elif target == "已下单":
        if not ctx.get("approvedBy"):
            miss.append("需采购总监审批")
        if (ctx.get("supplierStatus") or "") != "已准入":
            miss.append("供应商未通过准入")
    elif target in ("部分到货", "全部到货"):
        if float(ctx.get("receivedQty") or 0) <= 0:
            miss.append("尚无收货记录")
        if target == "全部到货" and float(ctx.get("receivedQty") or 0) + 1e-6 < float(ctx.get("orderedQty") or 0):
            miss.append("到货数量未达订单数量")
    elif target == "已结算":
        if not ctx.get("hasInvoice"):
            miss.append("尚未登记发票")
        if (ctx.get("matchResult") or "") != "通过":
            miss.append("三单匹配未通过")
    return miss


def po_stage_by_qty(ordered, received):
    """按累计到货量推断中间态（供收货后自动推进）。"""
    o, rcv = float(ordered or 0), float(received or 0)
    if rcv <= 0:
        return None
    if rcv + 1e-6 >= o:
        return "全部到货"
    return "部分到货"


def receive_rate(ordered, received):
    return min(1.0, ratio(received, ordered))


# ---------------------------------------------------------------- 三单匹配
def match3(po_amount, received_amount, invoice_amount, tolerance=0.02):
    """采购订单 / 收货单 / 发票 金额与数量三方比对。

    返回 {result, diff, rate, note}：
      - 无收货 / 无发票 → 无法匹配
      - |发票-收货| ÷ 收货 ≤ 容差 → 通过
      - 否则 金额差异超限（附差异额与差异率）
    """
    po, recv, inv = float(po_amount or 0), float(received_amount or 0), float(invoice_amount or 0)
    if recv <= 0:
        return {"result": "无收货", "diff": 0.0, "rate": 0.0, "note": "尚无收货金额"}
    if inv <= 0:
        return {"result": "无发票", "diff": 0.0, "rate": 0.0, "note": "尚未登记发票"}
    diff = r2(inv - recv)
    rate = r4(abs(diff) / recv) if recv else 0.0
    ok = rate <= float(tolerance) + 1e-9
    return {"result": "通过" if ok else "金额差异超限", "diff": diff, "rate": rate,
            "note": "容差 %.0f%%" % (float(tolerance) * 100),
            "poAmount": r2(po), "receivedAmount": r2(recv), "invoiceAmount": r2(inv)}


def invoice_diff_status(rate, tolerance=0.02):
    return "通过" if float(rate or 0) <= float(tolerance) + 1e-9 else "差异超限"


# ---------------------------------------------------------------- 库存
def available(on_hand, locked):
    return r2(float(on_hand or 0) - float(locked or 0))


def reorder_point(avg_daily_usage, lead_days, safety_stock):
    """补货点 = 日均耗用 × 采购提前期 + 安全库存（向上取整）。"""
    return float(math.ceil(float(avg_daily_usage or 0) * float(lead_days or 0)
                           + float(safety_stock or 0)))


def coverage_days(on_hand, avg_daily_usage):
    u = float(avg_daily_usage or 0)
    if u <= 0:
        return None
    return r2(float(on_hand or 0) / u)


def stock_state(on_hand, safety_stock, reorder, avg_daily_usage=0, max_stock=0):
    """库存状态：缺货 / 低于安全库存 / 待补货 / 正常 / 超储。"""
    on_hand = float(on_hand or 0)
    safety = float(safety_stock or 0)
    if on_hand <= 0:
        return "缺货"
    if on_hand < safety:
        return "低于安全库存"
    if reorder and on_hand <= float(reorder):
        return "待补货"
    if max_stock and on_hand > float(max_stock):
        return "超储"
    return "正常"


def turnover(issue_cost, avg_stock_amount):
    """库存周转次数 = 期间出库成本 ÷ 平均库存金额。"""
    return r2(ratio(issue_cost, avg_stock_amount))


def turnover_days(times, period_days=90):
    t = float(times or 0)
    if t <= 0:
        return None
    return r2(float(period_days) / t)


AGING_BUCKETS = ["0-30天", "31-60天", "61-90天", "91-180天", "180天以上"]


def aging_bucket(age_days):
    d = float(age_days or 0)
    if d <= 30:
        return AGING_BUCKETS[0]
    if d <= 60:
        return AGING_BUCKETS[1]
    if d <= 90:
        return AGING_BUCKETS[2]
    if d <= 180:
        return AGING_BUCKETS[3]
    return AGING_BUCKETS[4]


def expiry_state(expire_date, today_str, warn_days=90):
    left = days_between(today_str, expire_date)
    if left is None:
        return "无有效期"
    if left < 0:
        return "已过期"
    if left <= int(warn_days):
        return "近效期"
    return "正常"


def abc_classify(items, a_line=0.7, b_line=0.9, key="amount"):
    """ABC 分类：按金额降序累计占比，≤70% 记 A，≤90% 记 B，其余 C。"""
    total = sum(float(i.get(key) or 0) for i in items)
    out = []
    if total <= 0:
        for i in items:
            j = dict(i)
            j["abc"] = "C"
            j["share"] = 0.0
            j["cumShare"] = 0.0
            out.append(j)
        return out
    cum = 0.0
    for i in sorted(items, key=lambda x: -float(x.get(key) or 0)):
        amt = float(i.get(key) or 0)
        share = r4(amt / total)
        before = cum            # 判定用「加入本物料之前」的累计占比：金额最大的那个必然是 A
        cum = r4(cum + share)
        j = dict(i)
        j["share"] = share
        j["cumShare"] = cum
        j["abc"] = "A" if before < float(a_line) - 1e-9 else ("B" if before < float(b_line) - 1e-9 else "C")
        out.append(j)
    return out


def shortage_qty(on_hand, safety_stock, max_stock=0):
    """缺料补货量：补到安全库存（有最大库存则补到最大库存）。"""
    target = float(max_stock or 0) or float(safety_stock or 0)
    gap = target - float(on_hand or 0)
    return r2(gap) if gap > 0 else 0.0


# ---------------------------------------------------------------- 收货与质检
def inspect_rate(ok_qty, ng_qty):
    total = float(ok_qty or 0) + float(ng_qty or 0)
    return r4(float(ok_qty or 0) / total) if total else 0.0


def inspect_conclusion(ok_qty, ng_qty, tolerance=0.02):
    """质检结论：合格 / 让步接收（不良率 ≤ 容差且非全不良）/ 退货。"""
    total = float(ok_qty or 0) + float(ng_qty or 0)
    if total <= 0:
        return "待检"
    bad = ratio(ng_qty, total)
    if bad <= 0:
        return "合格"
    if bad <= float(tolerance):
        return "让步接收"
    return "退货"


def on_time_rate(records):
    """到货及时率：records 为 [{promise, actual}]，actual 为空表示未到货（不计入分母）。"""
    done = [r for r in records if r.get("actual")]
    if not done:
        return 0.0
    ok = [r for r in done if (days_between(r["promise"], r["actual"]) or 0) <= 0]
    return r4(len(ok) / float(len(done)))


def delay_days(promise, actual):
    d = days_between(promise, actual)
    return d if d is not None else 0


# ---------------------------------------------------------------- 结算与付款
def payment_due(invoice_date, terms_days):
    return add_days(invoice_date, int(terms_days or 0))


def overdue_days(due_date, today_str):
    d = days_between(due_date, today_str)
    return d if d and d > 0 else 0


def payable_state(due_date, paid, today_str):
    if float(paid or 0) > 0:
        return "已付"
    d = days_between(due_date, today_str)
    if d is None:
        return "未知"
    return "逾期" if d > 0 else ("待付" if d >= -7 else "未到期")


# ---------------------------------------------------------------- 事件签名
def sign_payload(secret, timestamp, body):
    """Webhook 签名：HMAC-SHA256(timestamp + "." + body)，与飞鹰 CRM 保持同一套算法。"""
    msg = ("%s.%s" % (timestamp, body)).encode("utf-8")
    return hmac.new(str(secret or "").encode("utf-8"), msg, hashlib.sha256).hexdigest()


def sha256(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------- 单据汇总
def sum_amount(items, qty_key="qty", price_key="price"):
    return r2(sum(float(i.get(qty_key) or 0) * float(i.get(price_key) or 0) for i in items))


def weighted_price(items, qty_key="qty", price_key="price"):
    qty = sum(float(i.get(qty_key) or 0) for i in items)
    if qty <= 0:
        return 0.0
    return r4(sum(float(i.get(qty_key) or 0) * float(i.get(price_key) or 0) for i in items) / qty)


def price_index(price, benchmark):
    """价格指数 = 本厂价 ÷ 市场均价。"""
    b = float(benchmark or 0)
    if b <= 0:
        return 1.0
    return r4(float(price or 0) / b)


def saving_rate(price, benchmark):
    """相对市场均价的节约率（正数=便宜）。"""
    b = float(benchmark or 0)
    if b <= 0:
        return 0.0
    return r4((b - float(price or 0)) / b)

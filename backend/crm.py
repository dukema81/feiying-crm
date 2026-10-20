# -*- coding: utf-8 -*-
"""飞鹰 CRM · 业务内核（纯函数，无 IO、无 SQL）

把「可计算的规则」全部收敛到这一层，服务层只做取数 / 落库 / 组装视图，
单元测试可以直接对拍，避免规则散落在接口里说不清楚。

包含：
  1. 数值与单号           money / doc_no
  2. 阶段与状态机         STAGES / can_move_stage / stage_gate
  3. 线索查重与分级       norm_phone / norm_company / similarity / name_affinity / dup_candidates / grade_of
  4. 客户评分             score_customer
  5. 漏斗与预测           funnel / forecast / weighted / conversion
  6. 报价折扣             quote_discount / need_discount_approval
  7. 回款计划与账龄       build_plans / plan_status / aging_buckets
  8. 服务 SLA             sla_dues / sla_state / sla_left_hours
  9. 市场活动 ROI         campaign_roi
 10. 权限矩阵             can / ROLE_PERM
 11. 集成：签名 / 分页   sign_payload / verify_signature / paginate
"""
import hashlib
import hmac
import math
import re
import unicodedata
from datetime import date, datetime, timedelta

# ---------------------------------------------------------------- 角色与权限
ROLE_LABEL = {
    "admin": "系统管理员",
    "sales_director": "销售总监",
    "sales": "销售经理",
    "sdr": "线索专员",
    "service": "客服工程师",
    "finance": "财务",
    "marketing": "市场专员",
}

# 权限点：read 全域读 / write 业务写 / approve 折扣审批 / admin 系统与集成
ROLE_PERM = {
    "admin": {"read", "write", "approve", "admin", "service", "finance", "marketing"},
    "sales_director": {"read", "write", "approve", "finance"},
    "sales": {"read", "write"},
    "sdr": {"read", "write"},
    "service": {"read", "service"},
    "finance": {"read", "finance"},
    "marketing": {"read", "marketing"},
}


def can(role, perm):
    return perm in ROLE_PERM.get(role, set())


def is_manager(role):
    return role in ("admin", "sales_director")


# ---------------------------------------------------------------- 数值
def r2(v):
    """金额两位小数，四舍五入（避免 0.005 漂移）。"""
    return float(round(float(v or 0) + 1e-9, 2))


def r4(v):
    return float(round(float(v or 0) + 1e-12, 4))


def money(v):
    return "%.2f" % r2(v)


def pct(v, digits=2):
    return "%.*f%%" % (digits, float(v or 0) * 100)


def ratio(a, b):
    return r4(float(a or 0) / float(b)) if b else 0.0


# ---------------------------------------------------------------- 单号
DOC_PREFIX = {
    "lead": "LD",
    "opportunity": "OPP",
    "quote": "QT",
    "contract": "CT",
    "payment": "SK",
    "ticket": "TK",
}


def doc_no(kind, dt, seq):
    """LD20261020-0001 / TK20261020-000123（工单 6 位）。"""
    d = dt if isinstance(dt, str) else dt.strftime("%Y-%m-%d")
    d = d.replace("-", "")[:8]
    width = 6 if kind == "ticket" else 4
    return "%s%s-%0*d" % (DOC_PREFIX[kind], d, width, int(seq))


def parse_no(no):
    """拆单号 → (kind, day, seq)；非法返回 None。"""
    m = re.match(r"^(LD|OPP|QT|CT|SK|TK)(\d{8})-(\d{4,6})$", str(no or ""))
    if not m:
        return None
    kind = [k for k, v in DOC_PREFIX.items() if v == m.group(1)]
    if not kind:
        return None
    return kind[0], m.group(2), int(m.group(3))


# ---------------------------------------------------------------- 阶段状态机
STAGES = [
    ("初步接触", 0.10),
    ("需求确认", 0.25),
    ("方案报价", 0.50),
    ("商务谈判", 0.75),
    ("赢单", 1.00),
    ("输单", 0.00),
]
STAGE_PROB = dict(STAGES)
STAGE_ORDER = [s for s, _ in STAGES]
OPEN_STAGES = ["初步接触", "需求确认", "方案报价", "商务谈判"]

# 进入该阶段时必须已具备的材料（前端提示 + 后端硬校验）
STAGE_GATE = {
    "需求确认": [("decision_maker", "决策人")],
    "方案报价": [("amount", "商机金额")],
    "商务谈判": [("decision_maker", "决策人"), ("competitor", "竞品情况")],
    "赢单": [("contract", "已签署合同")],
}


def stage_index(stage):
    return STAGE_ORDER.index(stage) if stage in STAGE_ORDER else -1


def can_move_stage(cur, nxt):
    """阶段流转白名单：

    - 进行中阶段只能前进（可跨级），或直接判输单；
    - 赢单必须从「商务谈判」进入（避免跳级虚报业绩）；
    - 输单可从任意进行中阶段进入；
    - 已结单（赢单/输单）不可再改，需走「重开」另行建单。
    """
    if cur not in STAGE_ORDER or nxt not in STAGE_ORDER:
        return False, "阶段不存在"
    if cur in ("赢单", "输单"):
        return False, "商机已结单，不能再变更阶段"
    if nxt == cur:
        return False, "阶段未变化"
    ci, ni = stage_index(cur), stage_index(nxt)
    if nxt == "输单":
        return True, ""
    if nxt == "赢单":
        if cur != "商务谈判":
            return False, "赢单必须从「商务谈判」关闭，当前为「%s」" % cur
        return True, ""
    if ni <= ci:
        return False, "阶段不能回退（%s → %s）" % (cur, nxt)
    return True, ""


def stage_gate(stage, opp, has_contract=False):
    """返回缺失项说明列表；空列表表示满足进入条件。"""
    miss = []
    for field, label in STAGE_GATE.get(stage, []):
        if field == "contract":
            if not has_contract:
                miss.append(label)
        elif field == "amount":
            if float(opp.get("amount") or 0) <= 0:
                miss.append(label)
        else:
            if not str(opp.get(field) or "").strip():
                miss.append(label)
    return miss


def opp_status(stage):
    return "赢单" if stage == "赢单" else ("输单" if stage == "输单" else "进行中")


# ---------------------------------------------------------------- 线索查重
def _nfkc(text):
    return unicodedata.normalize("NFKC", str(text or "")).strip()


def norm_phone(phone):
    """手机号归一：去空格/横线/括号，去 +86 / 0086 前缀。"""
    s = re.sub(r"[^\d]", "", _nfkc(phone))
    if s.startswith("0086"):
        s = s[4:]
    elif s.startswith("86") and len(s) == 13:
        s = s[2:]
    return s


def norm_company(name):
    """公司名归一：全角转半角、去空白与标点、去常见后缀与地域前缀。"""
    s = _nfkc(name).lower()
    s = re.sub(r"[\s\-_·,，.。()（）\[\]【】]", "", s)
    for suf in ("股份有限公司", "有限责任公司", "有限公司", "集团", "公司", "co.,ltd", "coltd", "ltd"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    for pre in ("苏州", "上海", "北京", "深圳", "杭州", "南京", "广州", "无锡", "宁波", "合肥", "武汉", "成都"):
        if s.startswith(pre) and len(s) > len(pre) + 1:
            s = s[len(pre):]
    return s


def similarity(a, b):
    """归一化后的相似度（0~1），用「公共子序列/较长者」的近似口径，纯 Python。"""
    x, y = norm_company(a), norm_company(b)
    if not x or not y:
        return 0.0
    if x == y:
        return 1.0
    short, long = (x, y) if len(x) <= len(y) else (y, x)
    if short in long:
        return r4(len(short) / len(long))
    # 最长公共子串
    best = 0
    prev = [0] * (len(short) + 1)
    for i in range(1, len(long) + 1):
        cur = [0] * (len(short) + 1)
        for j in range(1, len(short) + 1):
            if long[i - 1] == short[j - 1]:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return r4(best / len(long))


def name_affinity(a, b, threshold=0.62):
    """公司名是否「像同一家」：相似度达标，且共有前缀 ≥2 字或一方完整包含另一方。

    仅靠最长公共子串会把「无效测试公司9597611」与「公海测试公司9597613」判成同一家
    （公共片段全部落在「测试公司+编号」上），加一道前缀/包含闸口可显著降低误报。
    """
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


def dup_candidates(lead, leads, customers, threshold=0.62):
    """线索查重：手机号命中即强重复；公司名相似度 ≥ 阈值 或邮箱相同为疑似。

    返回 [{objType, no, name, reason, score}]，score 越大越像。
    """
    phone = norm_phone(lead.get("phone"))
    email = _nfkc(lead.get("email")).lower()
    name = lead.get("name") or ""
    out = []
    for src, objs in (("lead", leads or []), ("customer", customers or [])):
        for o in objs:
            if str(o.get("no") or o.get("code")) == str(lead.get("no") or lead.get("code") or ""):
                continue
            reasons = []
            score = 0.0
            if phone and norm_phone(o.get("phone")) == phone:
                reasons.append("手机号相同")
                score = max(score, 1.0)
            omail = _nfkc(o.get("email")).lower()
            if email and omail and email == omail:
                reasons.append("邮箱相同")
                score = max(score, 0.95)
            sim = name_affinity(name, o.get("name"), threshold)
            if sim >= threshold:
                reasons.append("名称相似 %.0f%%" % (sim * 100))
                score = max(score, sim)
            if reasons:
                out.append({"objType": src, "no": o.get("no") or o.get("code"),
                            "name": o.get("name"), "owner": o.get("owner") or "",
                            "reason": "；".join(reasons), "score": r4(score)})
    out.sort(key=lambda x: -x["score"])
    return out[:5]


LEAD_GRADE_RULE = {"A": 500000, "B": 150000}  # 预算分档


def grade_of(budget, source=None):
    """线索分级：预算 ≥50 万 A，≥15 万 B，其余 C；展会/老客推荐上浮一档。"""
    b = float(budget or 0)
    g = "A" if b >= LEAD_GRADE_RULE["A"] else ("B" if b >= LEAD_GRADE_RULE["B"] else "C")
    if source in ("展会", "老客推荐") and g != "A":
        g = "A" if g == "B" else "B"
    return g


# ---------------------------------------------------------------- 客户评分
def score_customer(days_since_follow=None, paid_total=0, open_opps=0, avg_satisfaction=0.0,
                   overdue_plans=0):
    """客户健康分 0~100：

    跟进新鲜度 30（≤7 天满分，>90 天 0，线性衰减）
    累计回款   40（30 万封顶，按对数缩放，避免大客户一家独大）
    商机活跃   20（3 个在谈商机封顶）
    服务满意度 10（5 分制）
    逾期扣分   -8 / 笔（最多 -24）
    """
    d = 999 if days_since_follow is None else max(0, int(days_since_follow))
    if d <= 7:
        recency = 30.0
    elif d >= 90:
        recency = 0.0
    else:
        recency = 30.0 * (1 - (d - 7) / 83.0)
    paid = 40.0 * min(1.0, math.log10(1 + max(0.0, float(paid_total))) / math.log10(1 + 300000))
    opps = 20.0 * min(1.0, max(0, int(open_opps)) / 3.0)
    sat = 10.0 * (min(5.0, max(0.0, float(avg_satisfaction))) / 5.0)
    pen = min(24.0, 8.0 * max(0, int(overdue_plans)))
    return r2(max(0.0, min(100.0, recency + paid + opps + sat - pen)))


def score_level(score):
    s = float(score or 0)
    if s >= 80:
        return "优质"
    if s >= 60:
        return "健康"
    if s >= 40:
        return "待经营"
    return "流失风险"


# ---------------------------------------------------------------- 漏斗与预测
def weighted(amount, probability):
    return r2(float(amount or 0) * float(probability or 0))


def funnel(opps):
    """按阶段汇总（只统计进行中 + 赢单，输单单列）。"""
    out = []
    total_open = sum(float(o.get("amount") or 0) for o in opps if o.get("status") == "进行中")
    for stage in OPEN_STAGES:
        rows = [o for o in opps if o.get("stage") == stage]
        amt = r2(sum(float(o.get("amount") or 0) for o in rows))
        out.append({"stage": stage, "count": len(rows), "amount": amt,
                    "prob": STAGE_PROB[stage], "weighted": weighted(amt, STAGE_PROB[stage]),
                    "share": ratio(amt, total_open)})
    won = [o for o in opps if o.get("stage") == "赢单"]
    lost = [o for o in opps if o.get("stage") == "输单"]
    closed = len(won) + len(lost)
    return {
        "stages": out,
        "openCount": sum(x["count"] for x in out),
        "openAmount": total_open,
        "wonCount": len(won),
        "wonAmount": r2(sum(float(o.get("amount") or 0) for o in won)),
        "lostCount": len(lost),
        "lostAmount": r2(sum(float(o.get("amount") or 0) for o in lost)),
        "winRate": ratio(len(won), closed),
        "avgDeal": ratio(sum(float(o.get("amount") or 0) for o in won), len(won)),
    }


def conversion(stages):
    """相邻阶段转化率（上一阶段量 → 下一阶段量）。"""
    out = []
    for i in range(1, len(stages)):
        prev, cur = stages[i - 1], stages[i]
        out.append({"from": prev["stage"], "to": cur["stage"],
                    "rate": ratio(cur["count"], prev["count"]) if prev["count"] else 0.0})
    return out


def forecast(opps, months, today=None):
    """按预计结单月汇总：加权（概率）/ 乐观（全额）/ 悲观（×0.7）。"""
    today = today or date.today()
    out = []
    for m in months:
        rows = [o for o in opps if o.get("status") in ("进行中", None, "")
                and str(o.get("expect_close_date") or "")[:7] == m]
        amt = r2(sum(float(o.get("amount") or 0) for o in rows))
        w = r2(sum(weighted(o.get("amount"), o.get("probability") or STAGE_PROB.get(o.get("stage"), 0))
                   for o in rows))
        out.append({"month": m, "count": len(rows), "amount": amt,
                    "weighted": w, "optimistic": amt, "pessimistic": r2(amt * 0.7)})
    return out


def month_list(start, n):
    """从 start（YYYY-MM 或 date）起连续 n 个月。"""
    if isinstance(start, str):
        y, m = int(start[:4]), int(start[5:7])
    else:
        y, m = start.year, start.month
    out = []
    for _ in range(n):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def sum_by(rows, key, val):
    out = {}
    for r in rows:
        k = r.get(key)
        out[k] = r2(out.get(k, 0) + float(r.get(val) or 0))
    return out


# ---------------------------------------------------------------- 报价
def quote_discount(list_amount, amount):
    """折扣率 = 1 - 成交/标准价；标准价为 0 时返回 0。"""
    la = float(list_amount or 0)
    if la <= 0:
        return 0.0
    return r4(max(0.0, 1 - float(amount or 0) / la))


def need_discount_approval(rate, threshold=0.15):
    return float(rate or 0) > float(threshold or 0)


def quote_amount(lines):
    """按行计算标准额 / 成交额。"""
    list_amt = 0.0
    amt = 0.0
    for ln in lines or []:
        qty = float(ln.get("qty") or 0)
        lp = float(ln.get("listPrice", ln.get("list_price")) or 0)
        pr = float(ln.get("price") or 0)
        list_amt += qty * lp
        amt += qty * pr
    return {"listAmount": r2(list_amt), "amount": r2(amt),
            "discountRate": quote_discount(list_amt, amt)}


# ---------------------------------------------------------------- 回款计划
def build_plans(amount, start_date, terms="3-4-3", n=None):
    """按付款条件生成等间隔分期计划。

    terms 形如 "3-4-3"（比例，和应为 10）或 "5-5"；也接受 "100"。
    日期按「签约日 + 30 天 × 期序」推进，末期对齐 90 天。
    """
    amount = r2(amount)
    s = str(terms or "3-4-3").replace(" ", "")
    parts = [p for p in re.split(r"[-/]", s) if p]
    try:
        weights = [float(p) for p in parts]
    except ValueError:
        weights = [10]
    if n:
        weights = [10.0 / int(n)] * int(n)
    if not weights or sum(weights) <= 0:
        weights = [10]
    total_w = sum(weights)
    d0 = start_date if isinstance(start_date, date) else datetime.strptime(
        str(start_date)[:10], "%Y-%m-%d").date()
    out = []
    acc = 0.0
    for i, w in enumerate(weights):
        amt = r2(amount * w / total_w) if i < len(weights) - 1 else r2(amount - acc)
        acc = r2(acc + amt)
        out.append({"seq": i + 1, "dueDate": (d0 + timedelta(days=30 * (i + 1))).isoformat(),
                    "amount": amt, "paidAmount": 0.0, "status": "未收"})
    return out


def plan_status(amount, paid, due_date, today=None):
    today = today or date.today()
    amt, pd = r2(amount), r2(paid)
    if pd >= amt - 0.005:
        return "已收"
    due = due_date if isinstance(due_date, date) else datetime.strptime(str(due_date)[:10], "%Y-%m-%d").date()
    if pd > 0:
        return "部分收款" if due >= today else "部分逾期"
    return "未收" if due >= today else "逾期"


def overdue_days(due_date, today=None):
    today = today or date.today()
    due = due_date if isinstance(due_date, date) else datetime.strptime(str(due_date)[:10], "%Y-%m-%d").date()
    return max(0, (today - due).days)


def aging_buckets(plans, today=None):
    """账龄分档：未到期 / 1-30 / 31-60 / 61-90 / 90+。"""
    today = today or date.today()
    buckets = [("未到期", 0, 0), ("1-30 天", 1, 30), ("31-60 天", 31, 60),
               ("61-90 天", 61, 90), ("90 天以上", 91, 10 ** 6)]
    out = {b[0]: 0.0 for b in buckets}
    for p in plans:
        left = r2(float(p.get("amount") or 0) - float(p.get("paidAmount", p.get("paid_amount")) or 0))
        if left <= 0:
            continue
        days = overdue_days(p.get("dueDate", p.get("due_date")), today)
        key = "未到期"
        for name, lo, hi in buckets[1:]:
            if lo <= days <= hi:
                key = name
        out[key] = r2(out[key] + left)
    return out


# ---------------------------------------------------------------- 服务 SLA
SLA_HOURS = {"P1": 4, "P2": 8, "P3": 24}


def sla_dues(created_at, priority="P2", hours=None):
    """响应时限 = 受理时限（同 SLA 小时数的一半，最少 1 小时），解决时限 = SLA 小时数。"""
    if isinstance(created_at, str):
        base = datetime.strptime(str(created_at)[:19], "%Y-%m-%d %H:%M:%S")
    else:
        base = created_at
    h = float(hours if hours is not None else SLA_HOURS.get(priority, 8))
    resp = base + timedelta(hours=max(1.0, h / 2.0))
    res = base + timedelta(hours=h)
    return resp.strftime("%Y-%m-%d %H:%M:%S"), res.strftime("%Y-%m-%d %H:%M:%S")


def sla_state(resolve_due, now=None, resolved_at=None, warn_hours=2.0):
    """正常 / 临期（剩余不足 warn_hours，默认 2 小时）/ 超时 / 已完成。"""
    if resolved_at:
        return "已完成"
    fmt = "%Y-%m-%d %H:%M:%S"
    now = now or datetime.now()
    if isinstance(now, str):
        now = datetime.strptime(str(now)[:19], fmt)
    due = datetime.strptime(str(resolve_due)[:19], fmt)
    left = (due - now).total_seconds() / 3600.0
    if left < 0:
        return "超时"
    if left <= float(warn_hours):
        return "临期"
    return "正常"


def sla_left_hours(resolve_due, now=None):
    fmt = "%Y-%m-%d %H:%M:%S"
    now = now or datetime.now()
    if isinstance(now, str):
        now = datetime.strptime(str(now)[:19], fmt)
    due = datetime.strptime(str(resolve_due)[:19], fmt)
    return r2((due - now).total_seconds() / 3600.0)


# ---------------------------------------------------------------- 市场 ROI
def campaign_roi(cost, won_amount, leads_count=0):
    cost = float(cost or 0)
    won = float(won_amount or 0)
    return {"cost": r2(cost), "revenue": r2(won), "roi": r4((won - cost) / cost) if cost else 0.0,
            "cpl": r2(cost / leads_count) if leads_count else 0.0,
            "leads": int(leads_count or 0)}


# ---------------------------------------------------------------- 集成
def sign_payload(secret, timestamp, body):
    """Webhook 签名：HMAC-SHA256(secret, timestamp + "." + body) 的十六进制小写。"""
    msg = ("%s.%s" % (timestamp, body)).encode("utf-8")
    return hmac.new(str(secret or "").encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_signature(secret, timestamp, body, signature):
    return hmac.compare_digest(sign_payload(secret, timestamp, body), str(signature or ""))


def paginate(items, page=1, size=20):
    page = max(1, int(page or 1))
    size = min(200, max(1, int(size or 20)))
    total = len(items)
    start = (page - 1) * size
    return {"list": items[start:start + size], "total": total, "page": page, "pageSize": size,
            "pages": int(math.ceil(total / float(size))) if total else 0}


def parse_time(text):
    s = str(text or "").strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    return None


def days_between(a, b):
    """b - a 的天数；任一为空返回 None。"""
    da, db = parse_time(a), parse_time(b)
    if not da or not db:
        return None
    return (db.date() - da.date()).days

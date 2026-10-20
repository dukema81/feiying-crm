# -*- coding: utf-8 -*-
"""飞鹰 CRM · REST 服务（标准库 http.server + sqlite3，零第三方依赖）

约定
- 成功 {"ok": true, "data": ...}；失败 {"error": "中文原因"}（可附带 dups 等提示字段）
- 鉴权两种：用户会话 Token（网页）与 API Key（系统对接，前缀 fyk_）
- 并发：SQLite 单写者，所有 /api/ 请求整段串行化（RLock）
- 集成：每次业务变更写 change_log（增量同步）+ 生成 Webhook 投递任务（后台线程重试）
"""
import csv
import functools
import hmac
import http.client
import io
import json
import os
import re
import secrets
import threading
import time
import traceback
import uuid
from datetime import date, datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

import crm
import db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE_DIR)
FRONTEND = os.path.join(ROOT, "frontend")
PORT = int(os.environ.get("FEIYING_PORT") or os.environ.get("PORT") or "8018")
HOST = os.environ.get("FEIYING_HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
LOCK = threading.RLock()
VERSION = "1.0.0"
START_TS = time.time()      # 进程启动时刻：健康检查里暴露 uptime，便于判断实例是否被反复重启

OPEN_PATHS = {("POST", "/api/auth/login"), ("GET", "/api/health"), ("GET", "/api/openapi.json")}
_RATE = {}
RATE_LIMIT = 240          # 每个 API Key 每分钟请求数
WEBHOOK_MAX_TRY = 3


class ApiError(Exception):
    def __init__(self, message, code=400, **extra):
        super().__init__(message)
        self.message = message
        self.code = code
        self.extra = extra


def today():
    return date.today().isoformat()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def rows(cn, sql, args=()):
    return db.rows(cn, sql, args)


def one(cn, sql, args=()):
    return db.one(cn, sql, args)


def with_db(fn):
    @functools.wraps(fn)
    def wrapper(cn, *a, **kw):
        out = fn(cn, *a, **kw)
        cn.commit()
        return out
    return wrapper


def write_op(fn):
    @functools.wraps(fn)
    def wrapper(cn, *a, **kw):
        with LOCK:
            return with_db(fn)(cn, *a, **kw)
    return wrapper


def op(cn, username, action, detail=""):
    db.log_action(cn, username, action, detail)


def rule_value(cn, code, default=None):
    r = one(cn, "SELECT * FROM rules WHERE code=?", (code,))
    if not r or not r["enabled"]:
        return default
    return r["value"]


def require(user, perm):
    if not crm.can(user["role"], perm):
        raise ApiError("当前角色（%s）无权执行该操作" % crm.ROLE_LABEL.get(user["role"], user["role"]), 403)


def need_admin(user):
    if user["role"] != "admin":
        raise ApiError("仅系统管理员可操作集成配置", 403)


def scope_of(user):
    """数据范围：销售只能看自己的客户/商机/合同；其余角色全域读。"""
    if user["role"] == "sales":
        return user["username"]
    return None


# ---------------------------------------------------------------- 鉴权
def auth_user(cn, token):
    if not token:
        return None
    if token.startswith("fyk_"):
        h = db.sha256(token)
        k = one(cn, "SELECT * FROM api_keys WHERE key_hash=? AND status='启用'", (h,))
        if not k:
            return None
        if k["expires_at"] and k["expires_at"][:10] < today():
            return None
        cn.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (now(), k["id"]))
        cn.commit()
        return {"username": k["owner"] or "api", "displayName": k["name"],
                "role": "admin" if k["scope"] == "write" else "sales",
                "roleLabel": "API Key（%s）" % ("读写" if k["scope"] == "write" else "只读"),
                "authType": "apikey", "keyId": k["id"], "scope": k["scope"]}
    s = one(cn, "SELECT * FROM sessions WHERE token=?", (token,))
    if not s:
        return None
    u = one(cn, "SELECT * FROM users WHERE username=?", (s["username"],))
    if not u:
        return None
    return {"username": u["username"], "displayName": u["display_name"], "role": u["role"],
            "roleLabel": crm.ROLE_LABEL.get(u["role"], u["role"]), "authType": "session"}


def rate_check(user):
    if user.get("authType") != "apikey":
        return
    kid = str(user.get("keyId"))
    win = int(time.time() // 60)
    slot = _RATE.get(kid)
    if not slot or slot[0] != win:
        _RATE[kid] = [win, 1]
        return
    slot[1] += 1
    if slot[1] > RATE_LIMIT:
        raise ApiError("超出调用配额（%d 次/分钟），请稍后重试" % RATE_LIMIT, 429)


# ---------------------------------------------------------------- 变更与事件
def emit(cn, event, obj_type, obj_no, payload, actor):
    """写变更日志（增量同步）并为订阅该事件的 Webhook 生成投递任务。"""
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    cn.execute("INSERT INTO change_log(obj_type,obj_no,op,actor,payload,changed_at) VALUES(?,?,?,?,?,?)",
               (obj_type, obj_no, "upsert", actor, body, now()))
    hooks = rows(cn, "SELECT * FROM webhooks WHERE status='启用'")
    for h in hooks:
        evs = [x.strip() for x in str(h["events"] or "*").split(",") if x.strip()]
        if "*" not in evs and event not in evs:
            continue
        sig = crm.sign_payload(h["secret"], str(int(time.time())),
                               json.dumps({"event": event, "data": payload}, ensure_ascii=False,
                                          sort_keys=True))
        cn.execute("INSERT INTO webhook_deliveries(webhook_id,event,payload,signature,status,"
                   "attempts,http_code,error,next_at,created_at,delivered_at)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (h["id"], event, body, sig, "待投递", 0, 0, "", now(), now(), ""))


def next_no(cn, kind, prefix_table, column="no"):
    """按「前缀+日期+当日流水」生成业务单号（事务内 MAX 递增，串行化保证不重号）。"""
    head = crm.doc_no(kind, today(), 0).rsplit("-", 1)[0] + "-"   # LD20261020-
    r = one(cn, "SELECT MAX(%s) m FROM %s WHERE %s LIKE ?" % (column, prefix_table, column),
            (head + "%",))
    seq = 0
    if r and r["m"]:
        tail = str(r["m"])[len(head):]
        digits = "".join(ch for ch in tail if ch.isdigit())
        seq = int(digits) if digits else 0
    return crm.doc_no(kind, today(), seq + 1)


def _hours_since(text):
    t = crm.parse_time(text)
    if not t:
        return 0.0
    return round(max(0.0, (datetime.now() - t).total_seconds() / 3600.0), 2)


def user_name(cn, username):
    if not username:
        return ""
    u = one(cn, "SELECT display_name FROM users WHERE username=?", (username,))
    return u["display_name"] if u else username


def map_names(cn):
    return {r["username"]: r["display_name"] for r in rows(cn, "SELECT username,display_name FROM users")}


# ---------------------------------------------------------------- 视图
def lead_view(r, names=None):
    names = names or {}
    status = r["status"]
    return {
        "no": r["no"], "name": r["name"], "contact": r["contact"], "phone": r["phone"],
        "email": r["email"], "source": r["source"], "industry": r["industry"], "region": r["region"],
        "budget": crm.r2(r["budget"]), "demand": r["demand"], "grade": r["grade"], "status": status,
        "owner": r["owner"], "ownerName": names.get(r["owner"], r["owner"] or ""),
        "creator": r["creator"], "campaignCode": r["campaign_code"],
        "convertedCustomer": r["converted_customer"], "invalidReason": r["invalid_reason"],
        "createdAt": r["created_at"], "assignedAt": r["assigned_at"],
        "lastFollowAt": r["last_follow_at"], "nextFollowAt": r["next_follow_at"],
        "ageDays": crm.days_between(r["created_at"], now()) or 0,
        "idleDays": crm.days_between(r["last_follow_at"], now()) if r["last_follow_at"] else None,
    }


def customer_view(r, names=None):
    names = names or {}
    return {
        "code": r["code"], "name": r["name"], "shortName": r["short_name"], "industry": r["industry"],
        "scale": r["scale"], "region": r["region"], "level": r["level"], "source": r["source"],
        "owner": r["owner"], "ownerName": names.get(r["owner"], r["owner"] or ""),
        "phone": r["phone"], "website": r["website"], "address": r["address"],
        "creditLimit": crm.r2(r["credit_limit"]), "status": r["status"],
        "score": crm.r2(r["score"]), "scoreLevel": crm.score_level(r["score"]),
        "campaignCode": r["campaign_code"], "createdAt": r["created_at"],
        "updatedAt": r["updated_at"], "lastFollowAt": r["last_follow_at"],
        "idleDays": crm.days_between(r["last_follow_at"], now()) if r["last_follow_at"] else None,
    }


def opp_view(r, names=None, has_contract=False):
    names = names or {}
    return {
        "no": r["no"], "name": r["name"], "customerCode": r["customer_code"],
        "customerName": r["customer_name"], "amount": crm.r2(r["amount"]), "stage": r["stage"],
        "stageIndex": crm.stage_index(r["stage"]), "probability": crm.r4(r["probability"]),
        "weighted": crm.weighted(r["amount"], r["probability"]),
        "expectCloseDate": r["expect_close_date"], "owner": r["owner"],
        "ownerName": names.get(r["owner"], r["owner"] or ""), "source": r["source"],
        "campaignCode": r["campaign_code"], "competitor": r["competitor"],
        "decisionMaker": r["decision_maker"], "status": r["status"],
        "winReason": r["win_reason"], "loseReason": r["lose_reason"],
        "nextAction": r["next_action"], "createdAt": r["created_at"], "updatedAt": r["updated_at"],
        "closedAt": r["closed_at"], "lastActivityAt": r["last_activity_at"],
        "daysToClose": crm.days_between(now(), r["expect_close_date"] or ""),
        "overdue": bool(r["expect_close_date"] and r["expect_close_date"][:10] < today()
                        and r["status"] == "进行中"),
        "hasContract": has_contract,
        "canAdvance": [s for s in crm.STAGE_ORDER
                       if crm.can_move_stage(r["stage"], s)[0]],
    }


def quote_view(r, names=None, threshold=0.15):
    names = names or {}
    return {
        "no": r["no"], "oppNo": r["opp_no"], "customerCode": r["customer_code"],
        "customerName": r["customer_name"], "title": r["title"], "amount": crm.r2(r["amount"]),
        "listAmount": crm.r2(r["list_amount"]), "discountRate": crm.r4(r["discount_rate"]),
        "discountPct": round(crm.r4(r["discount_rate"]) * 100, 2), "status": r["status"],
        "validUntil": r["valid_until"], "owner": r["owner"],
        "ownerName": names.get(r["owner"], r["owner"] or ""), "approver": r["approver"],
        "approverName": names.get(r["approver"], r["approver"] or ""), "approvedAt": r["approved_at"],
        "rejectReason": r["reject_reason"], "remark": r["remark"], "createdAt": r["created_at"],
        "needApproval": crm.need_discount_approval(r["discount_rate"], threshold),
    }


def contract_view(r, names=None, plans=None):
    names = names or {}
    plans = plans if plans is not None else []
    total = crm.r2(r["amount"])
    paid = crm.r2(sum(float(p["paid_amount"] or 0) for p in plans))
    overdue = crm.r2(sum(float(p["amount"] or 0) - float(p["paid_amount"] or 0)
                         for p in plans if "逾期" in str(p["status"])))
    return {
        "no": r["no"], "customerCode": r["customer_code"], "customerName": r["customer_name"],
        "quoteNo": r["quote_no"], "oppNo": r["opp_no"], "title": r["title"],
        "amount": total, "signDate": r["sign_date"], "startDate": r["start_date"],
        "endDate": r["end_date"], "paymentTerms": r["payment_terms"], "status": r["status"],
        "owner": r["owner"], "ownerName": names.get(r["owner"], r["owner"] or ""),
        "signedAt": r["signed_at"], "terminatedAt": r["terminated_at"], "remark": r["remark"],
        "createdAt": r["created_at"], "paidAmount": paid,
        "unpaidAmount": crm.r2(total - paid), "overdueAmount": overdue,
        "progress": crm.ratio(paid, total), "planCount": len(plans),
        "paidCount": len([p for p in plans if p["status"] == "已收"]),
    }


def ticket_view(r, names=None):
    names = names or {}
    left = crm.sla_left_hours(r["resolve_due"], now()) if r["resolve_due"] else 0.0
    state = r["sla_state"]
    if r["status"] in ("已解决", "已关闭"):
        state = "已完成"
    elif r["resolve_due"]:
        state = crm.sla_state(r["resolve_due"], now())
    return {
        "no": r["no"], "customerCode": r["customer_code"], "customerName": r["customer_name"],
        "contractNo": r["contract_no"], "title": r["title"], "category": r["category"],
        "priority": r["priority"], "status": r["status"], "owner": r["owner"],
        "ownerName": names.get(r["owner"], r["owner"] or ""), "creator": r["creator"],
        "description": r["description"], "createdAt": r["created_at"],
        "acceptedAt": r["accepted_at"], "resolvedAt": r["resolved_at"], "closedAt": r["closed_at"],
        "responseDue": r["response_due"], "resolveDue": r["resolve_due"], "slaState": state,
        "slaLeftHours": left, "satisfaction": r["satisfaction"], "resolution": r["resolution"],
        "ageHours": _hours_since(r["created_at"]),
    }


# ---------------------------------------------------------------- 认证
@write_op
def api_login(cn, body):
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    u = one(cn, "SELECT * FROM users WHERE username=?", (username,))
    if not u or u["password"] != db.sha256(password):
        raise ApiError("用户名或密码错误", 401)
    if u["status"] != "在职":
        raise ApiError("账号已停用，请联系管理员", 403)
    token = uuid.uuid4().hex
    cn.execute("INSERT INTO sessions(token,username) VALUES(?,?)", (token, username))
    op(cn, username, "登录", "")
    return {"token": token, "username": username, "displayName": u["display_name"],
            "role": u["role"], "roleLabel": crm.ROLE_LABEL.get(u["role"], u["role"])}


@write_op
def api_logout(cn, token):
    if token:
        cn.execute("DELETE FROM sessions WHERE token=?", (token,))
    return {"loggedOut": True}


@with_db
def api_me(cn, user):
    return {"username": user["username"], "displayName": user["displayName"],
            "role": user["role"], "roleLabel": user["roleLabel"],
            "authType": user.get("authType"), "perms": sorted(crm.ROLE_PERM.get(user["role"], set()))}


# ---------------------------------------------------------------- 首屏
@with_db
def api_bootstrap(cn, user):
    names = map_names(cn)
    sc = scope_of(user)
    opps = rows(cn, "SELECT * FROM opportunities")
    if sc:
        opps = [o for o in opps if o["owner"] == sc]
    f = crm.funnel(opps)
    won = [o for o in opps if o["stage"] == "赢单"]
    month = today()[:7]
    won_month = [o for o in won if str(o["closed_at"] or "")[:7] == month]
    plans = rows(cn, "SELECT * FROM contract_plans")
    overdue = [p for p in plans if "逾期" in str(p["status"])]
    tickets = rows(cn, "SELECT * FROM tickets")
    open_tickets = [t for t in tickets if t["status"] in ("待受理", "处理中", "待确认")]
    stale = [t for t in open_tickets if crm.sla_state(t["resolve_due"], now()) == "超时"]
    leads = rows(cn, "SELECT * FROM leads")
    my_leads = [l for l in leads if l["status"] == "待分配" or (sc and l["owner"] == sc)]
    if not sc:
        my_leads = [l for l in leads if l["status"] in ("待分配", "公海")] or leads
    months = crm.month_list(date.today() - timedelta(days=150), 6)
    trend = []
    for m in months:
        s = [o for o in won if str(o["closed_at"] or "")[:7] == m]
        trend.append({"month": m, "amount": crm.r2(sum(float(o["amount"]) for o in s)),
                      "count": len(s)})
    kpi = {
        "openAmount": f["openAmount"], "openCount": f["openCount"],
        "weighted": crm.r2(sum(x["weighted"] for x in f["stages"])),
        "wonAmount": f["wonAmount"], "wonCount": f["wonCount"],
        "monthWonAmount": crm.r2(sum(float(o["amount"]) for o in won_month)),
        "monthWonCount": len(won_month),
        "winRate": f["winRate"], "avgDeal": f["avgDeal"],
        "customerCount": len(rows(cn, "SELECT code FROM customers")),
        "leadCount": len([l for l in leads if l["status"] in ("待分配", "跟进中")]),
        "overdueAmount": crm.r2(sum(float(p["amount"]) - float(p["paid_amount"]) for p in overdue)),
        "overdueCount": len(overdue),
        "ticketOpen": len(open_tickets), "ticketOverdue": len(stale),
        "paidTotal": crm.r2(sum(float(p["paid_amount"]) for p in plans)),
        "contractAmount": crm.r2(sum(float(c["amount"]) for c in rows(cn, "SELECT amount FROM contracts")
                                     if c["amount"])),
    }
    top = rows(cn, "SELECT customer_name, SUM(amount) s FROM contracts GROUP BY customer_code "
                   "ORDER BY s DESC LIMIT 5")
    return {
        "user": {"username": user["username"], "displayName": user["displayName"],
                 "role": user["role"], "roleLabel": user["roleLabel"]},
        "today": today(), "kpi": kpi, "funnel": f, "trend": trend,
        "myLeads": [lead_view(l, names) for l in my_leads[:8]],
        "myOpps": [opp_view(o, names) for o in opps if o["status"] == "进行中"][:8],
        "topCustomers": [{"name": r["customer_name"], "amount": crm.r2(r["s"])} for r in top],
        "todos": _todos(cn, user, names),
        "rules": rows(cn, "SELECT code,name,value,unit,enabled,category FROM rules ORDER BY rowid"),
        "notices": _notices(cn),
    }


def _todos(cn, user, names):
    out = []
    sc = user["username"]
    for t in rows(cn, "SELECT * FROM tickets WHERE status IN ('待受理','处理中','待确认') ORDER BY created_at DESC LIMIT 5"):
        state = crm.sla_state(t["resolve_due"], now())
        if state in ("超时", "临期"):
            out.append({"kind": "工单", "no": t["no"], "title": t["title"],
                        "tag": "%s %s" % (t["priority"], state), "level": "red" if state == "超时" else "gold"})
    for p in rows(cn, "SELECT p.*, t.customer_name FROM contract_plans p "
                      "JOIN contracts t ON t.no=p.contract_no WHERE p.status LIKE '%逾期%' "
                      "ORDER BY p.due_date LIMIT 4"):
        out.append({"kind": "回款", "no": p["contract_no"], "title": "%s 逾期未收 %.0f 元"
                    % (p["customer_name"], float(p["amount"]) - float(p["paid_amount"])),
                    "tag": "逾期 %d 天" % crm.overdue_days(p["due_date"]), "level": "red"})
    for q in rows(cn, "SELECT * FROM quotes WHERE status='待审批' LIMIT 4"):
        out.append({"kind": "报价", "no": q["no"], "title": "%s 折扣 %.1f%% 待审批"
                    % (q["customer_name"], float(q["discount_rate"]) * 100),
                    "tag": "待审批", "level": "gold"})
    for o in rows(cn, "SELECT * FROM opportunities WHERE status='进行中' "
                      "AND expect_close_date < ? ORDER BY expect_close_date LIMIT 4", (today(),)):
        out.append({"kind": "商机", "no": o["no"], "title": "%s 预计结单已过期" % o["name"],
                    "tag": "延期", "level": "gold"})
    return out


def _notices(cn):
    out = []
    for l in rows(cn, "SELECT * FROM leads WHERE status='公海' ORDER BY created_at LIMIT 3"):
        out.append({"type": "公海线索", "text": "%s 已进公海，可领取" % l["name"], "no": l["no"]})
    ticket_over = one(cn, "SELECT COUNT(*) c FROM tickets WHERE status IN ('待受理','处理中') "
                          "AND resolve_due < ?", (now(),))["c"]
    if ticket_over:
        out.append({"type": "SLA", "text": "有 %d 张工单已超出解决时限" % ticket_over, "no": ""})
    return out


# ---------------------------------------------------------------- 线索
@with_db
def api_leads(cn, user, q):
    names = map_names(cn)
    sc = scope_of(user)
    status = (q.get("status") or ["全部"])[0]
    kw = (q.get("kw") or [""])[0].strip()
    source = (q.get("source") or ["全部"])[0]
    grade = (q.get("grade") or ["全部"])[0]
    owner = (q.get("owner") or [""])[0]
    sql = "SELECT * FROM leads WHERE 1=1"
    args = []
    if status and status != "全部":
        sql += " AND status=?"
        args.append(status)
    if source and source != "全部":
        sql += " AND source=?"
        args.append(source)
    if grade and grade != "全部":
        sql += " AND grade=?"
        args.append(grade)
    if owner:
        sql += " AND owner=?"
        args.append(owner)
    if kw:
        sql += " AND (name LIKE ? OR contact LIKE ? OR phone LIKE ?)"
        args += ["%" + kw + "%"] * 3
    sql += " ORDER BY created_at DESC"
    data = [lead_view(r, names) for r in rows(cn, sql, args)]
    if sc:
        data = [l for l in data if l["owner"] == sc or l["status"] in ("待分配", "公海")]
    stats = {}
    for r in rows(cn, "SELECT status, COUNT(*) c FROM leads GROUP BY status"):
        stats[r["status"]] = r["c"]
    p = crm.paginate(data, (q.get("page") or [1])[0], (q.get("pageSize") or [50])[0])
    p["stats"] = stats
    p["poolCount"] = stats.get("公海", 0)
    p["unassigned"] = stats.get("待分配", 0)
    return p


@with_db
def api_lead(cn, user, no):
    r = one(cn, "SELECT * FROM leads WHERE no=?", (no,))
    if not r:
        raise ApiError("线索不存在", 404)
    names = map_names(cn)
    v = lead_view(r, names)
    v["activities"] = [act_view(a, names) for a in rows(
        cn, "SELECT * FROM activities WHERE obj_type='lead' AND obj_no=? ORDER BY happen_at DESC", (no,))]
    v["poolLogs"] = rows(cn, "SELECT * FROM pool_logs WHERE lead_no=? ORDER BY id DESC", (no,))
    v["dups"] = crm.dup_candidates({"no": r["no"], "name": r["name"], "phone": r["phone"],
                                    "email": r["email"]},
                                   rows(cn, "SELECT * FROM leads"), rows(cn, "SELECT * FROM customers"))
    return v


@write_op
def api_lead_create(cn, user, body):
    require(user, "write")
    name = (body.get("name") or "").strip()
    phone = (body.get("phone") or "").strip()
    if not name:
        raise ApiError("线索名称（公司名）不能为空")
    if not phone and not (body.get("email") or "").strip():
        raise ApiError("手机号与邮箱至少填一个，否则无法查重与跟进")
    dups = crm.dup_candidates({"name": name, "phone": phone, "email": body.get("email")},
                              rows(cn, "SELECT * FROM leads"),
                              rows(cn, "SELECT * FROM customers"))
    if dups and rule_value(cn, "dup_check", 1) and not body.get("force"):
        raise ApiError("疑似重复：%s（%s）。确认要新建请加 force=true" %
                       (dups[0]["name"], dups[0]["reason"]), 409, dups=dups)
    no = next_no(cn, "lead", "leads")
    owner = (body.get("owner") or "").strip()
    status = "跟进中" if owner else "待分配"
    cn.execute(
        "INSERT INTO leads(no,name,contact,phone,email,source,industry,region,budget,demand,grade,status,"
        "owner,creator,campaign_code,converted_customer,invalid_reason,created_at,assigned_at,"
        "last_follow_at,next_follow_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (no, name, body.get("contact") or "", phone, body.get("email") or "",
         body.get("source") or "官网表单", body.get("industry") or "", body.get("region") or "",
         crm.r2(body.get("budget") or 0), body.get("demand") or "",
         crm.grade_of(body.get("budget"), body.get("source")), status, owner, user["username"],
         body.get("campaignCode") or "", "", "", now(), now() if owner else "", "", ""))
    if owner:
        cn.execute("INSERT INTO pool_logs(lead_no,action,from_owner,to_owner,reason,operator,created_at)"
                   " VALUES(?,?,?,?,?,?,?)", (no, "分配", "", owner, "建单时直接指定", user["username"], now()))
    op(cn, user["username"], "新建线索", "%s %s" % (no, name))
    emit(cn, "lead.created", "lead", no,
         {"no": no, "name": name, "phone": phone, "source": body.get("source") or "官网表单",
          "owner": owner, "grade": crm.grade_of(body.get("budget"), body.get("source"))},
         user["username"])
    return lead_view(one(cn, "SELECT * FROM leads WHERE no=?", (no,)), map_names(cn))


@write_op
def api_lead_update(cn, user, no, body):
    require(user, "write")
    r = one(cn, "SELECT * FROM leads WHERE no=?", (no,))
    if not r:
        raise ApiError("线索不存在", 404)
    if scope_of(user) and r["owner"] not in ("", user["username"]) and r["status"] != "公海":
        raise ApiError("只能维护自己名下的线索", 403)
    fields = {"contact": "contact", "phone": "phone", "email": "email", "source": "source",
              "industry": "industry", "region": "region", "demand": "demand", "grade": "grade"}
    sets, args = [], []
    for k, col in fields.items():
        if k in body:
            sets.append("%s=?" % col)
            args.append(body[k])
    if "budget" in body:
        sets.append("budget=?")
        args.append(crm.r2(body["budget"]))
        if "grade" not in body:
            sets.append("grade=?")
            args.append(crm.grade_of(body["budget"], body.get("source") or r["source"]))
    if body.get("nextFollowAt") is not None:
        sets.append("next_follow_at=?")
        args.append(body["nextFollowAt"])
    if not sets:
        raise ApiError("没有需要更新的字段")
    args.append(no)
    cn.execute("UPDATE leads SET %s WHERE no=?" % ",".join(sets), args)
    op(cn, user["username"], "更新线索", no)
    emit(cn, "lead.updated", "lead", no, {"no": no, "name": r["name"]}, user["username"])
    return lead_view(one(cn, "SELECT * FROM leads WHERE no=?", (no,)), map_names(cn))


@write_op
def api_lead_assign(cn, user, no, body):
    require(user, "write")
    if user["role"] not in ("admin", "sales_director"):
        raise ApiError("只有销售总监或管理员可以分配线索", 403)
    r = one(cn, "SELECT * FROM leads WHERE no=?", (no,))
    if not r:
        raise ApiError("线索不存在", 404)
    owner = (body.get("owner") or "").strip()
    if not one(cn, "SELECT username FROM users WHERE username=?", (owner,)):
        raise ApiError("负责人不存在：%s" % owner)
    cn.execute("UPDATE leads SET owner=?, status='跟进中', assigned_at=? WHERE no=?", (owner, now(), no))
    cn.execute("INSERT INTO pool_logs(lead_no,action,from_owner,to_owner,reason,operator,created_at)"
               " VALUES(?,?,?,?,?,?,?)",
               (no, "分配", r["owner"], owner, body.get("reason") or "手工分配", user["username"], now()))
    op(cn, user["username"], "分配线索", "%s → %s" % (no, owner))
    emit(cn, "lead.assigned", "lead", no, {"no": no, "owner": owner}, user["username"])
    return lead_view(one(cn, "SELECT * FROM leads WHERE no=?", (no,)), map_names(cn))


@write_op
def api_lead_convert(cn, user, no, body):
    require(user, "write")
    r = one(cn, "SELECT * FROM leads WHERE no=?", (no,))
    if not r:
        raise ApiError("线索不存在", 404)
    if r["status"] == "已转客户":
        raise ApiError("该线索已转客户：%s" % r["converted_customer"])
    if r["status"] == "无效":
        raise ApiError("已标记无效的线索不能转客户")
    code = (body.get("customerCode") or "").strip()
    if code:
        c = one(cn, "SELECT * FROM customers WHERE code=?", (code,))
        if not c:
            raise ApiError("客户不存在：%s" % code, 404)
    else:
        base = one(cn, "SELECT MAX(CAST(SUBSTR(code,3) AS INTEGER)) m FROM customers")["m"] or 0
        code = "C-%04d" % (int(base) + 1)
        cn.execute(
            "INSERT INTO customers(code,name,short_name,industry,scale,region,level,source,owner,phone,"
            "website,address,credit_limit,status,score,campaign_code,created_at,updated_at,last_follow_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (code, r["name"], r["name"][:6], r["industry"] or "制造业", "中型", r["region"] or "华东",
             "B", r["source"], r["owner"] or user["username"], r["phone"], "", "", 0, "活跃", 0,
             r["campaign_code"], now(), now(), now()))
        cn.execute("INSERT INTO contacts(customer_code,name,title,phone,email,wechat,is_primary,"
                   "remark,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (code, r["contact"] or "待补充", "联系人", r["phone"], r["email"], "", 1,
                    "由线索 %s 转入" % no, now()))
    cn.execute("UPDATE leads SET status='已转客户', converted_customer=? WHERE no=?", (code, no))
    cn.execute("INSERT INTO pool_logs(lead_no,action,from_owner,to_owner,reason,operator,created_at)"
               " VALUES(?,?,?,?,?,?,?)", (no, "转客户", r["owner"], r["owner"], code, user["username"], now()))
    op(cn, user["username"], "线索转客户", "%s → %s" % (no, code))
    emit(cn, "lead.converted", "lead", no, {"no": no, "customerCode": code}, user["username"])
    emit(cn, "customer.created", "customer", code, {"code": code, "name": r["name"]}, user["username"])
    return {"lead": lead_view(one(cn, "SELECT * FROM leads WHERE no=?", (no,)), map_names(cn)),
            "customerCode": code}


@write_op
def api_lead_invalid(cn, user, no, body):
    require(user, "write")
    r = one(cn, "SELECT * FROM leads WHERE no=?", (no,))
    if not r:
        raise ApiError("线索不存在", 404)
    reason = (body.get("reason") or "").strip()
    if not reason:
        raise ApiError("标记无效必须填写原因")
    cn.execute("UPDATE leads SET status='无效', invalid_reason=?, owner='' WHERE no=?", (reason, no))
    op(cn, user["username"], "线索置无效", "%s：%s" % (no, reason))
    emit(cn, "lead.invalid", "lead", no, {"no": no, "reason": reason}, user["username"])
    return lead_view(one(cn, "SELECT * FROM leads WHERE no=?", (no,)), map_names(cn))


@write_op
def api_lead_recycle(cn, user, no, body):
    require(user, "write")
    r = one(cn, "SELECT * FROM leads WHERE no=?", (no,))
    if not r:
        raise ApiError("线索不存在", 404)
    if r["status"] in ("已转客户", "无效"):
        raise ApiError("已转客户/无效线索不能回收")
    cn.execute("UPDATE leads SET status='公海', owner='' WHERE no=?", (no,))
    cn.execute("INSERT INTO pool_logs(lead_no,action,from_owner,to_owner,reason,operator,created_at)"
               " VALUES(?,?,?,?,?,?,?)", (no, "回收", r["owner"], "", body.get("reason") or "手工回收",
                                          user["username"], now()))
    op(cn, user["username"], "线索回收公海", no)
    emit(cn, "lead.recycled", "lead", no, {"no": no, "fromOwner": r["owner"]}, user["username"])
    return lead_view(one(cn, "SELECT * FROM leads WHERE no=?", (no,)), map_names(cn))


@write_op
def api_lead_claim(cn, user, no):
    require(user, "write")
    r = one(cn, "SELECT * FROM leads WHERE no=?", (no,))
    if not r:
        raise ApiError("线索不存在", 404)
    if r["status"] != "公海":
        raise ApiError("只有公海线索可以领取")
    cn.execute("UPDATE leads SET status='跟进中', owner=?, assigned_at=? WHERE no=?",
               (user["username"], now(), no))
    cn.execute("INSERT INTO pool_logs(lead_no,action,from_owner,to_owner,reason,operator,created_at)"
               " VALUES(?,?,?,?,?,?,?)", (no, "领取", "", user["username"], "从公海领取",
                                          user["username"], now()))
    op(cn, user["username"], "领取公海线索", no)
    emit(cn, "lead.claimed", "lead", no, {"no": no, "owner": user["username"]}, user["username"])
    return lead_view(one(cn, "SELECT * FROM leads WHERE no=?", (no,)), map_names(cn))


@with_db
def api_lead_check_dup(cn, user, q):
    name = (q.get("name") or [""])[0]
    phone = (q.get("phone") or [""])[0]
    email = (q.get("email") or [""])[0]
    return {"dups": crm.dup_candidates({"name": name, "phone": phone, "email": email},
                                       rows(cn, "SELECT * FROM leads"),
                                       rows(cn, "SELECT * FROM customers"))}


# ---------------------------------------------------------------- 客户
@with_db
def api_customers(cn, user, q):
    names = map_names(cn)
    sc = scope_of(user)
    kw = (q.get("kw") or [""])[0].strip()
    level = (q.get("level") or ["全部"])[0]
    status = (q.get("status") or ["全部"])[0]
    industry = (q.get("industry") or ["全部"])[0]
    sql = "SELECT * FROM customers WHERE 1=1"
    args = []
    if sc:
        sql += " AND owner=?"
        args.append(sc)
    if level != "全部":
        sql += " AND level=?"
        args.append(level)
    if status != "全部":
        sql += " AND status=?"
        args.append(status)
    if industry != "全部":
        sql += " AND industry=?"
        args.append(industry)
    if kw:
        sql += " AND (name LIKE ? OR code LIKE ? OR phone LIKE ?)"
        args += ["%" + kw + "%"] * 3
    sql += " ORDER BY score DESC, code"
    data = [customer_view(r, names) for r in rows(cn, sql, args)]
    # 附：在谈商机数、合同额、回款额（一次聚合，避免 N+1）
    agg = {r["customer_code"]: r for r in rows(
        cn, "SELECT customer_code, COUNT(*) c, SUM(amount) s FROM opportunities "
            "WHERE status='进行中' GROUP BY customer_code")}
    con = {r["customer_code"]: r for r in rows(
        cn, "SELECT customer_code, COUNT(*) c, SUM(amount) s FROM contracts GROUP BY customer_code")}
    pay = {r["customer_code"]: r for r in rows(
        cn, "SELECT customer_code, SUM(amount) s FROM payments GROUP BY customer_code")}
    tk = {r["customer_code"]: r for r in rows(
        cn, "SELECT customer_code, COUNT(*) c FROM tickets WHERE status IN ('待受理','处理中','待确认') "
            "GROUP BY customer_code")}
    for c in data:
        a = agg.get(c["code"]) or {}
        k = con.get(c["code"]) or {}
        p = pay.get(c["code"]) or {}
        t = tk.get(c["code"]) or {}
        c["openOpps"] = a.get("c") or 0
        c["openAmount"] = crm.r2(a.get("s") or 0)
        c["contractCount"] = k.get("c") or 0
        c["contractAmount"] = crm.r2(k.get("s") or 0)
        c["paidAmount"] = crm.r2(p.get("s") or 0)
        c["openTickets"] = t.get("c") or 0
    stats = {"level": {}, "status": {}}
    for r in rows(cn, "SELECT level, COUNT(*) c FROM customers GROUP BY level"):
        stats["level"][r["level"]] = r["c"]
    for r in rows(cn, "SELECT status, COUNT(*) c FROM customers GROUP BY status"):
        stats["status"][r["status"]] = r["c"]
    p = crm.paginate(data, (q.get("page") or [1])[0], (q.get("pageSize") or [100])[0])
    p["stats"] = stats
    return p


@with_db
def api_customer(cn, user, code):
    r = one(cn, "SELECT * FROM customers WHERE code=?", (code,))
    if not r:
        raise ApiError("客户不存在", 404)
    names = map_names(cn)
    v = customer_view(r, names)
    v["contacts"] = rows(cn, "SELECT * FROM contacts WHERE customer_code=? ORDER BY is_primary DESC, id",
                         (code,))
    opps = rows(cn, "SELECT * FROM opportunities WHERE customer_code=? ORDER BY created_at DESC", (code,))
    v["opportunities"] = [opp_view(o, names) for o in opps]
    quotes = rows(cn, "SELECT * FROM quotes WHERE customer_code=? ORDER BY created_at DESC", (code,))
    v["quotes"] = [quote_view(x, names) for x in quotes]
    contracts = rows(cn, "SELECT * FROM contracts WHERE customer_code=? ORDER BY created_at DESC", (code,))
    cviews = []
    for c in contracts:
        plans = rows(cn, "SELECT * FROM contract_plans WHERE contract_no=? ORDER BY seq", (c["no"],))
        cv = contract_view(c, names, plans)
        cv["plans"] = plans
        cviews.append(cv)
    v["contracts"] = cviews
    v["activities"] = [act_view(a, names) for a in rows(
        cn, "SELECT * FROM activities WHERE (obj_type='customer' AND obj_no=?) "
            "OR (obj_type='opportunity' AND obj_no IN (SELECT no FROM opportunities WHERE customer_code=?)) "
            "ORDER BY happen_at DESC LIMIT 30", (code, code))]
    v["tickets"] = [ticket_view(t, names) for t in rows(
        cn, "SELECT * FROM tickets WHERE customer_code=? ORDER BY created_at DESC", (code,))]
    v["payments"] = rows(cn, "SELECT * FROM payments WHERE customer_code=? ORDER BY pay_date DESC", (code,))
    plans = [p for c in cviews for p in c["plans"]]
    paid_total = crm.r2(sum(float(p["paid_amount"] or 0) for p in plans))
    avg_sat = one(cn, "SELECT COALESCE(AVG(satisfaction),0) s FROM tickets WHERE customer_code=? "
                      "AND satisfaction>0", (code,))["s"]
    overdue = len([p for p in plans if "逾期" in str(p["status"])])
    open_opps = len([o for o in opps if o["status"] == "进行中"])
    days = crm.days_between(r["last_follow_at"], now())
    score = crm.score_customer(days, paid_total, open_opps, avg_sat, overdue)
    cn.execute("UPDATE customers SET score=? WHERE code=?", (score, code))
    v["score"] = score
    v["scoreLevel"] = crm.score_level(score)
    v["stats"] = {
        "openAmount": crm.r2(sum(float(o["amount"]) for o in opps if o["status"] == "进行中")),
        "wonAmount": crm.r2(sum(float(o["amount"]) for o in opps if o["status"] == "赢单")),
        "contractAmount": crm.r2(sum(float(c["amount"]) for c in contracts)),
        "paidTotal": paid_total,
        "overdueAmount": crm.r2(sum(float(p["amount"]) - float(p["paid_amount"]) for p in plans
                                    if "逾期" in str(p["status"]))),
        "avgSatisfaction": crm.r2(avg_sat),
        "openTickets": len([t for t in v["tickets"] if t["status"] in ("待受理", "处理中", "待确认")]),
        "scoreParts": {"recencyDays": days, "paidTotal": paid_total, "openOpps": open_opps,
                       "satisfaction": crm.r2(avg_sat), "overduePlans": overdue},
    }
    return v


@write_op
def api_customer_create(cn, user, body):
    require(user, "write")
    name = (body.get("name") or "").strip()
    if not name:
        raise ApiError("客户名称不能为空")
    if one(cn, "SELECT code FROM customers WHERE name=?", (name,)):
        raise ApiError("客户已存在：%s" % name, 409)
    base = one(cn, "SELECT MAX(CAST(SUBSTR(code,3) AS INTEGER)) m FROM customers")["m"] or 0
    code = "C-%04d" % (int(base) + 1)
    cn.execute(
        "INSERT INTO customers(code,name,short_name,industry,scale,region,level,source,owner,phone,"
        "website,address,credit_limit,status,score,campaign_code,created_at,updated_at,last_follow_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (code, name, body.get("shortName") or name[:6], body.get("industry") or "制造业",
         body.get("scale") or "中型", body.get("region") or "华东", body.get("level") or "B",
         body.get("source") or "老客推荐", body.get("owner") or user["username"],
         body.get("phone") or "", body.get("website") or "", body.get("address") or "",
         crm.r2(body.get("creditLimit") or 0), "活跃", 0, body.get("campaignCode") or "",
         now(), now(), ""))
    op(cn, user["username"], "新建客户", "%s %s" % (code, name))
    emit(cn, "customer.created", "customer", code,
         {"code": code, "name": name, "owner": body.get("owner") or user["username"]}, user["username"])
    return customer_view(one(cn, "SELECT * FROM customers WHERE code=?", (code,)), map_names(cn))


@write_op
def api_customer_update(cn, user, code, body):
    require(user, "write")
    r = one(cn, "SELECT * FROM customers WHERE code=?", (code,))
    if not r:
        raise ApiError("客户不存在", 404)
    if scope_of(user) and r["owner"] != user["username"]:
        raise ApiError("只能维护自己名下的客户", 403)
    fields = {"name": "name", "shortName": "short_name", "industry": "industry", "scale": "scale",
              "region": "region", "level": "level", "source": "source", "owner": "owner",
              "phone": "phone", "website": "website", "address": "address", "status": "status"}
    sets, args = [], []
    for k, col in fields.items():
        if k in body:
            sets.append("%s=?" % col)
            args.append(body[k])
    if "creditLimit" in body:
        sets.append("credit_limit=?")
        args.append(crm.r2(body["creditLimit"]))
    if not sets:
        raise ApiError("没有需要更新的字段")
    sets.append("updated_at=?")
    args.append(now())
    args.append(code)
    cn.execute("UPDATE customers SET %s WHERE code=?" % ",".join(sets), args)
    op(cn, user["username"], "更新客户", code)
    emit(cn, "customer.updated", "customer", code,
         {"code": code, "name": body.get("name") or r["name"]}, user["username"])
    return customer_view(one(cn, "SELECT * FROM customers WHERE code=?", (code,)), map_names(cn))


# ---------------------------------------------------------------- 联系人
@with_db
def api_contacts(cn, user, q):
    code = (q.get("customer") or [""])[0]
    sql = "SELECT * FROM contacts WHERE 1=1"
    args = []
    if code:
        sql += " AND customer_code=?"
        args.append(code)
    sql += " ORDER BY customer_code, is_primary DESC, id"
    return rows(cn, sql, args)


@write_op
def api_contact_save(cn, user, body, cid=None):
    require(user, "write")
    code = (body.get("customerCode") or "").strip()
    name = (body.get("name") or "").strip()
    if not code or not name:
        raise ApiError("客户与联系人姓名必填")
    if not one(cn, "SELECT code FROM customers WHERE code=?", (code,)):
        raise ApiError("客户不存在：%s" % code, 404)
    if cid:
        cn.execute("UPDATE contacts SET name=?,title=?,phone=?,email=?,wechat=?,is_primary=?,remark=?"
                   " WHERE id=?",
                   (name, body.get("title") or "", body.get("phone") or "", body.get("email") or "",
                    body.get("wechat") or "", 1 if body.get("isPrimary") else 0,
                    body.get("remark") or "", cid))
    else:
        cid = cn.execute("INSERT INTO contacts(customer_code,name,title,phone,email,wechat,is_primary,"
                         "remark,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         (code, name, body.get("title") or "", body.get("phone") or "",
                          body.get("email") or "", body.get("wechat") or "",
                          1 if body.get("isPrimary") else 0, body.get("remark") or "",
                          now())).lastrowid
    if body.get("isPrimary"):
        cn.execute("UPDATE contacts SET is_primary=0 WHERE customer_code=? AND id<>?", (code, cid))
    op(cn, user["username"], "保存联系人", "%s / %s" % (code, name))
    return one(cn, "SELECT * FROM contacts WHERE id=?", (cid,))


@write_op
def api_contact_delete(cn, user, cid):
    require(user, "write")
    r = one(cn, "SELECT * FROM contacts WHERE id=?", (cid,))
    if not r:
        raise ApiError("联系人不存在", 404)
    cn.execute("DELETE FROM contacts WHERE id=?", (cid,))
    op(cn, user["username"], "删除联系人", "%s / %s" % (r["customer_code"], r["name"]))
    return {"deleted": cid}


# ---------------------------------------------------------------- 商机
def _has_contract(cn, opp_no):
    return bool(one(cn, "SELECT no FROM contracts WHERE opp_no=? AND status IN ('已签署','执行中','已完成')",
                    (opp_no,)))


@with_db
def api_opportunities(cn, user, q):
    names = map_names(cn)
    sc = scope_of(user)
    stage = (q.get("stage") or ["全部"])[0]
    status = (q.get("status") or ["全部"])[0]
    kw = (q.get("kw") or [""])[0].strip()
    owner = (q.get("owner") or [""])[0]
    sql = "SELECT * FROM opportunities WHERE 1=1"
    args = []
    if stage != "全部":
        sql += " AND stage=?"
        args.append(stage)
    if status != "全部":
        sql += " AND status=?"
        args.append(status)
    if owner:
        sql += " AND owner=?"
        args.append(owner)
    if kw:
        sql += " AND (name LIKE ? OR customer_name LIKE ? OR no LIKE ?)"
        args += ["%" + kw + "%"] * 3
    if sc:
        sql += " AND owner=?"
        args.append(sc)
    sql += " ORDER BY CASE status WHEN '进行中' THEN 0 ELSE 1 END, expect_close_date"
    data = [opp_view(r, names) for r in rows(cn, sql, args)]
    p = crm.paginate(data, (q.get("page") or [1])[0], (q.get("pageSize") or [100])[0])
    p["funnel"] = crm.funnel(rows(cn, "SELECT * FROM opportunities"))
    return p


@with_db
def api_opportunity(cn, user, no):
    r = one(cn, "SELECT * FROM opportunities WHERE no=?", (no,))
    if not r:
        raise ApiError("商机不存在", 404)
    names = map_names(cn)
    v = opp_view(r, names, _has_contract(cn, no))
    v["stageLogs"] = rows(cn, "SELECT * FROM stage_logs WHERE opp_no=? ORDER BY id DESC", (no,))
    v["activities"] = [act_view(a, names) for a in rows(
        cn, "SELECT * FROM activities WHERE obj_type='opportunity' AND obj_no=? ORDER BY happen_at DESC",
        (no,))]
    v["quotes"] = [quote_view(x, names) for x in rows(
        cn, "SELECT * FROM quotes WHERE opp_no=? ORDER BY created_at DESC", (no,))]
    v["contracts"] = [contract_view(c, names, rows(
        cn, "SELECT * FROM contract_plans WHERE contract_no=? ORDER BY seq", (c["no"],)))
        for c in rows(cn, "SELECT * FROM contracts WHERE opp_no=?", (no,))]
    v["stageGate"] = {s: crm.stage_gate(s, r, _has_contract(cn, no)) for s in crm.STAGE_ORDER}
    v["customer"] = customer_view(one(cn, "SELECT * FROM customers WHERE code=?", (r["customer_code"],)), names)
    return v


@write_op
def api_opportunity_create(cn, user, body):
    require(user, "write")
    name = (body.get("name") or "").strip()
    code = (body.get("customerCode") or "").strip()
    if not name:
        raise ApiError("商机名称不能为空")
    c = one(cn, "SELECT * FROM customers WHERE code=?", (code,))
    if not c:
        raise ApiError("客户不存在：%s" % code, 404)
    amount = crm.r2(body.get("amount") or 0)
    if amount <= 0:
        raise ApiError("商机金额必须大于 0")
    no = next_no(cn, "opportunity", "opportunities")
    stage = body.get("stage") or "初步接触"
    if stage not in crm.STAGE_ORDER:
        raise ApiError("阶段不存在：%s" % stage)
    cn.execute(
        "INSERT INTO opportunities(no,name,customer_code,customer_name,amount,stage,probability,"
        "expect_close_date,owner,source,campaign_code,competitor,decision_maker,status,win_reason,"
        "lose_reason,next_action,created_at,updated_at,closed_at,last_activity_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (no, name, code, c["name"], amount, stage, crm.STAGE_PROB[stage],
         body.get("expectCloseDate") or "", body.get("owner") or user["username"],
         body.get("source") or c["source"], body.get("campaignCode") or "",
         body.get("competitor") or "", body.get("decisionMaker") or "", "进行中", "", "",
         body.get("nextAction") or "", now(), now(), "", now()))
    cn.execute("INSERT INTO stage_logs(opp_no,from_stage,to_stage,amount,operator,remark,created_at)"
               " VALUES(?,?,?,?,?,?,?)", (no, "", stage, amount, user["username"], "商机创建", now()))
    op(cn, user["username"], "新建商机", "%s %s" % (no, name))
    emit(cn, "opportunity.created", "opportunity", no,
         {"no": no, "name": name, "customerCode": code, "amount": amount, "stage": stage,
          "owner": body.get("owner") or user["username"]}, user["username"])
    return opp_view(one(cn, "SELECT * FROM opportunities WHERE no=?", (no,)), map_names(cn))


@write_op
def api_opportunity_update(cn, user, no, body):
    require(user, "write")
    r = one(cn, "SELECT * FROM opportunities WHERE no=?", (no,))
    if not r:
        raise ApiError("商机不存在", 404)
    if scope_of(user) and r["owner"] != user["username"]:
        raise ApiError("只能维护自己名下的商机", 403)
    fields = {"name": "name", "expectCloseDate": "expect_close_date", "owner": "owner",
              "competitor": "competitor", "decisionMaker": "decision_maker",
              "nextAction": "next_action", "source": "source", "campaignCode": "campaign_code"}
    sets, args = [], []
    for k, col in fields.items():
        if k in body:
            sets.append("%s=?" % col)
            args.append(body[k])
    if "amount" in body:
        amount = crm.r2(body["amount"])
        if amount <= 0:
            raise ApiError("商机金额必须大于 0")
        sets.append("amount=?")
        args.append(amount)
    if not sets:
        raise ApiError("没有需要更新的字段")
    sets.append("updated_at=?")
    args.append(now())
    args.append(no)
    cn.execute("UPDATE opportunities SET %s WHERE no=?" % ",".join(sets), args)
    op(cn, user["username"], "更新商机", no)
    emit(cn, "opportunity.updated", "opportunity", no, {"no": no, "name": r["name"]}, user["username"])
    return opp_view(one(cn, "SELECT * FROM opportunities WHERE no=?", (no,)), map_names(cn))


def _stage_move(cn, user, no, body):
    require(user, "write")
    r = one(cn, "SELECT * FROM opportunities WHERE no=?", (no,))
    if not r:
        raise ApiError("商机不存在", 404)
    if scope_of(user) and r["owner"] != user["username"]:
        raise ApiError("只能推进自己名下的商机", 403)
    target = (body.get("stage") or "").strip()
    ok, msg = crm.can_move_stage(r["stage"], target)
    if not ok:
        raise ApiError(msg)
    # 允许在推进时顺带补录闸口字段（竞品 / 决策人），否则界面里填了也用不上
    eff = dict(r)
    for key, col in (("competitor", "competitor"), ("decisionMaker", "decision_maker")):
        val = (body.get(key) or "").strip()
        if val:
            eff[col] = val
    miss = crm.stage_gate(target, eff, _has_contract(cn, no))
    if miss:
        raise ApiError("进入「%s」前需补齐：%s" % (target, "、".join(miss)))
    for col in ("competitor", "decision_maker"):
        if eff.get(col) != r[col]:
            cn.execute("UPDATE opportunities SET %s=? WHERE no=?" % col, (eff[col], no))
    amount = crm.r2(body.get("amount") or r["amount"])
    cn.execute("UPDATE opportunities SET stage=?, probability=?, amount=?, status=?, updated_at=?,"
               " closed_at=? WHERE no=?",
               (target, crm.STAGE_PROB[target], amount, crm.opp_status(target), now(),
                now() if target in ("赢单", "输单") else "", no))
    if target == "输单" and (body.get("reason") or "").strip():
        cn.execute("UPDATE opportunities SET lose_reason=? WHERE no=?", (body["reason"], no))
    if target == "赢单":
        cn.execute("UPDATE opportunities SET win_reason=? WHERE no=?",
                   (body.get("reason") or "阶段推进至赢单", no))
    cn.execute("INSERT INTO stage_logs(opp_no,from_stage,to_stage,amount,operator,remark,created_at)"
               " VALUES(?,?,?,?,?,?,?)",
               (no, r["stage"], target, amount, user["username"], body.get("remark") or "", now()))
    op(cn, user["username"], "商机阶段推进", "%s %s→%s" % (no, r["stage"], target))
    emit(cn, "opportunity.won" if target == "赢单" else "opportunity.stage_changed",
         "opportunity", no,
         {"no": no, "name": r["name"], "fromStage": r["stage"], "toStage": target,
          "amount": amount, "owner": r["owner"], "customerCode": r["customer_code"]},
         user["username"])
    return opp_view(one(cn, "SELECT * FROM opportunities WHERE no=?", (no,)), map_names(cn))


@write_op
def api_opportunity_stage(cn, user, no, body):
    return _stage_move(cn, user, no, body)


@write_op
def api_opportunity_close(cn, user, no, body):
    result = (body.get("result") or "").strip()
    if result not in ("win", "lose"):
        raise ApiError("result 只能是 win 或 lose")
    if result == "lose" and not (body.get("reason") or "").strip():
        raise ApiError("输单必须填写原因")
    return _stage_move(cn, user, no, {"stage": "赢单" if result == "win" else "输单",
                                     "reason": body.get("reason") or "",
                                     "amount": body.get("amount")})


# ---------------------------------------------------------------- 跟进记录
def act_view(r, names=None):
    names = names or {}
    return {
        "id": r["id"], "objType": r["obj_type"], "objNo": r["obj_no"], "objName": r["obj_name"],
        "kind": r["kind"], "subject": r["subject"], "content": r["content"],
        "happenAt": r["happen_at"], "durationMin": r["duration_min"], "owner": r["owner"],
        "ownerName": names.get(r["owner"], r["owner"] or ""), "result": r["result"],
        "nextPlan": r["next_plan"], "nextAt": r["next_at"], "status": r["status"],
        "createdAt": r["created_at"],
    }


@with_db
def api_activities(cn, user, q):
    names = map_names(cn)
    obj_type = (q.get("objType") or [""])[0]
    obj_no = (q.get("objNo") or [""])[0]
    owner = (q.get("owner") or [""])[0]
    kind = (q.get("kind") or ["全部"])[0]
    sc = scope_of(user)
    sql = "SELECT * FROM activities WHERE 1=1"
    args = []
    if obj_type:
        sql += " AND obj_type=?"
        args.append(obj_type)
    if obj_no:
        sql += " AND obj_no=?"
        args.append(obj_no)
    if owner:
        sql += " AND owner=?"
        args.append(owner)
    elif sc:
        sql += " AND owner=?"
        args.append(sc)
    if kind != "全部":
        sql += " AND kind=?"
        args.append(kind)
    sql += " ORDER BY happen_at DESC LIMIT 300"
    data = [act_view(r, names) for r in rows(cn, sql, args)]
    by_kind = {}
    for a in data:
        by_kind[a["kind"]] = by_kind.get(a["kind"], 0) + 1
    return {"list": data, "total": len(data), "byKind": by_kind}


@write_op
def api_activity_create(cn, user, body):
    require(user, "write")
    obj_type = (body.get("objType") or "customer").strip()
    obj_no = (body.get("objNo") or "").strip()
    subject = (body.get("subject") or "").strip()
    if obj_type not in ("customer", "lead", "opportunity", "ticket"):
        raise ApiError("objType 只能是 customer / lead / opportunity / ticket")
    if not obj_no or not subject:
        raise ApiError("关联对象与主题必填")
    table = {"customer": "customers", "lead": "leads", "opportunity": "opportunities",
             "ticket": "tickets"}[obj_type]
    key = "code" if obj_type == "customer" else "no"
    obj = one(cn, "SELECT * FROM %s WHERE %s=?" % (table, key), (obj_no,))
    if not obj:
        raise ApiError("关联对象不存在：%s" % obj_no, 404)
    obj_name = obj.get("name") or obj.get("title") or ""
    happen = body.get("happenAt") or now()
    cid = cn.execute(
        "INSERT INTO activities(obj_type,obj_no,obj_name,kind,subject,content,happen_at,duration_min,"
        "owner,result,next_plan,next_at,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (obj_type, obj_no, obj_name, body.get("kind") or "电话", subject, body.get("content") or "",
         happen, int(body.get("durationMin") or 30), body.get("owner") or user["username"],
         body.get("result") or "", body.get("nextPlan") or "", body.get("nextAt") or "",
         body.get("status") or "完成", now())).lastrowid
    # 回写跟进时间，驱动「多久没跟进」预警与客户评分
    if obj_type == "lead":
        cn.execute("UPDATE leads SET last_follow_at=?, status=CASE WHEN status='待分配' THEN '跟进中' "
                   "ELSE status END, owner=CASE WHEN owner='' THEN ? ELSE owner END WHERE no=?",
                   (happen, user["username"], obj_no))
    elif obj_type == "customer":
        cn.execute("UPDATE customers SET last_follow_at=?, updated_at=? WHERE code=?",
                   (happen, now(), obj_no))
    elif obj_type == "opportunity":
        cn.execute("UPDATE opportunities SET last_activity_at=?, updated_at=? WHERE no=?",
                   (happen, now(), obj_no))
        if obj.get("customer_code"):
            cn.execute("UPDATE customers SET last_follow_at=?, updated_at=? WHERE code=?",
                       (happen, now(), obj["customer_code"]))
    else:
        cn.execute("INSERT INTO ticket_logs(ticket_no,action,content,operator,created_at)"
                   " VALUES(?,?,?,?,?)", (obj_no, "跟进", subject, user["username"], now()))
    op(cn, user["username"], "新增跟进", "%s %s" % (obj_type, obj_no))
    emit(cn, "activity.created", obj_type, obj_no,
         {"objType": obj_type, "objNo": obj_no, "kind": body.get("kind") or "电话",
          "subject": subject, "owner": body.get("owner") or user["username"]}, user["username"])
    return act_view(one(cn, "SELECT * FROM activities WHERE id=?", (cid,)), map_names(cn))


@write_op
def api_activity_done(cn, user, aid):
    require(user, "write")
    r = one(cn, "SELECT * FROM activities WHERE id=?", (aid,))
    if not r:
        raise ApiError("跟进记录不存在", 404)
    cn.execute("UPDATE activities SET status='完成' WHERE id=?", (aid,))
    return act_view(one(cn, "SELECT * FROM activities WHERE id=?", (aid,)), map_names(cn))


# ---------------------------------------------------------------- 产品
@with_db
def api_products(cn, user, q):
    return {"list": rows(cn, "SELECT * FROM products WHERE status='在售' ORDER BY code")}


# ---------------------------------------------------------------- 报价
@with_db
def api_quotes(cn, user, q):
    names = map_names(cn)
    sc = scope_of(user)
    status = (q.get("status") or ["全部"])[0]
    kw = (q.get("kw") or [""])[0].strip()
    sql = "SELECT * FROM quotes WHERE 1=1"
    args = []
    if status != "全部":
        sql += " AND status=?"
        args.append(status)
    if kw:
        sql += " AND (no LIKE ? OR customer_name LIKE ? OR title LIKE ?)"
        args += ["%" + kw + "%"] * 3
    if sc:
        sql += " AND owner=?"
        args.append(sc)
    sql += " ORDER BY created_at DESC"
    data = [quote_view(r, names) for r in rows(cn, sql, args)]
    p = crm.paginate(data, (q.get("page") or [1])[0], (q.get("pageSize") or [100])[0])
    p["stats"] = {r["status"]: r["c"] for r in rows(
        cn, "SELECT status, COUNT(*) c FROM quotes GROUP BY status")}
    return p


@with_db
def api_quote(cn, user, no):
    r = one(cn, "SELECT * FROM quotes WHERE no=?", (no,))
    if not r:
        raise ApiError("报价单不存在", 404)
    v = quote_view(r, map_names(cn))
    v["lines"] = rows(cn, "SELECT * FROM quote_lines WHERE quote_no=? ORDER BY seq", (no,))
    threshold = rule_value(cn, "discount_approval", 0.15)
    v["needApproval"] = crm.need_discount_approval(r["discount_rate"], threshold)
    v["threshold"] = threshold
    return v


@write_op
def api_quote_create(cn, user, body):
    require(user, "write")
    code = (body.get("customerCode") or "").strip()
    c = one(cn, "SELECT * FROM customers WHERE code=?", (code,))
    if not c:
        raise ApiError("客户不存在：%s" % code, 404)
    lines = body.get("lines") or []
    if not lines:
        raise ApiError("报价明细不能为空")
    prepared = []
    for ln in lines:
        p = one(cn, "SELECT * FROM products WHERE code=?", ((ln.get("productCode") or "").strip(),))
        if not p:
            raise ApiError("产品不存在：%s" % ln.get("productCode"))
        qty = float(ln.get("qty") or 0)
        if qty <= 0:
            raise ApiError("数量必须大于 0")
        price = crm.r2(ln.get("price") if ln.get("price") is not None else p["price"])
        if price < 0:
            raise ApiError("单价不能为负")
        prepared.append({"code": p["code"], "name": p["name"], "qty": qty,
                         "list": crm.r2(p["price"]), "price": price})
    calc = crm.quote_amount([{"qty": x["qty"], "listPrice": x["list"], "price": x["price"]}
                             for x in prepared])
    threshold = rule_value(cn, "discount_approval", 0.15)
    status = "待审批" if crm.need_discount_approval(calc["discountRate"], threshold) else "草稿"
    no = next_no(cn, "quote", "quotes")
    cn.execute(
        "INSERT INTO quotes(no,opp_no,customer_code,customer_name,title,amount,list_amount,discount_rate,"
        "status,valid_until,owner,approver,approved_at,reject_reason,remark,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (no, body.get("oppNo") or "", code, c["name"], body.get("title") or "%s 报价单" % c["name"],
         calc["amount"], calc["listAmount"], calc["discountRate"], status,
         body.get("validUntil") or (date.today() + timedelta(days=30)).isoformat(),
         body.get("owner") or user["username"], "", "", "", body.get("remark") or "", now()))
    for i, x in enumerate(prepared):
        cn.execute("INSERT INTO quote_lines(quote_no,seq,product_code,product_name,qty,list_price,price,"
                   "amount) VALUES(?,?,?,?,?,?,?,?)",
                   (no, i + 1, x["code"], x["name"], x["qty"], x["list"], x["price"],
                    crm.r2(x["qty"] * x["price"])))
    op(cn, user["username"], "新建报价", "%s %s" % (no, c["name"]))
    emit(cn, "quote.created", "quote", no,
         {"no": no, "customerCode": code, "amount": calc["amount"],
          "discountRate": calc["discountRate"], "status": status}, user["username"])
    return quote_view(one(cn, "SELECT * FROM quotes WHERE no=?", (no,)), map_names(cn))


def _quote_of(cn, no):
    r = one(cn, "SELECT * FROM quotes WHERE no=?", (no,))
    if not r:
        raise ApiError("报价单不存在", 404)
    return r


@write_op
def api_quote_approve(cn, user, no, body):
    require(user, "approve")
    r = _quote_of(cn, no)
    if r["status"] not in ("待审批", "已驳回"):
        raise ApiError("只有待审批的报价单可以批准，当前为「%s」" % r["status"])
    cn.execute("UPDATE quotes SET status='已批准', approver=?, approved_at=?, reject_reason='' WHERE no=?",
               (user["username"], now(), no))
    op(cn, user["username"], "批准报价", no)
    emit(cn, "quote.approved", "quote", no, {"no": no, "approver": user["username"]}, user["username"])
    return quote_view(one(cn, "SELECT * FROM quotes WHERE no=?", (no,)), map_names(cn))


@write_op
def api_quote_reject(cn, user, no, body):
    require(user, "approve")
    r = _quote_of(cn, no)
    if r["status"] != "待审批":
        raise ApiError("只有待审批的报价单可以驳回，当前为「%s」" % r["status"])
    reason = (body.get("reason") or "").strip()
    if not reason:
        raise ApiError("驳回必须填写原因")
    cn.execute("UPDATE quotes SET status='已驳回', approver=?, approved_at=?, reject_reason=? WHERE no=?",
               (user["username"], now(), reason, no))
    op(cn, user["username"], "驳回报价", "%s：%s" % (no, reason))
    emit(cn, "quote.rejected", "quote", no, {"no": no, "reason": reason}, user["username"])
    return quote_view(one(cn, "SELECT * FROM quotes WHERE no=?", (no,)), map_names(cn))


@write_op
def api_quote_send(cn, user, no, body):
    require(user, "write")
    r = _quote_of(cn, no)
    if r["status"] == "待审批":
        raise ApiError("折扣超出审批线，需销售总监批准后才能发送")
    if r["status"] in ("已发送", "已接受"):
        raise ApiError("报价单已发送，请勿重复操作")
    cn.execute("UPDATE quotes SET status='已发送' WHERE no=?", (no,))
    op(cn, user["username"], "发送报价", no)
    emit(cn, "quote.sent", "quote", no, {"no": no}, user["username"])
    return quote_view(one(cn, "SELECT * FROM quotes WHERE no=?", (no,)), map_names(cn))


@write_op
def api_quote_accept(cn, user, no, body):
    require(user, "write")
    r = _quote_of(cn, no)
    if r["status"] not in ("已发送", "已批准"):
        raise ApiError("只有已发送/已批准的报价单可以标记接受")
    cn.execute("UPDATE quotes SET status='已接受' WHERE no=?", (no,))
    op(cn, user["username"], "客户接受报价", no)
    emit(cn, "quote.accepted", "quote", no, {"no": no}, user["username"])
    return quote_view(one(cn, "SELECT * FROM quotes WHERE no=?", (no,)), map_names(cn))


# ---------------------------------------------------------------- 合同
@with_db
def api_contracts(cn, user, q):
    names = map_names(cn)
    sc = scope_of(user)
    status = (q.get("status") or ["全部"])[0]
    kw = (q.get("kw") or [""])[0].strip()
    sql = "SELECT * FROM contracts WHERE 1=1"
    args = []
    if status != "全部":
        sql += " AND status=?"
        args.append(status)
    if kw:
        sql += " AND (no LIKE ? OR customer_name LIKE ? OR title LIKE ?)"
        args += ["%" + kw + "%"] * 3
    if sc:
        sql += " AND owner=?"
        args.append(sc)
    sql += " ORDER BY created_at DESC"
    data = []
    for r in rows(cn, sql, args):
        plans = rows(cn, "SELECT * FROM contract_plans WHERE contract_no=? ORDER BY seq", (r["no"],))
        data.append(contract_view(r, names, plans))
    p = crm.paginate(data, (q.get("page") or [1])[0], (q.get("pageSize") or [100])[0])
    p["stats"] = {r["status"]: r["c"] for r in rows(
        cn, "SELECT status, COUNT(*) c FROM contracts GROUP BY status")}
    return p


@with_db
def api_contract(cn, user, no):
    r = one(cn, "SELECT * FROM contracts WHERE no=?", (no,))
    if not r:
        raise ApiError("合同不存在", 404)
    names = map_names(cn)
    plans = rows(cn, "SELECT * FROM contract_plans WHERE contract_no=? ORDER BY seq", (no,))
    v = contract_view(r, names, plans)
    v["plans"] = []
    for p in plans:
        pv = dict(p)
        pv["dueDate"] = p["due_date"]
        pv["paidAmount"] = crm.r2(p["paid_amount"])
        pv["leftAmount"] = crm.r2(float(p["amount"]) - float(p["paid_amount"]))
        pv["overdueDays"] = crm.overdue_days(p["due_date"]) if "逾期" in str(p["status"]) else 0
        v["plans"].append(pv)
    v["payments"] = rows(cn, "SELECT * FROM payments WHERE contract_no=? ORDER BY pay_date", (no,))
    v["customer"] = customer_view(one(cn, "SELECT * FROM customers WHERE code=?", (r["customer_code"],)), names)
    v["quote"] = quote_view(one(cn, "SELECT * FROM quotes WHERE no=?", (r["quote_no"],)), names) \
        if r["quote_no"] else None
    return v


@write_op
def api_contract_create(cn, user, body):
    require(user, "write")
    code = (body.get("customerCode") or "").strip()
    c = one(cn, "SELECT * FROM customers WHERE code=?", (code,))
    if not c:
        raise ApiError("客户不存在：%s" % code, 404)
    amount = crm.r2(body.get("amount") or 0)
    if amount <= 0:
        raise ApiError("合同金额必须大于 0")
    no = next_no(cn, "contract", "contracts")
    sign = body.get("signDate") or today()
    terms = body.get("paymentTerms") or "3-4-3"
    cn.execute(
        "INSERT INTO contracts(no,customer_code,customer_name,quote_no,opp_no,title,amount,sign_date,"
        "start_date,end_date,payment_terms,status,owner,signed_at,terminated_at,remark,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (no, code, c["name"], body.get("quoteNo") or "", body.get("oppNo") or "",
         body.get("title") or "%s 服务合同" % c["name"], amount, sign,
         body.get("startDate") or sign,
         body.get("endDate") or (datetime.strptime(sign, "%Y-%m-%d") + timedelta(days=365)).date().isoformat(),
         terms, "待签署", body.get("owner") or user["username"], "", "", body.get("remark") or "", now()))
    plans = crm.build_plans(amount, sign, terms)
    for p in plans:
        cn.execute("INSERT INTO contract_plans(contract_no,seq,due_date,amount,paid_amount,status,remark)"
                   " VALUES(?,?,?,?,?,?,?)",
                   (no, p["seq"], p["dueDate"], p["amount"], 0, "未收", ""))
    op(cn, user["username"], "新建合同", "%s %s" % (no, c["name"]))
    emit(cn, "contract.created", "contract", no,
         {"no": no, "customerCode": code, "amount": amount, "status": "待签署"}, user["username"])
    plan_rows = rows(cn, "SELECT * FROM contract_plans WHERE contract_no=? ORDER BY seq", (no,))
    return contract_view(one(cn, "SELECT * FROM contracts WHERE no=?", (no,)), map_names(cn),
                         plan_rows)


@write_op
def api_contract_sign(cn, user, no, body):
    require(user, "write")
    r = one(cn, "SELECT * FROM contracts WHERE no=?", (no,))
    if not r:
        raise ApiError("合同不存在", 404)
    if r["status"] not in ("草稿", "待签署"):
        raise ApiError("当前状态「%s」不可签署" % r["status"])
    sign = body.get("signDate") or today()
    cn.execute("UPDATE contracts SET status='已签署', sign_date=?, signed_at=? WHERE no=?",
               (sign, now(), no))
    plans = crm.build_plans(r["amount"], sign, r["payment_terms"])
    cn.execute("DELETE FROM contract_plans WHERE contract_no=?", (no,))
    for p in plans:
        cn.execute("INSERT INTO contract_plans(contract_no,seq,due_date,amount,paid_amount,status,remark)"
                   " VALUES(?,?,?,?,?,?,?)", (no, p["seq"], p["dueDate"], p["amount"], 0, "未收", ""))
    if r["opp_no"]:
        opp = one(cn, "SELECT * FROM opportunities WHERE no=?", (r["opp_no"],))
        if opp and opp["status"] == "进行中" and opp["stage"] == "商务谈判":
            cn.execute("UPDATE opportunities SET stage='赢单', probability=1, status='赢单', "
                       "closed_at=?, updated_at=?, win_reason='合同已签署' WHERE no=?",
                       (now(), now(), r["opp_no"]))
            cn.execute("INSERT INTO stage_logs(opp_no,from_stage,to_stage,amount,operator,remark,created_at)"
                       " VALUES(?,?,?,?,?,?,?)",
                       (r["opp_no"], "商务谈判", "赢单", r["amount"], user["username"], "合同签署自动推进",
                        now()))
    op(cn, user["username"], "合同签署", no)
    emit(cn, "contract.signed", "contract", no,
         {"no": no, "customerCode": r["customer_code"], "amount": crm.r2(r["amount"]),
          "signDate": sign, "owner": r["owner"]}, user["username"])
    return {"no": no, "status": "已签署", "plans": plans}


@write_op
def api_contract_terminate(cn, user, no, body):
    require(user, "approve")
    r = one(cn, "SELECT * FROM contracts WHERE no=?", (no,))
    if not r:
        raise ApiError("合同不存在", 404)
    if r["status"] in ("已完成", "已终止"):
        raise ApiError("合同已结单，不能终止")
    reason = (body.get("reason") or "").strip()
    if not reason:
        raise ApiError("终止合同必须填写原因")
    cn.execute("UPDATE contracts SET status='已终止', terminated_at=?, remark=? WHERE no=?",
               (now(), reason, no))
    op(cn, user["username"], "终止合同", "%s：%s" % (no, reason))
    emit(cn, "contract.terminated", "contract", no, {"no": no, "reason": reason}, user["username"])
    return {"no": no, "status": "已终止"}


# ---------------------------------------------------------------- 回款
@with_db
def api_payment_plans(cn, user, q):
    names = map_names(cn)
    sc = scope_of(user)
    status = (q.get("status") or ["全部"])[0]
    only_overdue = (q.get("overdue") or [""])[0] in ("1", "true")
    sql = ("SELECT p.*, t.customer_code, t.customer_name, t.owner, t.status cstatus "
           "FROM contract_plans p JOIN contracts t ON t.no=p.contract_no WHERE 1=1")
    args = []
    if sc:
        sql += " AND t.owner=?"
        args.append(sc)
    if status != "全部" and not only_overdue:
        sql += " AND p.status=?"
        args.append(status)
    sql += " ORDER BY p.due_date"
    data = []
    for p in rows(cn, sql, args):
        st = crm.plan_status(p["amount"], p["paid_amount"], p["due_date"])
        if only_overdue and "逾期" not in st:
            continue                                  # 以实时口径为准，避免状态列陈旧
        data.append({
            "id": p["id"], "contractNo": p["contract_no"], "seq": p["seq"],
            "dueDate": p["due_date"], "amount": crm.r2(p["amount"]),
            "paidAmount": crm.r2(p["paid_amount"]),
            "leftAmount": crm.r2(float(p["amount"]) - float(p["paid_amount"])),
            "status": st,
            "customerCode": p["customer_code"], "customerName": p["customer_name"],
            "owner": p["owner"], "ownerName": names.get(p["owner"], p["owner"] or ""),
            "overdueDays": crm.overdue_days(p["due_date"]) if "逾期" in st else 0,
        })
    p = crm.paginate(data, (q.get("page") or [1])[0], (q.get("pageSize") or [100])[0])
    p["aging"] = crm.aging_buckets([{"amount": x["amount"], "paidAmount": x["paidAmount"],
                                     "dueDate": x["dueDate"]} for x in data])
    p["totalUnpaid"] = crm.r2(sum(x["leftAmount"] for x in data))
    p["totalOverdue"] = crm.r2(sum(x["leftAmount"] for x in data if "逾期" in x["status"]))
    return p


@with_db
def api_payments(cn, user, q):
    sc = scope_of(user)
    sql = "SELECT * FROM payments WHERE 1=1"
    args = []
    if sc:
        sql += " AND customer_code IN (SELECT code FROM customers WHERE owner=?)"
        args.append(sc)
    kw = (q.get("kw") or [""])[0].strip()
    if kw:
        sql += " AND (no LIKE ? OR customer_name LIKE ? OR contract_no LIKE ?)"
        args += ["%" + kw + "%"] * 3
    sql += " ORDER BY pay_date DESC LIMIT 300"
    data = rows(cn, sql, args)
    out = []
    for r in data:
        out.append({"no": r["no"], "contractNo": r["contract_no"], "planId": r["plan_id"],
                    "customerCode": r["customer_code"], "customerName": r["customer_name"],
                    "amount": crm.r2(r["amount"]), "payDate": r["pay_date"], "method": r["method"],
                    "operator": r["operator"], "remark": r["remark"], "createdAt": r["created_at"]})
    return {"list": out, "total": len(out),
            "totalAmount": crm.r2(sum(x["amount"] for x in out))}


@write_op
def api_payment_create(cn, user, body):
    require(user, "finance" if user["role"] == "finance" else "write")
    no_contract = (body.get("contractNo") or "").strip()
    r = one(cn, "SELECT * FROM contracts WHERE no=?", (no_contract,))
    if not r:
        raise ApiError("合同不存在：%s" % no_contract, 404)
    if r["status"] in ("已终止",):
        raise ApiError("已终止的合同不能登记收款")
    amount = crm.r2(body.get("amount") or 0)
    if amount <= 0:
        raise ApiError("收款金额必须大于 0")
    plans = rows(cn, "SELECT * FROM contract_plans WHERE contract_no=? ORDER BY seq", (no_contract,))
    left_total = crm.r2(sum(float(p["amount"]) - float(p["paid_amount"]) for p in plans))
    if amount > left_total + 0.01:
        raise ApiError("收款金额 %.2f 超过合同未收余额 %.2f" % (amount, left_total))
    pay_date = body.get("payDate") or today()
    plan_id = int(body.get("planId") or 0)
    targets = [p for p in plans if p["id"] == plan_id] if plan_id else []
    if not targets:
        targets = [p for p in plans
                   if float(p["amount"]) - float(p["paid_amount"]) > 0.005]
    left = amount
    touched = []
    for p in targets:
        if left <= 0:
            break
        need = crm.r2(float(p["amount"]) - float(p["paid_amount"]))
        if need <= 0:
            continue
        take = min(need, left)
        new_paid = crm.r2(float(p["paid_amount"]) + take)
        st = crm.plan_status(p["amount"], new_paid, p["due_date"])
        cn.execute("UPDATE contract_plans SET paid_amount=?, status=? WHERE id=?",
                   (new_paid, st, p["id"]))
        cn.execute("INSERT INTO payments(no,contract_no,plan_id,customer_code,customer_name,amount,"
                   "pay_date,method,operator,remark,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (next_no(cn, "payment", "payments"), no_contract, p["id"], r["customer_code"],
                    r["customer_name"], take, pay_date, body.get("method") or "银行转账",
                    user["username"], body.get("remark") or "", now()))
        touched.append({"planId": p["id"], "seq": p["seq"], "amount": take, "status": st})
        left = crm.r2(left - take)
    plans2 = rows(cn, "SELECT * FROM contract_plans WHERE contract_no=? ORDER BY seq", (no_contract,))
    if all(p["status"] == "已收" for p in plans2) and r["status"] in ("已签署", "执行中"):
        cn.execute("UPDATE contracts SET status='已完成' WHERE no=?", (no_contract,))
    elif r["status"] == "已签署":
        cn.execute("UPDATE contracts SET status='执行中' WHERE no=?", (no_contract,))
    op(cn, user["username"], "登记收款", "%s %.2f" % (no_contract, amount))
    emit(cn, "payment.received", "payment", no_contract,
         {"contractNo": no_contract, "customerCode": r["customer_code"], "amount": amount,
          "payDate": pay_date, "method": body.get("method") or "银行转账"}, user["username"])
    return {"contractNo": no_contract, "amount": amount, "allocations": touched,
            "unpaidAmount": crm.r2(sum(float(p["amount"]) - float(p["paid_amount"]) for p in plans2))}


# ---------------------------------------------------------------- 工单
@with_db
def api_tickets(cn, user, q):
    names = map_names(cn)
    status = (q.get("status") or ["全部"])[0]
    priority = (q.get("priority") or ["全部"])[0]
    kw = (q.get("kw") or [""])[0].strip()
    only_over = (q.get("overdue") or [""])[0] in ("1", "true")
    sql = "SELECT * FROM tickets WHERE 1=1"
    args = []
    if status != "全部":
        sql += " AND status=?"
        args.append(status)
    if priority != "全部":
        sql += " AND priority=?"
        args.append(priority)
    if kw:
        sql += " AND (no LIKE ? OR title LIKE ? OR customer_name LIKE ?)"
        args += ["%" + kw + "%"] * 3
    sql += " ORDER BY CASE priority WHEN 'P1' THEN 0 WHEN 'P2' THEN 1 ELSE 2 END, created_at DESC"
    data = [ticket_view(r, names) for r in rows(cn, sql, args)]
    if only_over:
        data = [t for t in data if t["slaState"] == "超时"]
    stats = {"status": {}, "priority": {}, "sla": {}}
    for r in rows(cn, "SELECT status, COUNT(*) c FROM tickets GROUP BY status"):
        stats["status"][r["status"]] = r["c"]
    for r in rows(cn, "SELECT priority, COUNT(*) c FROM tickets GROUP BY priority"):
        stats["priority"][r["priority"]] = r["c"]
    for t in data:
        stats["sla"][t["slaState"]] = stats["sla"].get(t["slaState"], 0) + 1
    p = crm.paginate(data, (q.get("page") or [1])[0], (q.get("pageSize") or [100])[0])
    p["stats"] = stats
    p["avgSatisfaction"] = crm.r2(one(
        cn, "SELECT COALESCE(AVG(satisfaction),0) s FROM tickets WHERE satisfaction>0")["s"])
    return p


@with_db
def api_ticket(cn, user, no):
    r = one(cn, "SELECT * FROM tickets WHERE no=?", (no,))
    if not r:
        raise ApiError("工单不存在", 404)
    v = ticket_view(r, map_names(cn))
    v["logs"] = rows(cn, "SELECT * FROM ticket_logs WHERE ticket_no=? ORDER BY id", (no,))
    v["customer"] = customer_view(one(cn, "SELECT * FROM customers WHERE code=?", (r["customer_code"],)),
                                  map_names(cn))
    return v


@write_op
def api_ticket_create(cn, user, body):
    require(user, "write")
    code = (body.get("customerCode") or "").strip()
    c = one(cn, "SELECT * FROM customers WHERE code=?", (code,))
    if not c:
        raise ApiError("客户不存在：%s" % code, 404)
    title = (body.get("title") or "").strip()
    if not title:
        raise ApiError("工单标题不能为空")
    pri = (body.get("priority") or "P2").upper()
    if pri not in ("P1", "P2", "P3"):
        raise ApiError("优先级只能是 P1 / P2 / P3")
    hours = rule_value(cn, "sla_%s" % pri.lower(), crm.SLA_HOURS[pri])
    created = now()
    resp_due, res_due = crm.sla_dues(created, pri, hours)
    no = next_no(cn, "ticket", "tickets")
    cn.execute(
        "INSERT INTO tickets(no,customer_code,customer_name,contract_no,title,category,priority,status,"
        "owner,creator,description,created_at,accepted_at,resolved_at,closed_at,response_due,resolve_due,"
        "sla_state,satisfaction,resolution) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (no, code, c["name"], body.get("contractNo") or "", title, body.get("category") or "咨询", pri,
         "待受理", body.get("owner") or "", user["username"], body.get("description") or "",
         created, "", "", "", resp_due, res_due, "正常", 0, ""))
    cn.execute("INSERT INTO ticket_logs(ticket_no,action,content,operator,created_at) VALUES(?,?,?,?,?)",
               (no, "创建", "%s（%s）" % (title, pri), user["username"], created))
    op(cn, user["username"], "新建工单", "%s %s" % (no, title))
    emit(cn, "ticket.created", "ticket", no,
         {"no": no, "title": title, "priority": pri, "customerCode": code,
          "resolveDue": res_due}, user["username"])
    return ticket_view(one(cn, "SELECT * FROM tickets WHERE no=?", (no,)), map_names(cn))


@write_op
def api_ticket_action(cn, user, no, action, body):
    require(user, "service" if user["role"] == "service" else "write")
    r = one(cn, "SELECT * FROM tickets WHERE no=?", (no,))
    if not r:
        raise ApiError("工单不存在", 404)
    if action == "accept":
        if r["status"] != "待受理":
            raise ApiError("只有待受理工单可以受理，当前为「%s」" % r["status"])
        cn.execute("UPDATE tickets SET status='处理中', owner=?, accepted_at=? WHERE no=?",
                   (user["username"], now(), no))
        cn.execute("INSERT INTO ticket_logs(ticket_no,action,content,operator,created_at)"
                   " VALUES(?,?,?,?,?)", (no, "受理", body.get("comment") or "已受理", user["username"], now()))
        emit(cn, "ticket.accepted", "ticket", no, {"no": no, "owner": user["username"]}, user["username"])
    elif action == "resolve":
        if r["status"] in ("已解决", "已关闭"):
            raise ApiError("工单已解决/关闭，无需重复操作")
        resolution = (body.get("resolution") or "").strip()
        if not resolution:
            raise ApiError("解决工单必须填写处理结论")
        cn.execute("UPDATE tickets SET status='已解决', resolved_at=?, resolution=?, owner=? WHERE no=?",
                   (now(), resolution, r["owner"] or user["username"], no))
        cn.execute("INSERT INTO ticket_logs(ticket_no,action,content,operator,created_at)"
                   " VALUES(?,?,?,?,?)", (no, "解决", resolution, user["username"], now()))
        emit(cn, "ticket.resolved", "ticket", no,
             {"no": no, "resolution": resolution, "customerCode": r["customer_code"]}, user["username"])
    elif action == "close":
        if r["status"] == "已关闭":
            raise ApiError("工单已关闭")
        sat = int(body.get("satisfaction") or r["satisfaction"] or 0)
        if sat and not 1 <= sat <= 5:
            raise ApiError("满意度只能是 1~5")
        cn.execute("UPDATE tickets SET status='已关闭', closed_at=?, satisfaction=? WHERE no=?",
                   (now(), sat, no))
        cn.execute("INSERT INTO ticket_logs(ticket_no,action,content,operator,created_at)"
                   " VALUES(?,?,?,?,?)", (no, "关闭", "满意度 %d 分" % sat if sat else "客户确认关闭",
                                          user["username"], now()))
        emit(cn, "ticket.closed", "ticket", no, {"no": no, "satisfaction": sat}, user["username"])
    elif action == "comment":
        content = (body.get("content") or "").strip()
        if not content:
            raise ApiError("回复内容不能为空")
        cn.execute("INSERT INTO ticket_logs(ticket_no,action,content,operator,created_at)"
                   " VALUES(?,?,?,?,?)", (no, "回复", content, user["username"], now()))
    else:
        raise ApiError("不支持的动作：%s" % action)
    op(cn, user["username"], "工单操作", "%s %s" % (no, action))
    return ticket_view(one(cn, "SELECT * FROM tickets WHERE no=?", (no,)), map_names(cn))


# ---------------------------------------------------------------- 市场活动
@with_db
def api_campaigns(cn, user, q):
    names = map_names(cn)
    out = []
    for r in rows(cn, "SELECT * FROM campaigns ORDER BY start_date DESC"):
        leads = one(cn, "SELECT COUNT(*) c FROM campaign_members WHERE campaign_code=? AND lead_no<>''",
                    (r["code"],))["c"]
        if not leads:
            leads = one(cn, "SELECT COUNT(*) c FROM leads WHERE campaign_code=?", (r["code"],))["c"]
        won = one(cn, "SELECT COALESCE(SUM(o.amount),0) s, COUNT(*) c FROM opportunities o "
                      "WHERE o.status='赢单' AND (o.campaign_code=? OR o.customer_code IN "
                      "(SELECT customer_code FROM campaign_members WHERE campaign_code=? AND customer_code<>''))",
                  (r["code"], r["code"]))
        roi = crm.campaign_roi(r["cost"], won["s"], leads)
        out.append({
            "code": r["code"], "name": r["name"], "kind": r["kind"], "channel": r["channel"],
            "startDate": r["start_date"], "endDate": r["end_date"], "budget": crm.r2(r["budget"]),
            "cost": crm.r2(r["cost"]), "targetLeads": r["target_leads"], "owner": r["owner"],
            "ownerName": names.get(r["owner"], r["owner"] or ""), "status": r["status"],
            "remark": r["remark"], "leads": roi["leads"], "wonAmount": roi["revenue"],
            "wonCount": won["c"], "roi": roi["roi"], "cpl": roi["cpl"],
            "budgetUsage": crm.ratio(r["cost"], r["budget"]),
            "leadRate": crm.ratio(leads, r["target_leads"]),
        })
    return {"list": out, "total": len(out)}


@write_op
def api_campaign_create(cn, user, body):
    require(user, "marketing" if user["role"] == "marketing" else "write")
    name = (body.get("name") or "").strip()
    if not name:
        raise ApiError("活动名称不能为空")
    base = one(cn, "SELECT COUNT(*) c FROM campaigns")["c"]
    code = body.get("code") or "CP-%s-%02d" % (today()[:4], base + 1)
    if one(cn, "SELECT code FROM campaigns WHERE code=?", (code,)):
        raise ApiError("活动编码已存在：%s" % code, 409)
    cn.execute("INSERT INTO campaigns(code,name,kind,channel,start_date,end_date,budget,cost,"
               "target_leads,owner,status,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               (code, name, body.get("kind") or "线上投放", body.get("channel") or "",
                body.get("startDate") or today(), body.get("endDate") or today(),
                crm.r2(body.get("budget") or 0), crm.r2(body.get("cost") or 0),
                int(body.get("targetLeads") or 0), body.get("owner") or user["username"],
                body.get("status") or "进行中", body.get("remark") or ""))
    op(cn, user["username"], "新建市场活动", "%s %s" % (code, name))
    return {"code": code, "name": name}


# ---------------------------------------------------------------- 报表
@with_db
def api_report_funnel(cn, user, q):
    opps = rows(cn, "SELECT * FROM opportunities")
    f = crm.funnel(opps)
    f["conversion"] = crm.conversion(f["stages"])
    f["byOwner"] = []
    for r in rows(cn, "SELECT owner, COUNT(*) c, SUM(amount) s FROM opportunities "
                      "WHERE status='进行中' GROUP BY owner"):
        f["byOwner"].append({"owner": r["owner"], "ownerName": user_name(cn, r["owner"]),
                             "count": r["c"], "amount": crm.r2(r["s"])})
    f["threshold"] = rule_value(cn, "win_rate_alert", 0.35)
    return f


@with_db
def api_report_performance(cn, user, q):
    period = (q.get("period") or [today()[:7]])[0]
    names = map_names(cn)
    out = []
    for u in rows(cn, "SELECT * FROM users WHERE status='在职' AND role IN ('sales','sales_director')"):
        won = rows(cn, "SELECT * FROM opportunities WHERE owner=? AND status='赢单' "
                       "AND SUBSTR(closed_at,1,7)=?", (u["username"], period))
        open_rows = rows(cn, "SELECT * FROM opportunities WHERE owner=? AND status='进行中'",
                         (u["username"],))
        t = one(cn, "SELECT amount FROM targets WHERE owner=? AND period=?", (u["username"], period))
        target = crm.r2(t["amount"]) if t else 0.0
        won_amt = crm.r2(sum(float(x["amount"]) for x in won))
        out.append({
            "owner": u["username"], "ownerName": names.get(u["username"], u["username"]),
            "target": target, "wonAmount": won_amt, "wonCount": len(won),
            "rate": crm.ratio(won_amt, target),
            "openAmount": crm.r2(sum(float(x["amount"]) for x in open_rows)),
            "openCount": len(open_rows),
            "weighted": crm.r2(sum(crm.weighted(x["amount"], x["probability"]) for x in open_rows)),
            "avgDeal": crm.ratio(won_amt, len(won)),
            "paidAmount": crm.r2(one(
                cn, "SELECT COALESCE(SUM(p.amount),0) s FROM payments p JOIN contracts c ON c.no=p.contract_no "
                    "WHERE c.owner=? AND SUBSTR(p.pay_date,1,7)=?", (u["username"], period))["s"]),
        })
    out.sort(key=lambda x: -x["wonAmount"])
    return {"period": period, "list": out,
            "totalTarget": crm.r2(sum(x["target"] for x in out)),
            "totalWon": crm.r2(sum(x["wonAmount"] for x in out))}


@with_db
def api_report_source(cn, user, q):
    out = []
    for r in rows(cn, "SELECT source, COUNT(*) c FROM leads GROUP BY source ORDER BY c DESC"):
        src = r["source"]
        won = one(cn, "SELECT COUNT(*) c, COALESCE(SUM(o.amount),0) s FROM opportunities o "
                      "JOIN customers cu ON cu.code=o.customer_code "
                      "WHERE o.status='赢单' AND cu.source=?", (src,))
        conv = one(cn, "SELECT COUNT(*) c FROM leads WHERE source=? AND status='已转客户'", (src,))["c"]
        out.append({"source": src, "leads": r["c"], "converted": conv,
                    "conversionRate": crm.ratio(conv, r["c"]),
                    "wonCount": won["c"], "wonAmount": crm.r2(won["s"]),
                    "avgDeal": crm.ratio(won["s"], won["c"])})
    return {"list": out}


@with_db
def api_report_forecast(cn, user, q):
    months = int((q.get("months") or [rule_value(cn, "forecast_months", 3) or 3])[0])
    months = max(1, min(12, months))
    ms = crm.month_list(date.today().replace(day=1), months)
    opps = rows(cn, "SELECT * FROM opportunities WHERE status='进行中'")
    f = crm.forecast(opps, ms)
    total = {"amount": crm.r2(sum(x["amount"] for x in f)),
             "weighted": crm.r2(sum(x["weighted"] for x in f)),
             "count": sum(x["count"] for x in f)}
    return {"months": f, "total": total}


@with_db
def api_report_aging(cn, user, q):
    plans = rows(cn, "SELECT * FROM contract_plans")
    buckets = crm.aging_buckets(plans)
    by_customer = []
    for r in rows(cn, "SELECT t.customer_name, SUM(p.amount-p.paid_amount) s, COUNT(*) c "
                      "FROM contract_plans p JOIN contracts t ON t.no=p.contract_no "
                      "WHERE p.status LIKE '%逾期%' GROUP BY t.customer_code "
                      "ORDER BY s DESC LIMIT 10"):
        by_customer.append({"customerName": r["customer_name"], "amount": crm.r2(r["s"]),
                            "count": r["c"]})
    return {"buckets": buckets, "totalUnpaid": crm.r2(sum(buckets.values())),
            "overdue": crm.r2(sum(v for k, v in buckets.items() if k != "未到期")),
            "byCustomer": by_customer}


@with_db
def api_reports(cn, user, q):
    return {
        "funnel": api_report_funnel.__wrapped__(cn, user, q),
        "performance": api_report_performance.__wrapped__(cn, user, q),
        "source": api_report_source.__wrapped__(cn, user, q),
        "forecast": api_report_forecast.__wrapped__(cn, user, q),
        "aging": api_report_aging.__wrapped__(cn, user, q),
        "tickets": {
            "byPriority": rows(cn, "SELECT priority, COUNT(*) c FROM tickets GROUP BY priority"),
            "byCategory": rows(cn, "SELECT category, COUNT(*) c FROM tickets GROUP BY category"),
            "avgSatisfaction": crm.r2(one(
                cn, "SELECT COALESCE(AVG(satisfaction),0) s FROM tickets WHERE satisfaction>0")["s"]),
            "avgResolveHours": crm.r2(one(
                cn, "SELECT COALESCE(AVG((julianday(resolved_at)-julianday(created_at))*24),0) s "
                    "FROM tickets WHERE resolved_at<>''")["s"]),
        },
    }


# ---------------------------------------------------------------- 系统设置
@with_db
def api_settings(cn, user):
    return {"rules": rows(cn, "SELECT * FROM rules ORDER BY rowid"),
            "users": rows(cn, "SELECT username,display_name,role,team_code,phone,email,status FROM users"),
            "teams": rows(cn, "SELECT * FROM teams"),
            "targets": rows(cn, "SELECT * FROM targets ORDER BY period DESC, owner"),
            "integration": {
                "keys": one(cn, "SELECT COUNT(*) c FROM api_keys WHERE status='启用'")["c"],
                "webhooks": one(cn, "SELECT COUNT(*) c FROM webhooks WHERE status='启用'")["c"],
                "deliveries": one(cn, "SELECT COUNT(*) c FROM webhook_deliveries")["c"],
                "failed": one(cn, "SELECT COUNT(*) c FROM webhook_deliveries WHERE status='失败'")["c"],
            }}


@write_op
def api_rule_toggle(cn, user, code, body):
    if user["role"] != "admin":
        raise ApiError("仅系统管理员可调整业务规则", 403)
    r = one(cn, "SELECT * FROM rules WHERE code=?", (code,))
    if not r:
        raise ApiError("规则不存在：%s" % code, 404)
    if "enabled" in body:
        cn.execute("UPDATE rules SET enabled=? WHERE code=?", (1 if body["enabled"] else 0, code))
    if "value" in body:
        cn.execute("UPDATE rules SET value=? WHERE code=?", (float(body["value"]), code))
    op(cn, user["username"], "调整规则", "%s → %s" % (code, json.dumps(body, ensure_ascii=False)))
    return one(cn, "SELECT * FROM rules WHERE code=?", (code,))


@with_db
def api_logs(cn, user, q):
    return rows(cn, "SELECT * FROM op_logs ORDER BY id DESC LIMIT 200")


@with_db
def api_users(cn, user):
    return rows(cn, "SELECT username,display_name,role,team_code,phone,email,status FROM users ORDER BY role")


# ---------------------------------------------------------------- 集成
@with_db
def api_int_keys(cn, user):
    need_admin(user)
    out = []
    for r in rows(cn, "SELECT * FROM api_keys ORDER BY id DESC"):
        out.append({"id": r["id"], "name": r["name"], "keyPrefix": r["key_prefix"],
                    "scope": r["scope"], "owner": r["owner"], "status": r["status"],
                    "expiresAt": r["expires_at"], "lastUsedAt": r["last_used_at"],
                    "createdAt": r["created_at"]})
    return {"list": out, "total": len(out)}


@write_op
def api_int_key_create(cn, user, body):
    need_admin(user)
    name = (body.get("name") or "").strip()
    if not name:
        raise ApiError("Key 名称不能为空（建议写清对接方，如「金蝶云星空」）")
    scope = body.get("scope") or "read"
    if scope not in ("read", "write"):
        raise ApiError("scope 只能是 read 或 write")
    plain = "fyk_" + secrets.token_hex(20)
    kid = cn.execute("INSERT INTO api_keys(name,key_prefix,key_hash,scope,owner,status,expires_at,"
                     "last_used_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                     (name, plain[:12], db.sha256(plain), scope, user["username"], "启用",
                      body.get("expiresAt") or "", "", now())).lastrowid
    op(cn, user["username"], "新建 API Key", "%s（%s）" % (name, scope))
    return {"id": kid, "name": name, "key": plain, "scope": scope,
            "notice": "明文 Key 只在此次返回，请立即保存；服务端仅存哈希"}


@write_op
def api_int_key_revoke(cn, user, kid):
    need_admin(user)
    r = one(cn, "SELECT * FROM api_keys WHERE id=?", (kid,))
    if not r:
        raise ApiError("Key 不存在", 404)
    cn.execute("UPDATE api_keys SET status='吊销' WHERE id=?", (kid,))
    op(cn, user["username"], "吊销 API Key", r["name"])
    return {"id": kid, "status": "吊销"}


@with_db
def api_int_webhooks(cn, user):
    need_admin(user)
    out = rows(cn, "SELECT * FROM webhooks ORDER BY id DESC")
    for h in out:
        h["deliveryStats"] = {r["status"]: r["c"] for r in rows(
            cn, "SELECT status, COUNT(*) c FROM webhook_deliveries WHERE webhook_id=? GROUP BY status",
            (h["id"],))}
    return {"list": out, "events": ["lead.created", "lead.converted", "lead.assigned",
                                    "customer.created", "customer.updated",
                                    "opportunity.created", "opportunity.stage_changed",
                                    "opportunity.won", "quote.approved", "contract.signed",
                                    "payment.received", "ticket.created", "ticket.resolved",
                                    "ticket.closed"]}


@write_op
def api_int_webhook_save(cn, user, body, wid=None):
    need_admin(user)
    url = (body.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ApiError("回调地址必须以 http:// 或 https:// 开头")
    events = body.get("events")
    if isinstance(events, list):
        events = ",".join(events)
    events = events or "*"
    if wid:
        cn.execute("UPDATE webhooks SET name=?,url=?,events=?,status=? WHERE id=?",
                   (body.get("name") or "未命名", url, events, body.get("status") or "启用", wid))
        op(cn, user["username"], "更新 Webhook", url)
        wid2 = wid
    else:
        wid2 = cn.execute("INSERT INTO webhooks(name,url,events,secret,status,last_status,last_at,"
                          "fail_count,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                          (body.get("name") or "未命名", url, events,
                           body.get("secret") or secrets.token_hex(16), "启用", "", "", 0, now())).lastrowid
        op(cn, user["username"], "新建 Webhook", url)
    return one(cn, "SELECT * FROM webhooks WHERE id=?", (wid2,))


@write_op
def api_int_webhook_delete(cn, user, wid):
    need_admin(user)
    if not one(cn, "SELECT id FROM webhooks WHERE id=?", (wid,)):
        raise ApiError("Webhook 不存在", 404)
    cn.execute("DELETE FROM webhooks WHERE id=?", (wid,))
    op(cn, user["username"], "删除 Webhook", str(wid))
    return {"deleted": wid}


@write_op
def api_int_webhook_test(cn, user, wid):
    need_admin(user)
    h = one(cn, "SELECT * FROM webhooks WHERE id=?", (wid,))
    if not h:
        raise ApiError("Webhook 不存在", 404)
    payload = {"test": True, "at": now(), "note": "飞鹰 CRM 连通性测试"}
    cn.execute("INSERT INTO webhook_deliveries(webhook_id,event,payload,signature,status,attempts,"
               "http_code,error,next_at,created_at,delivered_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (wid, "webhook.test", json.dumps(payload, ensure_ascii=False),
                crm.sign_payload(h["secret"], str(int(time.time())),
                                 json.dumps(payload, ensure_ascii=False, sort_keys=True)),
                "待投递", 0, 0, "", now(), now(), ""))
    op(cn, user["username"], "测试 Webhook", h["url"])
    return {"queued": True, "webhookId": wid}


@with_db
def api_int_deliveries(cn, user, q):
    need_admin(user)
    status = (q.get("status") or ["全部"])[0]
    sql = "SELECT * FROM webhook_deliveries WHERE 1=1"
    args = []
    if status != "全部":
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY id DESC LIMIT 100"
    out = rows(cn, sql, args)
    for d in out:
        try:
            d["payload"] = json.loads(d["payload"])
        except Exception:
            pass
    return {"list": out, "total": len(out)}


@write_op
def api_int_delivery_retry(cn, user, did):
    need_admin(user)
    d = one(cn, "SELECT * FROM webhook_deliveries WHERE id=?", (did,))
    if not d:
        raise ApiError("投递记录不存在", 404)
    cn.execute("UPDATE webhook_deliveries SET status='待投递', next_at=?, error='' WHERE id=?",
               (now(), did))
    return {"id": did, "status": "待投递"}


@with_db
def api_int_mappings(cn, user, q):
    obj = (q.get("objType") or [""])[0]
    sql = "SELECT * FROM ext_mappings WHERE 1=1"
    args = []
    if obj:
        sql += " AND obj_type=?"
        args.append(obj)
    sql += " ORDER BY id DESC LIMIT 200"
    return {"list": rows(cn, sql, args)}


@write_op
def api_int_mapping_save(cn, user, body):
    require(user, "write")
    obj = (body.get("objType") or "").strip()
    local = (body.get("localNo") or "").strip()
    ext = (body.get("externalId") or "").strip()
    system = (body.get("system") or "").strip()
    if not obj or not local or not ext:
        raise ApiError("objType / localNo / externalId 均必填")
    exist = one(cn, "SELECT * FROM ext_mappings WHERE obj_type=? AND system=? AND external_id=?",
                (obj, system, ext))
    if exist:
        cn.execute("UPDATE ext_mappings SET local_no=? WHERE id=?", (local, exist["id"]))
        return {"id": exist["id"], "updated": True}
    mid = cn.execute("INSERT INTO ext_mappings(obj_type,local_no,external_id,system,created_at)"
                     " VALUES(?,?,?,?,?)", (obj, local, ext, system, now())).lastrowid
    op(cn, user["username"], "绑定外部 ID", "%s %s → %s" % (obj, local, ext))
    return {"id": mid, "updated": False}


@write_op
def api_int_resolve(cn, user, q):
    ext = (q.get("externalId") or [""])[0]
    system = (q.get("system") or [""])[0]
    sql = "SELECT * FROM ext_mappings WHERE external_id=?"
    args = [ext]
    if system:
        sql += " AND system=?"
        args.append(system)
    r = one(cn, sql, args)
    if not r:
        raise ApiError("未找到映射：%s" % ext, 404)
    return r


@with_db
def api_sync_changes(cn, user, q):
    obj = (q.get("object") or [""])[0]
    since = int((q.get("since") or ["0"])[0] or 0)
    limit = min(500, int((q.get("limit") or ["200"])[0] or 200))
    sql = "SELECT * FROM change_log WHERE id>?"
    args = [since]
    if obj:
        sql += " AND obj_type=?"
        args.append(obj)
    sql += " ORDER BY id LIMIT ?"
    args.append(limit + 1)
    data = rows(cn, sql, args)
    has_more = len(data) > limit
    data = data[:limit]
    for d in data:
        try:
            d["payload"] = json.loads(d["payload"])
        except Exception:
            pass
    return {"changes": data, "cursor": data[-1]["id"] if data else since, "hasMore": has_more,
            "count": len(data), "serverTime": now()}


@with_db
def api_integration_overview(cn, user):
    need_admin(user)
    return {
        "keys": one(cn, "SELECT COUNT(*) c FROM api_keys WHERE status='启用'")["c"],
        "webhooks": one(cn, "SELECT COUNT(*) c FROM webhooks WHERE status='启用'")["c"],
        "deliveries": one(cn, "SELECT COUNT(*) c FROM webhook_deliveries")["c"],
        "failed": one(cn, "SELECT COUNT(*) c FROM webhook_deliveries WHERE status='失败'")["c"],
        "pending": one(cn, "SELECT COUNT(*) c FROM webhook_deliveries WHERE status='待投递'")["c"],
        "changes": one(cn, "SELECT COUNT(*) c FROM change_log")["c"],
        "lastChange": one(cn, "SELECT MAX(changed_at) t FROM change_log")["t"],
        "mappings": one(cn, "SELECT COUNT(*) c FROM ext_mappings")["c"],
        "recent": rows(cn, "SELECT * FROM change_log ORDER BY id DESC LIMIT 12"),
    }


# ---------------------------------------------------------------- 导出
@with_db
def api_export_customers(cn, user):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["客户编码", "客户名称", "行业", "区域", "等级", "负责人", "健康分", "在谈商机数",
                "在谈金额", "合同额", "回款额", "最近跟进"])
    sc = scope_of(user)
    sql = "SELECT * FROM customers" + (" WHERE owner=?" if sc else "")
    for c in rows(cn, sql, (sc,) if sc else ()):
        agg = one(cn, "SELECT COUNT(*) c, COALESCE(SUM(amount),0) s FROM opportunities "
                      "WHERE customer_code=? AND status='进行中'", (c["code"],))
        con = one(cn, "SELECT COALESCE(SUM(amount),0) s FROM contracts WHERE customer_code=?",
                  (c["code"],))
        pay = one(cn, "SELECT COALESCE(SUM(amount),0) s FROM payments WHERE customer_code=?",
                  (c["code"],))
        w.writerow([c["code"], c["name"], c["industry"], c["region"], c["level"], c["owner"],
                    crm.r2(c["score"]), agg["c"], crm.r2(agg["s"]), crm.r2(con["s"]),
                    crm.r2(pay["s"]), c["last_follow_at"]])
    return {"csv": out.getvalue(), "filename": "customers.csv"}


@with_db
def api_export_opportunities(cn, user):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["商机编号", "商机名称", "客户", "金额", "阶段", "概率", "加权金额", "预计结单",
                "负责人", "状态", "竞品", "决策人"])
    for o in rows(cn, "SELECT * FROM opportunities ORDER BY expect_close_date"):
        w.writerow([o["no"], o["name"], o["customer_name"], crm.r2(o["amount"]), o["stage"],
                    crm.r4(o["probability"]), crm.weighted(o["amount"], o["probability"]),
                    o["expect_close_date"], o["owner"], o["status"], o["competitor"],
                    o["decision_maker"]])
    return {"csv": out.getvalue(), "filename": "opportunities.csv"}


# ---------------------------------------------------------------- OpenAPI
def openapi_spec():
    def op(summary, tag, perm="read", body=None, params=None):
        d = {"summary": summary, "tags": [tag],
             "responses": {"200": {"description": "成功"}},
             "security": [{"bearerAuth": []}]}
        if params:
            d["parameters"] = [{"name": k, "in": "query", "schema": {"type": "string"},
                                "description": v} for k, v in params.items()]
        if body:
            d["requestBody"] = {"content": {"application/json": {"schema": body}}}
        d["x-permission"] = perm
        return d

    S = lambda **kw: {"type": "object", "properties": kw}  # noqa: E731
    paths = {
        "/api/health": {"get": {"summary": "健康检查", "tags": ["系统"], "responses": {"200": {"description": "ok"}}}},
        "/api/auth/login": {"post": op("账号登录", "认证", "public",
                                       S(username={"type": "string"}, password={"type": "string"}))},
        "/api/auth/me": {"get": op("当前身份与权限点", "认证")},
        "/api/bootstrap": {"get": op("首屏数据（KPI / 漏斗 / 待办）", "系统")},
        "/api/leads": {"get": op("线索列表", "线索", params={"status": "状态", "kw": "关键字",
                                                          "page": "页码", "pageSize": "每页条数"}),
                       "post": op("新建线索", "线索", "write",
                                  S(name={"type": "string"}, phone={"type": "string"},
                                    email={"type": "string"}, source={"type": "string"},
                                    budget={"type": "number"}, owner={"type": "string"},
                                    force={"type": "boolean"}))},
        "/api/leads/{no}": {"get": op("线索详情（含查重与跟进）", "线索"),
                            "put": op("更新线索", "线索", "write")},
        "/api/leads/{no}/assign": {"post": op("分配线索（总监）", "线索", "write",
                                              S(owner={"type": "string"}))},
        "/api/leads/{no}/convert": {"post": op("线索转客户", "线索", "write")},
        "/api/leads/{no}/invalid": {"post": op("标记无效（需原因）", "线索", "write")},
        "/api/leads/{no}/recycle": {"post": op("回收进公海", "线索", "write")},
        "/api/leads/{no}/claim": {"post": op("领取公海线索", "线索", "write")},
        "/api/leads/check-dup": {"get": op("线索查重", "线索", params={"name": "公司名",
                                                                    "phone": "手机号",
                                                                    "email": "邮箱"})},
        "/api/customers": {"get": op("客户列表", "客户", params={"kw": "关键字", "level": "等级"}),
                           "post": op("新建客户", "客户", "write")},
        "/api/customers/{code}": {"get": op("客户 360（联系人/商机/合同/工单/时间线）", "客户")},
        "/api/contacts": {"get": op("联系人列表", "客户"), "post": op("新建联系人", "客户", "write")},
        "/api/opportunities": {"get": op("商机列表 + 漏斗", "商机", params={"stage": "阶段"}),
                               "post": op("新建商机", "商机", "write")},
        "/api/opportunities/{no}": {"get": op("商机详情（阶段闸口/报价/合同）", "商机")},
        "/api/opportunities/{no}/stage": {"post": op("推进阶段（含必填校验）", "商机", "write")},
        "/api/opportunities/{no}/close": {"post": op("赢单/输单", "商机", "write")},
        "/api/activities": {"get": op("跟进记录列表", "跟进", params={"objType": "对象类型",
                                                                  "objNo": "对象编号"}),
                            "post": op("新增跟进", "跟进", "write")},
        "/api/quotes": {"get": op("报价列表", "报价"), "post": op("新建报价（自动算折扣）", "报价", "write")},
        "/api/quotes/{no}/approve": {"post": op("批准报价（折扣超线时）", "报价", "approve")},
        "/api/quotes/{no}/reject": {"post": op("驳回报价", "报价", "approve")},
        "/api/quotes/{no}/send": {"post": op("发送报价", "报价", "write")},
        "/api/contracts": {"get": op("合同列表", "合同"), "post": op("新建合同（生成回款计划）", "合同", "write")},
        "/api/contracts/{no}/sign": {"post": op("合同签署（回写商机赢单）", "合同", "write")},
        "/api/payments": {"get": op("收款流水", "回款"), "post": op("登记收款（按计划核销）", "回款", "finance")},
        "/api/payments/plans": {"get": op("回款计划与账龄", "回款", params={"overdue": "只看逾期"})},
        "/api/tickets": {"get": op("工单列表（含 SLA）", "服务"), "post": op("新建工单", "服务", "write")},
        "/api/tickets/{no}/accept": {"post": op("受理工单", "服务", "write")},
        "/api/tickets/{no}/resolve": {"post": op("解决工单（需结论）", "服务", "write")},
        "/api/tickets/{no}/close": {"post": op("关闭工单（满意度）", "服务", "write")},
        "/api/campaigns": {"get": op("市场活动与 ROI", "营销"), "post": op("新建活动", "营销", "write")},
        "/api/reports": {"get": op("报表聚合（漏斗/业绩/来源/预测/账龄）", "报表")},
        "/api/reports/funnel": {"get": op("销售漏斗与转化", "报表")},
        "/api/reports/performance": {"get": op("业绩排行与目标达成", "报表", params={"period": "账期 YYYY-MM"})},
        "/api/reports/source": {"get": op("线索来源转化", "报表")},
        "/api/reports/forecast": {"get": op("销售预测（加权/乐观/悲观）", "报表", params={"months": "滚动月数"})},
        "/api/reports/aging": {"get": op("应收账龄", "报表")},
        "/api/settings": {"get": op("规则/用户/团队/集成概况", "系统")},
        "/api/rules/{code}": {"put": op("启停或调整规则阈值（管理员）", "系统", "admin")},
        "/api/logs": {"get": op("操作日志", "系统")},
        "/api/integration/keys": {"get": op("API Key 列表（脱敏）", "集成", "admin"),
                                  "post": op("新建 API Key（明文仅返回一次）", "集成", "admin")},
        "/api/integration/webhooks": {"get": op("Webhook 列表", "集成", "admin"),
                                      "post": op("新建 Webhook", "集成", "admin")},
        "/api/integration/deliveries": {"get": op("Webhook 投递日志", "集成", "admin",
                                                 params={"status": "待投递/成功/失败"})},
        "/api/integration/mappings": {"get": op("外部 ID 映射查询", "集成"),
                                      "post": op("绑定外部 ID", "集成", "write")},
        "/api/integration/resolve": {"get": op("按外部 ID 反查本地单号", "集成",
                                               params={"externalId": "外部 ID", "system": "来源系统"})},
        "/api/sync/changes": {"get": op("增量变更流（游标）", "集成",
                                       params={"object": "对象类型", "since": "游标", "limit": "条数"})},
        "/api/openapi.json": {"get": {"summary": "本契约（OpenAPI 3.0）", "tags": ["集成"],
                                      "responses": {"200": {"description": "ok"}}}},
    }
    return {
        "openapi": "3.0.3",
        "info": {"title": "飞鹰 CRM 开放接口", "version": VERSION,
                 "description": "客户/线索/商机/报价/合同/回款/工单/营销全流程 REST 接口。"
                                "鉴权支持用户会话 Token 与系统对接 API Key（Bearer fyk_...）。"
                                "变更通过 Webhook 推送与 /api/sync/changes 增量拉取两条通道对外。"},
        "servers": [{"url": "/", "description": "当前站点"}],
        "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
        "paths": paths,
    }


# ---------------------------------------------------------------- Webhook 投递
def _post_json(url, body, headers, timeout=5):
    """发送 JSON POST，返回 (http_code, err)。非 2xx 时 err 记状态码与响应片段。

    用 http.client 直连而不用 urllib：urllib 会把自定义头改写成 Title-Case，
    而对接方通常按文档里的 X-FYC-* 原文匹配，这里保持原始大小写发出去。
    """
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("回调地址不合法：%s" % url)
    cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    port = u.port or (443 if u.scheme == "https" else 80)
    path = (u.path or "/") + ("?" + u.query if u.query else "")
    hd = dict(headers)
    hd["Content-Length"] = str(len(body))
    conn = cls(u.hostname, port, timeout=timeout)
    try:
        conn.request("POST", path, body, hd)
        resp = conn.getresponse()
        code = resp.status
        snippet = resp.read(200).decode("utf-8", "ignore")
    finally:
        conn.close()
    err = "" if 200 <= code < 300 else "HTTP %s %s" % (code, snippet[:120])
    return code, err


def _deliver(delivery_id):
    cn = db.conn()
    try:
        d = one(cn, "SELECT * FROM webhook_deliveries WHERE id=?", (delivery_id,))
        if not d:
            return
        h = one(cn, "SELECT * FROM webhooks WHERE id=?", (d["webhook_id"],))
        if not h or h["status"] != "启用":
            return
        ts = str(int(time.time()))
        body = json.dumps({"id": d["id"], "event": d["event"], "createdAt": d["created_at"],
                           "data": json.loads(d["payload"] or "{}")},
                          ensure_ascii=False, sort_keys=True).encode("utf-8")
        sig = crm.sign_payload(h["secret"], ts, body.decode("utf-8"))
        code, err = 0, ""
        try:
            code, err = _post_json(h["url"], body, {
                "Content-Type": "application/json; charset=utf-8",
                "X-FYC-Event": d["event"],
                "X-FYC-Timestamp": ts,
                "X-FYC-Signature": "sha256=" + sig,
                "X-FYC-Delivery": str(d["id"]),
            }, timeout=5)
        except Exception as e:  # noqa: BLE001
            err = str(e)[:300]
        attempts = int(d["attempts"]) + 1
        okk = 200 <= code < 300
        with LOCK:
            if okk:
                cn.execute("UPDATE webhook_deliveries SET status='成功', attempts=?, http_code=?, "
                           "error='', delivered_at=? WHERE id=?", (attempts, code, now(), delivery_id))
                cn.execute("UPDATE webhooks SET last_status=?, last_at=?, fail_count=0 WHERE id=?",
                           ("成功 %d" % code, now(), h["id"]))
            else:
                retry = attempts < WEBHOOK_MAX_TRY
                nxt = (datetime.now() + timedelta(seconds=30 * (2 ** attempts))).strftime(
                    "%Y-%m-%d %H:%M:%S")
                cn.execute("UPDATE webhook_deliveries SET status=?, attempts=?, http_code=?, error=?, "
                           "next_at=? WHERE id=?",
                           ("待投递" if retry else "失败", attempts, code, err, nxt, delivery_id))
                cn.execute("UPDATE webhooks SET last_status=?, last_at=?, fail_count=fail_count+1 "
                           "WHERE id=?", ("失败：%s" % (err or code), now(), h["id"]))
            cn.commit()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    finally:
        cn.close()


def _worker_loop():
    while True:
        try:
            cn = db.conn()
            due = rows(cn, "SELECT id FROM webhook_deliveries WHERE status='待投递' AND next_at<=? "
                           "ORDER BY id LIMIT 20", (now(),))
            cn.close()
            for d in due:
                _deliver(d["id"])
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)


# ---------------------------------------------------------------- 路由表
ROUTES = [
    ("POST", r"^/api/auth/login$", lambda cn, u, b, q: api_login(cn, b), None),
    ("POST", r"^/api/auth/logout$", lambda cn, u, b, q: api_logout(cn, q.get("_token", [""])[0]), None),
    ("GET", r"^/api/auth/me$", lambda cn, u, b, q: api_me(cn, u), None),
    ("GET", r"^/api/bootstrap$", lambda cn, u, b, q: api_bootstrap(cn, u), None),
    # 线索
    ("GET", r"^/api/leads$", lambda cn, u, b, q: api_leads(cn, u, q), None),
    ("POST", r"^/api/leads$", lambda cn, u, b, q: api_lead_create(cn, u, b), None),
    ("GET", r"^/api/leads/check-dup$", lambda cn, u, b, q: api_lead_check_dup(cn, u, q), None),
    ("GET", r"^/api/leads/([\w\-]+)$", lambda cn, u, b, q, c: api_lead(cn, u, c), None),
    ("PUT", r"^/api/leads/([\w\-]+)$", lambda cn, u, b, q, c: api_lead_update(cn, u, c, b), None),
    ("POST", r"^/api/leads/([\w\-]+)/assign$", lambda cn, u, b, q, c: api_lead_assign(cn, u, c, b), None),
    ("POST", r"^/api/leads/([\w\-]+)/convert$", lambda cn, u, b, q, c: api_lead_convert(cn, u, c, b), None),
    ("POST", r"^/api/leads/([\w\-]+)/invalid$", lambda cn, u, b, q, c: api_lead_invalid(cn, u, c, b), None),
    ("POST", r"^/api/leads/([\w\-]+)/recycle$", lambda cn, u, b, q, c: api_lead_recycle(cn, u, c, b), None),
    ("POST", r"^/api/leads/([\w\-]+)/claim$", lambda cn, u, b, q, c: api_lead_claim(cn, u, c), None),
    # 客户
    ("GET", r"^/api/customers$", lambda cn, u, b, q: api_customers(cn, u, q), None),
    ("POST", r"^/api/customers$", lambda cn, u, b, q: api_customer_create(cn, u, b), None),
    ("GET", r"^/api/customers/([\w\-]+)$", lambda cn, u, b, q, c: api_customer(cn, u, c), None),
    ("PUT", r"^/api/customers/([\w\-]+)$", lambda cn, u, b, q, c: api_customer_update(cn, u, c, b), None),
    ("GET", r"^/api/contacts$", lambda cn, u, b, q: api_contacts(cn, u, q), None),
    ("POST", r"^/api/contacts$", lambda cn, u, b, q: api_contact_save(cn, u, b), None),
    ("PUT", r"^/api/contacts/(\d+)$", lambda cn, u, b, q, c: api_contact_save(cn, u, b, int(c)), None),
    ("DELETE", r"^/api/contacts/(\d+)$", lambda cn, u, b, q, c: api_contact_delete(cn, u, int(c)), None),
    # 商机
    ("GET", r"^/api/opportunities$", lambda cn, u, b, q: api_opportunities(cn, u, q), None),
    ("POST", r"^/api/opportunities$", lambda cn, u, b, q: api_opportunity_create(cn, u, b), None),
    ("GET", r"^/api/opportunities/([\w\-]+)$", lambda cn, u, b, q, c: api_opportunity(cn, u, c), None),
    ("PUT", r"^/api/opportunities/([\w\-]+)$", lambda cn, u, b, q, c: api_opportunity_update(cn, u, c, b), None),
    ("POST", r"^/api/opportunities/([\w\-]+)/stage$",
     lambda cn, u, b, q, c: api_opportunity_stage(cn, u, c, b), None),
    ("POST", r"^/api/opportunities/([\w\-]+)/close$",
     lambda cn, u, b, q, c: api_opportunity_close(cn, u, c, b), None),
    # 跟进
    ("GET", r"^/api/activities$", lambda cn, u, b, q: api_activities(cn, u, q), None),
    ("POST", r"^/api/activities$", lambda cn, u, b, q: api_activity_create(cn, u, b), None),
    ("POST", r"^/api/activities/(\d+)/done$", lambda cn, u, b, q, c: api_activity_done(cn, u, int(c)), None),
    # 产品
    ("GET", r"^/api/products$", lambda cn, u, b, q: api_products(cn, u, q), None),
    # 报价
    ("GET", r"^/api/quotes$", lambda cn, u, b, q: api_quotes(cn, u, q), None),
    ("POST", r"^/api/quotes$", lambda cn, u, b, q: api_quote_create(cn, u, b), None),
    ("GET", r"^/api/quotes/([\w\-]+)$", lambda cn, u, b, q, c: api_quote(cn, u, c), None),
    ("POST", r"^/api/quotes/([\w\-]+)/approve$", lambda cn, u, b, q, c: api_quote_approve(cn, u, c, b), None),
    ("POST", r"^/api/quotes/([\w\-]+)/reject$", lambda cn, u, b, q, c: api_quote_reject(cn, u, c, b), None),
    ("POST", r"^/api/quotes/([\w\-]+)/send$", lambda cn, u, b, q, c: api_quote_send(cn, u, c, b), None),
    ("POST", r"^/api/quotes/([\w\-]+)/accept$", lambda cn, u, b, q, c: api_quote_accept(cn, u, c, b), None),
    # 合同
    ("GET", r"^/api/contracts$", lambda cn, u, b, q: api_contracts(cn, u, q), None),
    ("POST", r"^/api/contracts$", lambda cn, u, b, q: api_contract_create(cn, u, b), None),
    ("GET", r"^/api/contracts/([\w\-]+)$", lambda cn, u, b, q, c: api_contract(cn, u, c), None),
    ("POST", r"^/api/contracts/([\w\-]+)/sign$", lambda cn, u, b, q, c: api_contract_sign(cn, u, c, b), None),
    ("POST", r"^/api/contracts/([\w\-]+)/terminate$",
     lambda cn, u, b, q, c: api_contract_terminate(cn, u, c, b), None),
    # 回款
    ("GET", r"^/api/payments$", lambda cn, u, b, q: api_payments(cn, u, q), None),
    ("POST", r"^/api/payments$", lambda cn, u, b, q: api_payment_create(cn, u, b), None),
    ("GET", r"^/api/payments/plans$", lambda cn, u, b, q: api_payment_plans(cn, u, q), None),
    # 工单
    ("GET", r"^/api/tickets$", lambda cn, u, b, q: api_tickets(cn, u, q), None),
    ("POST", r"^/api/tickets$", lambda cn, u, b, q: api_ticket_create(cn, u, b), None),
    ("GET", r"^/api/tickets/([\w\-]+)$", lambda cn, u, b, q, c: api_ticket(cn, u, c), None),
    ("POST", r"^/api/tickets/([\w\-]+)/(accept|resolve|close|comment)$",
     lambda cn, u, b, q, c, a: api_ticket_action(cn, u, c, a, b), None),
    # 营销
    ("GET", r"^/api/campaigns$", lambda cn, u, b, q: api_campaigns(cn, u, q), None),
    ("POST", r"^/api/campaigns$", lambda cn, u, b, q: api_campaign_create(cn, u, b), None),
    # 报表
    ("GET", r"^/api/reports$", lambda cn, u, b, q: api_reports(cn, u, q), None),
    ("GET", r"^/api/reports/funnel$", lambda cn, u, b, q: api_report_funnel(cn, u, q), None),
    ("GET", r"^/api/reports/performance$", lambda cn, u, b, q: api_report_performance(cn, u, q), None),
    ("GET", r"^/api/reports/source$", lambda cn, u, b, q: api_report_source(cn, u, q), None),
    ("GET", r"^/api/reports/forecast$", lambda cn, u, b, q: api_report_forecast(cn, u, q), None),
    ("GET", r"^/api/reports/aging$", lambda cn, u, b, q: api_report_aging(cn, u, q), None),
    # 系统
    ("GET", r"^/api/settings$", lambda cn, u, b, q: api_settings(cn, u), None),
    ("PUT", r"^/api/rules/([\w]+)$", lambda cn, u, b, q, c: api_rule_toggle(cn, u, c, b), None),
    ("GET", r"^/api/logs$", lambda cn, u, b, q: api_logs(cn, u, q), None),
    ("GET", r"^/api/users$", lambda cn, u, b, q: api_users(cn, u), None),
    # 集成
    ("GET", r"^/api/integration/overview$", lambda cn, u, b, q: api_integration_overview(cn, u), None),
    ("GET", r"^/api/integration/keys$", lambda cn, u, b, q: api_int_keys(cn, u), None),
    ("POST", r"^/api/integration/keys$", lambda cn, u, b, q: api_int_key_create(cn, u, b), None),
    ("DELETE", r"^/api/integration/keys/(\d+)$", lambda cn, u, b, q, c: api_int_key_revoke(cn, u, int(c)), None),
    ("GET", r"^/api/integration/webhooks$", lambda cn, u, b, q: api_int_webhooks(cn, u), None),
    ("POST", r"^/api/integration/webhooks$", lambda cn, u, b, q: api_int_webhook_save(cn, u, b), None),
    ("PUT", r"^/api/integration/webhooks/(\d+)$",
     lambda cn, u, b, q, c: api_int_webhook_save(cn, u, b, int(c)), None),
    ("DELETE", r"^/api/integration/webhooks/(\d+)$",
     lambda cn, u, b, q, c: api_int_webhook_delete(cn, u, int(c)), None),
    ("POST", r"^/api/integration/webhooks/(\d+)/test$",
     lambda cn, u, b, q, c: api_int_webhook_test(cn, u, int(c)), None),
    ("GET", r"^/api/integration/deliveries$", lambda cn, u, b, q: api_int_deliveries(cn, u, q), None),
    ("POST", r"^/api/integration/deliveries/(\d+)/retry$",
     lambda cn, u, b, q, c: api_int_delivery_retry(cn, u, int(c)), None),
    ("GET", r"^/api/integration/mappings$", lambda cn, u, b, q: api_int_mappings(cn, u, q), None),
    ("POST", r"^/api/integration/mappings$", lambda cn, u, b, q: api_int_mapping_save(cn, u, b), None),
    ("GET", r"^/api/integration/resolve$", lambda cn, u, b, q: api_int_resolve(cn, u, q), None),
    ("GET", r"^/api/sync/changes$", lambda cn, u, b, q: api_sync_changes(cn, u, q), None),
    # 导出
    ("GET", r"^/api/export/customers\.csv$", lambda cn, u, b, q: api_export_customers(cn, u), None),
    ("GET", r"^/api/export/opportunities\.csv$", lambda cn, u, b, q: api_export_opportunities(cn, u), None),
]


class Handler(SimpleHTTPRequestHandler):
    server_version = "FeiyingCRM/1.0"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=FRONTEND, **kw)

    def log_message(self, *a):
        pass

    def _send(self, code, payload, ctype="application/json; charset=utf-8", headers=None):
        body = payload if isinstance(payload, bytes) else json.dumps(
            payload, ensure_ascii=False, default=float).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            raise ApiError("请求体不是合法 JSON", 400)

    def _tokens(self):
        """收集本次请求携带的所有候选票据。

        为什么不止看 Authorization：某些反向代理会改写/注入 Authorization，
        导致正确票据被覆盖；因此同时接受自定义头、Cookie 与查询串，逐个尝试。
        """
        out = []
        for h in ("X-Fy-Token", "X-Auth-Token", "Authorization"):
            v = (self.headers.get(h) or "").strip()
            if not v:
                continue
            if v[:7].lower() == "bearer ":
                v = v[7:].strip()
            if v:
                out.append(v)
        for part in (self.headers.get("Cookie") or "").split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip() in ("fy_token", "token") and v.strip():
                    out.append(v.strip())
        seen, res = set(), []
        for t in out:
            if t not in seen:
                seen.add(t)
                res.append(t)
        return res

    def _dispatch(self, method):
        with LOCK:
            return self._route(method)

    def _route(self, method):
        parsed = urlparse(self.path)
        path = parsed.path
        for prefix in ("/crm", "/feiying"):
            if path.startswith(prefix + "/"):
                path = path[len(prefix):]
        query = parse_qs(parsed.query)
        body = {}
        if method in ("POST", "PUT", "DELETE", "PATCH"):
            try:
                body = self._read_body()
            except ApiError as e:
                return self._send(e.code, {"error": e.message})

        if path == "/api/health":
            info = {"status": "up", "version": VERSION, "time": now(),
                    "pid": os.getpid(), "uptime": int(time.time() - START_TS)}
            try:
                cn = db.conn()
                info["customers"] = cn.execute("SELECT COUNT(*) c FROM customers").fetchone()["c"]
                info["sessions"] = cn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"]
                info["journal"] = cn.execute("PRAGMA journal_mode").fetchone()[0]
                cn.close()
            except Exception as e:
                info["customers"] = 0
                info["dbError"] = str(e)[:120]
            return self._send(200, {"ok": True, "data": info})

        if path == "/api/openapi.json":
            return self._send(200, openapi_spec())

        tokens = self._tokens()
        if query.get("token"):
            tokens.append(query["token"][0])
        if isinstance(body, dict) and body.get("token"):
            tokens.append(str(body["token"]))
        token = tokens[0] if tokens else ""
        if method == "POST" and path == "/api/auth/logout":
            cn = db.conn()
            try:
                api_logout(cn, token)
            finally:
                cn.close()
            return self._send(200, {"ok": True, "data": {"loggedOut": True}})

        if not path.startswith("/api/"):
            return self._static(path)

        # 幂等：同一 Idempotency-Key 重复提交返回首次结果，避免对接方重试造成重复建单
        idem = self.headers.get("Idempotency-Key") or ""
        if idem and method == "POST":
            cn0 = db.conn()
            try:
                cached = one(cn0, "SELECT * FROM idem_keys WHERE key=?", (idem,))
            finally:
                cn0.close()
            if cached:
                return self._send(200, json.loads(cached["response"]),
                                  headers={"X-Idempotent-Replay": "true"})

        for m, pattern, fn, _ in ROUTES:
            if m != method:
                continue
            match = re.match(pattern, path)
            if not match:
                continue
            groups = match.groups()
            need_token = (method, path) not in OPEN_PATHS
            cn = db.conn()
            try:
                user = None
                for tk in tokens:
                    user = auth_user(cn, tk)
                    if user:
                        token = tk
                        break
                if need_token and not user:
                    return self._send(401, {"error": "未登录或会话已过期"})
                if user:
                    rate_check(user)
                query["_token"] = [token]
                args = [cn, user, body, query] + list(groups)
                data = fn(*args)
                if isinstance(data, dict) and "csv" in data:
                    csv_body = ("\ufeff" + data["csv"]).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition",
                                     "attachment; filename*=UTF-8''" + quote(data["filename"]))
                    self.send_header("Content-Length", str(len(csv_body)))
                    self.end_headers()
                    self.wfile.write(csv_body)
                    return None
                payload = {"ok": True, "data": data}
                if idem and method == "POST":
                    cn.execute("INSERT OR REPLACE INTO idem_keys(key,path,response,created_at)"
                               " VALUES(?,?,?,?)",
                               (idem, path, json.dumps(payload, ensure_ascii=False), now()))
                    cn.commit()
                return self._send(200, payload)
            except ApiError as e:
                out = {"error": e.message}
                out.update(e.extra)
                headers = {}
                if e.code == 429:
                    headers["Retry-After"] = "60"
                return self._send(e.code, out, headers=headers)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                return self._send(500, {"error": "服务异常：%s" % e})
            finally:
                cn.close()
        return self._send(404, {"error": "接口不存在：%s %s" % (method, path)})

    def _static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return None
        safe = path.replace("\\", "/").lstrip("/")
        if ".." in safe.split("/"):
            return self._send(403, {"error": "非法路径"})
        target = os.path.join(FRONTEND, *safe.split("/"))
        if not os.path.isfile(target):
            return self._send(404, {"error": "文件不存在"})
        ctype = "text/html; charset=utf-8"
        if target.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif target.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        with open(target, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)
        return None

    def do_GET(self):
        return self._dispatch("GET")

    def do_POST(self):
        return self._dispatch("POST")

    def do_PUT(self):
        return self._dispatch("PUT")

    def do_DELETE(self):
        return self._dispatch("DELETE")


def main():
    db.init_db()
    threading.Thread(target=_worker_loop, daemon=True).start()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"飞鹰 CRM v{VERSION} 已启动：http://{HOST}:{PORT}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()

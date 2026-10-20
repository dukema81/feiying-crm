# -*- coding: utf-8 -*-
"""飞泉 SCM · REST 服务（标准库 http.server + sqlite3，零第三方依赖）

约定
- 成功 {"ok": true, "data": ...}；失败 {"error": "中文原因"}（可附带 dups / missing 等提示字段）
- 鉴权：用户会话 Token 与 API Key（系统对接，前缀 fqk_）；票据支持多通道（头 / Cookie / 查询串），
  避免反向代理改写 Authorization 导致页面掉登录
- 并发：SQLite 单写者，所有 /api/ 请求整段串行化（RLock）
- 集成：每次业务变更写 change_log（增量同步）+ 生成 Webhook 投递任务（后台线程退避重试）
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
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse
from http.server import BaseHTTPRequestHandler

import db
import scm

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE_DIR)
FRONTEND = os.path.join(ROOT, "frontend")
PORT = int(os.environ.get("FEIQUAN_PORT") or os.environ.get("PORT") or "8019")
HOST = os.environ.get("FEIQUAN_HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
LOCK = threading.RLock()
VERSION = "1.0.0"
START_TS = time.time()

OPEN_PATHS = {("POST", "/api/auth/login"), ("GET", "/api/health"), ("GET", "/api/openapi.json")}
_RATE = {}
RATE_LIMIT = 240
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
    if not scm.can(user["role"], perm):
        raise ApiError("当前角色（%s）无权执行该操作" % scm.ROLE_LABEL.get(user["role"], user["role"]), 403)


def need_admin(user):
    if user["role"] != "admin":
        raise ApiError("仅系统管理员可操作集成配置", 403)


def scope_of(user):
    """数据范围：采购专员只能看自己名下单据，其余角色全域可读。"""
    if user["role"] == "buyer":
        return user["username"]
    return None


# ---------------------------------------------------------------- 鉴权
def auth_user(cn, token):
    if not token:
        return None
    if token.startswith("fqk_"):
        k = one(cn, "SELECT * FROM api_keys WHERE key_hash=? AND status='启用'", (scm.sha256(token),))
        if not k:
            return None
        if k["expires_at"] and k["expires_at"][:10] < today():
            return None
        cn.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (now(), k["id"]))
        cn.commit()
        return {"username": k["owner"] or "api", "displayName": k["name"],
                "role": "admin" if k["scope"] == "write" else "warehouse",
                "roleLabel": "API Key（%s）" % ("读写" if k["scope"] == "write" else "只读"),
                "authType": "apikey", "keyId": k["id"], "scope": k["scope"]}
    s = one(cn, "SELECT * FROM sessions WHERE token=?", (token,))
    if not s:
        return None
    u = one(cn, "SELECT * FROM users WHERE username=?", (s["username"],))
    if not u:
        return None
    return {"username": u["username"], "displayName": u["display_name"], "role": u["role"],
            "roleLabel": scm.ROLE_LABEL.get(u["role"], u["role"]), "authType": "session"}


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
    body = scm.dumps(payload)
    cn.execute("INSERT INTO change_log(obj_type,obj_no,op,actor,payload,changed_at) VALUES(?,?,?,?,?,?)",
               (obj_type, obj_no, "upsert", actor, body, now()))
    hooks = rows(cn, "SELECT * FROM webhooks WHERE status='启用'")
    for h in hooks:
        evs = [x.strip() for x in str(h["events"] or "*").split(",") if x.strip()]
        if "*" not in evs and event not in evs:
            continue
        sig = scm.sign_payload(h["secret"], str(int(time.time())),
                               json.dumps({"event": event, "data": payload}, ensure_ascii=False,
                                          sort_keys=True))
        cn.execute("INSERT INTO webhook_deliveries(webhook_id,event,payload,signature,status,attempts,"
                   "http_code,error,next_at,created_at,delivered_at)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (h["id"], event, body, sig, "待投递", 0, 0, "", now(), now(), ""))


def next_no(cn, kind, table, column="no"):
    head = scm.doc_no(kind, today(), 0).rsplit("-", 1)[0] + "-"
    r = one(cn, "SELECT MAX(%s) m FROM %s WHERE %s LIKE ?" % (column, table, column), (head + "%",))
    seq = 0
    if r and r["m"]:
        tail = str(r["m"])[len(head):]
        digits = "".join(ch for ch in tail if ch.isdigit())
        seq = int(digits) if digits else 0
    return scm.doc_no(kind, today(), seq + 1)


def user_name(cn, username):
    if not username:
        return ""
    u = one(cn, "SELECT display_name FROM users WHERE username=?", (username,))
    return u["display_name"] if u else username


def map_names(cn):
    return {r["username"]: r["display_name"] for r in rows(cn, "SELECT username,display_name FROM users")}


# ---------------------------------------------------------------- 视图
def sup_view(r, names=None, quals=None):
    names = names or {}
    quals = quals if quals is not None else []
    warn = [q for q in quals if scm.qual_state(q["expire_at"], today(),
                                              int(rule_warn_days_cache.get("v", 30))) in ("临期", "过期")]
    return {
        "code": r["code"], "name": r["name"], "shortName": r["short_name"], "category": r["category"],
        "level": r["level"], "status": r["status"], "score": scm.r2(r["score"]), "health": r["health"],
        "taxNo": r["tax_no"], "contact": r["contact"], "phone": r["phone"], "email": r["email"],
        "address": r["address"], "region": r["region"], "paymentTerms": r["payment_terms"],
        "leadDays": r["lead_days"], "capacity": r["capacity"], "currency": r["currency"],
        "remark": r["remark"], "createdAt": r["created_at"], "updatedAt": r["updated_at"],
        "qualCount": len(quals), "qualWarn": len(warn),
        "qualWorst": ("过期" if any(q["expire_at"] and scm.qual_state(q["expire_at"], today()) == "过期"
                                   for q in quals) else ("临期" if warn else "有效")),
    }


rule_warn_days_cache = {"v": 30}


def mat_view(r, on_hand=None, safety=None):
    safety = float(r["safety_stock"] if safety is None else safety)
    reorder = scm.reorder_point(r["avg_daily_usage"], r["lead_days"], safety)
    oh = float(r["on_hand"] if on_hand is None else on_hand) if (on_hand is not None or "on_hand" in r) else None
    return {
        "code": r["code"], "name": r["name"], "spec": r["spec"], "unit": r["unit"],
        "category": r["category"], "abc": r["abc"], "standardPrice": scm.r2(r["standard_price"]),
        "lastPrice": scm.r2(r["last_price"]), "leadDays": r["lead_days"],
        "safetyStock": scm.r2(r["safety_stock"]), "maxStock": scm.r2(r["max_stock"]),
        "minOrderQty": scm.r2(r["min_order_qty"]), "avgDailyUsage": scm.r2(r["avg_daily_usage"]),
        "mainSupplier": r["main_supplier"], "status": r["status"], "remark": r["remark"],
        "createdAt": r["created_at"], "updatedAt": r["updated_at"],
        "reorderPoint": scm.r2(reorder),
        "onHand": None if oh is None else scm.r2(oh),
        "coverageDays": None if oh is None else scm.coverage_days(oh, r["avg_daily_usage"]),
        "state": None if oh is None else scm.stock_state(oh, safety, reorder, r["avg_daily_usage"],
                                                         r["max_stock"]),
    }


def req_view(r, items=None, names=None):
    names = names or {}
    items = items or []
    return {
        "no": r["no"], "dept": r["dept"], "applicant": r["applicant"],
        "applicantName": names.get(r["applicant"], r["applicant"] or ""),
        "purpose": r["purpose"], "needDate": r["need_date"], "amount": scm.r2(r["amount"]),
        "status": r["status"], "approver": r["approver"],
        "approverName": names.get(r["approver"], r["approver"] or ""),
        "approvedAt": r["approved_at"], "rejectReason": r["reject_reason"],
        "convertedNo": r["converted_no"], "remark": r["remark"],
        "createdAt": r["created_at"], "updatedAt": r["updated_at"],
        "itemCount": len(items),
        "items": [{"id": i["id"], "materialCode": i["material_code"], "materialName": i["material_name"],
                   "spec": i["spec"], "unit": i["unit"], "qty": scm.r2(i["qty"]),
                   "estPrice": scm.r2(i["est_price"]), "amount": scm.r2(i["amount"]),
                   "remark": i["remark"]} for i in items],
    }


def po_view(r, items=None, names=None, receipts=None):
    names = names or {}
    items = items or []
    receipts = receipts or []
    ordered = float(r["ordered_qty"] or 0)
    received = float(r["received_qty"] or 0)
    overdue = bool(r["promise_date"] and r["promise_date"] < today()
                   and r["status"] in ("已下单", "部分到货"))
    return {
        "no": r["no"], "supplierCode": r["supplier_code"], "supplierName": r["supplier_name"],
        "reqNo": r["req_no"], "rfqNo": r["rfq_no"], "title": r["title"], "amount": scm.r2(r["amount"]),
        "currency": r["currency"], "status": r["status"], "stageIndex": scm.po_index(r["status"]),
        "promiseDate": r["promise_date"], "owner": r["owner"],
        "ownerName": names.get(r["owner"], r["owner"] or ""), "approver": r["approver"],
        "approverName": names.get(r["approver"], r["approver"] or ""),
        "approvedAt": r["approved_at"], "orderedAt": r["ordered_at"],
        "orderedQty": scm.r2(ordered), "receivedQty": scm.r2(received),
        "receivedAmount": scm.r2(r["received_amount"]), "invoicedAmount": scm.r2(r["invoiced_amount"]),
        "matchResult": r["match_result"], "closedAt": r["closed_at"],
        "cancelReason": r["cancel_reason"], "remark": r["remark"],
        "createdAt": r["created_at"], "updatedAt": r["updated_at"],
        "receiveRate": scm.receive_rate(ordered, received),
        "overdue": overdue,
        "delayDays": scm.delay_days(r["promise_date"], today()) if overdue else 0,
        "itemCount": int(r["item_count"]) if r.get("item_count") is not None else len(items),
        "receiptCount": int(r["receipt_count"]) if r.get("receipt_count") is not None else len(receipts),
        "canAdvance": [s for s in scm.PO_FLOW if scm.can_move_po(r["status"], s)[0]],
        "items": [{"id": i["id"], "materialCode": i["material_code"], "materialName": i["material_name"],
                   "spec": i["spec"], "unit": i["unit"], "qty": scm.r2(i["qty"]),
                   "price": scm.r2(i["price"]), "amount": scm.r2(i["amount"]),
                   "receivedQty": scm.r2(i["received_qty"]), "promiseDate": i["promise_date"],
                   "remark": i["remark"]} for i in items],
        "receipts": [{"no": x["no"], "status": x["status"], "receivedAt": x["received_at"],
                      "posterAt": x["posted_at"]} for x in receipts],
    }


def receipt_view(r, items=None, names=None):
    names = names or {}
    items = items or []
    ok = sum(float(i["ok_qty"] or 0) for i in items)
    ng = sum(float(i["ng_qty"] or 0) for i in items)
    return {
        "no": r["no"], "poNo": r["po_no"], "supplierCode": r["supplier_code"],
        "supplierName": r["supplier_name"], "warehouse": r["warehouse"], "status": r["status"],
        "inspectedBy": r["inspected_by"],
        "inspectedName": names.get(r["inspected_by"], r["inspected_by"] or ""),
        "inspectResult": r["inspect_result"], "receivedAt": r["received_at"],
        "postedAt": r["posted_at"], "remark": r["remark"],
        "createdAt": r["created_at"], "updatedAt": r["updated_at"],
        "okQty": scm.r2(ok), "ngQty": scm.r2(ng),
        "passRate": scm.inspect_rate(ok, ng),
        "items": [{"id": i["id"], "materialCode": i["material_code"], "materialName": i["material_name"],
                   "unit": i["unit"], "qty": scm.r2(i["qty"]), "okQty": scm.r2(i["ok_qty"]),
                   "ngQty": scm.r2(i["ng_qty"]), "price": scm.r2(i["price"]),
                   "amount": scm.r2(i["amount"]), "batch": i["batch"], "expireAt": i["expire_at"],
                   "remark": i["remark"]} for i in items],
    }


def invoice_view(r, po=None):
    po = po or {}
    due = r["due_date"] or ""
    return {
        "no": r["no"], "poNo": r["po_no"], "supplierCode": r["supplier_code"],
        "supplierName": r["supplier_name"], "invoiceNo": r["invoice_no"],
        "amount": scm.r2(r["amount"]), "taxRate": scm.r4(r["tax_rate"]),
        "invoiceDate": r["invoice_date"], "dueDate": due, "status": r["status"],
        "matchResult": r["match_result"], "diffAmount": scm.r2(r["diff_amount"]),
        "diffRate": scm.r4(r["diff_rate"]), "paidAmount": scm.r2(r["paid_amount"]),
        "paidAt": r["paid_at"], "remark": r["remark"],
        "createdAt": r["created_at"], "updatedAt": r["updated_at"],
        "overdueDays": scm.overdue_days(due, today()),
        "payState": scm.payable_state(due, r["paid_amount"], today()),
        "poAmount": scm.r2(po.get("amount", 0)),
        "receivedAmount": scm.r2(po.get("received_amount", 0)),
        "tolerance": 0.02,
    }


def stock_view(r, mat=None):
    mat = mat or {}
    safety = float(mat.get("safety_stock", 0) or 0)
    reorder = scm.reorder_point(mat.get("avg_daily_usage", 0), mat.get("lead_days", 0), safety)
    return {
        "id": r["id"], "materialCode": r["material_code"], "materialName": r["material_name"],
        "spec": r["spec"], "unit": r["unit"], "warehouse": r["warehouse"], "batch": r["batch"],
        "qty": scm.r2(r["qty"]), "locked": scm.r2(r["locked"]),
        "available": scm.available(r["qty"], r["locked"]),
        "unitCost": scm.r2(r["unit_cost"]),
        "amount": scm.r2(float(r["qty"] or 0) * float(r["unit_cost"] or 0)),
        "inDate": r["in_date"], "expireAt": r["expire_at"],
        "ageDays": scm.days_between(r["in_date"], today()) or 0,
        "abc": mat.get("abc", "C"), "safetyStock": scm.r2(safety),
        "reorderPoint": scm.r2(reorder),
        "state": scm.stock_state(r["qty"], safety, reorder, mat.get("avg_daily_usage", 0),
                                 mat.get("max_stock", 0)),
        "expiryState": scm.expiry_state(r["expire_at"], today()),
        "updatedAt": r["updated_at"],
    }


def rfq_view(r, items=None, quotes=None, names=None):
    names = names or {}
    items = items or []
    quotes = quotes or []
    best = min(quotes, key=lambda q: float(q["amount"] or 0)) if quotes else None
    return {
        "no": r["no"], "reqNo": r["req_no"], "title": r["title"], "status": r["status"],
        "deadline": r["deadline"], "owner": r["owner"],
        "ownerName": names.get(r["owner"], r["owner"] or ""),
        "awardedSupplier": r["awarded_supplier"], "awardedAmount": scm.r2(r["awarded_amount"]),
        "remark": r["remark"], "createdAt": r["created_at"], "updatedAt": r["updated_at"],
        "itemCount": len(items), "quoteCount": len(quotes),
        "bestAmount": scm.r2(best["amount"]) if best else 0.0,
        "bestSupplier": best["supplier_name"] if best else "",
        "spread": scm.r2((max(float(q["amount"] or 0) for q in quotes)
                          - min(float(q["amount"] or 0) for q in quotes)) if len(quotes) > 1 else 0),
        "items": [{"id": i["id"], "materialCode": i["material_code"], "materialName": i["material_name"],
                   "qty": scm.r2(i["qty"]), "unit": i["unit"]} for i in items],
        "quotes": [{"id": q["id"], "supplierCode": q["supplier_code"],
                    "supplierName": q["supplier_name"], "amount": scm.r2(q["amount"]),
                    "leadDays": q["lead_days"], "validDays": q["valid_days"],
                    "awarded": bool(q["awarded"]), "remark": q["remark"],
                    "createdAt": q["created_at"]} for q in quotes],
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
    cn.execute("INSERT INTO sessions(token,username,created_at) VALUES(?,?,?)", (token, username, now()))
    op(cn, username, "登录", "")
    return {"token": token, "username": username, "displayName": u["display_name"],
            "role": u["role"], "roleLabel": scm.ROLE_LABEL.get(u["role"], u["role"])}


@write_op
def api_logout(cn, token):
    if token:
        cn.execute("DELETE FROM sessions WHERE token=?", (token,))
    return {"loggedOut": True}


@with_db
def api_me(cn, user):
    return {"username": user["username"], "displayName": user["displayName"], "role": user["role"],
            "roleLabel": user["roleLabel"],
            "perms": sorted({p for p in ("read", "write", "approve", "stock", "finance", "admin")
                             if scm.can(user["role"], p)})}


# ---------------------------------------------------------------- 首屏
def _todos(cn, scope):
    out = []
    for r in rows(cn, "SELECT * FROM requisitions WHERE status='待审批' ORDER BY no DESC LIMIT 5"):
        out.append({"kind": "请购", "no": r["no"], "title": "%s · %s" % (r["purpose"], r["dept"]),
                    "tag": "待审批", "level": "gold", "route": "requisitions"})
    for r in rows(cn, "SELECT * FROM purchase_orders WHERE status='待审批' ORDER BY no DESC LIMIT 5"):
        out.append({"kind": "订单", "no": r["no"], "title": "%s · 待审批" % r["supplier_name"],
                    "tag": "待审批", "level": "gold", "route": "orders"})
    for r in rows(cn, "SELECT * FROM purchase_orders WHERE status IN ('已下单','部分到货') "
                      "AND promise_date<>'' AND promise_date<? ORDER BY promise_date LIMIT 5", (today(),)):
        out.append({"kind": "交期", "no": r["no"],
                    "title": "%s 承诺 %s，已逾期 %d 天" % (r["supplier_name"], r["promise_date"],
                                                          scm.delay_days(r["promise_date"], today())),
                    "tag": "逾期", "level": "red", "route": "orders"})
    for r in rows(cn, "SELECT * FROM receipts WHERE status='待质检' ORDER BY no DESC LIMIT 4"):
        out.append({"kind": "质检", "no": r["no"], "title": "%s 到货待检" % r["supplier_name"],
                    "tag": "待检", "level": "gold", "route": "receipts"})
    for r in rows(cn, "SELECT * FROM invoices WHERE status IN ('差异挂起','待匹配') "
                      "ORDER BY no DESC LIMIT 4"):
        out.append({"kind": "结算", "no": r["no"],
                    "title": "%s 发票%s" % (r["supplier_name"], r["match_result"] or "待匹配"),
                    "tag": "待处理", "level": "gold", "route": "invoices"})
    for r in rows(cn, "SELECT s.*, m.safety_stock, m.avg_daily_usage, m.lead_days FROM stock s "
                      "LEFT JOIN materials m ON m.code=s.material_code "
                      "GROUP BY s.material_code HAVING SUM(s.qty) < MAX(m.safety_stock) LIMIT 4"):
        out.append({"kind": "缺料", "no": r["material_code"], "title": "%s 低于安全库存" % r["material_name"],
                    "tag": "补货", "level": "red", "route": "stock"})
    return out[:14]


@with_db
def api_bootstrap(cn, user):
    rule_warn_days_cache["v"] = int(rule_value(cn, "qual_warn_days", 30) or 30)
    names = map_names(cn)
    sc = scope_of(user)
    pos = rows(cn, "SELECT * FROM purchase_orders")
    if sc:
        pos = [p for p in pos if p["owner"] == sc]
    open_pos = [p for p in pos if p["status"] in ("待审批", "已下单", "部分到货")]
    open_amount = scm.r2(sum(float(p["amount"] or 0) for p in open_pos))
    month = today()[:7]
    recv_month = scm.r2(sum(float(p["received_amount"] or 0) for p in pos
                            if (p["ordered_at"] or "")[:7] == month))
    # 到货及时率（近 90 天到货）
    recs = rows(cn, "SELECT r.received_at, p.promise_date FROM receipts r "
                    "JOIN purchase_orders p ON p.no=r.po_no WHERE r.received_at>=?",
                (scm.add_days(today(), -90),))
    otr = scm.on_time_rate([{"promise": x["promise_date"], "actual": x["received_at"]} for x in recs])
    mats = {m["code"]: m for m in rows(cn, "SELECT * FROM materials")}
    stock_rows = rows(cn, "SELECT material_code, SUM(qty) q, SUM(qty*unit_cost) amt FROM stock "
                          "GROUP BY material_code")
    stock_value = scm.r2(sum(float(x["amt"] or 0) for x in stock_rows))
    shortages = []
    for x in stock_rows:
        m = mats.get(x["material_code"])
        if not m:
            continue
        reorder = scm.reorder_point(m["avg_daily_usage"], m["lead_days"], m["safety_stock"])
        if float(x["q"] or 0) < float(m["safety_stock"] or 0):
            shortages.append({"materialCode": m["code"], "materialName": m["name"], "onHand": scm.r2(x["q"]),
                              "safetyStock": scm.r2(m["safety_stock"]),
                              "gap": scm.shortage_qty(x["q"], m["safety_stock"], m["max_stock"]),
                              "reorderPoint": scm.r2(reorder), "unit": m["unit"],
                              "state": scm.stock_state(x["q"], m["safety_stock"], reorder,
                                                       m["avg_daily_usage"], m["max_stock"])})
    shortages.sort(key=lambda s: -s["gap"])
    # 近效期批次
    expiring = []
    for s in rows(cn, "SELECT * FROM stock WHERE expire_at<>'' AND qty>0"):
        st = scm.expiry_state(s["expire_at"], today(), int(rule_value(cn, "expiry_warn_days", 90) or 90))
        if st in ("近效期", "已过期"):
            expiring.append({"materialCode": s["material_code"], "materialName": s["material_name"],
                             "warehouse": s["warehouse"], "batch": s["batch"], "qty": scm.r2(s["qty"]),
                             "expireAt": s["expire_at"], "state": st,
                             "leftDays": scm.days_between(today(), s["expire_at"])})
    expiring.sort(key=lambda x: x["leftDays"] or 0)
    # 资质预警
    qual_warn = rows(cn, "SELECT q.*, s.name supplier_name FROM supplier_quals q "
                         "JOIN suppliers s ON s.code=q.supplier_code WHERE q.expire_at<>'' AND q.expire_at<? "
                         "ORDER BY q.expire_at", (scm.add_days(today(), 45),))
    # 逾期发票/应付
    invs = rows(cn, "SELECT * FROM invoices WHERE paid_amount=0")
    overdue_pay = [i for i in invs if scm.overdue_days(i["due_date"], today()) > 0]
    pending_inv = [i for i in invs if i["status"] in ("待匹配", "差异挂起")]
    # 六月趋势
    trend = []
    for k in range(5, -1, -1):
        mm = (date.today().replace(day=1) - timedelta(days=30 * k)).strftime("%Y-%m")
        amt = scm.r2(sum(float(p["amount"] or 0) for p in pos if (p["created_at"] or "")[:7] == mm))
        cnt = len([p for p in pos if (p["created_at"] or "")[:7] == mm])
        trend.append({"month": mm, "amount": amt, "count": cnt})
    # 供应商采购额 TOP
    top = rows(cn, "SELECT supplier_name name, ROUND(SUM(amount),2) amount, COUNT(*) c "
                   "FROM purchase_orders GROUP BY supplier_code ORDER BY amount DESC LIMIT 6")
    kpi = {
        "openAmount": open_amount, "openCount": len(open_pos),
        "pendingApprove": len([p for p in pos if p["status"] == "待审批"]),
        "monthReceive": recv_month,
        "onTimeRate": otr,
        "stockValue": stock_value,
        "shortageCount": len(shortages),
        "expiringCount": len(expiring),
        "qualWarnCount": len(qual_warn),
        "pendingInvoice": len(pending_inv),
        "overduePayable": scm.r2(sum(float(i["amount"] or 0) for i in overdue_pay)),
        "overduePayableCount": len(overdue_pay),
        "supplierCount": one(cn, "SELECT COUNT(*) c FROM suppliers")["c"],
        "activeSupplier": one(cn, "SELECT COUNT(*) c FROM suppliers WHERE status='已准入'")["c"],
        "materialCount": one(cn, "SELECT COUNT(*) c FROM materials")["c"],
        "receiptPending": one(cn, "SELECT COUNT(*) c FROM receipts WHERE status='待质检'")["c"],
        "monthIssue": scm.r2(sum(float(m["cost"] or 0) for m in rows(
            cn, "SELECT * FROM stock_moves WHERE type='领用出库' AND created_at>=?",
            (today()[:8] + "01",)))),
    }
    suppliers = rows(cn, "SELECT * FROM suppliers ORDER BY score DESC")
    levels = {}
    for s in suppliers:
        levels[s["level"]] = levels.get(s["level"], 0) + 1
    return {
        "today": today(), "user": {"username": user["username"], "displayName": user["displayName"],
                                   "role": user["role"], "roleLabel": user["roleLabel"]},
        "kpi": kpi, "todos": _todos(cn, sc), "trend": trend, "topSuppliers": top,
        "shortages": shortages[:8], "expiring": expiring[:8],
        "qualWarn": [{"supplierCode": q["supplier_code"], "supplierName": q["supplier_name"],
                      "name": q["name"], "expireAt": q["expire_at"],
                      "state": scm.qual_state(q["expire_at"], today()),
                      "leftDays": scm.days_between(today(), q["expire_at"])} for q in qual_warn[:8]],
        "poStages": [{"stage": s, "count": len([p for p in pos if p["status"] == s]),
                      "amount": scm.r2(sum(float(p["amount"] or 0) for p in pos if p["status"] == s))}
                     for s in scm.PO_FLOW],
        "supplierLevels": [{"level": k, "count": v} for k, v in sorted(levels.items())],
        "rules": rows(cn, "SELECT * FROM rules ORDER BY rowid"),
        "warehouses": rows(cn, "SELECT * FROM warehouses ORDER BY code"),
    }


# ---------------------------------------------------------------- 供应商
@with_db
def api_suppliers(cn, user, q):
    kw = (q.get("kw") or [""])[0].strip()
    category = (q.get("category") or ["全部"])[0]
    level = (q.get("level") or ["全部"])[0]
    status = (q.get("status") or ["全部"])[0]
    sql = "SELECT * FROM suppliers WHERE 1=1"
    args = []
    if kw:
        sql += " AND (name LIKE ? OR short_name LIKE ? OR code LIKE ? OR contact LIKE ?)"
        args += ["%" + kw + "%"] * 4
    if category != "全部":
        sql += " AND category=?"
        args.append(category)
    if level != "全部":
        sql += " AND level=?"
        args.append(level)
    if status != "全部":
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY score DESC, code"
    data = rows(cn, sql, args)
    names = map_names(cn)
    out = []
    for s in data:
        quals = rows(cn, "SELECT * FROM supplier_quals WHERE supplier_code=? ORDER BY expire_at",
                     (s["code"],))
        v = sup_view(s, names, quals)
        agg = one(cn, "SELECT COUNT(*) c, COALESCE(SUM(amount),0) s FROM purchase_orders "
                      "WHERE supplier_code=?", (s["code"],))
        v["poCount"] = agg["c"]
        v["poAmount"] = scm.r2(agg["s"])
        out.append(v)
    return {"list": out, "total": len(out),
            "facets": {"categories": sorted({s["category"] for s in data}),
                       "levels": scm.SUP_LEVELS,
                       "status": ["待准入", "已准入", "观察", "冻结"]}}


@write_op
def api_supplier_create(cn, user, body):
    require(user, "write")
    name = (body.get("name") or "").strip()
    if len(name) < 4:
        raise ApiError("供应商名称至少 4 个字（需为工商全称）")
    tax_no = (body.get("taxNo") or "").strip()
    if tax_no:
        dup = one(cn, "SELECT * FROM suppliers WHERE tax_no=?", (tax_no,))
        if dup:
            raise ApiError("税号已存在：%s（%s）" % (dup["name"], dup["code"]), 409,
                           dups=[{"code": dup["code"], "name": dup["name"], "reason": "税号相同"}])
    dups = []
    for s in rows(cn, "SELECT * FROM suppliers"):
        sim = scm.name_affinity(name, s["name"])
        if sim >= 0.62:
            dups.append({"code": s["code"], "name": s["name"], "score": sim,
                         "reason": "名称相似 %d%%" % round(sim * 100)})
    if dups:
        raise ApiError("疑似重复供应商，请确认后再提交（可勾选「仍要新建」）", 409, dups=dups)
    code = "SUP-%04d" % (one(cn, "SELECT COUNT(*) c FROM suppliers")["c"] + 1)
    cn.execute("INSERT INTO suppliers(code,name,short_name,category,level,status,score,health,tax_no,"
               "contact,phone,email,address,region,payment_terms,lead_days,capacity,currency,remark,"
               "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (code, name, body.get("shortName") or name[:6], body.get("category") or "其他",
                body.get("level") or "B", "待准入", 0, "正常", tax_no, body.get("contact") or "",
                body.get("phone") or "", body.get("email") or "", body.get("address") or "",
                body.get("region") or "", int(body.get("paymentTerms") or 30),
                int(body.get("leadDays") or 15), body.get("capacity") or "", "CNY",
                body.get("remark") or "", now(), now()))
    op(cn, user["username"], "新建供应商", "%s %s" % (code, name))
    emit(cn, "supplier.created", "supplier", code, {"code": code, "name": name,
                                                    "status": "待准入"}, user["username"])
    return {"code": code, "status": "待准入"}


@with_db
def api_supplier_detail(cn, user, code):
    s = one(cn, "SELECT * FROM suppliers WHERE code=?", (code,))
    if not s:
        raise ApiError("供应商不存在：%s" % code, 404)
    names = map_names(cn)
    quals = rows(cn, "SELECT * FROM supplier_quals WHERE supplier_code=? ORDER BY expire_at", (code,))
    scores = rows(cn, "SELECT * FROM supplier_scores WHERE supplier_code=? ORDER BY id DESC", (code,))
    pos = rows(cn, "SELECT * FROM purchase_orders WHERE supplier_code=? ORDER BY no DESC", (code,))
    recs = rows(cn, "SELECT * FROM receipts WHERE supplier_code=? ORDER BY no DESC LIMIT 20", (code,))
    invs = rows(cn, "SELECT * FROM invoices WHERE supplier_code=? ORDER BY no DESC LIMIT 20", (code,))
    v = sup_view(s, names, quals)
    total = sum(float(p["amount"] or 0) for p in pos)
    delivered = [p for p in pos if p["status"] in ("全部到货", "已结算")]
    # 交付及时率：以订单承诺日 vs 最近一张收货单到货日
    pairs = []
    for p in pos:
        rc = [r for r in recs if r["po_no"] == p["no"]]
        pairs.append({"promise": p["promise_date"], "actual": rc[0]["received_at"] if rc else ""})
    v.update({
        "quals": [{"id": x["id"], "name": x["name"], "no": x["no"], "issuedAt": x["issued_at"],
                   "expireAt": x["expire_at"], "remark": x["remark"],
                   "state": scm.qual_state(x["expire_at"], today(),
                                           int(rule_warn_days_cache.get("v", 30)))} for x in quals],
        "scores": [{"period": x["period"], "deliveryRate": scm.r4(x["delivery_rate"]),
                    "qualityRate": scm.r4(x["quality_rate"]), "priceIndex": scm.r4(x["price_index"]),
                    "responseRate": scm.r4(x["response_rate"]), "score": scm.r2(x["score"]),
                    "level": x["level"]} for x in scores],
        "poCount": len(pos),
        "poAmount": scm.r2(total),
        "openPoCount": len([p for p in pos if p["status"] in ("待审批", "已下单", "部分到货")]),
        "onTimeRate": scm.on_time_rate(pairs),
        "deliveredCount": len(delivered),
        "receipts": [{"no": r["no"], "poNo": r["po_no"], "status": r["status"],
                      "receivedAt": r["received_at"], "inspectResult": r["inspect_result"]} for r in recs],
        "invoices": [{"no": r["no"], "poNo": r["po_no"], "amount": scm.r2(r["amount"]),
                      "status": r["status"], "matchResult": r["match_result"],
                      "dueDate": r["due_date"], "paidAmount": scm.r2(r["paid_amount"])} for r in invs],
        "orders": [{"no": p["no"], "title": p["title"], "amount": scm.r2(p["amount"]),
                    "status": p["status"], "promiseDate": p["promise_date"],
                    "receivedQty": scm.r2(p["received_qty"]), "orderedQty": scm.r2(p["ordered_qty"])}
                   for p in pos[:12]],
        "materials": [{"code": m["code"], "name": m["name"], "spec": m["spec"], "unit": m["unit"],
                       "price": scm.r2(m["standard_price"])}
                      for m in rows(cn, "SELECT * FROM materials WHERE main_supplier=?", (code,))],
    })
    return v


@write_op
def api_supplier_update(cn, user, code, body):
    require(user, "write")
    s = one(cn, "SELECT * FROM suppliers WHERE code=?", (code,))
    if not s:
        raise ApiError("供应商不存在：%s" % code, 404)
    fields = [("name", "name"), ("shortName", "short_name"), ("category", "category"),
              ("contact", "contact"), ("phone", "phone"), ("email", "email"),
              ("address", "address"), ("region", "region"), ("capacity", "capacity"),
              ("remark", "remark"), ("taxNo", "tax_no")]
    sets, args = [], []
    for k, col in fields:
        if k in body:
            sets.append("%s=?" % col)
            args.append(body[k])
    for k, col in (("paymentTerms", "payment_terms"), ("leadDays", "lead_days")):
        if k in body:
            sets.append("%s=?" % col)
            args.append(int(body[k] or 0))
    if not sets:
        raise ApiError("没有需要更新的字段")
    sets.append("updated_at=?")
    args += [now(), code]
    cn.execute("UPDATE suppliers SET %s WHERE code=?" % ",".join(sets), args)
    op(cn, user["username"], "更新供应商", code)
    return {"code": code, "updated": True}


@write_op
def api_supplier_status(cn, user, code, body):
    require(user, "write")
    s = one(cn, "SELECT * FROM suppliers WHERE code=?", (code,))
    if not s:
        raise ApiError("供应商不存在：%s" % code, 404)
    target = (body.get("status") or "").strip()
    if target not in ("待准入", "已准入", "观察", "冻结"):
        raise ApiError("状态只能是：待准入 / 已准入 / 观察 / 冻结")
    if target == "已准入":
        if user["role"] not in ("admin", "purchase_director"):
            raise ApiError("只有采购总监或管理员可以做准入审批", 403)
        n = one(cn, "SELECT COUNT(*) c FROM supplier_quals WHERE supplier_code=?", (code,))["c"]
        if n == 0:
            raise ApiError("准入前需至少登记 1 项资质")
        expired = [q for q in rows(cn, "SELECT * FROM supplier_quals WHERE supplier_code=?", (code,))
                   if q["expire_at"] and scm.qual_state(q["expire_at"], today()) == "过期"]
        if expired:
            raise ApiError("存在已过期资质（%s），请先更新" % expired[0]["name"])
    cn.execute("UPDATE suppliers SET status=?, health=?, updated_at=? WHERE code=?",
               (target, "正常" if target == "已准入" else ("冻结" if target == "冻结" else "观察"),
                now(), code))
    op(cn, user["username"], "供应商状态", "%s → %s" % (code, target))
    emit(cn, "supplier.status_changed", "supplier", code,
         {"code": code, "status": target}, user["username"])
    return {"code": code, "status": target}


@write_op
def api_supplier_qual_add(cn, user, code, body):
    require(user, "write")
    if not one(cn, "SELECT code FROM suppliers WHERE code=?", (code,)):
        raise ApiError("供应商不存在：%s" % code, 404)
    name = (body.get("name") or "").strip()
    if not name:
        raise ApiError("资质名称不能为空")
    expire = (body.get("expireAt") or "").strip()
    if expire and scm.parse_date(expire) is None:
        raise ApiError("到期日格式应为 yyyy-MM-dd")
    qid = cn.execute("INSERT INTO supplier_quals(supplier_code,name,no,issued_at,expire_at,remark)"
                     " VALUES(?,?,?,?,?,?)",
                     (code, name, body.get("no") or "", body.get("issuedAt") or "", expire,
                      body.get("remark") or "")).lastrowid
    op(cn, user["username"], "登记资质", "%s %s" % (code, name))
    return {"id": qid, "state": scm.qual_state(expire, today(),
                                               int(rule_warn_days_cache.get("v", 30)))}


@write_op
def api_supplier_score_add(cn, user, code, body):
    require(user, "write")
    s = one(cn, "SELECT * FROM suppliers WHERE code=?", (code,))
    if not s:
        raise ApiError("供应商不存在：%s" % code, 404)
    period = (body.get("period") or "").strip() or "%s-Q%d" % (date.today().year, (date.today().month - 1) // 3 + 1)
    dr = float(body.get("deliveryRate") or 0)
    qr = float(body.get("qualityRate") or 0)
    pi = float(body.get("priceIndex") or 1)
    rr = float(body.get("responseRate") or 0)
    for name, v in (("交付及时率", dr), ("质量合格率", qr), ("响应达标率", rr)):
        if not (0 <= v <= 1):
            raise ApiError("%s需在 0~1 之间（如 0.95）" % name)
    score = scm.supplier_score(dr, qr, pi, rr)
    level = scm.supplier_level(score)
    cn.execute("INSERT INTO supplier_scores(supplier_code,period,delivery_rate,quality_rate,"
               "price_index,response_rate,score,level,remark,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (code, period, dr, qr, pi, rr, score, level, body.get("remark") or "", now()))
    cn.execute("UPDATE suppliers SET score=?, level=?, updated_at=? WHERE code=?", (score, level, now(), code))
    op(cn, user["username"], "录入绩效", "%s %s 得分 %.2f" % (code, period, score))
    emit(cn, "supplier.scored", "supplier", code,
         {"code": code, "period": period, "score": score, "level": level}, user["username"])
    return {"period": period, "score": score, "level": level}


# ---------------------------------------------------------------- 物料
@with_db
def api_materials(cn, user, q):
    kw = (q.get("kw") or [""])[0].strip()
    category = (q.get("category") or ["全部"])[0]
    abc = (q.get("abc") or ["全部"])[0]
    sql = "SELECT m.*, COALESCE((SELECT SUM(qty) FROM stock s WHERE s.material_code=m.code),0) on_hand," \
          " COALESCE((SELECT SUM(qty*unit_cost) FROM stock s WHERE s.material_code=m.code),0) stock_amount" \
          " FROM materials m WHERE 1=1"
    args = []
    if kw:
        sql += " AND (m.name LIKE ? OR m.code LIKE ? OR m.spec LIKE ?)"
        args += ["%" + kw + "%"] * 3
    if category != "全部":
        sql += " AND m.category=?"
        args.append(category)
    if abc != "全部":
        sql += " AND m.abc=?"
        args.append(abc)
    sql += " ORDER BY m.code"
    data = rows(cn, sql, args)
    out = []
    for m in data:
        v = mat_view(m)
        v["stockAmount"] = scm.r2(m["stock_amount"])
        v["stockState"] = v.pop("state")
        out.append(v)
    return {"list": out, "total": len(out),
            "facets": {"categories": sorted({m["category"] for m in rows(cn, "SELECT category FROM materials")}),
                       "abc": ["A", "B", "C"]}}


@with_db
def api_material_check_dup(cn, user, q):
    name = (q.get("name") or [""])[0]
    spec = (q.get("spec") or [""])[0]
    out = []
    for m in rows(cn, "SELECT * FROM materials"):
        sim = scm.similarity(name, m["name"]) if name else 0.0
        same_spec = bool(spec) and scm.norm_text(spec) == scm.norm_text(m["spec"])
        if sim >= 0.7 or same_spec:
            out.append({"code": m["code"], "name": m["name"], "spec": m["spec"], "unit": m["unit"],
                        "score": scm.r4(sim), "sameSpec": same_spec,
                        "reason": "规格相同" if same_spec else "名称相似 %d%%" % round(sim * 100)})
    return {"dups": out}


@write_op
def api_material_create(cn, user, body):
    require(user, "write")
    name = (body.get("name") or "").strip()
    if not name:
        raise ApiError("物料名称不能为空")
    spec = (body.get("spec") or "").strip()
    if not (body.get("force") is True):
        dups = []
        for m in rows(cn, "SELECT * FROM materials"):
            if spec and scm.norm_text(spec) == scm.norm_text(m["spec"]) and \
                    scm.similarity(name, m["name"]) >= 0.5:
                dups.append({"code": m["code"], "name": m["name"], "spec": m["spec"],
                             "reason": "规格相同且名称相近", "score": scm.similarity(name, m["name"])})
        if dups:
            raise ApiError("疑似重复物料，请确认后再提交（可传 force=true 跳过）", 409, dups=dups)
    count = one(cn, "SELECT COUNT(*) c FROM materials")["c"]
    code = (body.get("code") or "MT-9%03d" % (count + 1)).strip()
    if one(cn, "SELECT code FROM materials WHERE code=?", (code,)):
        raise ApiError("物料编码已存在：%s" % code, 409)
    cn.execute("INSERT INTO materials(code,name,spec,unit,category,abc,standard_price,last_price,lead_days,"
               "safety_stock,max_stock,min_order_qty,avg_daily_usage,main_supplier,status,remark,"
               "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (code, name, spec, body.get("unit") or "个", body.get("category") or "其他",
                body.get("abc") or "C", float(body.get("standardPrice") or 0),
                float(body.get("standardPrice") or 0), int(body.get("leadDays") or 10),
                float(body.get("safetyStock") or 0), float(body.get("maxStock") or 0),
                float(body.get("minOrderQty") or 0), float(body.get("avgDailyUsage") or 0),
                body.get("mainSupplier") or "", "启用", body.get("remark") or "", now(), now()))
    cn.execute("INSERT INTO material_prices(material_code,supplier_code,price,effective_at,source,remark)"
               " VALUES(?,?,?,?,?,?)",
               (code, body.get("mainSupplier") or "", float(body.get("standardPrice") or 0),
                today(), "建档", "标准价"))
    op(cn, user["username"], "新建物料", "%s %s" % (code, name))
    emit(cn, "material.created", "material", code, {"code": code, "name": name}, user["username"])
    return {"code": code}


@with_db
def api_material_detail(cn, user, code):
    m = one(cn, "SELECT m.*, COALESCE((SELECT SUM(qty) FROM stock s WHERE s.material_code=m.code),0) on_hand"
                " FROM materials m WHERE m.code=?", (code,))
    if not m:
        raise ApiError("物料不存在：%s" % code, 404)
    v = mat_view(m)
    v["prices"] = rows(cn, "SELECT * FROM material_prices WHERE material_code=? ORDER BY effective_at DESC",
                       (code,))
    v["stock"] = rows(cn, "SELECT * FROM stock WHERE material_code=? ORDER BY warehouse", (code,))
    v["moves"] = rows(cn, "SELECT * FROM stock_moves WHERE material_code=? ORDER BY id DESC LIMIT 20", (code,))
    v["recentPo"] = rows(cn, "SELECT i.*, p.supplier_name, p.status, p.ordered_at FROM po_items i "
                             "JOIN purchase_orders p ON p.no=i.po_no WHERE i.material_code=? "
                             "ORDER BY p.no DESC LIMIT 10", (code,))
    v["suppliers"] = rows(cn, "SELECT s.code, s.name, s.level, s.status, "
                              "(SELECT price FROM material_prices mp WHERE mp.material_code=? "
                              " AND mp.supplier_code=s.code ORDER BY effective_at DESC LIMIT 1) price "
                              "FROM suppliers s WHERE s.code IN (SELECT supplier_code FROM material_prices "
                              "WHERE material_code=?)", (code, code))
    return v


@write_op
def api_material_update(cn, user, code, body):
    require(user, "write")
    if not one(cn, "SELECT code FROM materials WHERE code=?", (code,)):
        raise ApiError("物料不存在：%s" % code, 404)
    fields = [("name", "name"), ("spec", "spec"), ("unit", "unit"), ("category", "category"),
              ("abc", "abc"), ("mainSupplier", "main_supplier"), ("status", "status"),
              ("remark", "remark")]
    nums = [("standardPrice", "standard_price"), ("leadDays", "lead_days"),
            ("safetyStock", "safety_stock"), ("maxStock", "max_stock"),
            ("minOrderQty", "min_order_qty"), ("avgDailyUsage", "avg_daily_usage")]
    sets, args = [], []
    for k, col in fields:
        if k in body:
            sets.append("%s=?" % col)
            args.append(body[k])
    for k, col in nums:
        if k in body:
            sets.append("%s=?" % col)
            args.append(float(body[k] or 0))
    if not sets:
        raise ApiError("没有需要更新的字段")
    sets.append("updated_at=?")
    args += [now(), code]
    cn.execute("UPDATE materials SET %s WHERE code=?" % ",".join(sets), args)
    op(cn, user["username"], "更新物料", code)
    return {"code": code, "updated": True}


@write_op
def api_material_abc(cn, user):
    """按近 12 个月采购金额重算 ABC 分类。"""
    require(user, "write")
    since = scm.add_days(today(), -365)
    agg = rows(cn, "SELECT i.material_code code, m.name, SUM(i.amount) amount FROM po_items i "
                   "JOIN purchase_orders p ON p.no=i.po_no JOIN materials m ON m.code=i.material_code "
                   "WHERE p.ordered_at>=? GROUP BY i.material_code", (since,))
    classified = scm.abc_classify(agg)
    changed = 0
    for c in classified:
        old = one(cn, "SELECT abc FROM materials WHERE code=?", (c["code"],))
        if old and old["abc"] != c["abc"]:
            changed += 1
        cn.execute("UPDATE materials SET abc=? WHERE code=?", (c["abc"], c["code"]))
    op(cn, user["username"], "重算 ABC", "%d 个物料，%d 个分类变化" % (len(classified), changed))
    return {"total": len(classified), "changed": changed,
            "detail": [{"code": c["code"], "name": c["name"], "amount": scm.r2(c["amount"]),
                        "share": c["share"], "abc": c["abc"]} for c in classified[:20]]}


@with_db
def api_warehouses(cn, user):
    return rows(cn, "SELECT * FROM warehouses ORDER BY code")


# ---------------------------------------------------------------- 请购
@with_db
def api_reqs(cn, user, q):
    status = (q.get("status") or ["全部"])[0]
    kw = (q.get("kw") or [""])[0].strip()
    sql = "SELECT * FROM requisitions WHERE 1=1"
    args = []
    sc = scope_of(user)
    if sc:
        sql += " AND applicant=?"
        args.append(sc)
    if status != "全部":
        sql += " AND status=?"
        args.append(status)
    if kw:
        sql += " AND (no LIKE ? OR purpose LIKE ? OR dept LIKE ?)"
        args += ["%" + kw + "%"] * 3
    sql += " ORDER BY no DESC"
    data = rows(cn, sql, args)
    names = map_names(cn)
    out = []
    for r in data:
        items = rows(cn, "SELECT * FROM req_items WHERE req_no=?", (r["no"],))
        out.append(req_view(r, items, names))
    return {"list": out, "total": len(out),
            "statusList": ["草稿", "待审批", "已审批", "已转单", "已驳回", "已取消"]}


@write_op
def api_req_create(cn, user, body):
    require(user, "write")
    items = body.get("items") or []
    if not items:
        raise ApiError("请购至少需要一行物料明细")
    rows_ = []
    for it in items:
        m = one(cn, "SELECT * FROM materials WHERE code=?", (it.get("materialCode") or "",))
        if not m:
            raise ApiError("物料不存在：%s" % (it.get("materialCode") or ""))
        qty = float(it.get("qty") or 0)
        if qty <= 0:
            raise ApiError("物料 %s 的数量需大于 0" % m["code"])
        price = float(it.get("estPrice") or m["standard_price"] or 0)
        rows_.append({"m": m, "qty": qty, "price": price})
    amount = scm.sum_amount([{"qty": r["qty"], "price": r["price"]} for r in rows_])
    no = next_no(cn, "PR", "requisitions")
    need_date = body.get("needDate") or scm.add_days(today(), 14)
    cn.execute("INSERT INTO requisitions(no,dept,applicant,purpose,need_date,amount,status,approver,"
               "approved_at,reject_reason,converted_no,remark,created_at,updated_at)"
               " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (no, body.get("dept") or user.get("dept") or "计划部", user["username"],
                body.get("purpose") or "物料请购", need_date, amount, "草稿", "", "", "", "",
                body.get("remark") or "", now(), now()))
    for r in rows_:
        cn.execute("INSERT INTO req_items(req_no,material_code,material_name,spec,unit,qty,est_price,amount,"
                   "remark) VALUES(?,?,?,?,?,?,?,?,?)",
                   (no, r["m"]["code"], r["m"]["name"], r["m"]["spec"], r["m"]["unit"], r["qty"],
                    r["price"], scm.r2(r["qty"] * r["price"]), ""))
    op(cn, user["username"], "新建请购", "%s 金额 %.2f" % (no, amount))
    emit(cn, "req.created", "requisition", no, {"no": no, "amount": amount}, user["username"])
    return {"no": no, "amount": amount, "status": "草稿"}


@with_db
def api_req_detail(cn, user, no):
    r = one(cn, "SELECT * FROM requisitions WHERE no=?", (no,))
    if not r:
        raise ApiError("请购单不存在：%s" % no, 404)
    items = rows(cn, "SELECT * FROM req_items WHERE req_no=?", (no,))
    v = req_view(r, items, map_names(cn))
    v["pos"] = rows(cn, "SELECT no,status,amount,supplier_name FROM purchase_orders WHERE req_no=?", (no,))
    v["rfqs"] = rows(cn, "SELECT no,status,title,awarded_supplier FROM rfqs WHERE req_no=?", (no,))
    return v


@write_op
def api_req_submit(cn, user, no, body):
    require(user, "write")
    r = one(cn, "SELECT * FROM requisitions WHERE no=?", (no,))
    if not r:
        raise ApiError("请购单不存在：%s" % no, 404)
    if r["status"] != "草稿":
        raise ApiError("只有草稿状态可以提交（当前 %s）" % r["status"])
    if not one(cn, "SELECT COUNT(*) c FROM req_items WHERE req_no=?", (no,))["c"]:
        raise ApiError("请购单没有明细，不能提交")
    free_limit = float(rule_value(cn, "req_free_limit", 5000) or 0)
    if float(r["amount"]) <= free_limit and user["role"] in ("admin", "purchase_director"):
        cn.execute("UPDATE requisitions SET status='已审批', approver=?, approved_at=?, updated_at=? "
                   "WHERE no=?", (user["username"], now(), now(), no))
        op(cn, user["username"], "免审批通过", "%s（%.2f ≤ 阈值 %.2f）" % (no, r["amount"], free_limit))
        return {"no": no, "status": "已审批", "auto": True}
    cn.execute("UPDATE requisitions SET status='待审批', updated_at=? WHERE no=?", (now(), no))
    op(cn, user["username"], "提交请购", no)
    emit(cn, "req.submitted", "requisition", no, {"no": no, "amount": r["amount"]}, user["username"])
    return {"no": no, "status": "待审批", "auto": False}


@write_op
def api_req_approve(cn, user, no, body):
    require(user, "approve")
    r = one(cn, "SELECT * FROM requisitions WHERE no=?", (no,))
    if not r:
        raise ApiError("请购单不存在：%s" % no, 404)
    if r["status"] != "待审批":
        raise ApiError("只有待审批的请购可以批准（当前 %s）" % r["status"])
    period = "%s-Q%d" % (date.today().year, (date.today().month - 1) // 3 + 1)
    budget = one(cn, "SELECT * FROM budgets WHERE period=? AND dept=?", (period, r["dept"]))
    if budget and float(budget["used"] or 0) + float(r["amount"]) > float(budget["amount"] or 0):
        raise ApiError("部门预算不足：%s 本季剩余 %.2f 元，本次请购 %.2f 元"
                       % (r["dept"], float(budget["amount"]) - float(budget["used"]), float(r["amount"])),
                       400, budget={"period": period, "amount": budget["amount"], "used": budget["used"]})
    cn.execute("UPDATE requisitions SET status='已审批', approver=?, approved_at=?, updated_at=? WHERE no=?",
               (user["username"], now(), now(), no))
    if budget:
        cn.execute("UPDATE budgets SET used=? WHERE id=?", (float(budget["used"] or 0) + float(r["amount"]),
                                                           budget["id"]))
    op(cn, user["username"], "批准请购", "%s %.2f" % (no, r["amount"]))
    emit(cn, "req.approved", "requisition", no, {"no": no, "amount": r["amount"]}, user["username"])
    return {"no": no, "status": "已审批"}


@write_op
def api_req_reject(cn, user, no, body):
    require(user, "approve")
    r = one(cn, "SELECT * FROM requisitions WHERE no=?", (no,))
    if not r:
        raise ApiError("请购单不存在：%s" % no, 404)
    reason = (body.get("reason") or "").strip()
    if len(reason) < 2:
        raise ApiError("驳回必须填写原因（至少 2 个字）")
    if r["status"] not in ("待审批", "已审批"):
        raise ApiError("当前状态不可驳回：%s" % r["status"])
    cn.execute("UPDATE requisitions SET status='已驳回', reject_reason=?, approver=?, updated_at=? WHERE no=?",
               (reason, user["username"], now(), no))
    op(cn, user["username"], "驳回请购", "%s：%s" % (no, reason))
    emit(cn, "req.rejected", "requisition", no, {"no": no, "reason": reason}, user["username"])
    return {"no": no, "status": "已驳回"}


@write_op
def api_req_cancel(cn, user, no, body):
    require(user, "write")
    r = one(cn, "SELECT * FROM requisitions WHERE no=?", (no,))
    if not r:
        raise ApiError("请购单不存在：%s" % no, 404)
    if r["status"] in ("已转单", "已取消"):
        raise ApiError("已转单或已取消的请购不可再取消")
    cn.execute("UPDATE requisitions SET status='已取消', updated_at=? WHERE no=?", (now(), no))
    op(cn, user["username"], "取消请购", no)
    return {"no": no, "status": "已取消"}


def _make_po(cn, user, *, supplier, items, title, req_no="", rfq_no="", promise_date="", remark=""):
    """由请购/询价生成采购订单草稿（items: [{material, qty, price}]）。"""
    if supplier["status"] != "已准入":
        raise ApiError("供应商「%s」当前状态为 %s，未通过准入不能下单" % (supplier["name"], supplier["status"]))
    amount = scm.sum_amount([{"qty": i["qty"], "price": i["price"]} for i in items])
    no = next_no(cn, "PO", "purchase_orders")
    promise = promise_date or scm.add_days(today(), supplier["lead_days"] or 15)
    ordered = sum(float(i["qty"]) for i in items)
    cn.execute("INSERT INTO purchase_orders(no,supplier_code,supplier_name,req_no,rfq_no,title,amount,"
               "currency,status,promise_date,owner,approver,approved_at,ordered_at,ordered_qty,received_qty,"
               "received_amount,invoiced_amount,match_result,closed_at,cancel_reason,remark,created_at,"
               "updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (no, supplier["code"], supplier["name"], req_no, rfq_no, title, amount, "CNY", "草稿",
                promise, user["username"], "", "", "", ordered, 0, 0, 0, "", "", "", remark, now(), now()))
    for i in items:
        m = i["material"]
        cn.execute("INSERT INTO po_items(po_no,material_code,material_name,spec,unit,qty,price,amount,"
                   "received_qty,promise_date,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (no, m["code"], m["name"], m["spec"], m["unit"], i["qty"], i["price"],
                    scm.r2(i["qty"] * i["price"]), 0, promise, ""))
    op(cn, user["username"], "生成采购订单", "%s（%s，%.2f）" % (no, supplier["name"], amount))
    emit(cn, "po.created", "po", no, {"no": no, "supplier": supplier["name"], "amount": amount,
                                      "status": "草稿"}, user["username"])
    return no


@write_op
def api_req_to_po(cn, user, no, body):
    require(user, "write")
    r = one(cn, "SELECT * FROM requisitions WHERE no=?", (no,))
    if not r:
        raise ApiError("请购单不存在：%s" % no, 404)
    if r["status"] != "已审批":
        raise ApiError("只有已审批的请购可以转采购订单（当前 %s）" % r["status"])
    supplier = one(cn, "SELECT * FROM suppliers WHERE code=?", (body.get("supplierCode") or "",))
    if not supplier:
        raise ApiError("请选择供应商")
    items = []
    for it in rows(cn, "SELECT * FROM req_items WHERE req_no=?", (no,)):
        m = one(cn, "SELECT * FROM materials WHERE code=?", (it["material_code"],))
        price = float(body.get("priceMode") == "standard" and m["standard_price"] or it["est_price"])
        items.append({"material": m, "qty": float(it["qty"]), "price": price})
    po_no = _make_po(cn, user, supplier=supplier, items=items, title="%s 采购" % r["purpose"],
                     req_no=no, promise_date=body.get("promiseDate") or "",
                     remark=body.get("remark") or "")
    cn.execute("UPDATE requisitions SET status='已转单', converted_no=?, updated_at=? WHERE no=?",
               (po_no, now(), no))
    return {"reqNo": no, "poNo": po_no, "status": "已转单"}


@write_op
def api_req_to_rfq(cn, user, no, body):
    require(user, "write")
    r = one(cn, "SELECT * FROM requisitions WHERE no=?", (no,))
    if not r:
        raise ApiError("请购单不存在：%s" % no, 404)
    if r["status"] != "已审批":
        raise ApiError("只有已审批的请购可以发起询价（当前 %s）" % r["status"])
    codes = body.get("supplierCodes") or []
    min_sup = int(rule_value(cn, "rfq_min_suppliers", 2) or 2)
    if len(codes) < min_sup:
        raise ApiError("询价至少需要 %d 家供应商（当前 %d 家）" % (min_sup, len(codes)))
    no_rfq = next_no(cn, "RFQ", "rfqs")
    cn.execute("INSERT INTO rfqs(no,req_no,title,status,deadline,owner,awarded_supplier,awarded_amount,"
               "remark,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (no_rfq, no, "%s 询价比价" % r["purpose"], "询价中",
                body.get("deadline") or scm.add_days(today(), 7), user["username"], "", 0,
                body.get("remark") or "", now(), now()))
    for it in rows(cn, "SELECT * FROM req_items WHERE req_no=?", (no,)):
        cn.execute("INSERT INTO rfq_items(rfq_no,material_code,material_name,qty,unit) VALUES(?,?,?,?,?)",
                   (no_rfq, it["material_code"], it["material_name"], it["qty"], it["unit"]))
    cn.execute("UPDATE requisitions SET status='已转单', converted_no=?, updated_at=? WHERE no=?",
               (no_rfq, now(), no))
    op(cn, user["username"], "发起询价", "%s（%d 家）" % (no_rfq, len(codes)))
    emit(cn, "rfq.created", "rfq", no_rfq, {"no": no_rfq, "reqNo": no, "suppliers": codes},
         user["username"])
    return {"rfqNo": no_rfq, "suppliers": codes, "reqStatus": "已转单"}


# ---------------------------------------------------------------- 询价比价
@with_db
def api_rfqs(cn, user, q):
    data = rows(cn, "SELECT * FROM rfqs ORDER BY no DESC")
    names = map_names(cn)
    out = []
    for r in data:
        out.append(rfq_view(r, rows(cn, "SELECT * FROM rfq_items WHERE rfq_no=?", (r["no"],)),
                            rows(cn, "SELECT * FROM rfq_quotes WHERE rfq_no=? ORDER BY amount",
                                 (r["no"],)), names))
    return {"list": out, "total": len(out), "statusList": ["询价中", "已定标", "已取消"]}


@write_op
def api_rfq_quote(cn, user, no, body):
    require(user, "write")
    r = one(cn, "SELECT * FROM rfqs WHERE no=?", (no,))
    if not r:
        raise ApiError("询价单不存在：%s" % no, 404)
    if r["status"] != "询价中":
        raise ApiError("询价单已%s，不能再登记报价" % r["status"])
    sup = one(cn, "SELECT * FROM suppliers WHERE code=?", (body.get("supplierCode") or "",))
    if not sup:
        raise ApiError("请选择报价供应商")
    amount = float(body.get("amount") or 0)
    if amount <= 0:
        raise ApiError("报价金额需大于 0")
    exist = one(cn, "SELECT * FROM rfq_quotes WHERE rfq_no=? AND supplier_code=?", (no, sup["code"]))
    if exist:
        cn.execute("UPDATE rfq_quotes SET amount=?, lead_days=?, valid_days=?, remark=?, created_at=? "
                   "WHERE id=?", (amount, int(body.get("leadDays") or 0),
                                  int(body.get("validDays") or 30), body.get("remark") or "",
                                  now(), exist["id"]))
        qid = exist["id"]
    else:
        qid = cn.execute("INSERT INTO rfq_quotes(rfq_no,supplier_code,supplier_name,amount,lead_days,"
                         "valid_days,awarded,remark,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         (no, sup["code"], sup["name"], amount, int(body.get("leadDays") or 0),
                          int(body.get("validDays") or 30), 0, body.get("remark") or "",
                          now())).lastrowid
    op(cn, user["username"], "登记报价", "%s %s %.2f" % (no, sup["name"], amount))
    return {"id": qid, "supplierCode": sup["code"], "amount": amount}


@write_op
def api_rfq_award(cn, user, no, body):
    require(user, "approve")
    r = one(cn, "SELECT * FROM rfqs WHERE no=?", (no,))
    if not r:
        raise ApiError("询价单不存在：%s" % no, 404)
    if r["status"] != "询价中":
        raise ApiError("询价单已%s" % r["status"])
    quotes = rows(cn, "SELECT * FROM rfq_quotes WHERE rfq_no=? ORDER BY amount", (no,))
    min_sup = int(rule_value(cn, "rfq_min_suppliers", 2) or 2)
    if len(quotes) < min_sup:
        raise ApiError("报价家数不足（%d < %d），不能定标" % (len(quotes), min_sup))
    code = body.get("supplierCode") or quotes[0]["supplier_code"]
    q = [x for x in quotes if x["supplier_code"] == code]
    if not q:
        raise ApiError("该供应商没有报价记录")
    q = q[0]
    sup = one(cn, "SELECT * FROM suppliers WHERE code=?", (code,))
    items = rows(cn, "SELECT * FROM rfq_items WHERE rfq_no=?", (no,))
    if not items:
        raise ApiError("询价单没有物料明细")
    # 按标准价占比把总报价分摊到明细
    weights = []
    for it in items:
        m = one(cn, "SELECT * FROM materials WHERE code=?", (it["material_code"],))
        weights.append({"material": m, "qty": float(it["qty"]),
                        "w": float(m["standard_price"] or 1) * float(it["qty"])})
    total_w = sum(x["w"] for x in weights) or 1.0
    for x in weights:
        x["price"] = scm.r2(float(q["amount"]) * x["w"] / total_w / max(x["qty"], 1e-9))
    po_no = _make_po(cn, user, supplier=sup, items=weights, title="%s（询价定标）" % r["title"],
                     req_no=r["req_no"], rfq_no=no, remark="定标供应商：%s" % sup["name"])
    cn.execute("UPDATE rfq_quotes SET awarded=1 WHERE id=?", (q["id"],))
    cn.execute("UPDATE rfqs SET status='已定标', awarded_supplier=?, awarded_amount=?, updated_at=? "
               "WHERE no=?", (code, float(q["amount"]), now(), no))
    op(cn, user["username"], "询价定标", "%s → %s" % (no, sup["name"]))
    emit(cn, "rfq.awarded", "rfq", no, {"no": no, "supplier": sup["name"], "amount": q["amount"]},
         user["username"])
    return {"rfqNo": no, "poNo": po_no, "supplier": sup["name"], "amount": scm.r2(q["amount"])}


@write_op
def api_rfq_cancel(cn, user, no, body):
    require(user, "write")
    r = one(cn, "SELECT * FROM rfqs WHERE no=?", (no,))
    if not r:
        raise ApiError("询价单不存在：%s" % no, 404)
    if r["status"] == "已定标":
        raise ApiError("已定标的询价不能取消")
    cn.execute("UPDATE rfqs SET status='已取消', updated_at=? WHERE no=?", (now(), no))
    op(cn, user["username"], "取消询价", no)
    return {"no": no, "status": "已取消"}


@with_db
def api_rfq_detail(cn, user, no):
    r = one(cn, "SELECT * FROM rfqs WHERE no=?", (no,))
    if not r:
        raise ApiError("询价单不存在：%s" % no, 404)
    items = rows(cn, "SELECT * FROM rfq_items WHERE rfq_no=?", (no,))
    quotes = rows(cn, "SELECT * FROM rfq_quotes WHERE rfq_no=? ORDER BY amount", (no,))
    v = rfq_view(r, items, quotes, map_names(cn))
    v["req"] = one(cn, "SELECT no,dept,purpose,amount,status FROM requisitions WHERE no=?", (r["req_no"],))
    v["minSuppliers"] = int(rule_value(cn, "rfq_min_suppliers", 2) or 2)
    v["supplierOptions"] = rows(cn, "SELECT code,name,level,score,lead_days FROM suppliers "
                                    "WHERE status='已准入' ORDER BY score DESC")
    return v


# ---------------------------------------------------------------- 采购订单
@with_db
def api_orders(cn, user, q):
    status = (q.get("status") or ["全部"])[0]
    kw = (q.get("kw") or [""])[0].strip()
    supplier = (q.get("supplier") or [""])[0]
    only_overdue = (q.get("overdue") or ["0"])[0] == "1"
    sql = "SELECT p.*, (SELECT COUNT(*) FROM po_items i WHERE i.po_no=p.no) item_count," \
          " (SELECT COUNT(*) FROM receipts r WHERE r.po_no=p.no) receipt_count" \
          " FROM purchase_orders p WHERE 1=1"
    args = []
    sc = scope_of(user)
    if sc:
        sql += " AND p.owner=?"
        args.append(sc)
    if status != "全部":
        sql += " AND p.status=?"
        args.append(status)
    if supplier:
        sql += " AND p.supplier_code=?"
        args.append(supplier)
    if kw:
        sql += " AND (p.no LIKE ? OR p.title LIKE ? OR p.supplier_name LIKE ?)"
        args += ["%" + kw + "%"] * 3
    sql += " ORDER BY p.no DESC"
    names = map_names(cn)
    out = []
    for r in rows(cn, sql, args):
        v = po_view(r, None, names, None)
        if only_overdue and not v["overdue"]:
            continue
        out.append(v)
    overdue_count = len([x for x in out if x["overdue"]])
    return {"list": out, "total": len(out), "overdueCount": overdue_count,
            "statusList": scm.PO_FLOW + ["已取消"]}


@write_op
def api_order_create(cn, user, body):
    require(user, "write")
    supplier = one(cn, "SELECT * FROM suppliers WHERE code=?", (body.get("supplierCode") or "",))
    if not supplier:
        raise ApiError("请选择供应商")
    raws = body.get("items") or []
    if not raws:
        raise ApiError("采购订单至少需要一行明细")
    items = []
    for it in raws:
        m = one(cn, "SELECT * FROM materials WHERE code=?", (it.get("materialCode") or "",))
        if not m:
            raise ApiError("物料不存在：%s" % (it.get("materialCode") or ""))
        qty = float(it.get("qty") or 0)
        if qty <= 0:
            raise ApiError("物料 %s 数量需大于 0" % m["code"])
        if m["min_order_qty"] and qty < float(m["min_order_qty"]):
            raise ApiError("物料 %s 的最小起订量为 %s %s" % (m["code"], scm.r2(m["min_order_qty"]), m["unit"]))
        price = float(it.get("price") or m["standard_price"] or 0)
        if price <= 0:
            raise ApiError("物料 %s 的单价需大于 0" % m["code"])
        items.append({"material": m, "qty": qty, "price": price})
    no = _make_po(cn, user, supplier=supplier, items=items,
                  title=body.get("title") or "%s 采购" % items[0]["material"]["name"],
                  req_no=body.get("reqNo") or "", rfq_no=body.get("rfqNo") or "",
                  promise_date=body.get("promiseDate") or "", remark=body.get("remark") or "")
    # 成交价回写物料最近价与价格记录
    for i in items:
        cn.execute("UPDATE materials SET last_price=?, updated_at=? WHERE code=?",
                   (i["price"], now(), i["material"]["code"]))
        cn.execute("INSERT INTO material_prices(material_code,supplier_code,price,effective_at,source,remark)"
                   " VALUES(?,?,?,?,?,?)",
                   (i["material"]["code"], supplier["code"], i["price"], today(), "采购订单", no))
    return {"no": no, "amount": scm.r2(sum(i["qty"] * i["price"] for i in items)), "status": "草稿"}


@with_db
def api_order_detail(cn, user, no):
    r = one(cn, "SELECT * FROM purchase_orders WHERE no=?", (no,))
    if not r:
        raise ApiError("采购订单不存在：%s" % no, 404)
    items = rows(cn, "SELECT * FROM po_items WHERE po_no=?", (no,))
    receipts = rows(cn, "SELECT * FROM receipts WHERE po_no=? ORDER BY no", (no,))
    v = po_view(r, items, map_names(cn), receipts)
    invs = rows(cn, "SELECT * FROM invoices WHERE po_no=?", (no,))
    supplier = one(cn, "SELECT * FROM suppliers WHERE code=?", (r["supplier_code"],))
    v["supplier"] = {"code": supplier["code"], "name": supplier["name"], "status": supplier["status"],
                     "level": supplier["level"], "score": scm.r2(supplier["score"]),
                     "paymentTerms": supplier["payment_terms"]} if supplier else None
    v["invoices"] = [invoice_view(i, r) for i in invs]
    tolerance = float(rule_value(cn, "match_tolerance", 0.02) or 0.02)
    v["match"] = scm.match3(r["amount"], r["received_amount"], r["invoiced_amount"], tolerance)
    v["gate"] = {
        "待审批": scm.po_gate("待审批", {"itemCount": len(items), "amount": r["amount"]}),
        "已下单": scm.po_gate("已下单", {"approvedBy": r["approver"],
                                       "supplierStatus": supplier["status"] if supplier else ""}),
        "全部到货": scm.po_gate("全部到货", {"receivedQty": r["received_qty"],
                                           "orderedQty": r["ordered_qty"]}),
        "已结算": scm.po_gate("已结算", {"hasInvoice": bool(invs), "matchResult": v["match"]["result"]}),
    }
    v["tolerance"] = tolerance
    v["approveLimit"] = float(rule_value(cn, "po_approve_limit", 50000) or 0)
    return v


@write_op
def api_order_stage(cn, user, no, body):
    target = (body.get("target") or "").strip()
    # 结算动作由财务确认，其余推进走写权限
    if target == "已结算" and scm.can(user["role"], "finance"):
        pass
    else:
        require(user, "write")
    r = one(cn, "SELECT * FROM purchase_orders WHERE no=?", (no,))
    if not r:
        raise ApiError("采购订单不存在：%s" % no, 404)
    target = (body.get("target") or "").strip()
    if target == "已取消":
        return api_order_cancel.__wrapped__(cn, user, no, body)
    ok, msg = scm.can_move_po(r["status"], target)
    if not ok:
        raise ApiError(msg)
    supplier = one(cn, "SELECT * FROM suppliers WHERE code=?", (r["supplier_code"],))
    items = rows(cn, "SELECT * FROM po_items WHERE po_no=?", (no,))
    invs = rows(cn, "SELECT * FROM invoices WHERE po_no=?", (no,))
    tolerance = float(rule_value(cn, "match_tolerance", 0.02) or 0.02)
    m3 = scm.match3(r["amount"], r["received_amount"], r["invoiced_amount"], tolerance)
    eff_approver = r["approver"]
    if target == "已下单":
        limit = float(rule_value(cn, "po_approve_limit", 50000) or 0)
        if user["role"] not in ("admin", "purchase_director") and float(r["amount"]) > limit:
            raise ApiError("订单金额 %.2f 元超过 %.2f 元审批线，需采购总监审批" % (float(r["amount"]), limit), 403)
        if user["role"] in ("admin", "purchase_director", "finance"):
            eff_approver = user["username"]
        elif not eff_approver:
            eff_approver = user["username"]
    ctx = {"itemCount": len(items), "amount": r["amount"], "approvedBy": eff_approver,
           "supplierStatus": supplier["status"] if supplier else "",
           "receivedQty": r["received_qty"], "orderedQty": r["ordered_qty"],
           "hasInvoice": bool(invs), "matchResult": m3["result"]}
    miss = scm.po_gate(target, ctx)
    if miss:
        raise ApiError("推进到「%s」还缺：%s" % (target, "、".join(miss)), 400, missing=miss)
    sets = ["status=?", "updated_at=?"]
    args = [target, now()]
    if target == "已下单":
        sets += ["approver=?", "approved_at=?", "ordered_at=?"]
        args += [eff_approver, now(), now()]
    if target == "已结算":
        sets.append("closed_at=?")
        args.append(now())
    args.append(no)
    cn.execute("UPDATE purchase_orders SET %s WHERE no=?" % ",".join(sets), args)
    if target == "已结算":
        cn.execute("UPDATE invoices SET status='已付款' WHERE po_no=? AND paid_amount>=amount AND status<>'已付款'",
                   (no,))
    op(cn, user["username"], "订单推进", "%s %s → %s" % (no, r["status"], target))
    emit(cn, "po.stage_changed", "po", no,
         {"no": no, "from": r["status"], "to": target, "amount": r["amount"]}, user["username"])
    return {"no": no, "from": r["status"], "status": target}


@write_op
def api_order_cancel(cn, user, no, body):
    require(user, "write")
    r = one(cn, "SELECT * FROM purchase_orders WHERE no=?", (no,))
    if not r:
        raise ApiError("采购订单不存在：%s" % no, 404)
    if r["status"] in ("已结算", "已取消"):
        raise ApiError("订单已%s，不可取消" % r["status"])
    if float(r["received_qty"] or 0) > 0:
        raise ApiError("已有到货记录，不能直接取消；请先做退货处理")
    reason = (body.get("reason") or "").strip()
    if len(reason) < 2:
        raise ApiError("取消必须填写原因（至少 2 个字）")
    cn.execute("UPDATE purchase_orders SET status='已取消', cancel_reason=?, updated_at=? WHERE no=?",
               (reason, now(), no))
    op(cn, user["username"], "取消订单", "%s：%s" % (no, reason))
    emit(cn, "po.cancelled", "po", no, {"no": no, "reason": reason}, user["username"])
    return {"no": no, "status": "已取消"}


# ---------------------------------------------------------------- 收货与质检
@with_db
def api_receipts(cn, user, q):
    status = (q.get("status") or ["全部"])[0]
    kw = (q.get("kw") or [""])[0].strip()
    sql = "SELECT r.*, (SELECT COUNT(*) FROM receipt_items i WHERE i.receipt_no=r.no) item_count " \
          "FROM receipts r WHERE 1=1"
    args = []
    if status != "全部":
        sql += " AND r.status=?"
        args.append(status)
    if kw:
        sql += " AND (r.no LIKE ? OR r.po_no LIKE ? OR r.supplier_name LIKE ?)"
        args += ["%" + kw + "%"] * 3
    sql += " ORDER BY r.no DESC"
    names = map_names(cn)
    out = []
    for r in rows(cn, sql, args):
        items = rows(cn, "SELECT * FROM receipt_items WHERE receipt_no=?", (r["no"],))
        out.append(receipt_view(r, items, names))
    return {"list": out, "total": len(out), "statusList": ["待质检", "已质检", "已入库", "已退货"]}


@with_db
def api_receipt_detail(cn, user, no):
    r = one(cn, "SELECT * FROM receipts WHERE no=?", (no,))
    if not r:
        raise ApiError("收货单不存在：%s" % no, 404)
    items = rows(cn, "SELECT * FROM receipt_items WHERE receipt_no=?", (no,))
    v = receipt_view(r, items, map_names(cn))
    po = one(cn, "SELECT * FROM purchase_orders WHERE no=?", (r["po_no"],))
    v["po"] = {"no": po["no"], "title": po["title"], "amount": scm.r2(po["amount"]),
               "status": po["status"], "promiseDate": po["promise_date"]} if po else None
    return v


@write_op
def api_order_receive(cn, user, no, body):
    require(user, "stock")
    r = one(cn, "SELECT * FROM purchase_orders WHERE no=?", (no,))
    if not r:
        raise ApiError("采购订单不存在：%s" % no, 404)
    if r["status"] not in ("已下单", "部分到货"):
        raise ApiError("只有已下单或部分到货的订单可以收货（当前 %s）" % r["status"])
    warehouse = (body.get("warehouse") or "").strip()
    if not one(cn, "SELECT code FROM warehouses WHERE code=?", (warehouse,)):
        raise ApiError("请选择有效的收货仓库")
    po_items = rows(cn, "SELECT * FROM po_items WHERE po_no=?", (no,))
    payload = body.get("items") or []
    chosen = []
    for it in payload:
        row = [x for x in po_items if x["id"] == it.get("id") or x["material_code"] == it.get("materialCode")]
        if not row:
            raise ApiError("订单中不存在该明细：%s" % (it.get("id") or it.get("materialCode")))
        row = row[0]
        remain = float(row["qty"] or 0) - float(row["received_qty"] or 0)
        qty = float(it.get("qty") or 0)
        if qty <= 0:
            continue
        if qty > remain + 1e-6:
            raise ApiError("物料 %s 本次收货 %.2f 超过未收数量 %.2f" % (row["material_code"], qty, remain))
        chosen.append({"po_item": row, "qty": qty})
    if not chosen:
        # 未指定明细时按剩余数量全收
        for row in po_items:
            remain = float(row["qty"] or 0) - float(row["received_qty"] or 0)
            if remain > 0:
                chosen.append({"po_item": row, "qty": remain})
    if not chosen:
        raise ApiError("订单已全部收货，无需再收货")
    no_gr = next_no(cn, "GR", "receipts")
    cn.execute("INSERT INTO receipts(no,po_no,supplier_code,supplier_name,warehouse,status,inspected_by,"
               "inspect_result,received_at,posted_at,remark,created_at,updated_at)"
               " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (no_gr, no, r["supplier_code"], r["supplier_name"], warehouse, "待质检", "", "",
                body.get("receivedAt") or today(), "", body.get("remark") or "", now(), now()))
    for c in chosen:
        it = c["po_item"]
        cn.execute("INSERT INTO receipt_items(receipt_no,material_code,material_name,unit,qty,ok_qty,ng_qty,"
                   "price,amount,batch,expire_at,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (no_gr, it["material_code"], it["material_name"], it["unit"], c["qty"], 0, 0,
                    it["price"], scm.r2(c["qty"] * float(it["price"] or 0)), "", "", ""))
        cn.execute("UPDATE po_items SET received_qty=? WHERE id=?",
                   (float(it["received_qty"] or 0) + c["qty"], it["id"]))
    cn.execute("UPDATE purchase_orders SET received_qty=?, received_amount=?, updated_at=? WHERE no=?",
               (float(r["received_qty"] or 0) + sum(c["qty"] for c in chosen),
                scm.r2(float(r["received_amount"] or 0) + sum(c["qty"] * float(c["po_item"]["price"] or 0)
                                                             for c in chosen)), now(), no))
    op(cn, user["username"], "到货登记", "%s → %s（%d 行）" % (no_gr, no, len(chosen)))
    emit(cn, "receipt.created", "receipt", no_gr, {"no": no_gr, "poNo": no, "warehouse": warehouse},
         user["username"])
    return {"receiptNo": no_gr, "poNo": no, "lines": len(chosen), "status": "待质检"}


@write_op
def api_receipt_inspect(cn, user, no, body):
    require(user, "stock")
    r = one(cn, "SELECT * FROM receipts WHERE no=?", (no,))
    if not r:
        raise ApiError("收货单不存在：%s" % no, 404)
    if r["status"] != "待质检":
        raise ApiError("该收货单当前为「%s」，不能重复质检" % r["status"])
    payload = body.get("items") or []
    items = rows(cn, "SELECT * FROM receipt_items WHERE receipt_no=?", (no,))
    if not items:
        raise ApiError("收货单没有明细")
    if not payload:
        payload = [{"id": i["id"], "okQty": i["qty"], "ngQty": 0} for i in items]
    total_ok = total_ng = 0.0
    for it in payload:
        row = [x for x in items if x["id"] == it.get("id") or x["material_code"] == it.get("materialCode")]
        if not row:
            raise ApiError("收货单中不存在该明细：%s" % (it.get("id") or it.get("materialCode")))
        row = row[0]
        ok = float(it.get("okQty") if it.get("okQty") is not None else row["qty"])
        ng = float(it.get("ngQty") or 0)
        if ok < 0 or ng < 0:
            raise ApiError("合格/不合格数量不能为负")
        if abs(ok + ng - float(row["qty"])) > 1e-6:
            raise ApiError("物料 %s 的合格 %s + 不合格 %s 应等于到货 %s"
                           % (row["material_code"], scm.r2(ok), scm.r2(ng), scm.r2(row["qty"])))
        total_ok += ok
        total_ng += ng
        cn.execute("UPDATE receipt_items SET ok_qty=?, ng_qty=?, batch=?, expire_at=?, remark=? WHERE id=?",
                   (ok, ng, it.get("batch") or row["batch"] or "B%s001" % today()[5:7].replace("-", ""),
                    it.get("expireAt") or row["expire_at"] or "", it.get("remark") or "", row["id"]))
    tolerance = float(rule_value(cn, "match_tolerance", 0.02) or 0.02)
    conclusion = scm.inspect_conclusion(total_ok, total_ng, tolerance)
    cn.execute("UPDATE receipts SET status='已质检', inspected_by=?, inspect_result=?, updated_at=? WHERE no=?",
               (user["username"], conclusion, now(), no))
    op(cn, user["username"], "到货质检", "%s %s（合格率 %.1f%%）"
       % (no, conclusion, scm.inspect_rate(total_ok, total_ng) * 100))
    emit(cn, "receipt.inspected", "receipt", no,
         {"no": no, "result": conclusion, "okQty": scm.r2(total_ok), "ngQty": scm.r2(total_ng)},
         user["username"])
    return {"no": no, "result": conclusion, "okQty": scm.r2(total_ok), "ngQty": scm.r2(total_ng),
            "passRate": scm.inspect_rate(total_ok, total_ng)}


@write_op
def api_receipt_post(cn, user, no, body):
    """质检后入库：合格品入台账，写库存流水，回写订单到货进度并自动推进订单状态。"""
    require(user, "stock")
    r = one(cn, "SELECT * FROM receipts WHERE no=?", (no,))
    if not r:
        raise ApiError("收货单不存在：%s" % no, 404)
    if r["status"] == "已入库":
        raise ApiError("该收货单已入库，不能重复过账")
    if r["status"] == "待质检":
        raise ApiError("请先完成质检再入库")
    if r["status"] == "已退货":
        raise ApiError("该收货单已退货，不能入库")
    items = rows(cn, "SELECT * FROM receipt_items WHERE receipt_no=?", (no,))
    moved = 0
    for it in items:
        ok_qty = float(it["ok_qty"] or 0)
        if ok_qty <= 0:
            continue
        exist = one(cn, "SELECT * FROM stock WHERE material_code=? AND warehouse=? AND batch=?",
                    (it["material_code"], r["warehouse"], it["batch"]))
        if exist:
            cn.execute("UPDATE stock SET qty=qty+?, unit_cost=?, updated_at=? WHERE id=?",
                       (ok_qty, it["price"], now(), exist["id"]))
        else:
            cn.execute("INSERT INTO stock(material_code,material_name,spec,unit,warehouse,batch,qty,locked,"
                       "unit_cost,in_date,expire_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (it["material_code"], it["material_name"], "", it["unit"], r["warehouse"],
                        it["batch"], ok_qty, 0, it["price"], today(), it["expire_at"], now()))
        cn.execute("INSERT INTO stock_moves(no,type,material_code,material_name,warehouse,batch,qty,cost,"
                   "ref_no,reason,operator,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (next_no(cn, "MV", "stock_moves"), "采购入库", it["material_code"], it["material_name"],
                    r["warehouse"], it["batch"], ok_qty, scm.r2(ok_qty * float(it["price"] or 0)), no,
                    "收货入库", user["username"], now()))
        moved += 1
    cn.execute("UPDATE receipts SET status='已入库', posted_at=?, updated_at=? WHERE no=?", (now(), now(), no))
    po = one(cn, "SELECT * FROM purchase_orders WHERE no=?", (r["po_no"],))
    if po:
        ordered = float(po["ordered_qty"] or 0)
        received = float(po["received_qty"] or 0)
        stage = scm.po_stage_by_qty(ordered, received)
        if stage and scm.can_move_po(po["status"], stage)[0]:
            cn.execute("UPDATE purchase_orders SET status=?, updated_at=? WHERE no=?", (stage, now(), po["no"]))
            emit(cn, "po.stage_changed", "po", po["no"],
                 {"no": po["no"], "from": po["status"], "to": stage}, user["username"])
    op(cn, user["username"], "入库过账", "%s（%d 行入 %s）" % (no, moved, r["warehouse"]))
    emit(cn, "receipt.posted", "receipt", no,
         {"no": no, "poNo": r["po_no"], "warehouse": r["warehouse"], "lines": moved}, user["username"])
    return {"no": no, "status": "已入库", "lines": moved}


@write_op
def api_receipt_return(cn, user, no, body):
    require(user, "stock")
    r = one(cn, "SELECT * FROM receipts WHERE no=?", (no,))
    if not r:
        raise ApiError("收货单不存在：%s" % no, 404)
    if r["status"] == "已退货":
        raise ApiError("该收货单已退货")
    reason = (body.get("reason") or "").strip()
    if len(reason) < 2:
        raise ApiError("退货必须填写原因（至少 2 个字）")
    items = rows(cn, "SELECT * FROM receipt_items WHERE receipt_no=?", (no,))
    if r["status"] == "已入库":
        for it in items:
            ok_qty = float(it["ok_qty"] or 0)
            if ok_qty <= 0:
                continue
            exist = one(cn, "SELECT * FROM stock WHERE material_code=? AND warehouse=? AND batch=?",
                        (it["material_code"], r["warehouse"], it["batch"]))
            if exist:
                if float(exist["qty"] or 0) < ok_qty - 1e-6:
                    raise ApiError("仓库现存 %s 不足以退回（现存 %.2f，需退 %.2f）"
                                   % (it["material_code"], exist["qty"], ok_qty))
                cn.execute("UPDATE stock SET qty=qty-?, updated_at=? WHERE id=?",
                           (ok_qty, now(), exist["id"]))
            cn.execute("INSERT INTO stock_moves(no,type,material_code,material_name,warehouse,batch,qty,cost,"
                       "ref_no,reason,operator,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (next_no(cn, "MV", "stock_moves"), "退货出库", it["material_code"], it["material_name"],
                        r["warehouse"], it["batch"], ok_qty, scm.r2(ok_qty * float(it["price"] or 0)), no,
                        reason, user["username"], now()))
        po = one(cn, "SELECT * FROM purchase_orders WHERE no=?", (r["po_no"],))
        if po:
            back = sum(float(i["ok_qty"] or 0) for i in items)
            cn.execute("UPDATE purchase_orders SET received_qty=MAX(0, received_qty-?), "
                       "received_amount=MAX(0, received_amount-?), updated_at=? WHERE no=?",
                       (back, sum(float(i["ok_qty"] or 0) * float(i["price"] or 0) for i in items),
                        now(), po["no"]))
    cn.execute("UPDATE receipts SET status='已退货', remark=?, updated_at=? WHERE no=?",
               ("退货：%s" % reason, now(), no))
    op(cn, user["username"], "到货退货", "%s：%s" % (no, reason))
    emit(cn, "receipt.returned", "receipt", no, {"no": no, "reason": reason}, user["username"])
    return {"no": no, "status": "已退货"}


# ---------------------------------------------------------------- 库存
@with_db
def api_stock(cn, user, q):
    kw = (q.get("kw") or [""])[0].strip()
    wh = (q.get("warehouse") or ["全部"])[0]
    state = (q.get("state") or ["全部"])[0]
    expiry = (q.get("expiry") or ["全部"])[0]
    sql = "SELECT s.*, m.abc abc, m.safety_stock safety_stock, m.max_stock max_stock," \
          " m.avg_daily_usage avg_daily_usage, m.lead_days lead_days" \
          " FROM stock s LEFT JOIN materials m ON m.code=s.material_code WHERE 1=1"
    args = []
    if kw:
        sql += " AND (s.material_code LIKE ? OR s.material_name LIKE ? OR s.batch LIKE ?)"
        args += ["%" + kw + "%"] * 3
    if wh != "全部":
        sql += " AND s.warehouse=?"
        args.append(wh)
    sql += " ORDER BY s.material_code, s.warehouse"
    out = []
    for r in rows(cn, sql, args):
        v = stock_view(r, {"safety_stock": r["safety_stock"], "max_stock": r["max_stock"],
                           "avg_daily_usage": r["avg_daily_usage"], "lead_days": r["lead_days"],
                           "abc": r["abc"]})
        if state != "全部" and v["state"] != state:
            continue
        if expiry == "近效期" and v["expiryState"] not in ("近效期", "已过期"):
            continue
        if expiry == "有批次" and not r["batch"]:
            continue
        out.append(v)
    total_amount = scm.r2(sum(x["amount"] for x in out))
    return {"list": out, "total": len(out), "amount": total_amount,
            "stateList": ["正常", "待补货", "低于安全库存", "缺货", "超储"],
            "byWarehouse": rows(cn, "SELECT warehouse, COUNT(*) c, ROUND(SUM(qty*unit_cost),2) amount "
                                    "FROM stock GROUP BY warehouse ORDER BY warehouse")}


@with_db
def api_stock_summary(cn, user, q):
    kw = (q.get("kw") or [""])[0].strip()
    sql = ("SELECT m.*, COALESCE(SUM(s.qty),0) on_hand, COALESCE(SUM(s.qty*s.unit_cost),0) amount,"
           " COALESCE(SUM(s.locked),0) locked FROM materials m "
           "LEFT JOIN stock s ON s.material_code=m.code WHERE 1=1")
    args = []
    if kw:
        sql += " AND (m.code LIKE ? OR m.name LIKE ?)"
        args += ["%" + kw + "%"] * 2
    sql += " GROUP BY m.code ORDER BY m.code"
    out = []
    for m in rows(cn, sql, args):
        reorder = scm.reorder_point(m["avg_daily_usage"], m["lead_days"], m["safety_stock"])
        st = scm.stock_state(m["on_hand"], m["safety_stock"], reorder, m["avg_daily_usage"], m["max_stock"])
        out.append({"code": m["code"], "name": m["name"], "spec": m["spec"], "unit": m["unit"],
                    "abc": m["abc"], "category": m["category"], "onHand": scm.r2(m["on_hand"]),
                    "locked": scm.r2(m["locked"]),
                    "available": scm.available(m["on_hand"], m["locked"]),
                    "safetyStock": scm.r2(m["safety_stock"]), "maxStock": scm.r2(m["max_stock"]),
                    "reorderPoint": scm.r2(reorder), "avgDailyUsage": scm.r2(m["avg_daily_usage"]),
                    "coverageDays": scm.coverage_days(m["on_hand"], m["avg_daily_usage"]),
                    "amount": scm.r2(m["amount"]), "state": st,
                    "gap": scm.shortage_qty(m["on_hand"], m["safety_stock"], m["max_stock"])
                    if st in ("缺货", "低于安全库存", "待补货") else 0.0})
    return {"list": out, "total": len(out),
            "amount": scm.r2(sum(x["amount"] for x in out)),
            "counts": {s: len([x for x in out if x["state"] == s])
                       for s in ("正常", "待补货", "低于安全库存", "缺货", "超储")}}


@with_db
def api_moves(cn, user, q):
    kw = (q.get("kw") or [""])[0].strip()
    typ = (q.get("type") or ["全部"])[0]
    sql = "SELECT * FROM stock_moves WHERE 1=1"
    args = []
    if kw:
        sql += " AND (material_code LIKE ? OR material_name LIKE ? OR ref_no LIKE ?)"
        args += ["%" + kw + "%"] * 3
    if typ != "全部":
        sql += " AND type=?"
        args.append(typ)
    sql += " ORDER BY id DESC LIMIT 200"
    data = rows(cn, sql, args)
    return {"list": data, "total": len(data),
            "types": ["采购入库", "领用出库", "调拨出库", "调拨入库", "盘盈", "盘亏", "退货出库"],
            "inQty": scm.r2(sum(float(x["qty"] or 0) for x in data if "入库" in x["type"] or x["type"] == "盘盈")),
            "outQty": scm.r2(sum(float(x["qty"] or 0) for x in data if "出库" in x["type"] or x["type"] == "盘亏"))}


@write_op
def api_stock_adjust(cn, user, body):
    require(user, "stock")
    typ = (body.get("type") or "盘盈").strip()
    if typ not in ("盘盈", "盘亏", "领用出库", "其他入库"):
        raise ApiError("调整类型只能是：盘盈 / 盘亏 / 领用出库 / 其他入库")
    m = one(cn, "SELECT * FROM materials WHERE code=?", (body.get("materialCode") or "",))
    if not m:
        raise ApiError("物料不存在：%s" % (body.get("materialCode") or ""))
    wh = (body.get("warehouse") or "").strip()
    if not one(cn, "SELECT code FROM warehouses WHERE code=?", (wh,)):
        raise ApiError("请选择有效仓库")
    qty = float(body.get("qty") or 0)
    if qty <= 0:
        raise ApiError("数量需大于 0")
    batch = (body.get("batch") or "").strip() or "B%s001" % today()[5:7].replace("-", "")
    reason = (body.get("reason") or "").strip() or "手工调整"
    row = one(cn, "SELECT * FROM stock WHERE material_code=? AND warehouse=? AND batch=?",
              (m["code"], wh, batch))
    sign = -1 if typ in ("盘亏", "领用出库") else 1
    if sign < 0:
        if not row or float(row["qty"] or 0) < qty - 1e-6:
            raise ApiError("库存不足：%s 在 %s 现存 %.2f" % (m["code"], wh, float(row["qty"] or 0) if row else 0))
    if row:
        cn.execute("UPDATE stock SET qty=qty+?, updated_at=? WHERE id=?", (sign * qty, now(), row["id"]))
    else:
        cn.execute("INSERT INTO stock(material_code,material_name,spec,unit,warehouse,batch,qty,locked,"
                   "unit_cost,in_date,expire_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (m["code"], m["name"], m["spec"], m["unit"], wh, batch, qty, 0, m["last_price"],
                    today(), body.get("expireAt") or "", now()))
    cn.execute("INSERT INTO stock_moves(no,type,material_code,material_name,warehouse,batch,qty,cost,"
               "ref_no,reason,operator,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               (next_no(cn, "MV", "stock_moves"), typ, m["code"], m["name"], wh, batch, qty,
                scm.r2(qty * float(m["last_price"] or 0)), "", reason, user["username"], now()))
    op(cn, user["username"], "库存调整", "%s %s %s %.2f（%s）" % (typ, m["code"], wh, qty, reason))
    emit(cn, "stock.adjusted", "stock", m["code"],
         {"material": m["code"], "warehouse": wh, "type": typ, "qty": qty}, user["username"])
    return {"materialCode": m["code"], "warehouse": wh, "type": typ, "qty": scm.r2(qty)}


@with_db
def api_shortage(cn, user, q):
    out = []
    for m in rows(cn, "SELECT m.*, COALESCE(SUM(s.qty),0) on_hand FROM materials m "
                      "LEFT JOIN stock s ON s.material_code=m.code GROUP BY m.code"):
        reorder = scm.reorder_point(m["avg_daily_usage"], m["lead_days"], m["safety_stock"])
        st = scm.stock_state(m["on_hand"], m["safety_stock"], reorder, m["avg_daily_usage"], m["max_stock"])
        if st in ("缺货", "低于安全库存", "待补货"):
            gap = scm.shortage_qty(m["on_hand"], m["safety_stock"], m["max_stock"])
            out.append({"code": m["code"], "name": m["name"], "spec": m["spec"], "unit": m["unit"],
                        "abc": m["abc"], "onHand": scm.r2(m["on_hand"]),
                        "safetyStock": scm.r2(m["safety_stock"]), "reorderPoint": scm.r2(reorder),
                        "avgDailyUsage": scm.r2(m["avg_daily_usage"]),
                        "coverageDays": scm.coverage_days(m["on_hand"], m["avg_daily_usage"]),
                        "suggestQty": gap, "state": st,
                        "leadDays": m["lead_days"],
                        "suggestDate": scm.add_days(today(), max(1, int(m["lead_days"] or 1) - 3)),
                        "mainSupplier": m["main_supplier"],
                        "estAmount": scm.r2(gap * float(m["last_price"] or m["standard_price"] or 0))})
    out.sort(key=lambda x: (0 if x["state"] == "缺货" else 1, -x["estAmount"]))
    return {"list": out, "total": len(out),
            "amount": scm.r2(sum(x["estAmount"] for x in out)),
            "shortage": len([x for x in out if x["state"] == "缺货"])}


@with_db
def api_transfers(cn, user, q):
    data = rows(cn, "SELECT * FROM transfers ORDER BY no DESC")
    out = []
    for r in data:
        items = rows(cn, "SELECT * FROM transfer_items WHERE transfer_no=?", (r["no"],))
        out.append({"no": r["no"], "fromWh": r["from_wh"], "toWh": r["to_wh"], "status": r["status"],
                    "applicant": r["applicant"], "approver": r["approver"], "remark": r["remark"],
                    "createdAt": r["created_at"], "updatedAt": r["updated_at"],
                    "itemCount": len(items),
                    "qty": scm.r2(sum(float(i["qty"] or 0) for i in items)),
                    "items": [{"materialCode": i["material_code"], "materialName": i["material_name"],
                               "unit": i["unit"], "qty": scm.r2(i["qty"])} for i in items]})
    return {"list": out, "total": len(out), "statusList": ["草稿", "已审批", "已完成", "已取消"]}


@write_op
def api_transfer_create(cn, user, body):
    require(user, "stock")
    from_wh = (body.get("fromWh") or "").strip()
    to_wh = (body.get("toWh") or "").strip()
    if from_wh == to_wh:
        raise ApiError("调出与调入仓库不能相同")
    for w in (from_wh, to_wh):
        if not one(cn, "SELECT code FROM warehouses WHERE code=?", (w,)):
            raise ApiError("仓库不存在：%s" % w)
    items = body.get("items") or []
    if not items:
        raise ApiError("调拨单至少需要一行物料")
    no = next_no(cn, "TR", "transfers")
    cn.execute("INSERT INTO transfers(no,from_wh,to_wh,status,applicant,approver,remark,created_at,"
               "updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
               (no, from_wh, to_wh, "已审批" if user["role"] in ("warehouse", "admin") else "草稿",
                user["username"], "", body.get("remark") or "", now(), now()))
    for it in items:
        m = one(cn, "SELECT * FROM materials WHERE code=?", (it.get("materialCode") or "",))
        if not m:
            raise ApiError("物料不存在：%s" % (it.get("materialCode") or ""))
        qty = float(it.get("qty") or 0)
        if qty <= 0:
            raise ApiError("物料 %s 的调拨数量需大于 0" % m["code"])
        cn.execute("INSERT INTO transfer_items(transfer_no,material_code,material_name,unit,batch,qty)"
                   " VALUES(?,?,?,?,?,?)", (no, m["code"], m["name"], m["unit"],
                                            it.get("batch") or "", qty))
    op(cn, user["username"], "新建调拨", "%s %s→%s" % (no, from_wh, to_wh))
    return {"no": no, "status": "已审批"}


@write_op
def api_transfer_approve(cn, user, no, body):
    require(user, "stock")
    r = one(cn, "SELECT * FROM transfers WHERE no=?", (no,))
    if not r:
        raise ApiError("调拨单不存在：%s" % no, 404)
    if r["status"] != "草稿":
        raise ApiError("只有草稿状态的调拨单可以审批（当前 %s）" % r["status"])
    cn.execute("UPDATE transfers SET status='已审批', approver=?, updated_at=? WHERE no=?",
               (user["username"], now(), no))
    return {"no": no, "status": "已审批"}


@write_op
def api_transfer_post(cn, user, no, body):
    require(user, "stock")
    r = one(cn, "SELECT * FROM transfers WHERE no=?", (no,))
    if not r:
        raise ApiError("调拨单不存在：%s" % no, 404)
    if r["status"] != "已审批":
        raise ApiError("只有已审批的调拨单可以执行（当前 %s）" % r["status"])
    items = rows(cn, "SELECT * FROM transfer_items WHERE transfer_no=?", (no,))
    for it in items:
        qty = float(it["qty"] or 0)
        src = one(cn, "SELECT * FROM stock WHERE material_code=? AND warehouse=? ORDER BY qty DESC LIMIT 1",
                  (it["material_code"], r["from_wh"]))
        if not src or float(src["qty"] or 0) < qty - 1e-6:
            raise ApiError("调出仓库存不足：%s 现存 %.2f，需 %.2f"
                           % (it["material_code"], float(src["qty"] or 0) if src else 0, qty))
        cn.execute("UPDATE stock SET qty=qty-?, updated_at=? WHERE id=?", (qty, now(), src["id"]))
        dst = one(cn, "SELECT * FROM stock WHERE material_code=? AND warehouse=? AND batch=?",
                  (it["material_code"], r["to_wh"], src["batch"]))
        if dst:
            cn.execute("UPDATE stock SET qty=qty+?, updated_at=? WHERE id=?", (qty, now(), dst["id"]))
        else:
            cn.execute("INSERT INTO stock(material_code,material_name,spec,unit,warehouse,batch,qty,locked,"
                       "unit_cost,in_date,expire_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (it["material_code"], it["material_name"], "", it["unit"], r["to_wh"],
                        src["batch"], qty, 0, src["unit_cost"], today(), src["expire_at"] or "", now()))
        for wh, sign in ((r["from_wh"], -1), (r["to_wh"], 1)):
            cn.execute("INSERT INTO stock_moves(no,type,material_code,material_name,warehouse,batch,qty,cost,"
                       "ref_no,reason,operator,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (next_no(cn, "MV", "stock_moves"), "调拨入库" if sign > 0 else "调拨出库",
                        it["material_code"], it["material_name"], wh, src["batch"], qty,
                        scm.r2(qty * float(src["unit_cost"] or 0)), no, "仓间调拨",
                        user["username"], now()))
    cn.execute("UPDATE transfers SET status='已完成', updated_at=? WHERE no=?", (now(), no))
    op(cn, user["username"], "执行调拨", "%s %s→%s" % (no, r["from_wh"], r["to_wh"]))
    emit(cn, "stock.transferred", "transfer", no,
         {"no": no, "from": r["from_wh"], "to": r["to_wh"]}, user["username"])
    return {"no": no, "status": "已完成"}


@with_db
def api_stocktakes(cn, user, q):
    data = rows(cn, "SELECT * FROM stocktakes ORDER BY no DESC")
    out = []
    for r in data:
        items = rows(cn, "SELECT * FROM stocktake_items WHERE stocktake_no=?", (r["no"],))
        out.append({"no": r["no"], "warehouse": r["warehouse"], "status": r["status"],
                    "applicant": r["applicant"], "approver": r["approver"],
                    "diffAmount": scm.r2(r["diff_amount"]), "remark": r["remark"],
                    "createdAt": r["created_at"], "updatedAt": r["updated_at"],
                    "itemCount": len(items),
                    "diffCount": len([i for i in items if float(i["diff_qty"] or 0) != 0]),
                    "items": [{"materialCode": i["material_code"], "materialName": i["material_name"],
                               "unit": i["unit"], "batch": i["batch"], "bookQty": scm.r2(i["book_qty"]),
                               "realQty": scm.r2(i["real_qty"]), "diffQty": scm.r2(i["diff_qty"]),
                               "cost": scm.r2(i["cost"])} for i in items]})
    return {"list": out, "total": len(out), "statusList": ["草稿", "已完成"]}


@write_op
def api_stocktake_create(cn, user, body):
    require(user, "stock")
    wh = (body.get("warehouse") or "").strip()
    if not one(cn, "SELECT code FROM warehouses WHERE code=?", (wh,)):
        raise ApiError("请选择盘点仓库")
    no = next_no(cn, "ST", "stocktakes")
    cn.execute("INSERT INTO stocktakes(no,warehouse,status,applicant,approver,diff_amount,remark,"
               "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
               (no, wh, "草稿", user["username"], "", 0, body.get("remark") or "", now(), now()))
    for s in rows(cn, "SELECT * FROM stock WHERE warehouse=? ORDER BY material_code", (wh,)):
        cn.execute("INSERT INTO stocktake_items(stocktake_no,material_code,material_name,unit,batch,book_qty,"
                   "real_qty,diff_qty,cost) VALUES(?,?,?,?,?,?,?,?,?)",
                   (no, s["material_code"], s["material_name"], s["unit"], s["batch"], s["qty"],
                    s["qty"], 0, s["unit_cost"]))
    op(cn, user["username"], "发起盘点", "%s %s" % (no, wh))
    return {"no": no, "lines": one(cn, "SELECT COUNT(*) c FROM stocktake_items WHERE stocktake_no=?",
                                   (no,))["c"]}


@write_op
def api_stocktake_finish(cn, user, no, body):
    require(user, "stock")
    r = one(cn, "SELECT * FROM stocktakes WHERE no=?", (no,))
    if not r:
        raise ApiError("盘点单不存在：%s" % no, 404)
    if r["status"] == "已完成":
        raise ApiError("盘点单已完成")
    payload = body.get("items") or []
    items = rows(cn, "SELECT * FROM stocktake_items WHERE stocktake_no=?", (no,))
    diff_amount = 0.0
    for it in payload:
        row = [x for x in items if x["material_code"] == it.get("materialCode")
               and (x["batch"] or "") == (it.get("batch") or x["batch"] or "")]
        if not row:
            row = [x for x in items if x["material_code"] == it.get("materialCode")]
        if not row:
            continue
        row = row[0]
        real = float(it.get("realQty") if it.get("realQty") is not None else row["book_qty"])
        if real < 0:
            raise ApiError("实盘数量不能为负")
        diff = scm.r2(real - float(row["book_qty"] or 0))
        cn.execute("UPDATE stocktake_items SET real_qty=?, diff_qty=? WHERE id=?", (real, diff, row["id"]))
        if diff != 0:
            cn.execute("UPDATE stock SET qty=?, updated_at=? WHERE material_code=? AND warehouse=? AND batch=?",
                       (real, now(), row["material_code"], r["warehouse"], row["batch"]))
            cn.execute("INSERT INTO stock_moves(no,type,material_code,material_name,warehouse,batch,qty,cost,"
                       "ref_no,reason,operator,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (next_no(cn, "MV", "stock_moves"), "盘盈" if diff > 0 else "盘亏",
                        row["material_code"], row["material_name"], r["warehouse"], row["batch"],
                        abs(diff), scm.r2(abs(diff) * float(row["cost"] or 0)), no, "盘点差异",
                        user["username"], now()))
            diff_amount += diff * float(row["cost"] or 0)
    cn.execute("UPDATE stocktakes SET status='已完成', approver=?, diff_amount=?, updated_at=? WHERE no=?",
               (user["username"], scm.r2(diff_amount), now(), no))
    op(cn, user["username"], "完成盘点", "%s 差异金额 %.2f" % (no, diff_amount))
    emit(cn, "stock.stocktake", "stocktake", no, {"no": no, "diffAmount": scm.r2(diff_amount)},
         user["username"])
    return {"no": no, "status": "已完成", "diffAmount": scm.r2(diff_amount)}


# ---------------------------------------------------------------- 结算
@with_db
def api_invoices(cn, user, q):
    status = (q.get("status") or ["全部"])[0]
    kw = (q.get("kw") or [""])[0].strip()
    sql = "SELECT * FROM invoices WHERE 1=1"
    args = []
    if status != "全部":
        sql += " AND status=?"
        args.append(status)
    if kw:
        sql += " AND (no LIKE ? OR po_no LIKE ? OR supplier_name LIKE ? OR invoice_no LIKE ?)"
        args += ["%" + kw + "%"] * 4
    sql += " ORDER BY no DESC"
    out = []
    for r in rows(cn, sql, args):
        po = one(cn, "SELECT * FROM purchase_orders WHERE no=?", (r["po_no"],))
        out.append(invoice_view(r, po))
    tolerance = float(rule_value(cn, "match_tolerance", 0.02) or 0.02)
    return {"list": out, "total": len(out), "tolerance": tolerance,
            "statusList": ["待匹配", "待付款", "已付款", "差异挂起"],
            "summary": {
                "unpaid": scm.r2(sum(x["amount"] - x["paidAmount"] for x in out if x["paidAmount"] == 0)),
                "overdue": scm.r2(sum(x["amount"] - x["paidAmount"] for x in out if x["overdueDays"] > 0)),
                "diff": scm.r2(sum(abs(x["diffAmount"]) for x in out if x["matchResult"] == "金额差异超限")),
            }}


@write_op
def api_invoice_create(cn, user, body):
    require(user, "finance")
    po = one(cn, "SELECT * FROM purchase_orders WHERE no=?", (body.get("poNo") or "",))
    if not po:
        raise ApiError("采购订单不存在：%s" % (body.get("poNo") or ""))
    if po["status"] not in ("已下单", "部分到货", "全部到货"):
        raise ApiError("订单当前为「%s」，不能登记发票" % po["status"])
    amount = float(body.get("amount") or 0)
    if amount <= 0:
        raise ApiError("发票金额需大于 0")
    if one(cn, "SELECT no FROM invoices WHERE po_no=? AND invoice_no=?", (po["no"],
                                                                        body.get("invoiceNo") or "-")):
        raise ApiError("该订单已登记过同一发票号", 409)
    no = next_no(cn, "IV", "invoices")
    invoice_date = body.get("invoiceDate") or today()
    due = scm.payment_due(invoice_date, int(body.get("termsDays") or 30))
    tolerance = float(rule_value(cn, "match_tolerance", 0.02) or 0.02)
    m3 = scm.match3(po["amount"], po["received_amount"], amount, tolerance)
    status = "待付款" if m3["result"] == "通过" else "差异挂起"
    cn.execute("INSERT INTO invoices(no,po_no,supplier_code,supplier_name,invoice_no,amount,tax_rate,"
               "invoice_date,due_date,status,match_result,diff_amount,diff_rate,paid_amount,paid_at,"
               "remark,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (no, po["no"], po["supplier_code"], po["supplier_name"], body.get("invoiceNo") or "",
                amount, float(body.get("taxRate") or 0.13), invoice_date, due, status, m3["result"],
                m3["diff"], m3["rate"], 0, "", body.get("remark") or "", now(), now()))
    cn.execute("UPDATE purchase_orders SET invoiced_amount=?, match_result=?, updated_at=? WHERE no=?",
               (amount, m3["result"], now(), po["no"]))
    op(cn, user["username"], "登记发票", "%s %s %.2f（%s）" % (no, po["no"], amount, m3["result"]))
    emit(cn, "invoice.created", "invoice", no,
         {"no": no, "poNo": po["no"], "amount": amount, "match": m3["result"]}, user["username"])
    return {"no": no, "matchResult": m3["result"], "diffAmount": m3["diff"], "status": status,
            "dueDate": due}


@write_op
def api_invoice_match(cn, user, no, body):
    require(user, "finance")
    r = one(cn, "SELECT * FROM invoices WHERE no=?", (no,))
    if not r:
        raise ApiError("发票不存在：%s" % no, 404)
    po = one(cn, "SELECT * FROM purchase_orders WHERE no=?", (r["po_no"],))
    tolerance = float(rule_value(cn, "match_tolerance", 0.02) or 0.02)
    if body.get("tolerance"):
        tolerance = float(body["tolerance"])
    m3 = scm.match3(po["amount"] if po else 0, po["received_amount"] if po else 0, r["amount"], tolerance)
    status = "待付款" if m3["result"] == "通过" else "差异挂起"
    cn.execute("UPDATE invoices SET match_result=?, diff_amount=?, diff_rate=?, status=?, updated_at=? "
               "WHERE no=?", (m3["result"], m3["diff"], m3["rate"], status, now(), no))
    if po:
        cn.execute("UPDATE purchase_orders SET match_result=? WHERE no=?", (m3["result"], po["no"]))
    op(cn, user["username"], "三单匹配", "%s → %s（差异 %.2f）" % (no, m3["result"], m3["diff"]))
    emit(cn, "invoice.matched", "invoice", no, {"no": no, "result": m3["result"], "diff": m3["diff"]},
         user["username"])
    return {"no": no, "match": m3, "status": status}


@write_op
def api_invoice_pay(cn, user, no, body):
    require(user, "finance")
    r = one(cn, "SELECT * FROM invoices WHERE no=?", (no,))
    if not r:
        raise ApiError("发票不存在：%s" % no, 404)
    if r["match_result"] != "通过":
        raise ApiError("三单匹配未通过（%s），不能付款；请先处理差异" % (r["match_result"] or "未匹配"))
    amount = float(body.get("amount") or (float(r["amount"]) - float(r["paid_amount"] or 0)))
    if amount <= 0:
        raise ApiError("付款金额需大于 0")
    if amount + float(r["paid_amount"] or 0) > float(r["amount"]) + 0.01:
        raise ApiError("付款金额超过发票金额")
    paid = scm.r2(float(r["paid_amount"] or 0) + amount)
    status = "已付款" if paid + 0.01 >= float(r["amount"]) else "待付款"
    cn.execute("UPDATE invoices SET paid_amount=?, paid_at=?, status=?, updated_at=? WHERE no=?",
               (paid, now(), status, now(), no))
    op(cn, user["username"], "付款", "%s %.2f" % (no, amount))
    emit(cn, "invoice.paid", "invoice", no, {"no": no, "amount": amount, "paid": paid}, user["username"])
    return {"no": no, "paidAmount": paid, "status": status}


@with_db
def api_payables(cn, user, q):
    out = []
    for r in rows(cn, "SELECT * FROM invoices WHERE paid_amount<amount ORDER BY due_date"):
        po = one(cn, "SELECT * FROM purchase_orders WHERE no=?", (r["po_no"],))
        v = invoice_view(r, po)
        out.append(v)
    return {"list": out, "total": len(out),
            "due": scm.r2(sum(x["amount"] - x["paidAmount"] for x in out)),
            "overdue": scm.r2(sum(x["amount"] - x["paidAmount"] for x in out if x["overdueDays"] > 0)),
            "buckets": [{"bucket": b, "amount": scm.r2(sum(x["amount"] - x["paidAmount"] for x in out
                                                          if scm.aging_bucket(x["overdueDays"]) == b))}
                        for b in scm.AGING_BUCKETS]}


# ---------------------------------------------------------------- 报表
@with_db
def api_reports(cn, user, q):
    # 1) 采购趋势（6 个月）
    months = []
    for k in range(5, -1, -1):
        mm = (date.today().replace(day=1) - timedelta(days=30 * k)).strftime("%Y-%m")
        rows_ = [p for p in rows(cn, "SELECT * FROM purchase_orders WHERE status<>'已取消'")
                 if (p["ordered_at"] or p["created_at"] or "")[:7] == mm]
        months.append({"month": mm, "amount": scm.r2(sum(float(p["amount"] or 0) for p in rows_)),
                       "count": len(rows_)})
    # 2) 按物料类别
    by_cat = rows(cn, "SELECT m.category category, ROUND(SUM(i.amount),2) amount, COUNT(DISTINCT p.no) poCount "
                      "FROM po_items i JOIN purchase_orders p ON p.no=i.po_no "
                      "JOIN materials m ON m.code=i.material_code WHERE p.status<>'已取消' "
                      "GROUP BY m.category ORDER BY amount DESC")
    # 3) 供应商绩效 TOP
    sup = []
    for s in rows(cn, "SELECT * FROM suppliers ORDER BY score DESC LIMIT 10"):
        last = one(cn, "SELECT * FROM supplier_scores WHERE supplier_code=? ORDER BY id DESC LIMIT 1",
                   (s["code"],))
        pos = rows(cn, "SELECT * FROM purchase_orders WHERE supplier_code=? AND status<>'已取消'", (s["code"],))
        recs = rows(cn, "SELECT r.received_at, p.promise_date FROM receipts r "
                        "JOIN purchase_orders p ON p.no=r.po_no WHERE r.supplier_code=?", (s["code"],))
        sup.append({"code": s["code"], "name": s["name"], "level": s["level"], "status": s["status"],
                    "score": scm.r2(s["score"]),
                    "deliveryRate": last["delivery_rate"] if last else 0,
                    "qualityRate": last["quality_rate"] if last else 0,
                    "priceIndex": last["price_index"] if last else 1,
                    "poAmount": scm.r2(sum(float(p["amount"] or 0) for p in pos)),
                    "poCount": len(pos),
                    "onTimeRate": scm.on_time_rate([{"promise": x["promise_date"],
                                                    "actual": x["received_at"]} for x in recs])})
    # 4) 库存周转（近 90 天）
    period = scm.add_days(today(), -90)
    turnover = []
    for c in rows(cn, "SELECT m.category category FROM materials m GROUP BY m.category"):
        cat = c["category"]
        issue = one(cn, "SELECT COALESCE(SUM(v.cost),0) s FROM stock_moves v JOIN materials m "
                        "ON m.code=v.material_code WHERE v.type IN ('领用出库','调拨出库') "
                        "AND v.created_at>=? AND m.category=?", (period, cat))["s"]
        stock_amt = one(cn, "SELECT COALESCE(SUM(s.qty*s.unit_cost),0) s FROM stock s "
                            "JOIN materials m ON m.code=s.material_code WHERE m.category=?", (cat,))["s"]
        times = scm.turnover(issue, stock_amt)
        turnover.append({"category": cat, "issueAmount": scm.r2(issue), "stockAmount": scm.r2(stock_amt),
                         "times": times, "days": scm.turnover_days(times, 90)})
    turnover.sort(key=lambda x: -float(x["issueAmount"] or 0))
    # 5) 缺料与安全库存
    shortages = api_shortage.__wrapped__(cn, user, q)
    # 6) 到货准时率（按月）
    ontime = []
    for k in range(5, -1, -1):
        mm = (date.today().replace(day=1) - timedelta(days=30 * k)).strftime("%Y-%m")
        pairs = []
        for r in rows(cn, "SELECT r.received_at, p.promise_date FROM receipts r "
                          "JOIN purchase_orders p ON p.no=r.po_no WHERE r.received_at LIKE ?", (mm + "%",)):
            pairs.append({"promise": r["promise_date"], "actual": r["received_at"]})
        ontime.append({"month": mm, "rate": scm.on_time_rate(pairs), "count": len(pairs)})
    # 7) 价格波动（重点物料最近 3 次成交）
    price = []
    for m in rows(cn, "SELECT * FROM materials WHERE abc IN ('A','B') ORDER BY standard_price DESC LIMIT 8"):
        hist = rows(cn, "SELECT price, effective_at, source FROM material_prices WHERE material_code=? "
                        "ORDER BY effective_at DESC, id DESC LIMIT 4", (m["code"],))
        if not hist:
            continue
        latest = float(hist[0]["price"] or 0)
        bench = float(m["standard_price"] or 0)
        price.append({"code": m["code"], "name": m["name"], "unit": m["unit"],
                      "standard": scm.r2(bench), "latest": scm.r2(latest),
                      "index": scm.price_index(latest, bench),
                      "saving": scm.saving_rate(latest, bench),
                      "history": [{"price": scm.r2(h["price"]), "at": h["effective_at"],
                                   "source": h["source"]} for h in hist]})
    # 8) 应付账龄
    payables = api_payables.__wrapped__(cn, user, q)
    # 9) 综合 KPI
    pos = rows(cn, "SELECT * FROM purchase_orders WHERE status<>'已取消'")
    total_amount = sum(float(p["amount"] or 0) for p in pos)
    saving = 0.0
    for p in pos:
        supplier_score = one(cn, "SELECT score FROM suppliers WHERE code=?", (p["supplier_code"],))
        saving += float(p["amount"] or 0) * 0.02      # 以 2% 作为议价基准的估算口径（演示用）
    kpi = {
        "poCount": len(pos),
        "poAmount": scm.r2(total_amount),
        "avgPoAmount": scm.r2(total_amount / len(pos)) if pos else 0,
        "supplierCount": one(cn, "SELECT COUNT(*) c FROM suppliers")["c"],
        "activeSupplier": one(cn, "SELECT COUNT(*) c FROM suppliers WHERE status='已准入'")["c"],
        "stockAmount": one(cn, "SELECT COALESCE(SUM(qty*unit_cost),0) s FROM stock")["s"],
        "issueAmount": one(cn, "SELECT COALESCE(SUM(cost),0) s FROM stock_moves WHERE created_at>=?",
                           (period,))["s"],
        "shortageCount": shortages["total"],
        "payable": payables["due"],
        "overduePayable": payables["overdue"],
    }
    return {"kpi": kpi, "purchaseTrend": months, "byCategory": by_cat, "suppliers": sup,
            "turnover": turnover, "shortages": shortages["list"][:8],
            "onTime": ontime, "price": price, "payables": payables,
            "tolerance": float(rule_value(cn, "match_tolerance", 0.02) or 0.02)}


# ---------------------------------------------------------------- 设置
@with_db
def api_settings(cn, user):
    return {"rules": rows(cn, "SELECT * FROM rules ORDER BY rowid"),
            "users": rows(cn, "SELECT username,display_name,role,dept_code,phone,email,status FROM users"),
            "teams": rows(cn, "SELECT * FROM teams"),
            "warehouses": rows(cn, "SELECT * FROM warehouses"),
            "budgets": rows(cn, "SELECT * FROM budgets ORDER BY period DESC, dept"),
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
    if code == "qual_warn_days":
        rule_warn_days_cache["v"] = int(body.get("value") or 30)
    return one(cn, "SELECT * FROM rules WHERE code=?", (code,))


@with_db
def api_logs(cn, user, q):
    return rows(cn, "SELECT * FROM op_logs ORDER BY id DESC LIMIT 200")


@with_db
def api_users(cn, user):
    return rows(cn, "SELECT username,display_name,role,dept_code,phone,email,status FROM users ORDER BY role")


# ---------------------------------------------------------------- 集成
@with_db
def api_int_keys(cn, user):
    need_admin(user)
    out = []
    for r in rows(cn, "SELECT * FROM api_keys ORDER BY id DESC"):
        out.append({"id": r["id"], "name": r["name"], "keyPrefix": r["key_prefix"], "scope": r["scope"],
                    "owner": r["owner"], "status": r["status"], "expiresAt": r["expires_at"],
                    "lastUsedAt": r["last_used_at"], "createdAt": r["created_at"]})
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
    plain = "fqk_" + secrets.token_hex(20)
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
    return {"list": out, "events": [
        "supplier.created", "supplier.status_changed", "supplier.scored",
        "material.created", "req.created", "req.submitted", "req.approved", "req.rejected",
        "rfq.created", "rfq.awarded", "po.created", "po.stage_changed", "po.cancelled",
        "receipt.created", "receipt.inspected", "receipt.posted", "receipt.returned",
        "stock.adjusted", "stock.transferred", "stock.stocktake",
        "invoice.created", "invoice.matched", "invoice.paid"]}


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
                           body.get("secret") or secrets.token_hex(16), "启用", "", "", 0,
                           now())).lastrowid
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
    payload = {"test": True, "at": now(), "note": "飞泉 SCM 连通性测试"}
    cn.execute("INSERT INTO webhook_deliveries(webhook_id,event,payload,signature,status,attempts,"
               "http_code,error,next_at,created_at,delivered_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (wid, "webhook.test", json.dumps(payload, ensure_ascii=False),
                scm.sign_payload(h["secret"], str(int(time.time())),
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
    cn.execute("UPDATE webhook_deliveries SET status='待投递', next_at=?, error='' WHERE id=?", (now(), did))
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
def api_export_suppliers(cn, user):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["供应商编码", "名称", "类别", "等级", "状态", "综合分", "交付及时率", "质量合格率",
                "账期(天)", "提前期(天)", "订单数", "采购金额"])
    for s in rows(cn, "SELECT * FROM suppliers ORDER BY code"):
        last = one(cn, "SELECT * FROM supplier_scores WHERE supplier_code=? ORDER BY id DESC LIMIT 1",
                   (s["code"],))
        agg = one(cn, "SELECT COUNT(*) c, COALESCE(SUM(amount),0) a FROM purchase_orders WHERE supplier_code=?",
                  (s["code"],))
        w.writerow([s["code"], s["name"], s["category"], s["level"], s["status"], scm.r2(s["score"]),
                    scm.r4(last["delivery_rate"] if last else 0),
                    scm.r4(last["quality_rate"] if last else 0), s["payment_terms"], s["lead_days"],
                    agg["c"], scm.r2(agg["a"])])
    return {"csv": out.getvalue(), "filename": "suppliers.csv"}


@with_db
def api_export_orders(cn, user, q):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["订单号", "供应商", "标题", "金额", "状态", "承诺到货", "负责人", "已收数量", "订购数量",
                "到货率", "匹配结果"])
    for p in rows(cn, "SELECT p.*, u.display_name owner_name FROM purchase_orders p "
                      "LEFT JOIN users u ON u.username=p.owner ORDER BY p.no"):
        w.writerow([p["no"], p["supplier_name"], p["title"], scm.r2(p["amount"]), p["status"],
                    p["promise_date"], p["owner_name"] or p["owner"], scm.r2(p["received_qty"]),
                    scm.r2(p["ordered_qty"]),
                    "%.1f%%" % (scm.receive_rate(p["ordered_qty"], p["received_qty"]) * 100),
                    p["match_result"]])
    return {"csv": out.getvalue(), "filename": "purchase_orders.csv"}


# ---------------------------------------------------------------- OpenAPI
def openapi_spec():
    def op(summary, tag, perm="read", body=None, params=None):
        d = {"summary": summary, "tags": [tag], "responses": {"200": {"description": "成功"}},
             "security": [{"bearerAuth": []}]}
        if params:
            d["parameters"] = [{"name": k, "in": "query", "schema": {"type": "string"},
                                "description": v} for k, v in params.items()]
        if body:
            d["requestBody"] = {"content": {"application/json": {"schema": body}}}
        d["x-permission"] = perm
        return d

    S = lambda **kw: {"type": "object", "properties": kw}   # noqa: E731
    paths = {
        "/api/health": {"get": {"summary": "健康检查", "tags": ["系统"],
                                 "responses": {"200": {"description": "ok"}}}},
        "/api/auth/login": {"post": op("账号登录", "认证", "public",
                                       S(username={"type": "string"}, password={"type": "string"}))},
        "/api/auth/me": {"get": op("当前身份与权限点", "认证")},
        "/api/bootstrap": {"get": op("供应链驾驶舱首屏（KPI / 待办 / 预警）", "系统")},
        "/api/suppliers": {"get": op("供应商列表", "供应商", params={"kw": "关键字", "category": "类别",
                                                                 "level": "等级", "status": "状态"}),
                           "post": op("新建供应商（含查重）", "供应商", "write",
                                      S(name={"type": "string"}, taxNo={"type": "string"},
                                        category={"type": "string"}))},
        "/api/suppliers/{code}": {"get": op("供应商 360（资质/绩效/订单/收货/发票）", "供应商"),
                                  "put": op("更新供应商", "供应商", "write")},
        "/api/suppliers/{code}/status": {"post": op("准入/观察/冻结", "供应商", "write")},
        "/api/suppliers/{code}/quals": {"post": op("登记资质", "供应商", "write")},
        "/api/suppliers/{code}/score": {"post": op("录入季度绩效", "供应商", "write")},
        "/api/materials": {"get": op("物料列表", "物料", params={"kw": "关键字", "abc": "ABC"}),
                           "post": op("新建物料", "物料", "write")},
        "/api/materials/{code}": {"get": op("物料详情（价格/库存/流水）", "物料"),
                                  "put": op("更新物料", "物料", "write")},
        "/api/materials/check-dup": {"get": op("物料查重", "物料", params={"name": "名称", "spec": "规格"})},
        "/api/materials/abc-recalc": {"post": op("按采购金额重算 ABC", "物料", "write")},
        "/api/requisitions": {"get": op("请购列表", "请购", params={"status": "状态", "kw": "关键字"}),
                              "post": op("新建请购", "请购", "write")},
        "/api/requisitions/{no}": {"get": op("请购详情", "请购")},
        "/api/requisitions/{no}/submit": {"post": op("提交请购（小额自动通过）", "请购", "write")},
        "/api/requisitions/{no}/approve": {"post": op("批准请购（校验部门预算）", "请购", "approve")},
        "/api/requisitions/{no}/reject": {"post": op("驳回请购", "请购", "approve")},
        "/api/requisitions/{no}/to-order": {"post": op("转采购订单", "请购", "write")},
        "/api/requisitions/{no}/to-rfq": {"post": op("发起询价", "请购", "write")},
        "/api/rfqs": {"get": op("询价列表", "询价")},
        "/api/rfqs/{no}": {"get": op("询价详情与报价对比", "询价")},
        "/api/rfqs/{no}/quotes": {"post": op("登记供应商报价", "询价", "write")},
        "/api/rfqs/{no}/award": {"post": op("定标并生成订单", "询价", "approve")},
        "/api/orders": {"get": op("采购订单列表", "采购", params={"status": "状态", "overdue": "只看逾期",
                                                             "supplier": "供应商"}),
                        "post": op("新建采购订单", "采购", "write")},
        "/api/orders/{no}": {"get": op("采购订单详情（闸口/匹配/发票）", "采购")},
        "/api/orders/{no}/stage": {"post": op("订单状态推进", "采购", "write")},
        "/api/orders/{no}/cancel": {"post": op("取消订单", "采购", "write")},
        "/api/orders/{no}/receive": {"post": op("到货登记（生成收货单）", "收货", "stock")},
        "/api/receipts": {"get": op("收货单列表", "收货", params={"status": "状态"})},
        "/api/receipts/{no}": {"get": op("收货单详情", "收货")},
        "/api/receipts/{no}/inspect": {"post": op("到货质检", "收货", "stock")},
        "/api/receipts/{no}/post": {"post": op("入库过账（写库存与流水）", "收货", "stock")},
        "/api/receipts/{no}/return": {"post": op("到货退货", "收货", "stock")},
        "/api/stock": {"get": op("库存台账", "库存", params={"warehouse": "仓库", "state": "状态",
                                                         "expiry": "近效期"})},
        "/api/stock/summary": {"get": op("按物料汇总库存与状态", "库存")},
        "/api/stock/shortage": {"get": op("缺料与补货建议", "库存")},
        "/api/stock/adjust": {"post": op("库存调整（盘盈亏/领用）", "库存", "stock")},
        "/api/moves": {"get": op("出入库流水", "库存", params={"type": "类型", "kw": "关键字"})},
        "/api/transfers": {"get": op("调拨单列表", "库存"), "post": op("新建调拨", "库存", "stock")},
        "/api/transfers/{no}/approve": {"post": op("审批调拨", "库存", "stock")},
        "/api/transfers/{no}/post": {"post": op("执行调拨", "库存", "stock")},
        "/api/stocktakes": {"get": op("盘点单列表", "库存"), "post": op("发起盘点", "库存", "stock")},
        "/api/stocktakes/{no}/finish": {"post": op("完成盘点（差异过账）", "库存", "stock")},
        "/api/invoices": {"get": op("发票列表", "结算", params={"status": "状态"}),
                          "post": op("登记发票（自动三单匹配）", "结算", "finance")},
        "/api/invoices/{no}/match": {"post": op("重新三单匹配", "结算", "finance")},
        "/api/invoices/{no}/pay": {"post": op("付款核销", "结算", "finance")},
        "/api/payables": {"get": op("应付与账龄", "结算")},
        "/api/reports": {"get": op("供应链报表（趋势/绩效/周转/缺料/准时率/价格）", "报表")},
        "/api/settings": {"get": op("规则、用户、仓网与预算", "系统")},
        "/api/rules/{code}": {"put": op("调整业务规则", "系统", "admin")},
        "/api/logs": {"get": op("操作日志", "系统")},
        "/api/integration/overview": {"get": op("集成概览", "集成", "admin")},
        "/api/integration/keys": {"get": op("API Key 列表", "集成", "admin"),
                                  "post": op("创建 API Key", "集成", "admin")},
        "/api/integration/webhooks": {"get": op("Webhook 列表", "集成", "admin"),
                                      "post": op("新建 Webhook", "集成", "admin")},
        "/api/integration/deliveries": {"get": op("投递记录", "集成", "admin")},
        "/api/sync/changes": {"get": op("增量同步游标", "集成", params={"since": "游标", "object": "对象类型"})},
        "/api/integration/resolve": {"get": op("外部 ID 反查", "集成", params={"externalId": "外部单号"})},
    }
    return {
        "openapi": "3.0.3",
        "info": {"title": "飞泉 SCM 系统 API", "version": VERSION,
                 "description": "供应链管理：供应商准入 → 请购 → 询价比价 → 采购订单 → 收货质检 → 入库 → "
                                "三单匹配 → 付款；库存台账、调拨盘点、报表与三层集成通道。"},
        "servers": [{"url": "/", "description": "当前实例"}],
        "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
        "paths": paths,
        "x-token-channels": ["X-Fy-Token", "Authorization: Bearer", "Cookie fy_token", "?token=",
                             "body.token"],
    }


# ---------------------------------------------------------------- Webhook 投递
def _post_json(url, body, headers, timeout=5):
    """发送 JSON POST，返回 (http_code, err)。用 http.client 保持自定义头原始大小写。"""
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
    return code, ("" if 200 <= code < 300 else "HTTP %s %s" % (code, snippet[:120]))


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
        sig = scm.sign_payload(h["secret"], ts, body.decode("utf-8"))
        code, err = 0, ""
        try:
            code, err = _post_json(h["url"], body, {
                "Content-Type": "application/json; charset=utf-8",
                "X-FQC-Event": d["event"],
                "X-FQC-Timestamp": ts,
                "X-FQC-Signature": "sha256=" + sig,
                "X-FQC-Delivery": str(d["id"]),
            }, timeout=5)
        except Exception as e:  # noqa: BLE001
            err = str(e)[:300]
        attempts = int(d["attempts"]) + 1
        okk = 200 <= code < 300
        with LOCK:
            if okk:
                cn.execute("UPDATE webhook_deliveries SET status='成功', attempts=?, http_code=?, error='', "
                           "delivered_at=? WHERE id=?", (attempts, code, now(), delivery_id))
                cn.execute("UPDATE webhooks SET last_status=?, last_at=?, fail_count=0 WHERE id=?",
                           ("成功 %d" % code, now(), h["id"]))
            else:
                retry = attempts < WEBHOOK_MAX_TRY
                nxt = (datetime.now() + timedelta(seconds=30 * (2 ** attempts))).strftime(
                    "%Y-%m-%d %H:%M:%S")
                cn.execute("UPDATE webhook_deliveries SET status=?, attempts=?, http_code=?, error=?, "
                           "next_at=? WHERE id=?", ("待投递" if retry else "失败", attempts, code, err,
                                                    nxt, delivery_id))
                cn.execute("UPDATE webhooks SET last_status=?, last_at=?, fail_count=fail_count+1 WHERE id=?",
                           ("失败：%s" % (err or code), now(), h["id"]))
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
    # 供应商
    ("GET", r"^/api/suppliers$", lambda cn, u, b, q: api_suppliers(cn, u, q), None),
    ("POST", r"^/api/suppliers$", lambda cn, u, b, q: api_supplier_create(cn, u, b), None),
    ("GET", r"^/api/suppliers/([\w\-]+)$", lambda cn, u, b, q, c: api_supplier_detail(cn, u, c), None),
    ("PUT", r"^/api/suppliers/([\w\-]+)$", lambda cn, u, b, q, c: api_supplier_update(cn, u, c, b), None),
    ("POST", r"^/api/suppliers/([\w\-]+)/status$",
     lambda cn, u, b, q, c: api_supplier_status(cn, u, c, b), None),
    ("POST", r"^/api/suppliers/([\w\-]+)/quals$",
     lambda cn, u, b, q, c: api_supplier_qual_add(cn, u, c, b), None),
    ("POST", r"^/api/suppliers/([\w\-]+)/score$",
     lambda cn, u, b, q, c: api_supplier_score_add(cn, u, c, b), None),
    # 物料
    ("GET", r"^/api/materials$", lambda cn, u, b, q: api_materials(cn, u, q), None),
    ("POST", r"^/api/materials$", lambda cn, u, b, q: api_material_create(cn, u, b), None),
    ("GET", r"^/api/materials/check-dup$", lambda cn, u, b, q: api_material_check_dup(cn, u, q), None),
    ("POST", r"^/api/materials/abc-recalc$", lambda cn, u, b, q: api_material_abc(cn, u), None),
    ("GET", r"^/api/materials/([\w\-]+)$", lambda cn, u, b, q, c: api_material_detail(cn, u, c), None),
    ("PUT", r"^/api/materials/([\w\-]+)$", lambda cn, u, b, q, c: api_material_update(cn, u, c, b), None),
    ("GET", r"^/api/warehouses$", lambda cn, u, b, q: api_warehouses(cn, u), None),
    # 请购
    ("GET", r"^/api/requisitions$", lambda cn, u, b, q: api_reqs(cn, u, q), None),
    ("POST", r"^/api/requisitions$", lambda cn, u, b, q: api_req_create(cn, u, b), None),
    ("GET", r"^/api/requisitions/([\w\-]+)$", lambda cn, u, b, q, c: api_req_detail(cn, u, c), None),
    ("POST", r"^/api/requisitions/([\w\-]+)/submit$",
     lambda cn, u, b, q, c: api_req_submit(cn, u, c, b), None),
    ("POST", r"^/api/requisitions/([\w\-]+)/approve$",
     lambda cn, u, b, q, c: api_req_approve(cn, u, c, b), None),
    ("POST", r"^/api/requisitions/([\w\-]+)/reject$",
     lambda cn, u, b, q, c: api_req_reject(cn, u, c, b), None),
    ("POST", r"^/api/requisitions/([\w\-]+)/cancel$",
     lambda cn, u, b, q, c: api_req_cancel(cn, u, c, b), None),
    ("POST", r"^/api/requisitions/([\w\-]+)/to-order$",
     lambda cn, u, b, q, c: api_req_to_po(cn, u, c, b), None),
    ("POST", r"^/api/requisitions/([\w\-]+)/to-rfq$",
     lambda cn, u, b, q, c: api_req_to_rfq(cn, u, c, b), None),
    # 询价
    ("GET", r"^/api/rfqs$", lambda cn, u, b, q: api_rfqs(cn, u, q), None),
    ("GET", r"^/api/rfqs/([\w\-]+)$", lambda cn, u, b, q, c: api_rfq_detail(cn, u, c), None),
    ("POST", r"^/api/rfqs/([\w\-]+)/quotes$", lambda cn, u, b, q, c: api_rfq_quote(cn, u, c, b), None),
    ("POST", r"^/api/rfqs/([\w\-]+)/award$", lambda cn, u, b, q, c: api_rfq_award(cn, u, c, b), None),
    ("POST", r"^/api/rfqs/([\w\-]+)/cancel$", lambda cn, u, b, q, c: api_rfq_cancel(cn, u, c, b), None),
    # 采购订单
    ("GET", r"^/api/orders$", lambda cn, u, b, q: api_orders(cn, u, q), None),
    ("POST", r"^/api/orders$", lambda cn, u, b, q: api_order_create(cn, u, b), None),
    ("GET", r"^/api/orders/([\w\-]+)$", lambda cn, u, b, q, c: api_order_detail(cn, u, c), None),
    ("POST", r"^/api/orders/([\w\-]+)/stage$", lambda cn, u, b, q, c: api_order_stage(cn, u, c, b), None),
    ("POST", r"^/api/orders/([\w\-]+)/cancel$", lambda cn, u, b, q, c: api_order_cancel(cn, u, c, b), None),
    ("POST", r"^/api/orders/([\w\-]+)/receive$", lambda cn, u, b, q, c: api_order_receive(cn, u, c, b), None),
    # 收货
    ("GET", r"^/api/receipts$", lambda cn, u, b, q: api_receipts(cn, u, q), None),
    ("GET", r"^/api/receipts/([\w\-]+)$", lambda cn, u, b, q, c: api_receipt_detail(cn, u, c), None),
    ("POST", r"^/api/receipts/([\w\-]+)/inspect$",
     lambda cn, u, b, q, c: api_receipt_inspect(cn, u, c, b), None),
    ("POST", r"^/api/receipts/([\w\-]+)/post$", lambda cn, u, b, q, c: api_receipt_post(cn, u, c, b), None),
    ("POST", r"^/api/receipts/([\w\-]+)/return$",
     lambda cn, u, b, q, c: api_receipt_return(cn, u, c, b), None),
    # 库存
    ("GET", r"^/api/stock$", lambda cn, u, b, q: api_stock(cn, u, q), None),
    ("GET", r"^/api/stock/summary$", lambda cn, u, b, q: api_stock_summary(cn, u, q), None),
    ("GET", r"^/api/stock/shortage$", lambda cn, u, b, q: api_shortage(cn, u, q), None),
    ("POST", r"^/api/stock/adjust$", lambda cn, u, b, q: api_stock_adjust(cn, u, b), None),
    ("GET", r"^/api/moves$", lambda cn, u, b, q: api_moves(cn, u, q), None),
    ("GET", r"^/api/transfers$", lambda cn, u, b, q: api_transfers(cn, u, q), None),
    ("POST", r"^/api/transfers$", lambda cn, u, b, q: api_transfer_create(cn, u, b), None),
    ("POST", r"^/api/transfers/([\w\-]+)/approve$",
     lambda cn, u, b, q, c: api_transfer_approve(cn, u, c, b), None),
    ("POST", r"^/api/transfers/([\w\-]+)/post$",
     lambda cn, u, b, q, c: api_transfer_post(cn, u, c, b), None),
    ("GET", r"^/api/stocktakes$", lambda cn, u, b, q: api_stocktakes(cn, u, q), None),
    ("POST", r"^/api/stocktakes$", lambda cn, u, b, q: api_stocktake_create(cn, u, b), None),
    ("POST", r"^/api/stocktakes/([\w\-]+)/finish$",
     lambda cn, u, b, q, c: api_stocktake_finish(cn, u, c, b), None),
    # 结算
    ("GET", r"^/api/invoices$", lambda cn, u, b, q: api_invoices(cn, u, q), None),
    ("POST", r"^/api/invoices$", lambda cn, u, b, q: api_invoice_create(cn, u, b), None),
    ("POST", r"^/api/invoices/([\w\-]+)/match$", lambda cn, u, b, q, c: api_invoice_match(cn, u, c, b), None),
    ("POST", r"^/api/invoices/([\w\-]+)/pay$", lambda cn, u, b, q, c: api_invoice_pay(cn, u, c, b), None),
    ("GET", r"^/api/payables$", lambda cn, u, b, q: api_payables(cn, u, q), None),
    # 报表与系统
    ("GET", r"^/api/reports$", lambda cn, u, b, q: api_reports(cn, u, q), None),
    ("GET", r"^/api/settings$", lambda cn, u, b, q: api_settings(cn, u), None),
    ("PUT", r"^/api/rules/([\w\-]+)$", lambda cn, u, b, q, c: api_rule_toggle(cn, u, c, b), None),
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
    ("GET", r"^/api/export/suppliers$", lambda cn, u, b, q: api_export_suppliers(cn, u), None),
    ("GET", r"^/api/export/orders$", lambda cn, u, b, q: api_export_orders(cn, u, q), None),
]


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "FeiquanSCM/" + VERSION

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, payload, headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)
        return None

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
        """多通道取票：任意一个有效即可，避免反向代理改写 Authorization 后掉登录。"""
        out = []
        for h in ("X-Fq-Key", "X-Fq-Token", "X-Auth-Token", "Authorization"):
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
                if k.strip() in ("fq_token", "token") and v.strip():
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
        for prefix in ("/scm", "/feiquan"):
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
                info["suppliers"] = cn.execute("SELECT COUNT(*) c FROM suppliers").fetchone()["c"]
                info["materials"] = cn.execute("SELECT COUNT(*) c FROM materials").fetchone()["c"]
                info["journal"] = cn.execute("PRAGMA journal_mode").fetchone()[0]
                cn.close()
            except Exception as e:  # noqa: BLE001
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
                data = fn(cn, user, body, query, *groups)
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
                headers = {"Retry-After": "60"} if e.code == 429 else None
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
    print("飞泉 SCM v%s 已启动：http://%s:%s" % (VERSION, HOST, PORT))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()

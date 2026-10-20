# -*- coding: utf-8 -*-
"""开发期接口冒烟：把「请购 → 询价 → 订单 → 收货质检 → 入库 → 发票 → 付款」跑一遍。

用法：python tools/smoke_api.py [BASE]
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8031").rstrip("/")
TOK = {"v": ""}
FAIL = []


def call(method, path, body=None, token=None, headers=None):
    url = BASE + path
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 method=method)
    req.add_header("Content-Type", "application/json")
    tk = token if token is not None else TOK["v"]
    if tk:
        req.add_header("Authorization", "Bearer " + tk)
        req.add_header("X-Fq-Token", tk)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def ok(method, path, body=None, **kw):
    st, r = call(method, path, body, **kw)
    if st != 200:
        FAIL.append("%s %s → %s %s" % (method, path, st, r))
        print("  FAIL %s %s → %s %s" % (method, path, st, str(r)[:200]))
        return None
    return r["data"]


def login(user="admin", pwd="admin123"):
    st, r = call("POST", "/api/auth/login", {"username": user, "password": pwd})
    assert st == 200, r
    TOK["v"] = r["data"]["token"]
    print("login ok:", user, r["data"]["roleLabel"])


print("== 基础 ==")
login()
h = ok("GET", "/api/health")
b = ok("GET", "/api/bootstrap")
print("  kpi:", {k: b["kpi"][k] for k in ("openAmount", "openCount", "stockValue", "shortageCount",
                                          "onTimeRate", "pendingInvoice")})
print("  todos:", len(b["todos"]), "poStages:", [(s["stage"], s["count"]) for s in b["poStages"]])

print("== 供应商 / 物料 ==")
sups = ok("GET", "/api/suppliers")
print("  供应商:", sups["total"], "等级分布:", [(x["level"], 1) for x in sups["list"][:3]])
s0 = sups["list"][0]
d = ok("GET", "/api/suppliers/" + s0["code"])
print("  360:", d["code"], "资质", len(d["quals"]), "绩效", len(d["scores"]), "订单", d["poCount"])
mats = ok("GET", "/api/materials?abc=A")
print("  物料 A 类:", mats["total"])
m0 = mats["list"][0]
md = ok("GET", "/api/materials/" + m0["code"])
print("  物料详情:", md["code"], "现存量", md["onHand"], "状态", md.get("state"), "价格记录", len(md["prices"]))
print("  缺料:", ok("GET", "/api/stock/shortage")["total"], "补货金额",
      ok("GET", "/api/stock/shortage")["amount"])

print("== 请购 → 订单 ==")
req = ok("POST", "/api/requisitions", {"dept": "计划部", "purpose": "冒烟测试备料", "needDate": "2026-11-10",
                                       "items": [{"materialCode": m0["code"], "qty": 500}]})
print("  新建请购:", req)
no = req["no"]
print("  提交:", ok("POST", "/api/requisitions/%s/submit" % no, {}))
st, r = call("POST", "/api/requisitions/%s/approve" % no, {})
print("  批准:", st, r.get("data") or r.get("error"))
sup_ok = [s for s in sups["list"] if s["status"] == "已准入"][0]
po = ok("POST", "/api/requisitions/%s/to-order" % no, {"supplierCode": sup_ok["code"]})
print("  转单:", po)
pono = po["poNo"]

print("== 订单状态机 ==")
print("  详情闸口:", ok("GET", "/api/orders/" + pono)["gate"])
print("  推进待审批:", ok("POST", "/api/orders/%s/stage" % pono, {"target": "待审批"}))
print("  推进已下单:", ok("POST", "/api/orders/%s/stage" % pono, {"target": "已下单"}))

print("== 收货 → 质检 → 入库 ==")
login("sunlei", "fe@2026")
rc = ok("POST", "/api/orders/%s/receive" % pono, {"warehouse": "WH-SZ"})
print("  收货:", rc)
grn = rc["receiptNo"]
items = ok("GET", "/api/receipts/" + grn)["items"]
print("  质检:", ok("POST", "/api/receipts/%s/inspect" % grn,
                   {"items": [{"id": i["id"], "okQty": i["qty"] - 2, "ngQty": 2} for i in items]}))
print("  入库:", ok("POST", "/api/receipts/%s/post" % grn, {}))
print("  订单状态:", ok("GET", "/api/orders/" + pono)["status"])

print("== 发票 → 匹配 → 付款 ==")
login("huangli", "fe@2026")
inv = ok("POST", "/api/invoices", {"poNo": pono, "invoiceNo": "FP20261020001",
                                   "amount": ok("GET", "/api/orders/" + pono)["receivedAmount"],
                                   "invoiceDate": "2026-10-20"})
print("  发票:", inv)
print("  匹配:", ok("POST", "/api/invoices/%s/match" % inv["no"], {}))
print("  付款:", ok("POST", "/api/invoices/%s/pay" % inv["no"], {}))

print("== 订单结算 ==")
print("  推进已结算:", ok("POST", "/api/orders/%s/stage" % pono, {"target": "已结算"}))

print("== 库存作业 ==")
login("sunlei", "fe@2026")
print("  调拨:", ok("POST", "/api/transfers", {"fromWh": "WH-SZ", "toWh": "WH-KS",
                                             "items": [{"materialCode": m0["code"], "qty": 10}]}))
tr = ok("GET", "/api/transfers")["list"][0]["no"]
print("  执行调拨:", ok("POST", "/api/transfers/%s/post" % tr, {}))
st = ok("POST", "/api/stocktakes", {"warehouse": "WH-SZ"})
print("  盘点:", st, ok("POST", "/api/stocktakes/%s/finish" % st["no"], {}))

print("== 报表 / 设置 / 集成 ==")
login()
rep = ok("GET", "/api/reports")
print("  报表:", list(rep.keys()))
print("  采购趋势:", [(x["month"], x["amount"]) for x in rep["purchaseTrend"]])
print("  周转:", [(x["category"], x["times"]) for x in rep["turnover"][:3]])
print("  准时率:", [(x["month"], x["rate"]) for x in rep["onTime"]])
print("  设置:", len(ok("GET", "/api/settings")["rules"]), "条规则")
print("  集成:", ok("GET", "/api/integration/overview"))
print("  同步:", ok("GET", "/api/sync/changes?since=0&limit=3")["count"])
st, _ = call("GET", "/api/export/orders")
print("  导出 CSV:", st)

print()
if FAIL:
    print("失败 %d 项：" % len(FAIL))
    for f in FAIL:
        print(" -", f)
    sys.exit(1)
print("接口冒烟全部通过。")

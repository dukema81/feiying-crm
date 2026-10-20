# -*- coding: utf-8 -*-
"""飞泉SCM系统 · 离线单文件 DEMO 生成器

思路：起一个临时后端（独立临时库），把前端需要的全部数据抓成快照内嵌进单个 HTML；
再用 fetch 拦截器在浏览器内存里实现请购 / 询价 / 订单推进 / 收货质检 / 库存作业 /
三单匹配 / 付款 / 集成配置等写操作，口径与后端一致，因此 DEMO 打开即用、
无需服务与网络。
"""
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8879
BASE = "http://127.0.0.1:%d" % PORT

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(path, method="GET", body=None, token=None):
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + urllib.parse.quote(path, safe="/?=&%.:_-"),
                                 data=data, headers=headers, method=method)
    try:
        with _OPENER.open(req, timeout=40) as r:
            j = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit("接口异常 %s %s：%s" % (method, path, e.read().decode("utf-8", "ignore")))
    if "data" not in j:
        raise SystemExit("接口异常 %s：%s" % (path, j))
    return j["data"]


def wait_health(timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        try:
            call("/api/health")
            return True
        except Exception:
            time.sleep(0.4)
    return False


def q(v):
    return urllib.parse.quote(str(v))


def snapshot():
    db_path = os.path.join(ROOT, "reports", "demo_seed.db")
    for suf in ("", "-wal", "-shm"):
        if os.path.exists(db_path + suf):
            os.remove(db_path + suf)
    env = dict(os.environ)
    env["FEIQUAN_PORT"] = str(PORT)
    env["FEIQUAN_DB"] = db_path
    env.pop("http_proxy", None)
    env.pop("HTTP_PROXY", None)
    proc = subprocess.Popen([sys.executable, os.path.join("backend", "server.py")],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        if not wait_health():
            raise SystemExit("后端启动失败（端口 %d 被占用？）" % PORT)
        tk = call("/api/auth/login", "POST",
                  {"username": "admin", "password": "admin123"})["token"]

        snap = {"boot": call("/api/bootstrap", token=tk), "me": call("/api/auth/me", token=tk)}
        snap["suppliers"] = call("/api/suppliers", token=tk)
        snap["supD"] = {x["code"]: call("/api/suppliers/" + q(x["code"]), token=tk)
                        for x in snap["suppliers"]["list"]}
        snap["materials"] = call("/api/materials", token=tk)
        snap["matD"] = {x["code"]: call("/api/materials/" + q(x["code"]), token=tk)
                        for x in snap["materials"]["list"]}
        snap["warehouses"] = call("/api/warehouses", token=tk)
        snap["reqs"] = call("/api/requisitions", token=tk)
        snap["reqD"] = {x["no"]: call("/api/requisitions/" + q(x["no"]), token=tk)
                        for x in snap["reqs"]["list"]}
        snap["rfqs"] = call("/api/rfqs", token=tk)
        snap["rfqD"] = {x["no"]: call("/api/rfqs/" + q(x["no"]), token=tk)
                        for x in snap["rfqs"]["list"]}
        snap["orders"] = call("/api/orders", token=tk)
        snap["orderD"] = {x["no"]: call("/api/orders/" + q(x["no"]), token=tk)
                          for x in snap["orders"]["list"]}
        snap["receipts"] = call("/api/receipts", token=tk)
        snap["receiptD"] = {x["no"]: call("/api/receipts/" + q(x["no"]), token=tk)
                            for x in snap["receipts"]["list"]}
        snap["stock"] = call("/api/stock", token=tk)
        snap["stockSummary"] = call("/api/stock/summary", token=tk)
        snap["shortage"] = call("/api/stock/shortage", token=tk)
        snap["moves"] = call("/api/moves", token=tk)
        snap["transfers"] = call("/api/transfers", token=tk)
        snap["stocktakes"] = call("/api/stocktakes", token=tk)
        snap["invoices"] = call("/api/invoices", token=tk)
        snap["payables"] = call("/api/payables", token=tk)
        snap["reports"] = call("/api/reports", token=tk)
        snap["settings"] = call("/api/settings", token=tk)
        snap["logs"] = call("/api/logs", token=tk)
        snap["integ"] = {
            "overview": call("/api/integration/overview", token=tk),
            "keys": call("/api/integration/keys", token=tk),
            "webhooks": call("/api/integration/webhooks", token=tk),
            "deliveries": call("/api/integration/deliveries", token=tk),
            "mappings": call("/api/integration/mappings", token=tk),
            "sync": call("/api/sync/changes?since=0&limit=15", token=tk),
        }
        print("快照完成：供应商 %d / 物料 %d / 请购 %d / 询价 %d / 订单 %d / 收货 %d / "
              "库存 %d 行 / 发票 %d"
              % (len(snap["suppliers"]["list"]), len(snap["materials"]["list"]),
                 len(snap["reqs"]["list"]), len(snap["rfqs"]["list"]),
                 len(snap["orders"]["list"]), len(snap["receipts"]["list"]),
                 len(snap["stock"]["list"]), len(snap["invoices"]["list"])))
        return snap
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def main():
    snap = snapshot()

    read = lambda p: io.open(os.path.join(ROOT, p), encoding="utf-8").read()
    css = read("frontend/style.css")
    shell = read("frontend/index.html")
    mock = read("tools/demo_mock.js")
    fe = [read("frontend/app.js"), read("frontend/mdm.js"), read("frontend/buy.js"),
          read("frontend/stock.js"), read("frontend/fin.js"), read("frontend/intg.js")]

    body = shell.split("<body>", 1)[1].rsplit("</body>", 1)[0]
    body = body.split('<div class="mask"')[0]

    parts = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>飞泉SCM系统 · 离线演示版</title>",
        "<style>",
        css,
        "html,body{height:auto}",
        ".app{height:auto;min-height:100vh}",
        ".demo-badge{position:fixed;right:16px;bottom:38px;z-index:99;background:#c8963e;"
        "color:#2b1c00;font-size:12px;padding:5px 12px;border-radius:14px;"
        "box-shadow:0 4px 14px rgba(0,0,0,.25);font-weight:600;letter-spacing:.3px}",
        "</style>",
        "</head>",
        "<body>",
        body,
        '<div class="demo-badge">离线演示版 · 数据确定性生成，写操作只在浏览器内存生效</div>',
        '<div class="mask" id="mask"><div class="dialog" id="dialog"></div></div>',
        "<script>window.__DEMO__ = true; var DB = " + json.dumps(snap, ensure_ascii=False) + ";</script>",
        "<script>\n" + mock + "\n</script>",
    ]
    for js in fe:
        parts.append("<script>\n" + js + "\n</script>")
    parts += ["</body>", "</html>"]

    out_dir = os.path.join(ROOT, "demo")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "飞泉SCM系统Demo.html")
    io.open(out, "w", encoding="utf-8").write("\n".join(parts))
    print("已生成：%s（%.1f KB）" % (out, os.path.getsize(out) / 1024.0))


if __name__ == "__main__":
    main()

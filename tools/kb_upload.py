# -*- coding: utf-8 -*-
"""飞鹰CRM系统 · 文档批量上传知识库（分类 33 企业管理系统）

用法：
    python tools/kb_upload.py            # 仅上传（会与旧文档并存）
    python tools/kb_upload.py --replace  # 先删同名旧文档再上传（改版推荐）

docx/zip 必须走 curl -F（手写 multipart 会 parse 失败），md 亦统一走 curl。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = r"C:/Users/maxl/WorkBuddy/Claw/feiying-crm"
BASE = "http://42.193.158.63"
CAT = 33
PASSWORD = "YCSpyVwt@J2UByom3#n6gb"
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOKEN = None
REPLACE = "--replace" in sys.argv

DOCS = [
    ("docs/飞鹰CRM系统建设方案.md", "飞鹰CRM系统建设方案",
     "「飞鹰CRM系统」完整建设方案 V1.0：建设目标与范围、零依赖总体架构（标准库 http.server + sqlite3）、"
     "线索-客户-商机-报价-合同-回款主线、服务工单 SLA 与市场 ROI、业务规则引擎（8 条规则 + 阶段状态机 + "
     "阶段闸口 + 查重分级 + 健康分 + 折扣审批）、7 类角色权限与数据范围、29 表数据模型、80 条 REST 路由、"
     "三条集成通道（REST/Webhook/增量同步）、14 页前端设计、指标口径、非功能设计与实施计划。",
     "飞鹰CRM,企业管理系统,CRM,销售管理,商机,回款,建设方案"),
    ("docs/feiying_plan_v1.docx", "飞鹰CRM系统建设方案（docx 版）",
     "《飞鹰CRM系统建设方案》排版版本（Word V1.0），含封面、目录与全部 13 章内容。",
     "飞鹰CRM,企业管理系统,建设方案,docx"),
    ("docs/API.md", "飞鹰CRM系统 REST 接口契约",
     "80 条路由的完整契约：统一响应包与状态码、两种鉴权（会话 Token / API Key fyk_）、分页与过滤、"
     "Idempotency-Key 幂等、限流 240 次每分钟、线索/客户/商机/跟进/报价/合同/回款/工单/市场/报表全量接口、"
     "集成中心（Key/Webhook/投递日志/外部 ID 映射/增量同步）、Webhook HMAC 签名协议、状态字典与对接实施建议。",
     "飞鹰CRM,API,接口契约,REST,Webhook,增量同步,对接"),
    ("docs/feiying_api_v1.docx", "飞鹰CRM系统 REST 接口契约（docx 版）",
     "《飞鹰CRM系统 REST 接口契约》排版版本（Word V1.0），面向对接方提供。",
     "飞鹰CRM,API,docx,对接"),
    ("docs/飞鹰CRM系统-测试报告.md", "飞鹰CRM系统测试报告",
     "三层自动化测试 127 项全部通过（业务内核单元 53 / REST 接口 60 / 端到端 UI 14），质量门禁 PASS。"
     "含分层策略与环境、覆盖矩阵、关键验证点（状态机与闸口、折扣审批、回款核销、SLA、幂等与签名）、"
     "16 项缺陷台账（现象/根因/修复/验证）、性能观测、遗留风险与复现命令。",
     "飞鹰CRM,测试报告,质量门禁,自动化测试,Playwright"),
    ("docs/feiying_test_v1.docx", "飞鹰CRM系统测试报告（docx 版）",
     "《飞鹰CRM系统测试报告》排版版本（Word V1.0），含封面、目录与完整测试结论（127 项）。",
     "飞鹰CRM,测试报告,docx"),
    ("docs/飞鹰CRM系统-项目说明与操作手册.md", "飞鹰CRM系统项目说明与操作手册",
     "面向岗位的操作手册：启动与八账号登录、界面骨架、14 个页面逐页说明、线索建单与查重/转客户、"
     "客户 360 六标签、商机闸口推进、报价折扣审批、合同签署与收款、回款账龄、工单 SLA、市场 ROI、"
     "报表六标签、集成中心五标签、规则启停、常见问题与数据运维。",
     "飞鹰CRM,操作手册,用户指南,培训"),
    ("docs/feiying_manual_v1.docx", "飞鹰CRM系统项目说明与操作手册（docx 版）",
     "《飞鹰CRM系统项目说明与操作手册》排版版本（Word V1.0）。",
     "飞鹰CRM,操作手册,docx"),
    ("demo/飞鹰CRM系统Demo.zip", "飞鹰CRM系统离线演示（DEMO）",
     "单文件离线演示：解压后双击 HTML 即可用浏览器打开，无需服务与网络。内置确定性演示数据"
     "（48 线索 / 36 客户 / 52 商机 / 19 报价 / 11 合同 / 30 期回款计划 / 18 工单），"
     "建单、查重、转客户、阶段推进、折扣审批、合同签署、收款核销、工单 SLA 在浏览器内存按与后端一致的口径真实计算。",
     "飞鹰CRM,DEMO,离线演示,客户管理,销售管理"),
]


def req(path, method="GET", body=None, token=None, ctype="application/json"):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", ctype)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with OP.open(r, timeout=90) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def curl_upload(path, title, desc, tags):
    full = os.path.join(ROOT, path)
    mime = "application/zip" if full.endswith(".zip") else (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if full.endswith(".docx") else "text/markdown")
    cmd = ["curl", "-s", "--noproxy", "*",
           "-H", "Authorization: Bearer " + TOKEN,
           "-F", "file=@%s;type=%s" % (full, mime),
           "-F", "title=" + title,
           "-F", "description=" + desc,
           "-F", "categoryId=%d" % CAT,
           "-F", "tags=" + tags,
           BASE + "/api/documents/upload"]
    out = subprocess.run(cmd, capture_output=True, timeout=300)
    try:
        return json.loads(out.stdout.decode("utf-8", "ignore"))
    except Exception:
        return {"code": -1, "raw": out.stdout.decode("utf-8", "ignore")[:400],
                "err": out.stderr.decode("utf-8", "ignore")[:200]}


def existing(cat=CAT):
    """拉取分类下的文档（分页参数是 pageNum/pageSize，返回 records 不是 list；用 page/size 只会拿到前 10 条）。"""
    st, j = req("/api/documents?categoryId=%d&pageNum=1&pageSize=200" % cat, token=TOKEN)
    data = j.get("data") or {}
    if isinstance(data, list):
        return data
    return data.get("records") or data.get("list") or []


def delete_doc(doc_id):
    st, j = req("/api/documents/%s" % doc_id, "DELETE", token=TOKEN)
    return st, j


def build_demo_zip():
    src = os.path.join(ROOT, "demo", "飞鹰CRM系统Demo.html")
    out = os.path.join(ROOT, "demo", "飞鹰CRM系统Demo.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(src, "飞鹰CRM系统Demo.html")
        z.writestr("使用说明.txt",
                   "飞鹰CRM系统 · 离线演示\r\n"
                   "1. 解压后双击「飞鹰CRM系统Demo.html」，用浏览器打开即可，无需安装、无需联网。\r\n"
                   "2. 内置确定性演示数据：48 线索 / 36 客户 / 52 商机 / 19 报价 / 11 合同 / 30 期回款计划 / 18 工单。\r\n"
                   "3. 建线索（含查重提示）、转客户、商机阶段推进、报价折扣审批、合同签署、登记收款、"
                   "工单受理/解决/关闭都在浏览器内存里按与后端一致的口径真实计算；刷新即回到初始状态。\r\n"
                   "4. 账号：离线版固定以 admin（系统管理员）进入，便于一个人体验完整流程。\r\n"
                   "5. 完整版本（多账号 + 真实权限 + 落地数据）请部署 backend/server.py 后访问 http://127.0.0.1:8018/。\r\n")
    print("DEMO zip 重建：%.1f KB" % (os.path.getsize(out) / 1024.0))


def main():
    global TOKEN
    st, j = req("/api/auth/login", "POST", {"username": "admin", "password": PASSWORD})
    assert j.get("code") == 200, j
    TOKEN = j["data"]["token"]
    st, j = req("/api/users/whoami", token=TOKEN)
    print("whoami:", j.get("code"))

    build_demo_zip()

    if REPLACE:
        olds = existing()
        want = {t for _, t, _, _ in DOCS}
        for r in olds:
            if r.get("title") in want:
                st, j = delete_doc(r.get("id"))
                print("删除旧文档 %s id=%s -> %s" % (r.get("title"), r.get("id"), st))
                time.sleep(0.4)

    results = []
    for path, title, desc, tags in DOCS:
        j = curl_upload(path, title, desc, tags)
        code = j.get("code")
        doc_id = (j.get("data") or {}).get("id") if isinstance(j.get("data"), dict) else j.get("data")
        size = os.path.getsize(os.path.join(ROOT, path))
        print("%-46s code=%s id=%s %.1fKB" % (os.path.basename(path), code, doc_id, size / 1024.0))
        if code != 200:
            print("   !!", str(j)[:300])
        results.append((path, title, code, doc_id))
        time.sleep(1.2)

    ok = [r for r in results if r[2] == 200]
    print("\n上传成功 %d / %d" % (len(ok), len(results)))
    with open(os.path.join(ROOT, "reports", "kb_upload_result.json"), "w", encoding="utf-8") as f:
        json.dump([{"file": r[0], "title": r[1], "code": r[2], "id": r[3]} for r in results],
                  f, ensure_ascii=False, indent=2)
    st, j = req("/api/document-categories", token=TOKEN)
    for c in (j.get("data") or []):
        if isinstance(c, dict) and c.get("id") == CAT:
            print("cat33 docCount:", c.get("docCount"))


if __name__ == "__main__":
    main()

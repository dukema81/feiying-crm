# 飞泉SCM系统（Feiquan SCM）

面向中小制造企业的供应链管理系统：**供应商管理 → 采购执行（请购 / 询价 / 订单 / 收货质检）→ 仓储库存（批次台账 / 调拨 / 盘点）→ 结算付款（三单匹配 / 应付账龄）**，并提供 API Key / Webhook / 增量同步三条开放集成通道。

零依赖：仅用 Python 标准库（http.server + sqlite3）与原生 HTML/CSS/JS，单机可跑、离线可用。

## 快速开始

```bash
python backend/server.py
# 打开 http://127.0.0.1:8019
# 管理员：admin / admin123；其余账号密码 fe@2026（详见操作手册）
```

首次启动自动建库并生成确定性演示数据（种子 20261020）。

环境变量：`FEIQUAN_PORT`（默认 8019）、`FEIQUAN_DB`（默认 backend/data/feiquan.db）。

## 功能一览

| 域 | 能力 |
|---|---|
| 供应商 | 360 档案、资质预警与准入闸口、四维绩效（交付35/质量35/价格15/协同15）自动定级、健康状态联动 |
| 采购 | 请购（免审批金额 + 预算校验）、询价比价（≥2 家定标）、订单状态机（草稿→待审批→已下单→部分到货→全部到货→已结算）与五类闸口、收货质检（合格/让步接收/退货） |
| 库存 | 批次台账、安全库存/补货点/覆盖天数、ABC 分类、缺料一键转请购、调拨、盘点、手工调整、库龄效期 |
| 结算 | 发票登记即三单匹配（容差 2%）、差异挂起禁付、部分付款、应付账龄五档 |
| 分析 | 供应链驾驶舱、报表九模块（趋势/类别/绩效/周转/准时率/价格波动/账龄等） |
| 集成 | API Key（fqk_ 前缀，限流 240/min）、Webhook（23 事件，HMAC-SHA256 签名，退避重试）、增量同步（游标式） |

## 测试

三层自动化测试 169 项全部通过（单元 85 / 接口 71 / 端到端 UI 13）：

```bash
python scripts/run_tests.py      # 一键门禁
python tools/smoke_demo.py       # 离线 DEMO 冒烟
```

## 文档

- `docs/飞泉SCM系统建设方案.md` / `.docx` — 完整设计方案
- `docs/API.md` — 82 条 REST 接口契约（对接方必读）
- `docs/飞泉SCM系统-测试报告.md` — 三层测试与缺陷台账
- `docs/飞泉SCM系统-项目说明与操作手册.md` — 逐页操作说明

离线演示：`demo/飞泉SCM系统Demo.html` 双击即可在浏览器体验全部写操作（内存计算）。

## 目录结构

```
backend/   scm.py 业务内核（纯函数）· db.py 34表 · seed.py 演示数据 · server.py 82条路由
frontend/  app/mdm/buy/stock/fin/intg.js + style.css（14 页，零依赖）
tests/     test_unit_core / test_api / test_e2e_ui（Playwright）
tools/     构建 DEMO / 文档 / 测试冒烟 / 知识库上传 / GitHub 推送
deploy/    部署打包脚本
```

## 在线演示

https://drone-store.app.workbuddy.host/

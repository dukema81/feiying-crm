# 飞鹰CRM系统（Feiying CRM）

面向 B2B 项目型销售团队的客户与销售全流程管理系统：**线索 → 客户 → 商机 → 报价 → 合同 → 回款 → 服务** 一条主线跑通，规则口径全部由后端纯函数内核统一计算。

零第三方依赖：后端 Python 标准库（`http.server` + `sqlite3`），前端原生 HTML/CSS/JS。一条命令启动，单文件离线 DEMO 双击即用。

## 在线访问

- 云端实例：<https://drone-store.app.workbuddy.host/>（账号 `admin` / `admin123`，演示数据已预置）
- 代码仓库：<https://github.com/dukema81/feiying-crm>
- 离线单文件 DEMO：`demo/飞鹰CRM系统Demo.html`（双击即用，数据在浏览器内存中，改完刷新即复原）

## 快速开始

```bash
cd backend
python server.py            # 默认 http://127.0.0.1:8018，首启自动建库并灌演示数据
```

浏览器打开 <http://127.0.0.1:8018>，用 `admin` / `admin123` 登录（其余岗位账号见手册：密码统一 `fe@2026`）。

离线演示（无需服务与网络）：双击 `demo/飞鹰CRM系统Demo.html`。

## 功能一览

| 模块 | 关键能力 |
|---|---|
| 营销获客 | 线索池、查重（手机/邮箱/公司名相似度）、A/B/C 分级、分配/领取/回收公海、市场活动与 ROI/CPL |
| 客户经营 | 客户档案、联系人、客户 360（联系人/商机/报价/合同/工单/时间线）、健康分与流失预警 |
| 销售过程 | 商机看板与列表、阶段状态机（只能前进、赢单须从商务谈判进）、阶段闸口、跟进记录 |
| 交易与回款 | 报价明细与折扣审批（超阈须批准才能发送）、合同付款条件与签署、回款计划 FIFO 核销、账龄五档 |
| 客户服务 | 工单 SLA（P1 4h / P2 8h / P3 24h，临期 2h 预警）、受理/解决/关闭评价 |
| 分析 | 漏斗与相邻转化、业绩排行、来源转化、滚动预测（加权/乐观/悲观）、应收账龄、服务分析 |
| 系统与集成 | 7 类角色权限与数据范围、8 条可在线调整的业务规则、操作日志、API Key / Webhook / 增量同步 / 外部 ID 映射 |

## 目录结构

```
backend/    crm.py 业务内核（纯函数）｜db.py 29 表 DDL｜seed.py 确定性演示数据｜server.py 80 条路由
frontend/   14 个页面：app.js 框架 + sales/deal/svc/intg 四组业务页
tests/      单元 53 项｜接口 59 项｜端到端 14 项（Playwright）
tools/      DEMO 构建、文档构建、知识库上传、GitHub 推送、冒烟脚本
deploy/     部署包构建
docs/       建设方案、接口契约、测试报告、操作手册（md + docx）
demo/       离线单文件演示
scripts/    一键测试门禁
```

## 测试与质量门禁

```bash
python scripts/run_tests.py        # 三层 127 项，全绿才允许部署
python tools/build_demo.py         # 重建离线 DEMO
python tools/smoke_demo.py         # 离线 DEMO 冒烟（Playwright）
```

当前状态：**127 / 127 通过，门禁 PASS**（单元 53、接口 60、端到端 14），产物见 `reports/`。

## 对外接口

- 机器可读契约：`GET /api/openapi.json`（OpenAPI 3.0.3）
- 三条对接通道：REST 拉取（API Key `fyk_...`）、Webhook 推送（HMAC-SHA256 签名 + 退避重试）、增量同步（`/api/sync/changes?since=`）
- 配套能力：`Idempotency-Key` 幂等、240 次/分钟/Key 限流、外部 ID 映射反查
- 完整说明见 [`docs/API.md`](docs/API.md)

## 文档

| 文档 | 内容 |
|---|---|
| `docs/飞鹰CRM系统建设方案.md` | 背景目标、架构取舍、数据模型、核心流程、规则引擎、权限、集成、实施计划 |
| `docs/API.md` | 80 条路由契约、鉴权与错误码、Webhook 与增量同步协议、对接建议 |
| `docs/飞鹰CRM系统-测试报告.md` | 127 项测试结论、覆盖矩阵、17 项缺陷台账、性能观测、遗留风险 |
| `docs/飞鹰CRM系统-项目说明与操作手册.md` | 启动与账号、14 页逐页操作、常见问题、数据运维 |

## 说明

- 默认单组织单账套；多组织/多币种、CPQ、移动端列为后续演进。
- 演示数据确定性生成（`SEED=20261020`，日历锚点 2026-10-20），删除 `data/feiying.db*` 后重启即可重置。

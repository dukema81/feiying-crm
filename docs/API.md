# 飞鹰CRM系统 REST 接口契约（API.md）

本文是飞鹰CRM 对外开放接口的完整契约，供 ERP、BI、客服、财务等系统对接使用。机器可读版本：`GET /api/openapi.json`（OpenAPI 3.0.3）。

## 通用约定

### 基础

| 项 | 值 |
|---|---|
| 基础地址 | `http://<host>:8018`（默认端口 8018，可用 `FEIYING_PORT` 覆盖） |
| 传输 | HTTP/1.1，JSON（UTF-8，`Content-Type: application/json`） |
| 版本 | `1.0.0`（`/api/health` 返回） |
| 路由数 | 80 条（含 2 条 CSV 导出） |
| 时间格式 | `YYYY-MM-DD HH:MM:SS`（本地时间，无时区后缀） |
| 金额 | 数字，两位小数（人民币元） |

### 响应包

成功：

```json
{ "ok": true, "data": { }, "serverTime": "2026-10-20 10:00:00" }
```

失败（HTTP 状态码同步语义）：

```json
{ "error": "进入「商务谈判」前需补齐：竞品情况" }
```

### 状态码与错误语义

| 状态码 | 含义 | 典型场景 |
|---|---|---|
| 200 | 成功 | — |
| 400 | 参数或业务规则不通过 | 阶段不能回退、闸口未补齐、收款超额 |
| 401 | 未登录 / 会话过期 / Key 失效 | Token 无效、Key 被吊销 |
| 403 | 权限不足 | 非管理员配置集成、销售看他人客户 |
| 404 | 对象不存在 | 单号不存在、映射未找到 |
| 409 | 冲突 | 线索疑似重复、编码已存在 |
| 429 | 超出配额 | API Key 每分钟 240 次 |
| 500 | 服务异常 | `{"error": "服务异常：..."}` |

### 鉴权

两种票据：**用户会话 Token**（页面/联调用）与 **API Key**（系统对接，前缀 `fyk_`）。

票据可以放在下列任一通道，服务端按顺序取第一个**有效**的，因此被反向代理改写某个头时仍能通过：

| 顺序 | 通道 | 示例 |
|---|---|---|
| 1 | 自定义头 `X-Fy-Token` | `X-Fy-Token: <token>` |
| 2 | 头 `X-Auth-Token` | `X-Auth-Token: <token>` |
| 3 | 标准头 `Authorization` | `Authorization: Bearer <token>` |
| 4 | Cookie `fy_token` | `Cookie: fy_token=<token>` |
| 5 | 查询串（CSV 下载/浏览器直链） | `GET /api/leads?token=<token>` |
| 6 | 请求体字段 | `{"token": "<token>", ...}` |

> 部署提示：常见网关会注入自己的 `Authorization: Bearer <JWT>`，把业务票据覆盖掉；前端因此同时下发 `X-Fy-Token` 与 `fy_token` Cookie，双通道兜底。

- **用户会话**：Token 由 `POST /api/auth/login` 返回，`POST /api/auth/logout` 后立即失效（服务端 `sessions` 表）。
- **API Key**：只在创建时返回一次明文，服务端仅存 SHA-256 哈希；支持 `read` / `write` 范围与有效期；写操作建议同时带 `Idempotency-Key`。

免鉴权端点：`POST /api/auth/login`、`GET /api/health`、`GET /api/openapi.json`。

### 分页与过滤

列表接口统一参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `page` | 1 | 页码 |
| `pageSize` | 100 | 每页条数（上限 500） |
| `kw` | 空 | 关键字，各模块自定义匹配字段 |
| `status` | `全部` | 状态过滤，`全部` 表示不过滤 |

返回：`{ list, total, page, pageSize, pages, ...模块附加统计 }`。

### 幂等（推荐所有写接口使用）

请求头 `Idempotency-Key: <业务幂等键>`：

- 首次请求：正常处理，响应被缓存；
- 重复请求（同 Key + 同方法 + 同路径）：直接回放首次响应，并带 `X-Idempotent-Replay: true`；
- 适合「网络超时重试」「消息重投」场景，避免重复建单。

### 限流

每个 API Key 每分钟 240 次请求；超限返回 `429` 并带 `Retry-After: 60`。

### 变更事件与增量游标

所有写操作都会追加一条 `change_log`（自增 `id`）并向订阅的 Webhook 入队投递。`GET /api/sync/changes?since=<游标>` 可拉取变更流，游标只增不减，可断点续传。

## 认证与系统

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/auth/login` | 公开 | 账号登录，返回 Token、角色与权限点 |
| POST | `/api/auth/logout` | 登录态 | 注销当前 Token |
| GET | `/api/auth/me` | read | 当前身份、角色、权限点、数据范围 |
| GET | `/api/bootstrap` | read | 首屏聚合：KPI、漏斗、趋势、我的在谈、待办、规则 |
| GET | `/api/health` | 公开 | 健康检查（含关键对象计数） |
| GET | `/api/openapi.json` | 公开 | OpenAPI 3.0 契约 |
| GET | `/api/settings` | read | 规则、用户、团队、目标、集成开关 |
| PUT | `/api/rules/{code}` | admin | 启停规则或改阈值 `{enabled, value}` |
| GET | `/api/logs` | read | 操作日志（最近 200 条） |
| GET | `/api/users` | read | 用户列表 |
| GET | `/api/products` | read | 产品价目（报价选品用） |

```bash
curl -X POST http://127.0.0.1:8018/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
# → {"ok":true,"data":{"token":"...","username":"admin","displayName":"系统管理员","role":"admin","roleLabel":"系统管理员"}}
```

## 线索

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/leads` | read | 线索列表，附 `stats`（状态计数）、`poolCount`、`unassigned` |
| GET | `/api/leads/check-dup` | read | 查重：`?phone=&name=&email=`，返回 `dups[]` |
| POST | `/api/leads` | write | 新建线索（命中查重返回 409，可 `force=true` 强制） |
| GET | `/api/leads/{no}` | read | 线索详情（含 `activities`、`poolLogs`、`dups`） |
| PUT | `/api/leads/{no}` | write | 修改线索字段 |
| POST | `/api/leads/{no}/assign` | write | 分配 `{owner}` |
| POST | `/api/leads/{no}/claim` | write | 领取（公海 → 跟进中） |
| POST | `/api/leads/{no}/recycle` | write | 回收公海 `{reason}` |
| POST | `/api/leads/{no}/invalid` | write | 标记无效 `{reason}`（必填） |
| POST | `/api/leads/{no}/convert` | write | 转客户，返回 `customerCode` |

新建请求体：

```json
{ "name": "苏州精工机械有限公司", "contact": "周工", "phone": "13900000001",
  "email": "zhou@example.com", "source": "展会", "industry": "装备制造",
  "region": "华东", "budget": 680000, "demand": "12 月前上线", "owner": "liuyang",
  "campaignCode": "CP-2026-01", "force": false }
```

关键返回字段：`no`（`LD20261020-0001`）、`grade`（A/B/C）、`status`（待分配/跟进中/公海/已转客户/无效）、`idleDays`（距上次跟进天数）、`dups[]`（`{objType,no,name,reason,score}`）。

```bash
# 查重
curl -H "Authorization: Bearer $TK" \
  "http://127.0.0.1:8018/api/leads/check-dup?phone=13900000001&name=%E8%8B%8F%E5%B7%9E%E7%B2%BE%E5%B7%A5"

# 建线索（带幂等键，可安全重试）
curl -X POST http://127.0.0.1:8018/api/leads \
  -H "Authorization: Bearer fyk_xxx" -H "Idempotency-Key: erp-lead-20261020-001" \
  -H "Content-Type: application/json" \
  -d '{"name":"苏州某某机械有限公司","phone":"13900000002","budget":260000,"source":"官网表单"}'
```

## 客户与联系人

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/customers` | read | 客户列表（含健康分、在谈、合同额、回款、工单数） |
| POST | `/api/customers` | write | 新建客户，返回 `code`（`C-0001`） |
| GET | `/api/customers/{code}` | read | 客户 360：联系人/商机/报价/合同/工单/跟进/回款 + `stats` |
| PUT | `/api/customers/{code}` | write | 修改客户 |
| GET | `/api/contacts` | read | 联系人列表 `?customer=<code>` |
| POST | `/api/contacts` | write | 新增联系人 |
| PUT | `/api/contacts/{id}` | write | 修改联系人 |
| DELETE | `/api/contacts/{id}` | write | 删除联系人 |

客户列表行关键字段：`code,name,level,score,scoreLevel,openOpps,openAmount,contractCount,contractAmount,paidAmount,openTickets,status,ownerName`。

## 商机

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/opportunities` | read | 商机列表 + `funnel`（阶段汇总/加权/赢率/平均客单） |
| POST | `/api/opportunities` | write | 新建商机（默认「初步接触」） |
| GET | `/api/opportunities/{no}` | read | 详情（含 `stageLogs`、`stageGate`、`canAdvance`、关联报价/合同） |
| PUT | `/api/opportunities/{no}` | write | 修改商机（含补录决策人、竞品） |
| POST | `/api/opportunities/{no}/stage` | write | 推进阶段 `{stage, competitor?, decisionMaker?, amount?, remark?}` |
| POST | `/api/opportunities/{no}/close` | write | 结单 `{result: win\|lose, reason}`（lose 必填原因；win 需已签合同且处于商务谈判） |

阶段机：`初步接触 → 需求确认 → 方案报价 → 商务谈判 → 赢单/输单`，只能前进可跨级，不能回退；结单后锁定。

阶段闸口（不满足即 400）：`需求确认` 需决策人；`方案报价` 需金额 > 0；`商务谈判` 需决策人 + 竞品；`赢单` 需已签署合同。

```bash
curl -X POST http://127.0.0.1:8018/api/opportunities/OPP20261020-0001/stage \
  -H "Authorization: Bearer fyk_xxx" -H "Content-Type: application/json" \
  -d '{"stage":"商务谈判","competitor":"销售易","decisionMaker":"王建国 信息总监"}'
```

## 跟进记录

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/activities` | read | 列表 `?objType=&objNo=&kind=&owner=`，附 `byKind` 统计 |
| POST | `/api/activities` | write | 新建跟进 `{objType, objNo, kind, subject, content, happenAt, durationMin, nextPlan}` |
| POST | `/api/activities/{id}/done` | write | 完成任务型跟进 |

`objType` 取值：`lead` / `customer` / `opportunity` / `ticket`。

## 报价

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/quotes` | read | 报价列表（`stats` 按状态计数） |
| POST | `/api/quotes` | write | 新建报价（自动算折扣并决定是否进审批） |
| GET | `/api/quotes/{no}` | read | 详情（含明细行、`threshold`、`needApproval`） |
| POST | `/api/quotes/{no}/approve` | approve | 批准（仅待审批） |
| POST | `/api/quotes/{no}/reject` | approve | 驳回 `{reason}` |
| POST | `/api/quotes/{no}/send` | write | 发送客户（草稿/已批准可用；超阈折扣须先批准） |
| POST | `/api/quotes/{no}/accept` | write | 客户已接受 |

```json
{ "customerCode": "C-0005", "title": "CRM 系统报价单", "validUntil": "2026-11-20",
  "oppNo": "OPP20261020-0001", "remark": "含 1 年运维",
  "lines": [ { "productCode": "P-CRM-PRO", "qty": 2, "price": 128000 } ] }
```

折扣率 = 1 − 报价额 / 标准额；超过 `discount_approval`（默认 15%）→ 状态「待审批」，批准后才能发送。状态机：草稿 / 待审批 / 已批准 / 已发送 / 已接受 / 已驳回 / 已失效。

## 合同

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/contracts` | read | 合同列表（含进度、逾期金额、`stats`） |
| POST | `/api/contracts` | write | 新建合同（按付款条件自动生成回款计划） |
| GET | `/api/contracts/{no}` | read | 详情（`plans`、`payments`、`customer`、`quote`） |
| POST | `/api/contracts/{no}/sign` | write | 签署 `{signDate}`（计划按签署日重排，关联商机自动赢单） |
| POST | `/api/contracts/{no}/terminate` | approve | 终止 `{reason}` |

```json
{ "customerCode": "C-0005", "title": "CRM 年度服务合同", "amount": 238000,
  "signDate": "2026-10-20", "paymentTerms": "3-4-3", "oppNo": "OPP20261020-0001",
  "quoteNo": "QT20261020-0001" }
```

付款条件：`3-4-3`（三期 30%/40%/30%）、`5-5`（两期）、`10`（一次性）；应收日 = 签约日 + 30 天 × 期序，末期兜底尾差，合计等于合同额。

## 回款

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/payments/plans` | read | 回款计划列表 + `aging`（账龄五档）+ `totalUnpaid`/`totalOverdue`；`?overdue=1` 只看逾期 |
| GET | `/api/payments` | read | 收款流水 `?kw=` |
| POST | `/api/payments` | finance/write | 登记收款 `{contractNo, amount, payDate, method, planId?, remark}` |

核销规则：不指定 `planId` 时按到期日 FIFO 核销；超过合同未收余额返回 400；全部收齐合同自动转「已完成」。

## 服务工单

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/tickets` | read | 工单列表 + `stats`（状态/优先级/SLA 分布）+ `avgSatisfaction`；`?overdue=1` 只看超时 |
| POST | `/api/tickets` | write | 新建工单 `{customerCode, title, category, priority, description, contractNo?}` |
| GET | `/api/tickets/{no}` | read | 详情（含 `logs` 轨迹、`slaLeftHours`、`slaState`） |
| POST | `/api/tickets/{no}/accept` | service | 受理 `{comment}` |
| POST | `/api/tickets/{no}/resolve` | service | 解决 `{resolution}`（必填） |
| POST | `/api/tickets/{no}/close` | service | 关闭并评价 `{satisfaction: 1-5}` |
| POST | `/api/tickets/{no}/comment` | service | 回复 `{content}` |

SLA：P1 4h / P2 8h / P3 24h（可在规则里改）；响应时限 = 解决时限 ÷ 2（最少 1h）；剩余 ≤2h 为「临期」，<0 为「超时」，解决/关闭后为「已完成」。

## 市场活动

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/campaigns` | read | 活动列表，附 `leads/wonAmount/roi/cpl/budgetUsage/leadRate` |
| POST | `/api/campaigns` | marketing/write | 新建活动 `{code?, name, kind, channel, startDate, endDate, budget, cost, targetLeads}` |

ROI =(归因签约额 − 投入)/ 投入；CPL = 投入 / 线索数；预算执行率 = 投入 / 预算。

## 报表

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/reports` | read | 一次返回六块：funnel / performance / source / forecast / aging / tickets |
| GET | `/api/reports/funnel` | read | 漏斗 + 相邻转化 + 负责人维度 + 赢率预警线 |
| GET | `/api/reports/performance` | read | 业绩排行 `?period=2026-10` |
| GET | `/api/reports/source` | read | 来源转化（线索数/转客户/转化率/赢单/客单） |
| GET | `/api/reports/forecast` | read | 滚动预测 `?months=3`（加权/乐观/悲观） |
| GET | `/api/reports/aging` | read | 应收账龄五档 + 逾期 TOP 客户 |
| GET | `/api/export/customers.csv` | read | 客户导出（支持 `?token=`） |
| GET | `/api/export/opportunities.csv` | read | 商机导出（支持 `?token=`） |

## 集成中心

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/integration/overview` | admin | Key/订阅/投递/映射/变更总量概览 |
| GET | `/api/integration/keys` | admin | Key 列表（仅前缀，不返回明文） |
| POST | `/api/integration/keys` | admin | 新建 Key `{name, scope: read\|write, expiresAt}`，返回一次性 `key` |
| DELETE | `/api/integration/keys/{id}` | admin | 吊销 Key |
| GET | `/api/integration/webhooks` | admin | 订阅列表 + 支持事件清单 |
| POST | `/api/integration/webhooks` | admin | 新建订阅 `{name, url, secret, events}` |
| PUT | `/api/integration/webhooks/{id}` | admin | 修改订阅 |
| DELETE | `/api/integration/webhooks/{id}` | admin | 删除订阅 |
| POST | `/api/integration/webhooks/{id}/test` | admin | 触发测试投递 |
| GET | `/api/integration/deliveries` | admin | 投递日志 `?status=全部\|待投递\|成功\|失败` |
| POST | `/api/integration/deliveries/{id}/retry` | admin | 手动重发 |
| GET | `/api/integration/mappings` | admin | 外部 ID 映射列表 `?objType=&system=` |
| POST | `/api/integration/mappings` | write | 绑定映射 `{objType, localNo, externalId, system}` |
| GET | `/api/integration/resolve` | read | 反查 `?externalId=&system=` → 本地单号 |
| GET | `/api/sync/changes` | read | 增量变更流 `?since=<游标>&object=&limit=` |

### Webhook 投递协议

请求头：

```
POST /your-endpoint HTTP/1.1
Content-Type: application/json; charset=utf-8
X-FYC-Event: contract.signed
X-FYC-Timestamp: 1761000000
X-FYC-Signature: sha256=<hex>
X-FYC-Delivery: 128
```

请求体：

```json
{ "id": 128, "event": "contract.signed", "createdAt": "2026-10-20 10:00:00",
  "data": { "no": "CT20261020-0003", "customerCode": "C-0005", "amount": 238000 } }
```

签名算法（接收端必须校验，建议同时校验时间戳 5 分钟窗口防重放）：

```python
signature = "sha256=" + hmac.new(secret.encode(), (timestamp + "." + raw_body).encode(), hashlib.sha256).hexdigest()
```

返回 2xx 视为成功；否则按 30 / 60 / 120 秒退避重试 3 次，仍失败标记「失败」，可在投递日志手动重发。响应体不参与校验，可用于排错回显。

支持事件：`lead.created`、`lead.converted`、`lead.assigned`、`opportunity.created`、`opportunity.stage_changed`、`opportunity.won`、`quote.created`、`quote.approved`、`contract.created`、`contract.signed`、`payment.received`、`ticket.created`、`ticket.resolved`、`webhook.test`（`*` 表示全部）。

### 增量同步协议

```bash
# 首次全量对账：从 0 开始
curl -H "Authorization: Bearer fyk_xxx" \
  "http://127.0.0.1:8018/api/sync/changes?since=0&limit=200"
# → {"changes":[{"id":85,"obj_type":"lead","obj_no":"LD20261020-0007","op":"upsert","payload":{...},
#                "actor":"liuyang","changed_at":"..."}], "cursor":85, "hasMore":false, "count":1}

# 下次从这里继续
curl -H "Authorization: Bearer fyk_xxx" \
  "http://127.0.0.1:8018/api/sync/changes?since=85&object=customer"
```

约定：`id` 单调递增即游标；`hasMore=true` 表示还有下一页，继续用返回的 `cursor` 拉；`object` 可限定对象类型（`lead/customer/opportunity/quote/contract/payment/ticket`）。

### 外部 ID 映射

用于双向同步时把外部系统主键与本地单号绑定：

```bash
# 绑定（幂等：同 system+externalId 已存在则更新 localNo）
curl -X POST http://127.0.0.1:8018/api/integration/mappings \
  -H "Authorization: Bearer fyk_xxx" -H "Content-Type: application/json" \
  -d '{"objType":"customer","localNo":"C-0005","externalId":"KINGDEE-10086","system":"KINGDEE"}'

# 反查
curl -H "Authorization: Bearer fyk_xxx" \
  "http://127.0.0.1:8018/api/integration/resolve?externalId=KINGDEE-10086&system=KINGDEE"
```

## 状态字典

| 对象 | 状态 |
|---|---|
| 线索 | 待分配 / 跟进中 / 公海 / 已转客户 / 无效 |
| 商机阶段 | 初步接触 / 需求确认 / 方案报价 / 商务谈判 / 赢单 / 输单 |
| 商机状态 | 进行中 / 赢单 / 输单 |
| 报价 | 草稿 / 待审批 / 已批准 / 已发送 / 已接受 / 已驳回 / 已失效 |
| 合同 | 待签署 / 已签署 / 执行中 / 已完成 / 已终止 |
| 回款计划 | 未收 / 部分收款 / 部分逾期 / 已收 / 逾期 |
| 工单 | 待受理 / 处理中 / 待确认 / 已解决 / 已关闭 |
| 工单 SLA | 正常 / 临期 / 超时 / 已完成 |
| 客户状态 | 活跃 / 沉睡 / 流失 |

## 对接实施建议

1. **先拉后推**：初始化用 `/api/sync/changes?since=0` 全量灌数，稳定后用 Webhook 增量接收；Webhook 丢掉的消息再用增量同步兜底（游标续传）。
2. **写操作必须带幂等键**：`Idempotency-Key` 用业务唯一值（如 ERP 单据号），防止重试导致重复建单。
3. **限流预算**：每 Key 240 次/分钟；批量对账建议 `pageSize=500`，按 `cursor` 分页，不要并发打满。
4. **权限最小化**：报表/BI 只用 `read` 范围 Key；能建单的 `write` Key 单独发放并设置有效期。
5. **失败可观测**：`/api/integration/deliveries` 查投递失败原因，`/api/logs` 查本地操作轨迹，联合定位。

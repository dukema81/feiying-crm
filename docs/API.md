# 飞泉SCM系统 REST 接口契约

> 版本 V1.0 · 82 条路由 · OpenAPI 3.0（运行期 `GET /api/openapi.json` 可取完整规范）
> 本契约面向对接方：ERP / WMS / 财务系统 / BI 平台均可据此直接对接。

## 1. 通用约定

### 1.1 基础地址与格式

- 基础地址：`http://{host}:8019`（部署后为公网域名）。
- 请求体与响应体均为 UTF-8 JSON；CSV 导出接口返回 `text/csv`（带 BOM）。
- 统一响应包：

```json
{"ok": true,  "data": { ... }}
{"error": "错误信息", "...": "附加字段"}
```

### 1.2 状态码

| 码 | 含义 |
|---|---|
| 200 | 成功 |
| 400 | 业务校验失败（错误信息可直接展示，如「三单匹配未通过，不能付款」） |
| 401 | 未登录 / Token 失效 |
| 403 | 权限不足（角色缺权限位、read Key 调写接口、非管理员访问集成中心） |
| 404 | 资源不存在 |
| 409 | 冲突（供应商 / 发票号重复等，附加 `dups` 字段） |
| 429 | 限流（附加 `Retry-After: 60`） |

### 1.3 鉴权

**会话 Token**（人机交互）：`POST /api/auth/login` 获取，任意一个通道传递即可（服务端逐个校验、取首个有效）：

1. 请求头 `X-Fq-Token: {token}`
2. 请求头 `X-Auth-Token: {token}`
3. 请求头 `Authorization: Bearer {token}`
4. Cookie `fq_token={token}`
5. 查询参数 `?token={token}` / body 字段 `token`

**API Key**（系统对接）：集成中心生成，形如 `fqk_xxx`，服务端只存 SHA-256：

- 请求头 `X-Fq-Key: fqk_xxx` 或 `Authorization: Bearer fqk_xxx`
- scope=`read` 只能 GET；scope=`write` 可调用全部写接口
- 限流：每 Key 每分钟 240 次，超限 429

### 1.4 幂等与写保护

- 写接口（POST/PUT/DELETE）支持请求头 `Idempotency-Key: {uuid}`，同 Key 重复请求直接返回首次响应（响应头 `X-Idempotent-Replay: true`）。
- 买家的单据写入有数据范围隔离（仅见自己名下）。

## 2. 认证与启动

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/auth/login` | 登录，body `{"username","password"}`，返回 `token / role / roleLabel` |
| `POST` | `/api/auth/logout` | 登出 |
| `GET` | `/api/auth/me` | 当前用户与权限位 |
| `GET` | `/api/bootstrap` | 前端启动数据：KPI、待办、趋势、预警、规则 |
| `GET` | `/api/health` | 健康检查（免鉴权） |
| `GET` | `/api/openapi.json` | OpenAPI 3.0 规范（免鉴权） |

```bash
curl -X POST http://127.0.0.1:8019/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
```

## 3. 供应商

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/suppliers?status=&level=&kw=` | 列表（状态 / 等级 / 关键字过滤） |
| `POST` | `/api/suppliers` | 新建（自动查重，重复返回 409 + dups） |
| `GET` | `/api/suppliers/{code}` | 360 详情（资质 / 绩效 / 订单 / 收货 / 发票） |
| `PUT` | `/api/suppliers/{code}` | 更新（name/paymentTerms/leadDays/contact 等） |
| `POST` | `/api/suppliers/{code}/status` | 状态流转 `{"status":"已准入"}`；准入要求 ≥1 项资质 |
| `POST` | `/api/suppliers/{code}/quals` | 登记资质 `{"name","no","expireAt"}` |
| `POST` | `/api/suppliers/{code}/score` | 录入绩效 `{"period","deliveryRate","qualityRate","priceIndex","responseRate"}` |

综合分 = 35×交付 + 35×质量 + 15×价格 + 15×协同；等级 A≥85 / B≥70 / C≥55 / D<55。

## 4. 物料与仓库

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/materials?kw=&abc=` | 物料列表 |
| `POST` | `/api/materials` | 新建（编码唯一，重复 409） |
| `GET` | `/api/materials/check-dup?name=` | 名称查重 |
| `POST` | `/api/materials/abc-recalc` | 重算 ABC 分类 |
| `GET` | `/api/materials/{code}` | 详情（价格史 / 分仓库存 / 流水 / 近期订单） |
| `PUT` | `/api/materials/{code}` | 更新 |
| `GET` | `/api/warehouses` | 仓库列表 |

## 5. 请购单

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/requisitions?status=&kw=` | 列表 |
| `POST` | `/api/requisitions` | 新建 `{"dept","purpose","needDate","items":[{materialCode,qty,estPrice}]}` |
| `GET` | `/api/requisitions/{no}` | 详情（含明细） |
| `POST` | `/api/requisitions/{no}/submit` | 提交（≤免审批金额自动通过） |
| `POST` | `/api/requisitions/{no}/approve` | 批准（校验部门季度预算） |
| `POST` | `/api/requisitions/{no}/reject` | 驳回 `{"reason"}` |
| `POST` | `/api/requisitions/{no}/cancel` | 取消 |
| `POST` | `/api/requisitions/{no}/to-order` | 转采购订单（生成草稿订单） |
| `POST` | `/api/requisitions/{no}/to-rfq` | 发起询价 `{"supplierCodes":[...]}`（≥rfq_min_suppliers 家） |

## 6. 询价比价

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/rfqs` | 列表（含最优价 / 价差） |
| `GET` | `/api/rfqs/{no}` | 详情（含报价明细） |
| `POST` | `/api/rfqs/{no}/quotes` | 登记报价 `{"supplierCode","amount","leadDays","validDays"}`（同商覆盖更新） |
| `POST` | `/api/rfqs/{no}/award` | 定标 `{"supplierCode","amount"}`（≥2 家报价；自动生成订单并分摊明细价） |
| `POST` | `/api/rfqs/{no}/cancel` | 取消 |

## 7. 采购订单

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/orders?status=&kw=&supplier=&overdue=1` | 列表（canAdvance 给出可推进目标） |
| `POST` | `/api/orders` | 直接建单 `{"supplierCode","title","promiseDate","items":[{materialCode,qty,price}]}` |
| `GET` | `/api/orders/{no}` | 详情（明细 + 收货单 + 闸口缺失项） |
| `POST` | `/api/orders/{no}/stage` | 推进 `{"target":"已下单"}`；状态机只能前进；「已结算」需财务权限 + 三单匹配通过 |
| `POST` | `/api/orders/{no}/cancel` | 取消 `{"reason"}` |
| `POST` | `/api/orders/{no}/receive` | 收货登记 `{"warehouse","items":[{materialCode,qty,batch,expireAt}]}`；自动推进部分 / 全部到货 |

状态机：草稿 → 待审批 → 已下单 → 部分到货 → 全部到货 → 已结算（可取消；不可回退；终态锁定）。

## 8. 收货质检

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/receipts?status=&kw=` | 列表 |
| `GET` | `/api/receipts/{no}` | 详情（明细含批次效期） |
| `POST` | `/api/receipts/{no}/inspect` | 质检 `{"items":[{materialCode,okQty,ngQty,batch,expireAt}]}`；结论 合格 / 让步接收（≤2%）/ 退货 |
| `POST` | `/api/receipts/{no}/post` | 入库过账（仅合格品入账，写采购入库流水） |
| `POST` | `/api/receipts/{no}/return` | 退货 `{"reason"}` |

## 9. 库存

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/stock?kw=&warehouse=&state=&expiry=` | 批次台账 |
| `GET` | `/api/stock/summary?kw=` | 物料汇总（现存量 / 可用 / 补货点 / 覆盖天数 / 状态） |
| `GET` | `/api/stock/shortage` | 缺料与补货建议（建议量 / 建议下单日 / 预计金额 / 主供应商） |
| `POST` | `/api/stock/adjust` | 手工调整 `{"materialCode","warehouse","type":"盘盈\|盘亏\|领用出库\|其他入库","qty","batch","reason"}` |
| `GET` | `/api/moves?kw=&type=` | 出入库流水（近 200 条） |
| `GET` | `/api/transfers` | 调拨单列表 |
| `POST` | `/api/transfers` | 新建调拨 `{"fromWh","toWh","items":[{materialCode,qty}]}` |
| `POST` | `/api/transfers/{no}/approve` | 审批（草稿→已审批） |
| `POST` | `/api/transfers/{no}/post` | 执行（校验调出仓库存，写两条流水） |
| `GET` | `/api/stocktakes` | 盘点单列表 |
| `POST` | `/api/stocktakes` | 发起盘点 `{"warehouse","remark"}`（按仓快照） |
| `POST` | `/api/stocktakes/{no}/finish` | 完成盘点 `{"items":[{materialCode,batch,realQty}]}`（差异过账） |

## 10. 结算付款

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/invoices?status=&kw=` | 发票列表（含匹配结果 / 差异率 / 逾期天数） |
| `POST` | `/api/invoices` | 登记发票 `{"poNo","invoiceNo","amount","taxRate","termsDays"}`；登记即三单匹配 |
| `POST` | `/api/invoices/{no}/match` | 重新匹配 `{"tolerance":0.02}`（可选覆盖容差） |
| `POST` | `/api/invoices/{no}/pay` | 付款 `{"amount"}`（部分付款；匹配未通过 400） |
| `GET` | `/api/payables` | 应付与账龄五档 |

**三单匹配口径**：`|发票额 − 收货额| ÷ 收货额 ≤ match_tolerance(0.02)` → 通过；无收货 / 无发票分别返回「无收货」「无发票」。

## 11. 报表 / 设置 / 日志

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/reports` | 报表九模块（趋势 / 类别 / 供应商绩效 / 周转 / 缺料 / 准时率 / 价格波动 / 账龄 / KPI） |
| `GET` | `/api/settings` | 规则 / 仓网 / 预算 / 用户 |
| `PUT` | `/api/rules/{code}` | 规则启停 / 调阈值（仅管理员） |
| `GET` | `/api/logs` | 操作日志（近 200 条） |
| `GET` | `/api/users` | 用户列表 |

## 12. 集成中心（仅管理员）

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/integration/overview` | 集成总览（Key / Webhook / 投递 / 变更计数） |
| `GET` / `POST` | `/api/integration/keys` | Key 列表 / 新建（明文只返回一次） |
| `DELETE` | `/api/integration/keys/{id}` | 吊销 |
| `GET` / `POST` | `/api/integration/webhooks` | 订阅列表 / 新建 `{"name","url","events":[...]}` |
| `PUT` / `DELETE` | `/api/integration/webhooks/{id}` | 更新 / 删除 |
| `POST` | `/api/integration/webhooks/{id}/test` | 发送测试事件 |
| `GET` | `/api/integration/deliveries?status=` | 投递记录 |
| `POST` | `/api/integration/deliveries/{id}/retry` | 手动重投 |
| `GET` / `POST` | `/api/integration/mappings` | 外部 ID 映射列表 / 绑定 `{"objType","localNo","externalId","system"}` |
| `GET` | `/api/integration/resolve?externalId=&system=` | 外部 ID 反查本系统单号 |
| `GET` | `/api/sync/changes?since=&object=&limit=` | 增量变更流 |

## 13. Webhook 事件协议

### 13.1 请求头

| 头 | 说明 |
|---|---|
| X-FQC-Event | 事件名，如 `po.stage_changed` |
| X-FQC-Timestamp | Unix 秒级时间戳 |
| X-FQC-Signature | HMAC-SHA256 签名 |
| X-FQC-Delivery | 投递 ID |

### 13.2 签名校验（接收方）

```python
import hmac, hashlib
expected = hmac.new(secret.encode(), f"{ts}.".encode() + raw_body, hashlib.sha256).hexdigest()
assert hmac.compare_digest(expected, signature)
assert abs(now - int(ts)) < 300          # 防重放
```

### 13.3 事件清单（23 种）

`supplier.created / supplier.status_changed / supplier.scored / material.created /`
`req.created / req.submitted / req.approved / req.rejected / rfq.created / rfq.awarded /`
`po.created / po.stage_changed / po.cancelled / receipt.created / receipt.inspected /`
`receipt.posted / receipt.returned / stock.adjusted / stock.transferred / stock.stocktake /`
`invoice.created / invoice.matched / invoice.paid`

### 13.4 重试策略

失败（非 2xx / 超时）按 30s → 60s → 120s 退避重试，最多 3 次；最终失败保留记录，可在投递记录页手动重投。

## 14. 增量同步对接示例

```bash
# 首次全量
curl -H "X-Fq-Key: fqk_xxx" "http://host:8019/api/sync/changes?since=0&limit=200"
# 返回 {"changes":[...], "cursor": 47, "hasMore": true, ...}
# 之后按 cursor 续拉；hasMore=true 时立即再拉
curl -H "X-Fq-Key: fqk_xxx" "http://host:8019/api/sync/changes?since=47&limit=200"
# 外部 ID 反查
curl -H "X-Fq-Key: fqk_xxx" "http://host:8019/api/integration/resolve?externalId=KD-PO-8891"
```

## 15. 路由总表（82 条）

| `POST` | `/api/auth/login` | |
| `POST` | `/api/auth/logout` | |
| `GET` | `/api/auth/me` | |
| `GET` | `/api/bootstrap` | |
| `GET` | `/api/suppliers` | |
| `POST` | `/api/suppliers` | |
| `GET` | `/api/suppliers/{noOrCode}` | |
| `PUT` | `/api/suppliers/{noOrCode}` | |
| `POST` | `/api/suppliers/{noOrCode}/status` | |
| `POST` | `/api/suppliers/{noOrCode}/quals` | |
| `POST` | `/api/suppliers/{noOrCode}/score` | |
| `GET` | `/api/materials` | |
| `POST` | `/api/materials` | |
| `GET` | `/api/materials/check-dup` | |
| `POST` | `/api/materials/abc-recalc` | |
| `GET` | `/api/materials/{noOrCode}` | |
| `PUT` | `/api/materials/{noOrCode}` | |
| `GET` | `/api/warehouses` | |
| `GET` | `/api/requisitions` | |
| `POST` | `/api/requisitions` | |
| `GET` | `/api/requisitions/{noOrCode}` | |
| `POST` | `/api/requisitions/{noOrCode}/submit` | |
| `POST` | `/api/requisitions/{noOrCode}/approve` | |
| `POST` | `/api/requisitions/{noOrCode}/reject` | |
| `POST` | `/api/requisitions/{noOrCode}/cancel` | |
| `POST` | `/api/requisitions/{noOrCode}/to-order` | |
| `POST` | `/api/requisitions/{noOrCode}/to-rfq` | |
| `GET` | `/api/rfqs` | |
| `GET` | `/api/rfqs/{noOrCode}` | |
| `POST` | `/api/rfqs/{noOrCode}/quotes` | |
| `POST` | `/api/rfqs/{noOrCode}/award` | |
| `POST` | `/api/rfqs/{noOrCode}/cancel` | |
| `GET` | `/api/orders` | |
| `POST` | `/api/orders` | |
| `GET` | `/api/orders/{noOrCode}` | |
| `POST` | `/api/orders/{noOrCode}/stage` | |
| `POST` | `/api/orders/{noOrCode}/cancel` | |
| `POST` | `/api/orders/{noOrCode}/receive` | |
| `GET` | `/api/receipts` | |
| `GET` | `/api/receipts/{noOrCode}` | |
| `POST` | `/api/receipts/{noOrCode}/inspect` | |
| `POST` | `/api/receipts/{noOrCode}/post` | |
| `POST` | `/api/receipts/{noOrCode}/return` | |
| `GET` | `/api/stock` | |
| `GET` | `/api/stock/summary` | |
| `GET` | `/api/stock/shortage` | |
| `POST` | `/api/stock/adjust` | |
| `GET` | `/api/moves` | |
| `GET` | `/api/transfers` | |
| `POST` | `/api/transfers` | |
| `POST` | `/api/transfers/{noOrCode}/approve` | |
| `POST` | `/api/transfers/{noOrCode}/post` | |
| `GET` | `/api/stocktakes` | |
| `POST` | `/api/stocktakes` | |
| `POST` | `/api/stocktakes/{noOrCode}/finish` | |
| `GET` | `/api/invoices` | |
| `POST` | `/api/invoices` | |
| `POST` | `/api/invoices/{noOrCode}/match` | |
| `POST` | `/api/invoices/{noOrCode}/pay` | |
| `GET` | `/api/payables` | |
| `GET` | `/api/reports` | |
| `GET` | `/api/settings` | |
| `PUT` | `/api/rules/{noOrCode}` | |
| `GET` | `/api/logs` | |
| `GET` | `/api/users` | |
| `GET` | `/api/integration/overview` | |
| `GET` | `/api/integration/keys` | |
| `POST` | `/api/integration/keys` | |
| `DELETE` | `/api/integration/keys/{id}` | |
| `GET` | `/api/integration/webhooks` | |
| `POST` | `/api/integration/webhooks` | |
| `PUT` | `/api/integration/webhooks/{id}` | |
| `DELETE` | `/api/integration/webhooks/{id}` | |
| `POST` | `/api/integration/webhooks/{id}/test` | |
| `GET` | `/api/integration/deliveries` | |
| `POST` | `/api/integration/deliveries/{id}/retry` | |
| `GET` | `/api/integration/mappings` | |
| `POST` | `/api/integration/mappings` | |
| `GET` | `/api/integration/resolve` | |
| `GET` | `/api/sync/changes` | |
| `GET` | `/api/export/suppliers` | |
| `GET` | `/api/export/orders` | |

## 16. 对接实施建议

1. **先主数据后单据**：先同步供应商 / 物料，再消费 req / po / receipt / invoice 事件。
2. **幂等消费**：以 `obj_no + op` 做幂等键；Webhook 与增量同步可并用（Webhook 保实时、增量保兜底）。
3. **回写只写对方**：本系统为主数据的对象（供应商 / 物料 / 订单状态），对接系统不要反向直写数据库，统一走 API。
4. **凭证分管**：每个对接方独立 Key（一人一键），只读同步用 read scope，便于单独吊销与审计。

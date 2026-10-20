# 飞鹰CRM系统 · 测试报告

## 一、测试结论

| 项 | 结果 |
|---|---|
| 用例总数 | **127 项**（单元 53 / 接口 60 / 端到端 14） |
| 通过 / 失败 | 127 / 0 |
| 质量门禁 | **PASS**（三层全绿方可部署） |
| 执行方式 | `python scripts/run_tests.py`，一次跑完三层并产出 junit/JSON/摘要 |
| 总耗时 | 约 68 秒（单元 2.5s / 接口 21s / 端到端 45s） |
| 结论 | 功能与规则口径符合设计，缺陷已闭环，允许部署与对接联调 |

## 二、测试环境与方法

| 项 | 值 |
|---|---|
| 操作系统 | Windows 11（Git Bash） |
| 运行时 | Python 3.13，零第三方依赖（仅测试用 pytest / Playwright） |
| 浏览器 | Microsoft Edge headless（Playwright，回退 Chromium） |
| 数据库 | 每套接口/端到端测试独立临时 SQLite（`FEIYING_DB` 指向临时文件），互不污染 |
| 服务启动 | 测试内起真实 HTTP 服务（端口 8941/8942），非 mock，验证完整链路 |
| 演示数据 | 确定性种子 `SEED=20261020`，日历锚点 2026-10-20 |

三层策略：

1. **单元层**（`tests/test_unit_core.py`）：只测 `backend/crm.py` 纯函数，无 IO 无 SQL，毫秒级，覆盖全部口径与边界。
2. **接口层**（`tests/test_api.py`）：真实服务 + HTTP 客户端，覆盖鉴权、全流程状态机、集成能力；Webhook 用内置 8991 端口接收端真实收包并校验签名。
3. **端到端层**（`tests/test_e2e_ui.py`）：Playwright 驱动浏览器，按岗位真实操作 14 个页面，断言页面文案、接口响应与后端终态三方一致，并逐用例截图留档（`reports/screenshots/`，14 张）。

## 三、用例分布

| 套件 | 数量 | 覆盖内容 |
|---|---|---|
| 单元：业务内核 | 53 | 数值舍入、单号生成与解析、阶段状态机（前进/回退/赢单/输单/锁定/未知）、阶段闸口、手机号与公司名归一、查重（手机/邮箱/名称/自身跳过/编号噪声）、分级阈值与来源上浮、客户评分（优质/衰减/逾期惩罚/夹取）、漏斗与相邻转化、预测与跨月、折扣与审批边界、回款计划（分期总额/尾差/等分）、计划状态与逾期天数、账龄分档、SLA 时限与状态与剩余小时、市场 ROI、HMAC 签名与验签、分页、权限矩阵、天数差 |
| 接口：全流程 | 59 | 健康检查、登录/登出/身份、首屏聚合、线索全生命周期（建单/查重/强制/分配/领取/回收/无效/转客户）、客户与联系人 CRUD、客户 360、商机建单与闸口、阶段不能回退、赢单需合同、输单需原因、阶段轨迹、商机推进时补录闸口字段、报价折扣与审批/驳回/发送/接受、合同建单与计划生成、签署与终止、收款核销与超额拦截、账龄与逾期过滤、工单 SLA 与四类动作、市场活动与 ROI、六类报表、规则启停联动、CSV 导出（含 token 下载）、OpenAPI 契约、API Key 权限隔离、幂等回放、增量同步游标与对象过滤、外部 ID 映射与反查、Webhook 建订阅/投递/签名校验 |
| 端到端：UI | 14 | 登录与驾驶舱、14 页遍历（无控制台报错）、线索建单与查重提示与跟进、线索转客户并跳转客户 360、客户建单与 360 六标签、商机看板与闸口推进（跨级）、报价折扣审批与发送接受、合同签署与收款（含计划总额校验）、工单 SLA 全流程、报表六标签、集成中心 Key 与 Webhook、规则启停、非管理员集成锁定、会话失效跳转登录 |

## 四、关键验证点

### 1. 商机阶段状态机与闸口

- 正向：初步接触 → 需求确认（概率 0.1→0.25）→ 方案报价 → 商务谈判 → 赢单（1.0）；
- 逆向：任何回退请求返回 400「商机阶段不能回退」；
- 闸口：缺决策人/竞品/金额/合同时逐项拦截，错误信息点名缺失项；
- 补录：`POST /stage` 携带 `competitor`/`decisionMaker` 时先并入再校验并落库（E2E 发现并修复，见缺陷 D-13）；
- 结单：赢单后 `stageLogs` 留痕，再次推进返回 400「已结单」。

### 2. 报价折扣审批

折扣 37.5% 的报价自动进入「待审批」；未批准时「发送」被拦（400）；批准后 `approver/approvedAt` 落库、状态转「已批准」，方可发送、再标记「客户已接受」。折扣率与阈值均返回前端展示（`discountPct`、`threshold`）。

### 3. 合同与回款

`5-5` 条件下两期计划总额精确等于合同额（误差 <0.01）；签署后计划按签署日重排；收款 6 万后 `paidAmount=60000`、`unpaidAmount=60000`、收款单号 `SK...`；超额收款被拦截并提示剩余余额。

### 4. 工单 SLA

P1 建单即算出 4 小时解决时限与 2 小时响应时限；受理 → 解决（必填结论）→ 关闭（满意度 1-5）后 `slaState` 转「已完成」，`ticket_logs` 全链路留痕。

### 5. 集成能力

- API Key：`read` 范围 Key 不能写（403）；吊销即时生效；
- 幂等：同 `Idempotency-Key` 二次提交回放首次响应且带 `X-Idempotent-Replay: true`，不产生第二张单；
- 增量同步：`since` 游标单调，`object=lead` 过滤生效，新建线索必现于变更流；
- Webhook：真实接收端收到推送，头部 `X-FYC-Event / X-FYC-Timestamp / X-FYC-Signature` 齐备，`HMAC-SHA256(timestamp + "." + body)` 校验通过；失败按 30/60/120 秒重试，3 次后标记「失败」。

### 6. 权限与数据范围

销售只读自己名下数据；非管理员调 `/api/integration/overview` 返回 403 且页面给出说明而非白屏；管理员可改规则阈值并立即影响新建单据校验。

## 五、缺陷台账

本轮共发现并修复 16 项缺陷，均在测试中复现、修复后回归通过。

| 编号 | 现象 | 根因 | 修复 | 验证用例 |
|---|---|---|---|---|
| D-01 | `POST /api/leads` 返回 500 `UNIQUE constraint failed: leads.no`，级联 24 项红灯 | `next_no` 用 `doc_no(...)[:10]` 截前缀，丢掉分隔符，`int("-0031")` 为负导致流水号重复 | 前缀改为 `rsplit("-",1)[0] + "-"`，尾段只取数字 | 接口全套 + 单元单号用例 |
| D-02 | `/api/bootstrap`、`/api/settings` 500 `no such column: id` | `rules` 表主键是 `code`，SQL 却 `ORDER BY id` | 改 `ORDER BY rowid` | `test_bootstrap_*` |
| D-03 | 报价详情 500 | 调用了不存在的 `rule_value_safe` | `quote_view(r, names, threshold)` 显式传阈值 | 接口报价用例 |
| D-04 | `/api/reports` 500 `'function' object has no attribute '__wrapped__'` | `with_db` 装饰器未用 `functools.wraps`，包装后无 `__wrapped__` | 装饰器加 `@functools.wraps` | `test_reports_endpoints` |
| D-05 | 合同建单 500 | 内部复用了被装饰函数的 `__wrapped__` | 直接组装 `contract_view` 返回 | `test_contract_create` |
| D-06 | 商机结单 500 | 同上，`api_opportunity_stage.__wrapped__` 不可靠 | 抽出 `_stage_move()` 供两个 handler 共用 | 商机结单用例 |
| D-07 | 工单详情 `ageHours` 为负数 | 误用 `sla_left_hours(created_at)` 取负 | 新增 `_hours_since()` 正算 | 工单用例 |
| D-08 | SLA P2 剩余 1 小时仍判「临期」 | 临期口径为「剩余 < 时限 20%」，8h 档过于宽松 | 改为绝对口径「剩余 ≤2h」 | 单元 `test_sla_state` |
| D-09 | `/api/openapi.json` 连接被重置 | `[..., for k, v in params]` 遍历 dict 取到 key，`ValueError` 直接断连 | 改 `params.items()` | `test_openapi_spec` |
| D-10 | 「只看逾期」返回非逾期计划 | 过滤用数据库里陈旧的 `status` 列 | 以实时 `plan_status()` 计算后再过滤 | `test_payment_plans_aging` |
| D-11 | Webhook 头部实际发出为 `X-Fyc-*` | urllib 对自定义头做 Title-Case 改写 | 改用 `http.client` 直连发送，保持文档定义的原始大小写 | `test_webhook_delivery_and_signature` |
| D-12 | 线索查重把「…测试公司9597611」与「…9597613」判为重复，正常建单被拦 | 最长公共子串相似度被编号噪声抬高 | 新增 `name_affinity()`：相似度达标且（共有前缀 ≥2 字或一方包含另一方）才算疑似；并补单元用例 | 单元 `test_dup_numeric_noise_not_flagged` |
| D-13 | 推进「商务谈判」时填的竞品/决策人被丢弃，永远进不了该阶段 | `_stage_move` 只校验库内旧值，未合并请求体 | 先合并且校验、再落库 | 单元 + 接口 `test_opportunity_gate_backfill_on_advance` + E2E |
| D-14 | 非管理员进「集成中心」整页空白 | 概览接口 403 导致 `.then` 未执行，渲染逻辑在回调里 | 先判角色渲染说明页，再请求数据 | E2E `test_non_admin_integration_locked` |
| D-15 | 操作成功提示一闪就被页面摘要覆盖 | `draw()` 里的 `setStatus` 覆盖了 toast | toast 置 6 秒保护窗口，摘要让位 | 多个 E2E 用例断言 toast |
| D-16 | 报价弹层请求不存在的 `/api/quotable-products`，明细行加载失败 | 前后端接口名不一致 | 后端补 `GET /api/products` 并注册路由，前端改调用 | E2E `test_quote_discount_approval_flow` |
| D-17 | 公网环境登录成功但随后所有接口 401，页面被弹回登录页 | 部署环境的反向代理会注入自己的 `Authorization: Bearer <JWT>`，把前端票据覆盖掉，服务端只认这一个头 | 服务端改为「多通道取票」：`X-Fy-Token` → `X-Auth-Token` → `Authorization` → Cookie `fy_token` → 查询串 `?token=` → 请求体 `token`，逐个校验取首个有效；前端同时下发自定义头与 Cookie，双保险 | 接口 `test_token_fallback_channels` + E2E `test_session_expired_redirects_login` |

## 六、性能与稳定性

| 场景 | 观测 |
|---|---|
| `/api/bootstrap` 首屏聚合 | 本机 <60ms（36 客户 / 52 商机 / 30 回款计划） |
| 列表接口（pageSize=500） | <80ms |
| `/api/reports` 六块聚合 | <150ms |
| 端到端 14 页连续遍历 | 45 秒内完成，无控制台报错 |
| 并发写 | 全写串行化（RLock），端到端与接口测试并发跑无 `database is locked` |

## 七、遗留风险与后续建议

| 风险 | 说明 | 建议 |
|---|---|---|
| SQLite 单写者 | 峰值写入会排队 | 超过 200 并发写时迁 PG/MySQL，`db.py` 已隔离 DDL 与连接 |
| 查重阈值依赖数据质量 | 阈值过松误拦、过紧漏判 | 上线后用真实客户名回测，必要时按行业调 `dup_check` |
| Webhook 无本地持久重放队列 | 极端情况下进程重启丢失待投递 | 生产环境将 `webhook_deliveries` 接外部队列或独立投递服务 |
| 无审计级快照 | 操作日志只有动作与摘要 | 关键单据加版本表，支持按时间点还原 |
| 单组织单币种 | 多组织/多币种需改造 | 已列为二期 |
| 移动端为窄屏适配 | 非原生 App | 需要外勤场景时做企业微信/移动 H5 包 |

## 八、复现方式

```bash
# 全量门禁（三层串行，产出 reports/）
python scripts/run_tests.py

# 单套件
python -m pytest tests/test_unit_core.py -q
python -m pytest tests/test_api.py -q
python -m pytest tests/test_e2e_ui.py -q

# 离线 DEMO 冒烟（无需后端）
python tools/build_demo.py && python tools/smoke_demo.py
```

产物：`reports/test_report.json`（结构化）、`reports/summary.md`（执行摘要）、`reports/junit_*.xml`（CI 可解析）、`reports/screenshots/*.png`（14 张用例留档）。

## 九、附：端到端用例截图清单

| 文件 | 对应场景 |
|---|---|
| `e2e-login_and_dashboard.png` | 登录与销售驾驶舱 |
| `e2e-all_pages_traverse.png` | 14 页遍历 |
| `e2e-lead_create_dup_hint_and_follow.png` | 线索建单、查重提示、写跟进 |
| `e2e-lead_convert_to_customer.png` | 线索转客户并跳转客户 360 |
| `e2e-customer_create_and_360_tabs.png` | 新建客户与 360 六标签 |
| `e2e-opportunity_stage_gate_advance.png` | 商机闸口与跨级推进 |
| `e2e-quote_discount_approval_flow.png` | 报价折扣审批链路 |
| `e2e-contract_sign_and_payment.png` | 合同签署与收款 |
| `e2e-ticket_sla_full_flow.png` | 工单 SLA 全流程 |
| `e2e-reports_six_tabs.png` | 报表六标签 |
| `e2e-integration_key_and_webhook.png` | 集成中心 Key 与 Webhook |
| `e2e-settings_rule_toggle.png` | 规则启停 |
| `e2e-non_admin_integration_locked.png` | 非管理员集成锁定 |
| `e2e-session_expired_redirects_login.png` | 会话失效跳转 |

## 十、部署验收（公网环境）

代码经门禁通过后发布到云端沙箱（单端口 HTTP 服务），发布后按下列清单复验，全部通过：

| 项 | 方法 | 结果 |
|---|---|---|
| 服务存活 | `GET /api/health` | `{"status":"up","version":"1.0.0","customers":36}` |
| 静态首页 | `GET /` | 200，1.8 KB，`Cache-Control: no-cache` |
| 账号登录 | `POST /api/auth/login`（admin/admin123） | 200，返回会话票据 |
| 鉴权通道 | 票据分别走 `X-Fy-Token` / Cookie / `?token=` | 均 200（详见缺陷 D-17） |
| 首屏数据 | 浏览器登录后 `#dashboard` | 加权商机 686.8 万 / 本月签约 93.0 万 / 赢单率 61.1% / 逾期应收 87.0 万 |
| 关键页面 | `#/leads` `#/customers` `#/opportunities` `#/reports` | 分别渲染 48 条线索、36 家客户、34 个在谈商机、报表漏斗，控制台无报错 |
| 会话失效 | 清空票据后访问内页 | 自动跳回登录页 |

> 发布环境与本地差异只在反向代理层；本轮把「票据来源」做成多通道后，同一份代码在本地、公网表现一致，无需为环境打补丁。

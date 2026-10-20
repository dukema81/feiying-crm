/* 飞鹰 CRM · 集成中心（API Key / Webhook / 外部映射 / 增量同步） */
(function (window, document) {
  "use strict";
  var F = window.F;

  function me() { return (F.state.boot && F.state.boot.user) || {}; }
  function isAdmin() { return me().role === "admin"; }

  F.register("integration", function () {
    var st = { tab: "keys", deliveryStatus: "全部" };

    function draw() {
      if (!isAdmin()) {
        /* 非管理员连概览接口都会 403，先给出说明页，避免整页空白 */
        document.getElementById("view").innerHTML =
          '<div class="panel"><div class="panel-title">集成中心</div><div class="panel-body">' +
          "集成配置仅系统管理员可见（当前角色：" + F.esc(me().roleLabel || me().role) +
          "）。业务接口仍按角色权限开放，如需对接请联系管理员开通 API Key 或 Webhook。" +
          "</div></div>";
        F.setStatus("集成中心 · 当前角色无配置权限");
        F.setSide("");
        return;
      }
      F.api("GET", "/api/integration/overview").then(function (ov) {
        var base = location.origin + "/";
        var tabs = [["keys", "API Key"], ["hooks", "Webhook"], ["deliveries", "投递日志"],
          ["maps", "外部 ID 映射"], ["sync", "增量同步"]];
        var html = '<div class="kpi-grid four">' +
          '<div class="kpi"><div class="k-label">启用 API Key</div><div class="k-value">' + ov.keys + "</div></div>" +
          '<div class="kpi green"><div class="k-label">启用 Webhook</div><div class="k-value">' + ov.webhooks + "</div></div>" +
          '<div class="kpi ' + (ov.failed ? "red" : "gold") + '"><div class="k-label">投递失败</div><div class="k-value">' +
          ov.failed + '<span class="small muted"> / 共 ' + ov.deliveries + "</span></div></div>" +
          '<div class="kpi"><div class="k-label">变更事件</div><div class="k-value">' + ov.changes +
          '<span class="small muted" style="font-size:11px"> 条</span></div></div></div>' +
          '<div class="panel"><div class="panel-title">对接方式（三条通道，任选或组合）</div>' +
          '<div class="panel-body">' +
          '<div class="intg-grid">' +
          '<div class="intg-card"><b>① REST 拉取</b><div class="small muted">用 API Key 直接调用业务接口，' +
          '支持分页（pageNum/pageSize）、关键字与状态过滤。</div>' +
          '<pre class="code">curl -H "Authorization: Bearer fyk_xxx" \\\n  ' + base + 'api/customers?page=1\&pageSize=50</pre></div>' +
          '<div class="intg-card"><b>② Webhook 推送</b><div class="small muted">业务变更实时推送，' +
          'HMAC-SHA256 签名，失败重试 3 次（30s/60s/120s 退避）。</div>' +
          '<pre class="code">X-FYC-Event: contract.signed\nX-FYC-Timestamp: 1761000000\nX-FYC-Signature: sha256=…</pre></div>' +
          '<div class="intg-card"><b>③ 增量同步</b><div class="small muted">按自增游标拉取变更流，' +
          '适合定时对账；游标只增不减，可断点续传。</div>' +
          '<pre class="code">GET ' + base + 'api/sync/changes?\nsince=120\&object=customer\&limit=200</pre></div>' +
          "</div>" +
          '<div class="small muted" style="margin-top:10px">机器可读契约：<a href="api/openapi.json" target="_blank">' +
          "GET /api/openapi.json</a>（OpenAPI 3.0）· 幂等：请求头 <code>Idempotency-Key</code> · " +
          "限流：240 次/分钟/Key（超限 429 + Retry-After）</div>" +
          "</div></div>" +
          '<div class="tabs" id="iTabs">' + tabs.map(function (t) {
            return '<button class="' + (t[0] === st.tab ? "on" : "") + '" data-tab="' + t[0] + '">' +
              t[1] + "</button>";
          }).join("") + "</div><div id='iBody'></div>";
        document.getElementById("view").innerHTML = html;
        document.querySelectorAll("#iTabs button").forEach(function (b) {
          b.addEventListener("click", function () { st.tab = b.getAttribute("data-tab"); draw(); });
        });
        if (st.tab === "keys") drawKeys();
        else if (st.tab === "hooks") drawHooks();
        else if (st.tab === "deliveries") drawDeliveries();
        else if (st.tab === "maps") drawMaps();
        else drawSync();
        F.setStatus("集成中心 · 变更事件 " + ov.changes + " 条 · 最近一次 " + (ov.lastChange || "—"));
      });
    }

    function drawKeys() {
      F.api("GET", "/api/integration/keys").then(function (d) {
        document.getElementById("iBody").innerHTML =
          '<div class="panel"><div class="panel-title">API Key' +
          '<span class="panel-actions"><button class="btn sm primary" id="kNew">+ 新建 Key</button></span></div>' +
          '<div class="panel-body flush">' +
          F.table([
            { label: "名称", key: "name" },
            { label: "前缀", render: function (r) { return '<span class="mono small">' + F.esc(r.keyPrefix) + "…</span>"; } },
            { label: "范围", render: function (r) { return F.tag(r.scope === "write" ? "读写" : "只读",
              r.scope === "write" ? "gold" : "gray"); } },
            { label: "状态", render: function (r) { return F.tag(r.status); } },
            { label: "有效期至", render: function (r) { return F.esc(r.expiresAt || "长期"); } },
            { label: "最近使用", render: function (r) { return '<span class="small muted">' +
              F.esc(r.lastUsedAt || "未使用") + "</span>"; } },
            { label: "操作", render: function (r) {
              return r.status === "启用" ? '<button class="btn sm danger" data-revoke="' + r.id + '">吊销</button>' : "—";
            } }
          ], d.list, { empty: "还没有 API Key" }) + "</div></div>" +
          '<div class="panel"><div class="panel-title">调用示例</div><div class="panel-body">' +
          '<pre class="code"># 1) 只读拉取客户\ncurl -H "Authorization: Bearer fyk_xxx" \\\n  ' +
          location.origin + '/api/customers?page=1\&pageSize=50\n\n' +
          '# 2) 写入线索（需 write 范围 + 幂等键，重复提交不会建两条）\n' +
          'curl -X POST ' + location.origin + '/api/leads \\\n' +
          '  -H "Authorization: Bearer fyk_xxx" \\\n' +
          '  -H "Idempotency-Key: erp-lead-20261020-001" \\\n' +
          '  -H "Content-Type: application/json" \\\n' +
          '  -d \'{"name":"苏州某某机械有限公司","phone":"13900000001","budget":260000}\'</pre>' +
          "</div></div>";
        document.getElementById("kNew").addEventListener("click", newKey);
        document.querySelectorAll("[data-revoke]").forEach(function (b) {
          b.addEventListener("click", function () {
            var id = b.getAttribute("data-revoke");
            if (!window.confirm("吊销后该 Key 立即失效，确认？")) return;
            F.api("DELETE", "/api/integration/keys/" + id).then(function () {
              F.toast("已吊销", "ok"); draw();
            }).catch(function (e) { F.toast(e.message, "err"); });
          });
        });
      });
    }

    function newKey() {
      var body = '<div class="form-grid">' +
        '<label>名称 *</label><input id="kN" type="text" placeholder="如 金蝶云星空 / BI 平台">' +
        '<label>范围</label><select id="kS"><option value="read">只读（推荐给报表/BI）</option>' +
        '<option value="write">读写（可建单，谨慎授予）</option></select>' +
        '<label>有效期至</label><input id="kE" type="date" value="' + F.addDays(365) + '">' +
        "</div>";
      F.dialog("新建 API Key", body, '<button class="btn" data-close17="1">取消</button>' +
        '<button class="btn primary" id="kSave">生成</button>');
      document.querySelector("[data-close17]").addEventListener("click", F.closeDialog);
      document.getElementById("kSave").addEventListener("click", function () {
        F.api("POST", "/api/integration/keys", {
          name: document.getElementById("kN").value.trim(),
          scope: document.getElementById("kS").value,
          expiresAt: document.getElementById("kE").value
        }).then(function (r) {
          F.dialog("API Key 已生成（仅显示一次）",
            '<div class="warn-box">请立即复制保存，关闭后无法再次查看明文。</div>' +
            '<div class="keybox" id="keyPlain">' + F.esc(r.key) + "</div>" +
            '<div class="small muted">用法：<code>Authorization: Bearer &lt;key&gt;</code>，范围 ' +
            F.esc(r.scope) + "</div>",
            '<button class="btn" data-close18="1">我已保存</button>');
          document.querySelector("[data-close18]").addEventListener("click", function () {
            F.closeDialog(); draw();
          });
        }).catch(function (e) { F.toast(e.message, "err"); });
      });
    }

    function drawHooks() {
      F.api("GET", "/api/integration/webhooks").then(function (d) {
        document.getElementById("iBody").innerHTML =
          '<div class="panel"><div class="panel-title">Webhook 订阅' +
          '<span class="panel-actions"><button class="btn sm primary" id="hNew">+ 新建订阅</button></span></div>' +
          '<div class="panel-body flush">' +
          F.table([
            { label: "名称", key: "name" },
            { label: "回调地址", render: function (r) { return '<span class="mono small">' + F.esc(r.url) + "</span>"; } },
            { label: "事件", render: function (r) { return '<span class="small">' +
              F.esc((r.events || "").split(",").slice(0, 3).join(", ")) +
              ((r.events || "").split(",").length > 3 ? "…" : "") + "</span>"; } },
            { label: "状态", render: function (r) { return F.tag(r.status); } },
            { label: "最近结果", render: function (r) { return '<span class="small">' +
              F.esc(r.last_status || "—") + "</span>"; } },
            { label: "成功/失败", render: function (r) {
              var s = r.deliveryStats || {};
              return '<span class="small">' + (s["成功"] || 0) + " / <b class='" +
                ((s["失败"] || 0) ? "up" : "") + "'>" + (s["失败"] || 0) + "</b></span>"; } },
            { label: "操作", render: function (r) {
              return '<button class="btn sm" data-test="' + r.id + '">测试</button> ' +
                '<button class="btn sm danger" data-del="' + r.id + '">删除</button>';
            } }
          ], d.list, { empty: "还没有 Webhook" }) + "</div></div>" +
          '<div class="panel"><div class="panel-title">支持的事件</div><div class="panel-body">' +
          '<div class="chips">' + (d.events || []).map(function (e) {
            return '<span class="chip">' + F.esc(e) + "</span>";
          }).join("") + "</div>" +
          '<div class="small muted" style="margin-top:8px">签名算法：' +
          "<code>sha256=HMAC_SHA256(secret, timestamp + \".\" + body)</code>，请在接收端校验 " +
          "X-FYC-Signature 与时间戳（5 分钟窗口）防重放。</div></div></div>";
        document.getElementById("hNew").addEventListener("click", newHook);
        document.querySelectorAll("[data-test]").forEach(function (b) {
          b.addEventListener("click", function () {
            F.api("POST", "/api/integration/webhooks/" + b.getAttribute("data-test") + "/test", {})
              .then(function () { F.toast("测试事件已入队，5 秒内投递；可在「投递日志」查看结果", "ok"); })
              .catch(function (e) { F.toast(e.message, "err"); });
          });
        });
        document.querySelectorAll("[data-del]").forEach(function (b) {
          b.addEventListener("click", function () {
            if (!window.confirm("删除后不再推送，确认？")) return;
            F.api("DELETE", "/api/integration/webhooks/" + b.getAttribute("data-del"))
              .then(function () { F.toast("已删除", "ok"); draw(); })
              .catch(function (e) { F.toast(e.message, "err"); });
          });
        });
      });
    }

    function newHook() {
      var body = '<div class="form-grid">' +
        '<label>名称 *</label><input id="hN" type="text" placeholder="如 ERP 同步接收端">' +
        '<label>回调地址 *</label><input id="hU" type="text" placeholder="https://erp.example.com/hooks/crm">' +
        '<label>密钥</label><input id="hS" type="text" value="crm-secret-' + Math.random().toString(36).slice(2, 10) + '">' +
        '<label>订阅事件</label><input id="hE" type="text" value="*" placeholder="* 表示全部，或用逗号分隔">' +
        "</div>" +
        '<div class="small muted" style="margin-top:8px">接收端需返回 2xx；失败按 30s / 60s / 120s 退避重试，' +
        "3 次仍失败标记为「失败」，可在投递日志手动重发。</div>";
      F.dialog("新建 Webhook", body, '<button class="btn" data-close19="1">取消</button>' +
        '<button class="btn primary" id="hSave">保存</button>');
      document.querySelector("[data-close19]").addEventListener("click", F.closeDialog);
      document.getElementById("hSave").addEventListener("click", function () {
        F.api("POST", "/api/integration/webhooks", {
          name: document.getElementById("hN").value.trim(),
          url: document.getElementById("hU").value.trim(),
          secret: document.getElementById("hS").value.trim(),
          events: document.getElementById("hE").value.trim() || "*"
        }).then(function () { F.closeDialog(); F.toast("Webhook 已创建", "ok"); draw(); })
          .catch(function (e) { F.toast(e.message, "err"); });
      });
    }

    function drawDeliveries() {
      F.api("GET", "/api/integration/deliveries?" + F.qs({ status: st.deliveryStatus }))
        .then(function (d) {
          var chips = ["全部", "待投递", "成功", "失败"].map(function (s) {
            return '<button class="chip ' + (st.deliveryStatus === s ? "on" : "") + '" data-ds="' + s + '">' +
              s + "</button>";
          }).join("");
          document.getElementById("iBody").innerHTML =
            '<div class="panel"><div class="panel-title">投递日志' +
            '<span class="panel-actions small muted">后台线程每 5 秒扫描待投递任务</span></div>' +
            '<div class="panel-body"><div class="chips">' + chips + "</div></div>" +
            '<div class="panel-body flush">' +
            F.table([
              { label: "ID", num: true, key: "id" },
              { label: "事件", render: function (r) { return F.tag(r.event, "blue"); } },
              { label: "状态", render: function (r) { return F.tag(r.status); } },
              { label: "尝试", num: true, key: "attempts" },
              { label: "HTTP", num: true, render: function (r) { return r.http_code || "—"; } },
              { label: "错误", render: function (r) { return '<span class="small muted">' +
                F.esc((r.error || "").slice(0, 40)) + "</span>"; } },
              { label: "创建", render: function (r) { return '<span class="small muted">' +
                F.esc(r.created_at) + "</span>"; } },
              { label: "操作", render: function (r) {
                return r.status !== "成功" ? '<button class="btn sm" data-retry="' + r.id +
                  '">重发</button>' : "—";
              } }
            ], d.list, { empty: "暂无投递记录（可先在 Webhook 页点「测试」）" }) + "</div></div>";
          document.querySelectorAll("[data-ds]").forEach(function (b) {
            b.addEventListener("click", function () {
              st.deliveryStatus = b.getAttribute("data-ds"); draw();
            });
          });
          document.querySelectorAll("[data-retry]").forEach(function (b) {
            b.addEventListener("click", function () {
              F.api("POST", "/api/integration/deliveries/" + b.getAttribute("data-retry") + "/retry", {})
                .then(function () { F.toast("已重新入队", "ok"); draw(); })
                .catch(function (e) { F.toast(e.message, "err"); });
            });
          });
        });
    }

    function drawMaps() {
      F.api("GET", "/api/integration/mappings").then(function (d) {
        document.getElementById("iBody").innerHTML =
          '<div class="panel"><div class="panel-title">外部 ID 映射' +
          '<span class="panel-actions"><button class="btn sm primary" id="mNew">+ 绑定映射</button></span></div>' +
          '<div class="panel-body flush">' +
          F.table([
            { label: "对象", render: function (r) { return F.tag(r.obj_type, "gray"); } },
            { label: "本地编号", render: function (r) { return '<span class="mono small">' + F.esc(r.local_no) + "</span>"; } },
            { label: "外部 ID", render: function (r) { return '<span class="mono small">' + F.esc(r.external_id) + "</span>"; } },
            { label: "来源系统", key: "system" },
            { label: "创建", render: function (r) { return '<span class="small muted">' + F.esc(r.created_at) + "</span>"; } }
          ], d.list, { empty: "暂无映射" }) + "</div></div>" +
          '<div class="panel"><div class="panel-title">反查示例</div><div class="panel-body">' +
          '<pre class="code">GET /api/integration/resolve?externalId=crm-1001\&system=ERP\n' +
          '→ {"localNo": "C-0001", "objType": "customer"}</pre></div></div>';
        document.getElementById("mNew").addEventListener("click", function () {
          var body = '<div class="form-grid">' +
            '<label>对象类型</label><select id="mT"><option>customer</option><option>lead</option>' +
            "<option>opportunity</option><option>contract</option></select>" +
            '<label>本地编号</label><input id="mL" type="text" placeholder="如 C-0001">' +
            '<label>外部 ID</label><input id="mE" type="text" placeholder="如 crm-1001">' +
            '<label>来源系统</label><input id="mS" type="text" value="ERP">' +
            "</div>";
          F.dialog("绑定外部 ID", body, '<button class="btn" data-close20="1">取消</button>' +
            '<button class="btn primary" id="mSave">保存</button>');
          document.querySelector("[data-close20]").addEventListener("click", F.closeDialog);
          document.getElementById("mSave").addEventListener("click", function () {
            F.api("POST", "/api/integration/mappings", {
              objType: document.getElementById("mT").value,
              localNo: document.getElementById("mL").value.trim(),
              externalId: document.getElementById("mE").value.trim(),
              system: document.getElementById("mS").value.trim()
            }).then(function () { F.closeDialog(); F.toast("映射已保存", "ok"); draw(); })
              .catch(function (e) { F.toast(e.message, "err"); });
          });
        });
      });
    }

    function drawSync() {
      F.api("GET", "/api/sync/changes?since=0&limit=15").then(function (d) {
        document.getElementById("iBody").innerHTML =
          '<div class="panel"><div class="panel-title">增量变更流' +
          '<span class="panel-actions small muted">当前游标 ' + d.cursor + " / 共 " + d.count + " 条</span></div>" +
          '<div class="panel-body flush">' +
          F.table([
            { label: "游标", num: true, key: "id" },
            { label: "对象", render: function (r) { return F.tag(r.obj_type, "gray"); } },
            { label: "编号", render: function (r) { return '<span class="mono small">' + F.esc(r.obj_no) + "</span>"; } },
            { label: "动作", key: "op" },
            { label: "操作人", key: "actor" },
            { label: "时间", render: function (r) { return '<span class="small muted">' + F.esc(r.changed_at) + "</span>"; } }
          ], d.changes, { empty: "暂无变更" }) + "</div></div>" +
          '<div class="panel"><div class="panel-title">拉取方式</div><div class="panel-body">' +
          '<pre class="code">cursor = 0\nwhile True:\n    r = GET /api/sync/changes?since={cursor}\&limit=200\n' +
          '    for ch in r["changes"]:\n        apply(ch)          # 幂等 upsert\n' +
          '    cursor = r["cursor"]\n    if not r["hasMore"]:\n        sleep(60)          # 定时轮询</pre>' +
          "</div></div>";
        F.setStatus("集成中心 · 增量同步游标 " + d.cursor);
      });
    }

    draw();
  });
})(window, document);

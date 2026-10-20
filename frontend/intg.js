/* 飞泉 SCM · 集成中心（API Key / Webhook / 投递记录 / 外部映射 / 增量变更流） */
(function (window, document) {
  "use strict";
  var F = window.F;

  function isAdmin() {
    var u = (F.state.boot && F.state.boot.user) || {};
    return u.role === "admin";
  }

  var EVENTS = [
    "supplier.created", "supplier.status_changed", "supplier.scored",
    "material.created", "req.created", "req.submitted", "req.approved", "req.rejected",
    "rfq.created", "rfq.awarded", "po.created", "po.stage_changed", "po.cancelled",
    "receipt.created", "receipt.inspected", "receipt.posted", "receipt.returned",
    "stock.adjusted", "stock.transferred", "stock.stocktake",
    "invoice.created", "invoice.matched", "invoice.paid"
  ];

  var OBJECTS = ["supplier", "material", "requisition", "rfq", "po", "receipt", "stock",
    "transfer", "stocktake", "invoice"];

  F.register("integration", function () {
    if (!isAdmin()) {
      document.getElementById("view").innerHTML =
        '<div class="panel"><div class="panel-title">集成中心</div><div class="panel-body">' +
        '<div class="warn-box">集成中心仅管理员可见：API Key 与 Webhook 属于系统级凭证，' +
        "当前账号（" + F.esc(((F.state.boot || {}).user || {}).role_label || "非管理员") +
        "）没有访问权限。如需对接 ERP / WMS / 财务系统，请联系系统管理员开通。</div>" +
        '<div class="note" style="margin-top:10px">对接方仍可通过管理员分配的 API Key 调用开放接口，' +
        "接口文档见《飞泉 SCM 系统设计方案》第 9 章与 docs/API.md。</div></div></div>";
      F.setStatus("集成中心 · 需要管理员权限");
      F.setSide('<div class="side-block"><div class="hd">已开放的对接方式</div><div class="bd small muted" ' +
        'style="line-height:1.9">① REST + API Key（Header: X-Fq-Key）<br>' +
        "② Webhook 事件推送（HMAC-SHA256 签名）<br>" +
        "③ 增量同步 /api/sync/changes?since=&object=</div></div>");
      return;
    }

    var st = { tab: "keys" };

    function draw() {
      F.api("GET", "/api/integration/overview").then(function (ov) {
        var tabs = [["keys", "API Key"], ["hooks", "Webhook"], ["deliveries", "投递记录"],
          ["mappings", "外部映射"], ["changes", "变更流"]].map(function (t) {
          return '<button class="' + (st.tab === t[0] ? "on" : "") + '" data-tab="' + t[0] + '">' +
            t[1] + "</button>";
        }).join("");

        var html = '<div class="kpi-grid four">' +
          '<div class="kpi"><div class="k-label">启用中的 API Key</div><div class="k-value">' + ov.keys +
          '</div><div class="k-sub">scope 分 read / write</div></div>' +
          '<div class="kpi green"><div class="k-label">启用中的 Webhook</div><div class="k-value">' +
          ov.webhooks + '</div><div class="k-sub">待投递 ' + ov.pending + " 条</div></div>" +
          '<div class="kpi red"><div class="k-label">投递失败</div><div class="k-value">' + ov.failed +
          '</div><div class="k-sub">共 ' + ov.deliveries + " 条投递记录</div></div>" +
          '<div class="kpi gold"><div class="k-label">增量变更</div><div class="k-value">' + ov.changes +
          '</div><div class="k-sub">最近 ' + F.esc((ov.lastChange || "—").slice(5, 16)) + "</div></div></div>" +
          '<div class="panel"><div class="panel-title">集成中心' +
          '<span class="panel-actions small muted">凭证仅管理员可见 · 明文 Key 只展示一次</span></div>' +
          '<div class="panel-body" style="padding-bottom:0"><div class="tabs">' + tabs + "</div></div>" +
          '<div class="panel-body" id="intgBody">加载中…</div></div>';
        document.getElementById("view").innerHTML = html;
        document.querySelectorAll("[data-tab]").forEach(function (b) {
          b.addEventListener("click", function () { st.tab = b.getAttribute("data-tab"); draw(); });
        });
        if (st.tab === "keys") return drawKeys();
        if (st.tab === "hooks") return drawHooks();
        if (st.tab === "deliveries") return drawDeliveries();
        if (st.tab === "mappings") return drawMappings();
        return drawChanges();
      }).catch(function (e) { F.showErr(e); });
    }

    function drawKeys() {
      F.api("GET", "/api/integration/keys").then(function (d) {
        var box = document.getElementById("intgBody");
        box.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;' +
          'margin-bottom:8px"><div class="small muted">共 ' + d.total + " 个 Key</div>" +
          '<button class="btn sm primary" id="kNew">+ 新建 API Key</button></div>' +
          '<div style="margin:0 -14px -14px">' + F.table([
            { label: "名称", key: "name" },
            { label: "前缀", render: function (r) { return '<span class="mono small">' +
              F.esc(r.keyPrefix) + "…</span>"; } },
            { label: "权限", render: function (r) { return F.tag(r.scope, r.scope === "write" ? "gold" : "blue"); } },
            { label: "状态", render: function (r) { return F.tag(r.status); } },
            { label: "创建人", key: "owner" },
            { label: "创建时间", render: function (r) { return '<span class="small muted">' +
              F.esc(r.createdAt) + "</span>"; } },
            { label: "最近使用", render: function (r) { return r.lastUsedAt
              ? '<span class="small muted">' + F.esc(r.lastUsedAt) + "</span>"
              : '<span class="muted">未使用</span>'; } },
            { label: "有效期", render: function (r) { return r.expiresAt
              ? F.esc(r.expiresAt) : '<span class="muted">长期</span>'; } },
            { label: "操作", render: function (r) {
              return r.status === "启用"
                ? '<button class="btn xs danger" data-revoke="' + r.id + '">吊销</button>'
                : '<span class="muted">—</span>';
            } }
          ], d.list, { empty: "还没有 API Key" }) + "</div>";
        document.getElementById("kNew").addEventListener("click", function () {
          F.dialog("新建 API Key", '<div class="form-grid">' +
            '<label>名称</label><input id="kName" type="text" placeholder="如：金蝶云星空对接">' +
            '<label>权限</label><select id="kScope"><option value="read">read（只读）</option>' +
            '<option value="write">write（读写）</option></select></div>' +
            '<div class="note" style="margin-top:10px">Key 形如 <span class="mono">fqk_…</span>，' +
            "服务端只保存 SHA-256 哈希；调用时放在请求头 <span class='mono'>X-Fq-Key</span>。</div>",
            '<button class="btn" data-close2="1">取消</button>' +
            '<button class="btn primary" id="kSave">生成 Key</button>');
          document.getElementById("dialog").querySelector("[data-close2]")
            .addEventListener("click", F.closeDialog);
          document.getElementById("kSave").addEventListener("click", function () {
            F.api("POST", "/api/integration/keys", {
              name: document.getElementById("kName").value.trim(),
              scope: document.getElementById("kScope").value
            }).then(function (r) {
              F.dialog("Key 已生成 · 请立即保存", '<div class="keybox mono">' + F.esc(r.key) + "</div>" +
                '<div class="note" style="margin-top:10px">' + F.esc(r.notice) + "</div>" +
                '<div class="small muted" style="margin-top:8px">调用示例：<br>' +
                '<span class="mono">curl -H "X-Fq-Key: ' + F.esc(r.key) + '" ' +
                'http://127.0.0.1:8019/api/orders</span></div>',
                '<button class="btn primary" data-close2="1">我已保存</button>');
              document.getElementById("dialog").querySelector("[data-close2]")
                .addEventListener("click", function () { F.closeDialog(); draw(); });
            }).catch(function (e) { F.showErr(e); });
          });
        });
        document.querySelectorAll("[data-revoke]").forEach(function (b) {
          b.addEventListener("click", function () {
            if (!window.confirm("吊销后该 Key 立即失效，确认吊销？")) return;
            F.api("DELETE", "/api/integration/keys/" + b.getAttribute("data-revoke"))
              .then(function () { F.toast("Key 已吊销", "ok"); draw(); })
              .catch(function (e) { F.showErr(e); });
          });
        });
        F.setStatus("集成中心 · API Key " + d.total + " 个");
        F.setSide('<div class="side-block"><div class="hd">鉴权方式</div><div class="bd small muted" ' +
          'style="line-height:1.9">请求头任选其一：<br><span class="mono">X-Fq-Key: fqk_…</span><br>' +
          '<span class="mono">Authorization: Bearer fqk_…</span><br>' +
          "write 权限的 Key 才能调用 POST / PUT / DELETE 接口。</div></div>" +
          '<div class="side-block"><div class="hd">建议</div><div class="bd small muted" style="line-height:1.9">' +
          "按对接方一人一键，便于单独吊销与审计；只读同步用 read，回写单据才给 write。</div></div>");
      }).catch(function (e) { F.showErr(e); });
    }

    function drawHooks() {
      F.api("GET", "/api/integration/webhooks").then(function (d) {
        var box = document.getElementById("intgBody");
        box.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;' +
          'margin-bottom:8px"><div class="small muted">共 ' + d.list.length + " 个订阅</div>" +
          '<button class="btn sm primary" id="wNew">+ 新建 Webhook</button></div>' +
          '<div style="margin:0 -14px -14px">' + F.table([
            { label: "名称", render: function (r) { return '<b>' + F.esc(r.name) + '</b><div class="muted small mono">' +
              F.esc(r.url) + "</div>"; } },
            { label: "事件", render: function (r) {
              var ev = String(r.events || "*");
              if (ev === "*") return F.tag("全部事件", "blue");
              var arr = ev.split(",");
              return arr.slice(0, 2).map(function (x) { return F.tag(x.trim(), "gray"); }).join(" ") +
                (arr.length > 2 ? '<span class="small muted"> +' + (arr.length - 2) + "</span>" : "");
            } },
            { label: "状态", render: function (r) { return F.tag(r.status); } },
            { label: "投递统计", render: function (r) {
              var s = r.deliveryStats || {};
              var parts = Object.keys(s).map(function (k) { return k + " " + s[k]; });
              return parts.length ? '<span class="small">' + F.esc(parts.join(" / ")) + "</span>"
                : '<span class="muted">无记录</span>';
            } },
            { label: "最近投递", render: function (r) { return r.last_at
              ? '<span class="small muted">' + F.esc(r.last_at) + "</span>" +
                (r.last_status ? " " + F.tag(r.last_status, r.last_status === "成功" ? "green" : "red") : "")
              : '<span class="muted">—</span>'; } },
            { label: "操作", render: function (r) {
              return '<button class="btn xs" data-edit="' + r.id + '">编辑</button> ' +
                '<button class="btn xs" data-test="' + r.id + '">测试</button> ' +
                '<button class="btn xs danger" data-del="' + r.id + '">删除</button>';
            } }
          ], d.list, { empty: "还没有配置 Webhook" }) + "</div>";

        document.getElementById("wNew").addEventListener("click", function () { hookForm(null, d.list); });
        document.querySelectorAll("[data-edit]").forEach(function (b) {
          b.addEventListener("click", function () {
            var id = Number(b.getAttribute("data-edit"));
            hookForm(d.list.filter(function (x) { return x.id === id; })[0], d.list);
          });
        });
        document.querySelectorAll("[data-test]").forEach(function (b) {
          b.addEventListener("click", function () {
            F.api("POST", "/api/integration/webhooks/" + b.getAttribute("data-test") + "/test", {})
              .then(function () { F.toast("测试事件已入队，可在投递记录查看结果", "ok"); st.tab = "deliveries"; draw(); })
              .catch(function (e) { F.showErr(e); });
          });
        });
        document.querySelectorAll("[data-del]").forEach(function (b) {
          b.addEventListener("click", function () {
            if (!window.confirm("删除该 Webhook 订阅？历史投递记录保留。")) return;
            F.api("DELETE", "/api/integration/webhooks/" + b.getAttribute("data-del"))
              .then(function () { F.toast("Webhook 已删除", "ok"); draw(); })
              .catch(function (e) { F.showErr(e); });
          });
        });
        F.setStatus("集成中心 · Webhook " + d.list.length + " 个");
        F.setSide('<div class="side-block"><div class="hd">签名校验</div><div class="bd small muted" ' +
          'style="line-height:1.9">收到回调后校验：<br>' +
          "签名原文 = <span class='mono'>timestamp + \".\" + body</span><br>" +
          "HMAC-SHA256(secret) 与 <span class='mono'>X-FQC-Signature</span> 比对；" +
          "时间戳偏移超过 5 分钟应拒绝，防止重放。</div></div>" +
          '<div class="side-block"><div class="hd">重试策略</div><div class="bd small muted" ' +
          'style="line-height:1.9">失败按 30 × 2ⁿ 秒退避重试，最多 3 次；最终失败保留记录，' +
          "可在投递记录页手动重投。</div></div>");
      }).catch(function (e) { F.showErr(e); });
    }

    function hookForm(h, list) {
      var picked = String((h && h.events) || "*") === "*" ? EVENTS.slice()
        : String(h.events).split(",").map(function (s) { return s.trim(); });
      var evHtml = EVENTS.map(function (e) {
        return '<label class="small" style="display:block;margin:2px 0"><input type="checkbox" class="ev"' +
          ' value="' + e + '"' + (picked.indexOf(e) >= 0 ? " checked" : "") + "> " + e + "</label>";
      }).join("");
      F.dialog(h ? "编辑 Webhook" : "新建 Webhook", '<div class="form-grid">' +
        '<label>名称</label><input id="wName" type="text" value="' + F.esc((h && h.name) || "") +
        '" placeholder="如：WMS 到货通知">' +
        '<label>地址</label><input id="wUrl" type="text" value="' + F.esc((h && h.url) || "") +
        '" placeholder="https://wms.example.com/hooks/fq">' +
        '<label>状态</label><select id="wStatus"><option>启用</option><option>停用</option></select>' +
        '<label>密钥</label><input id="wSecret" type="text" value="' + F.esc((h && h.secret) || "") +
        '" placeholder="留空自动生成 32 位"></div>' +
        '<div class="section-title" style="margin-top:10px">订阅事件（不选默认全部）</div>' +
        '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0 10px;max-height:200px;overflow:auto">' +
        evHtml + "</div>",
        '<button class="btn" data-close2="1">取消</button>' +
        '<button class="btn" id="wAll">全选</button>' +
        '<button class="btn primary" id="wSave">保存</button>');
      var dlg = document.getElementById("dialog");
      dlg.querySelector("[data-close2]").addEventListener("click", F.closeDialog);
      if (h) document.getElementById("wStatus").value = h.status || "启用";
      document.getElementById("wAll").addEventListener("click", function () {
        var all = document.querySelectorAll(".ev");
        var needCheck = Array.prototype.some.call(all, function (c) { return !c.checked; });
        Array.prototype.forEach.call(all, function (c) { c.checked = needCheck; });
      });
      document.getElementById("wSave").addEventListener("click", function () {
        var evs = [];
        document.querySelectorAll("#dialog .ev").forEach(function (c) {
          if (c.checked) evs.push(c.value);
        });
        var payload = {
          name: document.getElementById("wName").value.trim() || "未命名",
          url: document.getElementById("wUrl").value.trim(),
          events: evs.length ? evs : "*",
          status: document.getElementById("wStatus").value,
          secret: document.getElementById("wSecret").value.trim()
        };
        var req = h
          ? F.api("PUT", "/api/integration/webhooks/" + h.id, payload)
          : F.api("POST", "/api/integration/webhooks", payload);
        req.then(function () {
          F.closeDialog();
          F.toast("Webhook 已保存", "ok");
          draw();
        }).catch(function (e) { F.showErr(e); });
      });
    }

    function drawDeliveries() {
      F.api("GET", "/api/integration/deliveries").then(function (d) {
        var box = document.getElementById("intgBody");
        box.innerHTML = '<div class="small muted" style="margin-bottom:8px">最近 ' + d.total +
          " 条投递记录（最多 100 条）</div>" +
          '<div style="margin:0 -14px -14px">' + F.table([
            { label: "ID", render: function (r) { return '<span class="mono small">#' + r.id + "</span>"; } },
            { label: "事件", render: function (r) { return F.tag(r.event, "blue"); } },
            { label: "状态", render: function (r) { return F.tag(r.status); } },
            { label: "尝试", num: true, render: function (r) { return r.attempts + " 次"; } },
            { label: "HTTP", num: true, render: function (r) { return r.http_code || "—"; } },
            { label: "创建时间", render: function (r) { return '<span class="small muted">' +
              F.esc(r.created_at) + "</span>"; } },
            { label: "完成时间", render: function (r) { return r.delivered_at
              ? '<span class="small muted">' + F.esc(r.delivered_at) + "</span>" : '<span class="muted">—</span>'; } },
            { label: "错误", render: function (r) { return r.error
              ? '<span class="small down">' + F.esc(String(r.error).slice(0, 40)) + "</span>"
              : '<span class="muted">—</span>'; } },
            { label: "操作", render: function (r) {
              return '<button class="btn xs" data-pk="' + r.id + '">查看</button> ' +
                (r.status !== "成功" ? '<button class="btn xs primary" data-retry="' + r.id + '">重投</button>' : "");
            } }
          ], d.list, { empty: "暂无投递记录" }) + "</div>";
        document.querySelectorAll("[data-pk]").forEach(function (b) {
          b.addEventListener("click", function () {
            var id = Number(b.getAttribute("data-pk"));
            var row = d.list.filter(function (x) { return x.id === id; })[0];
            F.dialog("投递详情 #" + id, '<div class="form-grid">' +
              '<label>事件</label><div class="mono small">' + F.esc(row.event) + "</div>" +
              '<label>状态</label><div>' + F.tag(row.status) + "</div>" +
              '<label>签名</label><div class="mono small" style="word-break:break-all">' +
              F.esc(row.signature || "—") + "</div>" +
              '<label>下次重试</label><div class="small muted">' + F.esc(row.next_at || "—") + "</div></div>" +
              '<div class="section-title" style="margin-top:10px">Payload</div>' +
              '<pre class="code" style="max-height:280px;overflow:auto">' +
              F.esc(JSON.stringify(row.payload, null, 2)) + "</pre>",
              '<button class="btn" data-close2="1">关闭</button>');
            document.getElementById("dialog").querySelector("[data-close2]")
              .addEventListener("click", F.closeDialog);
          });
        });
        document.querySelectorAll("[data-retry]").forEach(function (b) {
          b.addEventListener("click", function () {
            F.api("POST", "/api/integration/deliveries/" + b.getAttribute("data-retry") + "/retry", {})
              .then(function () { F.toast("已重新入队", "ok"); draw(); })
              .catch(function (e) { F.showErr(e); });
          });
        });
        F.setStatus("投递记录 · " + d.total + " 条");
        F.setSide('<div class="side-block"><div class="hd">状态含义</div><div class="bd small muted" ' +
          'style="line-height:1.9">待投递：已入队等待投递线程；成功：2xx 响应；失败：重试次数用尽，' +
          "需排查接收端后手动重投。</div></div>");
      }).catch(function (e) { F.showErr(e); });
    }

    function drawMappings() {
      F.api("GET", "/api/integration/mappings").then(function (d) {
        var box = document.getElementById("intgBody");
        box.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;' +
          'margin-bottom:8px"><div class="small muted">共 ' + d.list.length + " 条外部 ID 映射</div>" +
          '<button class="btn sm primary" id="mNew">+ 绑定映射</button></div>' +
          '<div style="margin:0 -14px -14px">' + F.table([
            { label: "对象类型", render: function (r) { return F.tag(r.obj_type, "gray"); } },
            { label: "本系统单号", render: function (r) { return '<span class="mono small">' +
              F.esc(r.local_no) + "</span>"; } },
            { label: "外部 ID", render: function (r) { return '<span class="mono small">' +
              F.esc(r.external_id) + "</span>"; } },
            { label: "外部系统", key: "system" },
            { label: "创建时间", render: function (r) { return '<span class="small muted">' +
              F.esc(r.created_at) + "</span>"; } }
          ], d.list, { empty: "还没有映射关系" }) + "</div>";
        document.getElementById("mNew").addEventListener("click", function () {
          F.dialog("绑定外部 ID", '<div class="form-grid">' +
            '<label>对象类型</label><select id="mObj">' + OBJECTS.map(function (o) {
              return '<option value="' + o + '">' + o + "</option>";
            }).join("") + "</select>" +
            '<label>本系统单号</label><input id="mLocal" type="text" placeholder="如 PO20261020-0001">' +
            '<label>外部 ID</label><input id="mExt" type="text" placeholder="如 KD-PO-8891">' +
            '<label>外部系统</label><input id="mSys" type="text" placeholder="如 金蝶云星空"></div>' +
            '<div class="note" style="margin-top:10px">映射用于对接方按外部主键反查本系统单据：' +
            'GET /api/integration/resolve?externalId=…&system=…</div>',
            '<button class="btn" data-close2="1">取消</button>' +
            '<button class="btn primary" id="mSave">保存</button>');
          document.getElementById("dialog").querySelector("[data-close2]")
            .addEventListener("click", F.closeDialog);
          document.getElementById("mSave").addEventListener("click", function () {
            F.api("POST", "/api/integration/mappings", {
              objType: document.getElementById("mObj").value,
              localNo: document.getElementById("mLocal").value.trim(),
              externalId: document.getElementById("mExt").value.trim(),
              system: document.getElementById("mSys").value.trim()
            }).then(function (r) {
              F.closeDialog();
              F.toast(r.updated ? "映射已更新" : "映射已创建", "ok");
              draw();
            }).catch(function (e) { F.showErr(e); });
          });
        });
        F.setStatus("外部映射 · " + d.list.length + " 条");
        F.setSide('<div class="side-block"><div class="hd">映射口径</div><div class="bd small muted" ' +
          'style="line-height:1.9">同一外部系统 + 外部 ID 唯一；重复绑定会更新本系统单号。' +
          "建议对接方首次同步时先调用 resolve，命中则走更新，未命中再创建。</div></div>");
      }).catch(function (e) { F.showErr(e); });
    }

    function drawChanges() {
      var cursor = 0;
      function load(since) {
        F.api("GET", "/api/sync/changes?" + F.qs({ since: since || 0, limit: 50 })).then(function (d) {
          var box = document.getElementById("intgBody");
          if (!since) {
            box.innerHTML = '<div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">' +
              '<select id="cObj" style="width:150px"><option value="">全部对象</option>' +
              OBJECTS.map(function (o) { return '<option value="' + o + '">' + o + "</option>"; }).join("") +
              '</select><button class="btn sm" id="cPull">拉取最新 50 条</button>' +
              '<span class="small muted" id="cInfo"></span></div><div id="cList"></div>';
          }
          cursor = d.cursor;
          var html = '<div style="margin:0 -14px -14px">' + F.table([
            { label: "游标", render: function (r) { return '<span class="mono small">#' + r.id + "</span>"; } },
            { label: "对象", render: function (r) { return F.tag(r.obj_type, "gray"); } },
            { label: "单号", render: function (r) { return '<span class="mono small">' +
              F.esc(r.obj_no) + "</span>"; } },
            { label: "动作", render: function (r) { return F.tag(r.op, "blue"); } },
            { label: "操作人", key: "actor" },
            { label: "时间", render: function (r) { return '<span class="small muted">' +
              F.esc(r.changed_at) + "</span>"; } }
          ], d.changes, { empty: "没有变更" }) + "</div>";
          var list = document.getElementById("cList");
          if (list) list.innerHTML = html; else box.innerHTML += html;
          var info = document.getElementById("cInfo");
          if (info) info.textContent = "本次 " + d.count + " 条 · 游标 " + d.cursor +
            (d.hasMore ? " · 还有更多" : " · 已到末尾");
          if (!since) {
            document.getElementById("cPull").addEventListener("click", function () {
              var obj = document.getElementById("cObj").value;
              F.api("GET", "/api/sync/changes?" + F.qs({ since: 0, object: obj, limit: 50 }))
                .then(function (res) {
                  F.toast("拉取 " + res.count + " 条变更，游标 " + res.cursor, "ok");
                  draw();
                }).catch(function (e) { F.showErr(e); });
            });
          }
          F.setStatus("变更流 · 游标 " + d.cursor);
          F.setSide('<div class="side-block"><div class="hd">增量同步用法</div><div class="bd small muted" ' +
            'style="line-height:1.9">首次 since=0 拉全量，记录返回 cursor；下次带 since=cursor 继续拉取，' +
            "hasMore=true 时立即再拉一次。<br>建议按对象分topic消费，与本系统主键 obj_no 对齐。</div></div>" +
            '<div class="side-block"><div class="hd">对接顺序</div><div class="bd small muted" ' +
            'style="line-height:1.9">主数据（供应商 / 物料）→ 单据（请购 / 订单 / 收货 / 发票）→ 库存与结算。' +
            "回写建议只写对方系统，不在两侧同时改同一单。</div></div>");
        }).catch(function (e) { F.showErr(e); });
      }
      load(0);
    }

    draw();
  });
})(window, document);

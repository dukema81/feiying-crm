/* 飞泉 SCM · 前端框架、供应链驾驶舱、基础设置与日志（原生 JS，零依赖） */
(function (window, document) {
  "use strict";

  var F = window.F = {};
  var TOKEN_KEY = "fq_token";

  F.state = { boot: null, route: "dashboard", params: {} };

  /* ---------------------------------------------------------- 基础工具 */
  F.esc = function (s) {
    return String(s === undefined || s === null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  F.num = function (v, d) {
    var n = Number(v || 0);
    return n.toLocaleString("zh-CN", { minimumFractionDigits: d === undefined ? 2 : d,
      maximumFractionDigits: d === undefined ? 2 : d });
  };
  F.money = function (v) { return F.num(v, 2); };
  F.wan = function (v) {
    var n = Number(v || 0);
    return Math.abs(n) >= 10000 ? (n / 10000).toFixed(1) + " 万" : F.num(n, 0);
  };
  F.int = function (v) { return F.num(v, 0); };
  F.qty = function (v) {
    var n = Number(v || 0);
    return Number.isInteger(n) ? F.int(n) : F.num(n, 2);
  };
  F.pct = function (v, d) {
    var n = Number(v || 0) * 100;
    return n.toFixed(d === undefined ? 1 : d) + "%";
  };
  F.cls = function (v) { var n = Number(v || 0); return n > 0 ? "up" : (n < 0 ? "down" : "flat"); };
  F.today = function () { return new Date().toISOString().slice(0, 10); };
  F.addDays = function (n) {
    var d = new Date();
    d.setDate(d.getDate() + n);
    return d.toISOString().slice(0, 10);
  };
  F.qs = function (o) {
    return Object.keys(o || {}).filter(function (k) { return o[k] !== undefined && o[k] !== null; })
      .map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(o[k]); }).join("&");
  };
  F.dash = function (v) { return v === null || v === undefined || v === "" ? "—" : v; };

  var TAGS = {
    // 供应商
    "待准入": "gold", "已准入": "green", "观察": "red", "冻结": "gray",
    "A": "green", "B": "blue", "C": "gold", "D": "red",
    "有效": "green", "临期": "gold", "过期": "red", "未知": "gray",
    // 请购
    "草稿": "gray", "待审批": "gold", "已审批": "blue", "已转单": "green",
    "已驳回": "red", "已取消": "gray",
    // 询价
    "询价中": "blue", "已定标": "green",
    // 订单
    "已下单": "blue", "部分到货": "gold", "全部到货": "green", "已结算": "green",
    // 收货
    "待质检": "gold", "已质检": "blue", "已入库": "green", "已退货": "red",
    "合格": "green", "让步接收": "gold", "退货": "red", "待检": "gray",
    // 发票
    "待匹配": "gold", "待付款": "blue", "已付款": "green", "差异挂起": "red",
    "金额差异超限": "red", "通过": "green", "无收货": "gray", "无发票": "gray",
    "逾期": "red", "未到期": "gray", "已付": "green", "待付": "blue",
    // 库存
    "正常": "green", "待补货": "gold", "低于安全库存": "red", "缺货": "red", "超储": "blue",
    "近效期": "gold", "已过期": "red", "无有效期": "gray",
    // 通用
    "启用": "green", "停用": "gray", "吊销": "red", "禁用": "gray",
    "已完成": "green", "处理中": "blue", "成功": "green", "失败": "red", "待投递": "gold",
    "采购入库": "green", "领用出库": "blue", "调拨出库": "gold", "调拨入库": "green",
    "盘盈": "green", "盘亏": "red", "退货出库": "red", "其他入库": "blue"
  };
  F.tag = function (s, cls) {
    return '<span class="tag ' + (cls || TAGS[s] || "gray") + '">' + F.esc(s) + "</span>";
  };
  F.scoreBadge = function (score) {
    var s = Number(score || 0);
    var cls = s >= 85 ? "green" : (s >= 70 ? "blue" : (s >= 55 ? "gold" : "red"));
    return '<span class="score ' + cls + '">' + s.toFixed(0) + "</span>";
  };
  F.levelTag = function (lv) { return F.tag(lv, lv === "A" ? "green" : lv === "B" ? "blue" : lv === "C" ? "gold" : "red"); };

  /* ---------------------------------------------------------- 请求 */
  F.raw = function (method, path, body, headers) {
    var h = { "Content-Type": "application/json" };
    var tk = localStorage.getItem(TOKEN_KEY);
    if (tk) { h.Authorization = "Bearer " + tk; h["X-Fq-Token"] = tk; }
    Object.keys(headers || {}).forEach(function (k) { h[k] = headers[k]; });
    var opt = { method: method, headers: h };
    if (body !== undefined && body !== null) opt.body = JSON.stringify(body);
    return fetch(path.replace(/^\//, ""), opt).then(function (r) {
      return r.json().catch(function () { return { error: "响应解析失败" }; })
        .then(function (j) { return { status: r.status, body: j }; });
    });
  };

  F.api = function (method, path, body) {
    return F.raw(method, path, body).then(function (x) {
      if (x.status === 401) {
        localStorage.removeItem(TOKEN_KEY);
        location.href = "./login.html";
        return new Promise(function () {});
      }
      if (x.status >= 400) {
        var e = new Error((x.body && x.body.error) || ("请求失败 " + x.status));
        e.status = x.status;
        e.body = x.body;
        throw e;
      }
      return x.body.data;
    });
  };

  F.toast = function (msg, kind) {
    var el = document.getElementById("statusMsg");
    if (!el) return;
    el.textContent = msg;
    F._toastUntil = Date.now() + 6000;
    el.style.color = kind === "err" ? "#ffb3a7" : (kind === "ok" ? "#9ee6b8" : "");
    clearTimeout(F._t);
    F._t = setTimeout(function () { el.style.color = ""; }, 8000);
  };
  F.setStatus = function (t) {
    var el = document.getElementById("statusMsg");
    if (!el) return;
    if (F._toastUntil && Date.now() < F._toastUntil) return;
    el.textContent = t;
  };
  F.setSide = function (html) { var el = document.getElementById("side"); if (el) el.innerHTML = html; };

  /* ---------------------------------------------------------- 路由 */
  function parseHash() {
    var h = (location.hash || "#dashboard").replace(/^#\/?/, "");
    var i = h.indexOf("?");
    var route = i < 0 ? h : h.slice(0, i);
    var qs = i < 0 ? "" : h.slice(i + 1);
    var params = {};
    qs.split("&").forEach(function (kv) {
      if (!kv) return;
      var j = kv.indexOf("=");
      params[decodeURIComponent(j < 0 ? kv : kv.slice(0, j))] =
        decodeURIComponent(j < 0 ? "" : kv.slice(j + 1));
    });
    return { route: route || "dashboard", params: params };
  }

  F.go = function (route, params) {
    location.hash = "#" + route + (params && Object.keys(params).length ? "?" + F.qs(params) : "");
  };

  var PAGES = {};
  F.register = function (name, fn) { PAGES[name] = fn; };

  function render() {
    var r = parseHash();
    F.state.route = r.route;
    F.state.params = r.params;
    var fn = PAGES[r.route] || PAGES.dashboard;
    var view = document.getElementById("view");
    view.innerHTML = "";
    paintNav(r.route);
    try {
      fn(r.params);
    } catch (e) {
      view.innerHTML = '<div class="panel"><div class="panel-body">页面渲染失败：' +
        F.esc(e.message) + "</div></div>";
    }
  }

  /* ---------------------------------------------------------- 导航 */
  var TREE = [
    { grp: "总览", items: [["dashboard", "供应链驾驶舱"]] },
    { grp: "主数据", items: [["suppliers", "供应商档案"], ["materials", "物料主数据"]] },
    { grp: "采购执行", items: [["requisitions", "请购单"], ["rfqs", "询价比价"],
      ["orders", "采购订单"], ["receipts", "收货质检"]] },
    { grp: "库存", items: [["stock", "库存台账"], ["stockops", "库存作业"]] },
    { grp: "结算与分析", items: [["invoices", "结算付款"], ["reports", "报表分析"]] },
    { grp: "系统", items: [["integration", "集成中心"], ["settings", "基础设置"], ["logs", "操作日志"]] }
  ];

  var MENU = TREE.map(function (g) { return [g.grp, g.items.map(function (i) { return i[0]; })]; });

  var TITLE = {
    dashboard: "供应链驾驶舱", suppliers: "供应商档案", materials: "物料主数据",
    requisitions: "请购单", rfqs: "询价比价", orders: "采购订单", receipts: "收货质检",
    stock: "库存台账", stockops: "库存作业", invoices: "结算付款", reports: "报表分析",
    integration: "集成中心", settings: "基础设置", logs: "操作日志"
  };
  F.TITLE = TITLE;

  function paintNav(route) {
    var tree = document.getElementById("tree");
    var boot = F.state.boot || {};
    var kpi = boot.kpi || {};
    var badgeFor = { dashboard: (boot.todos || []).length, requisitions: kpi.pendingApprove || 0,
      receipts: kpi.receiptPending || 0, stock: kpi.shortageCount || 0,
      invoices: kpi.pendingInvoice || 0 };
    tree.innerHTML = TREE.map(function (g) {
      return '<div class="grp">' + F.esc(g.grp) + "</div>" + g.items.map(function (it) {
        var n = badgeFor[it[0]] || 0;
        var badge = n ? '<b class="nav-badge">' + n + "</b>" : "";
        return '<a href="#' + it[0] + '" class="' + (it[0] === route ? "on" : "") + '">' +
          F.esc(it[1]) + badge + "</a>";
      }).join("");
    }).join("");

    var mb = document.getElementById("menubar");
    var groupOf = {};
    MENU.forEach(function (m) { m[1].forEach(function (r) { groupOf[r] = m[0]; }); });
    mb.innerHTML = MENU.map(function (m) {
      return '<button class="' + (groupOf[route] === m[0] ? "on" : "") + '" data-group="' +
        F.esc(m[0]) + '">' + F.esc(m[0]) + "</button>";
    }).join("");
    mb.querySelectorAll("button").forEach(function (b) {
      b.addEventListener("click", function () {
        var g = b.getAttribute("data-group");
        var target = MENU.filter(function (m) { return m[0] === g; })[0];
        if (target) F.go(target[1][0]);
      });
    });

    var ts = document.getElementById("tabstrip");
    ts.innerHTML = '<span class="tab">' + F.esc(TITLE[route] || route) + "</span>" +
      '<span class="muted small">飞泉 SCM / ' + F.esc(TITLE[route] || route) + "</span>";
  }

  /* ---------------------------------------------------------- 通用渲染 */
  F.table = function (headers, rows, opts) {
    opts = opts || {};
    var th = headers.map(function (h) {
      return "<th class='" + (h.num ? "num" : "") + "'" +
        (h.width ? " style='width:" + h.width + "'" : "") + ">" + F.esc(h.label) + "</th>";
    }).join("");
    var body = rows && rows.length ? rows.map(function (r, i) {
      return '<tr class="' + (opts.click ? "clickable" : "") + '"' +
        (opts.click ? " data-key='" + F.esc(opts.click(r, i)) + "'" : "") + ">" +
        headers.map(function (h) {
          var v = h.render ? h.render(r, i) : F.esc(r[h.key]);
          return "<td class='" + (h.num ? "num" : "") + "'>" + v + "</td>";
        }).join("") + "</tr>";
    }).join("") : '<tr class="empty-row"><td colspan="' + headers.length + '">' +
      F.esc(opts.empty || "暂无数据") + "</td></tr>";
    return "<table class='grid-table'><thead><tr>" + th + "</tr></thead><tbody>" + body + "</tbody></table>";
  };

  F.bindRows = function (root, fn) {
    (root || document).querySelectorAll("#view tbody tr[data-key]").forEach(function (tr) {
      tr.addEventListener("click", function () { fn(tr.getAttribute("data-key"), tr); });
    });
  };

  F.dialog = function (title, body, foot) {
    var mask = document.getElementById("mask");
    var dlg = document.getElementById("dialog");
    dlg.innerHTML = '<div class="dh">' + F.esc(title) +
      '<span class="x" data-close="1">×</span></div><div class="db">' + body + "</div>" +
      (foot ? '<div class="df">' + foot + "</div>" : "");
    mask.className = "mask on";
    dlg.querySelector("[data-close]").addEventListener("click", F.closeDialog);
    return dlg;
  };
  F.closeDialog = function () { document.getElementById("mask").className = "mask"; };
  F.dialogOpen = function () {
    return document.getElementById("mask").className.indexOf("on") >= 0;
  };

  F.lineChart = function (series, opts) {
    opts = opts || {};
    var W = opts.width || 640, H = opts.height || 190, P = 34;
    var labels = opts.labels || [];
    var all = [];
    series.forEach(function (s) { all = all.concat(s.data); });
    var max = Math.max.apply(null, all.concat([1]));
    var min = opts.zero === false ? Math.min.apply(null, all) : 0;
    var span = max - min || 1;
    var colors = opts.colors || ["#1f7a8c", "#c8963e", "#7a5ea8"];
    var w = (W - P * 2) / Math.max(1, labels.length - 1);
    var grid = [0, 0.25, 0.5, 0.75, 1].map(function (t) {
      var y = P + (H - P * 1.6) * t;
      var val = max - span * t;
      return '<line x1="' + P + '" y1="' + y + '" x2="' + (W - P) + '" y2="' + y +
        '" stroke="#eef2f5"/><text x="6" y="' + (y + 4) + '" font-size="10" fill="#8b9aa6">' +
        (val >= 10000 ? (val / 10000).toFixed(1) + "万" : Math.round(val)) + "</text>";
    }).join("");
    var paths = series.map(function (s, si) {
      var d = s.data.map(function (v, i) {
        var x = P + w * i;
        var y = P + (H - P * 1.6) * (1 - (v - min) / span);
        return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
      }).join(" ");
      return '<path d="' + d + '" fill="none" stroke="' + colors[si % colors.length] +
        '" stroke-width="2"/>' + s.data.map(function (v, i) {
          var x = P + w * i;
          var y = P + (H - P * 1.6) * (1 - (v - min) / span);
          return '<circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="2.6" fill="' +
            colors[si % colors.length] + '"/>';
        }).join("");
    }).join("");
    var xlabels = labels.map(function (t, i) {
      return '<text x="' + (P + w * i) + '" y="' + (H - 6) +
        '" font-size="10" fill="#8b9aa6" text-anchor="middle">' + F.esc(t) + "</text>";
    }).join("");
    return '<svg viewBox="0 0 ' + W + " " + H + '" width="100%" height="' + H + '">' +
      grid + paths + xlabels + "</svg>";
  };

  F.barChart = function (items, opts) {
    opts = opts || {};
    var W = opts.width || 640, H = opts.height || 180, P = 34;
    var max = Math.max.apply(null, items.map(function (i) { return i.value; }).concat([1]));
    var gap = (W - P * 2) / Math.max(1, items.length);
    var bw = gap * 0.56;
    return '<svg viewBox="0 0 ' + W + " " + H + '" width="100%" height="' + H + '">' +
      items.map(function (it, i) {
        var h = (H - P * 1.8) * (it.value / max);
        var x = P + gap * i + (gap - bw) / 2;
        var y = H - P - h;
        return '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + bw.toFixed(1) +
          '" height="' + h.toFixed(1) + '" rx="2" fill="' + (it.color || "#2b9eb3") + '"/>' +
          '<text x="' + (x + bw / 2).toFixed(1) + '" y="' + (y - 5) +
          '" font-size="10" fill="#5d6f7c" text-anchor="middle">' + F.esc(it.label2 || "") +
          "</text>" + '<text x="' + (x + bw / 2).toFixed(1) + '" y="' + (H - 8) +
          '" font-size="10" fill="#8b9aa6" text-anchor="middle">' + F.esc(it.label) + "</text>";
      }).join("") + "</svg>";
  };

  // 阶段分布条（采购订单流程）
  F.flowBars = function (stages) {
    var max = Math.max.apply(null, stages.map(function (s) { return s.amount; }).concat([1]));
    return '<div class="funnel">' + stages.map(function (s) {
      var w = Math.max(6, Math.round(s.amount / max * 100));
      return '<div class="fn-row"><div class="fn-name">' + F.esc(s.stage) + "</div>" +
        '<div class="fn-bar"><i style="width:' + w + '%"></i></div>' +
        '<div class="fn-val">' + F.wan(s.amount) + ' <span class="muted small">' + s.count + " 单</span></div>" +
        '<div class="fn-conv">' + (s.count ? "" : "—") + "</div></div>";
    }).join("") + "</div>";
  };

  F.empty = function (text) {
    return '<div class="empty-hint">' + F.esc(text || "暂无数据") + "</div>";
  };

  F.kv = function (label, value) {
    return '<div class="side-kv"><span>' + F.esc(label) + "</span><b>" + value + "</b></div>";
  };

  /* ---------------------------------------------------------- 驾驶舱 */
  F.register("dashboard", function () {
    var b = F.state.boot;
    if (!b) return;
    var k = b.kpi;
    var html = '<div class="kpi-grid six">' +
      '<div class="kpi"><div class="k-label">在途采购</div><div class="k-value">' + F.wan(k.openAmount) +
      '</div><div class="k-sub">' + k.openCount + " 单 · 待审批 " + k.pendingApprove + "</div></div>" +
      '<div class="kpi green"><div class="k-label">本月到货金额</div><div class="k-value">' +
      F.wan(k.monthReceive) + '</div><div class="k-sub">近 90 天准时率 ' + F.pct(k.onTimeRate, 0) + "</div></div>" +
      '<div class="kpi"><div class="k-label">库存金额</div><div class="k-value">' + F.wan(k.stockValue) +
      '</div><div class="k-sub">本月领用 ' + F.wan(k.monthIssue) + "</div></div>" +
      '<div class="kpi red"><div class="k-label">缺料预警</div><div class="k-value">' + k.shortageCount +
      '</div><div class="k-sub">近效期批次 ' + k.expiringCount + " 个</div></div>" +
      '<div class="kpi gold"><div class="k-label">待处理发票</div><div class="k-value">' +
      k.pendingInvoice + '</div><div class="k-sub">逾期应付 ' + F.wan(k.overduePayable) + "</div></div>" +
      '<div class="kpi"><div class="k-label">供应商 / 物料</div><div class="k-value">' +
      k.supplierCount + '</div><div class="k-sub">已准入 ' + k.activeSupplier + " · 物料 " +
      k.materialCount + " 项</div></div></div>";

    html += '<div class="panel"><div class="panel-title">采购订单流程分布' +
      '<span class="panel-actions small muted">在途金额 ' + F.wan(k.openAmount) + "</span></div>" +
      '<div class="panel-body">' + F.flowBars(b.poStages || []) + "</div></div>";

    html += '<div class="panel"><div class="panel-title">近 6 个月采购金额</div><div class="panel-body">' +
      F.lineChart([{ name: "amount", data: (b.trend || []).map(function (t) { return t.amount; }) }],
        { labels: (b.trend || []).map(function (t) { return t.month.slice(5) + "月"; }) }) +
      "</div></div>";

    html += '<div class="panel"><div class="panel-title">待办与预警' +
      '<span class="panel-actions"><a class="btn sm" href="#reports">看报表</a></span></div>' +
      '<div class="panel-body flush">' +
      F.table([
        { label: "类别", render: function (r) { return F.tag(r.kind, "gray"); } },
        { label: "对象", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
        { label: "事项", render: function (r) { return F.esc(r.title); } },
        { label: "状态", render: function (r) { return F.tag(r.tag, r.level); } }
      ], b.todos || [], { empty: "没有待办，节奏不错" }) + "</div></div>";

    html += '<div class="panel"><div class="panel-title">缺料与补货建议' +
      '<span class="panel-actions small muted">共 ' + k.shortageCount + " 项</span></div>" +
      '<div class="panel-body flush">' +
      F.table([
        { label: "物料", render: function (r) { return F.esc(r.materialName) +
          '<div class="muted small mono">' + F.esc(r.materialCode) + "</div>"; } },
        { label: "现存量", num: true, render: function (r) { return F.qty(r.onHand) + " " + F.esc(r.unit); } },
        { label: "安全库存", num: true, render: function (r) { return F.qty(r.safetyStock); } },
        { label: "建议补货", num: true, render: function (r) { return '<b class="up">' + F.qty(r.gap) + "</b>"; } },
        { label: "状态", render: function (r) { return F.tag(r.state); } }
      ], b.shortages || [], { empty: "库存健康，暂无缺料" }) + "</div></div>";

    document.getElementById("view").innerHTML = html;

    var supList = (b.topSuppliers || []).map(function (s) {
      return '<div class="side-kv"><span>' + F.esc(String(s.name).slice(0, 10)) + "</span><b>" +
        F.wan(s.amount) + "</b></div>";
    }).join("");
    F.setSide(
      '<div class="side-block"><div class="hd">本月快照</div><div class="bd">' +
      F.kv("本月到货", '<span class="up">' + F.wan(k.monthReceive) + "</span>") +
      F.kv("在途采购", F.wan(k.openAmount)) +
      F.kv("库存金额", F.wan(k.stockValue)) +
      F.kv("逾期应付", '<span class="up">' + F.wan(k.overduePayable) + "</span>") +
      "</div></div>" +
      '<div class="side-block"><div class="hd">采购额 TOP 供应商</div><div class="bd">' +
      (supList || '<div class="muted small">暂无数据</div>') + "</div></div>" +
      '<div class="side-block"><div class="hd">资质预警</div><div class="bd">' +
      ((b.qualWarn || []).length ? (b.qualWarn || []).map(function (q) {
        return '<div class="side-kv"><span>' + F.esc(String(q.supplierName).slice(0, 9)) + "</span><b>" +
          F.tag(q.state) + "</b></div>";
      }).join("") : '<div class="muted small">资质均在有效期内</div>') + "</div></div>" +
      '<div class="side-block"><div class="hd">业务规则</div><div class="bd small muted" style="line-height:1.9">' +
      (b.rules || []).map(function (r) {
        return (r.enabled ? "● " : "○ ") + F.esc(r.name) + "：" + r.value + F.esc(r.unit || "") +
          (r.enabled ? "" : "（停用）");
      }).join("<br>") + "</div></div>");
    F.setStatus("供应链驾驶舱 · 数据截至 " + b.today);
  });

  /* ---------------------------------------------------------- 设置 */
  F.register("settings", function () {
    F.api("GET", "/api/settings").then(function (d) {
      var role = localStorage.getItem("fq_role") || "";
      var html = '<div class="panel"><div class="panel-title">业务规则' +
        (role === "admin" ? '<span class="panel-actions small muted">管理员可启停与调整阈值</span>' : "") +
        "</div><div class='panel-body flush'>" +
        F.table([
          { label: "规则", render: function (r) { return F.esc(r.name) + ' <span class="muted small mono">' +
            F.esc(r.code) + "</span>"; } },
          { label: "分类", render: function (r) { return F.tag(r.category, "gray"); } },
          { label: "阈值", num: true, render: function (r) {
            if (role !== "admin") return r.value + F.esc(r.unit || "");
            return '<input type="number" step="any" data-rule-val="' + F.esc(r.code) +
              '" value="' + r.value + '" style="width:90px"> <span class="small muted">' +
              F.esc(r.unit || "") + "</span>";
          } },
          { label: "说明", render: function (r) { return '<span class="small muted">' + F.esc(r.remark) + "</span>"; } },
          { label: "状态", render: function (r) {
            if (role !== "admin") return r.enabled ? F.tag("启用") : F.tag("停用");
            return '<label class="small"><input type="checkbox" data-rule="' + F.esc(r.code) + '"' +
              (r.enabled ? " checked" : "") + "> 启用</label>";
          } }
        ], d.rules || []) + "</div></div>" +
        '<div class="panel"><div class="panel-title">仓网与预算</div><div class="panel-body">' +
        '<div class="small muted" style="margin-bottom:8px">仓库</div>' +
        F.table([{ label: "编码", key: "code" }, { label: "名称", key: "name" },
          { label: "地址", key: "location" }, { label: "保管人", key: "keeper" },
          { label: "说明", render: function (r) { return '<span class="small muted">' + F.esc(r.remark) + "</span>"; } }],
          d.warehouses || []) +
        '<div class="small muted" style="margin:12px 0 8px">部门采购预算</div>' +
        F.table([{ label: "期间", key: "period" }, { label: "部门", key: "dept" },
          { label: "预算", num: true, render: function (r) { return F.money(r.amount); } },
          { label: "已用", num: true, render: function (r) { return F.money(r.used); } },
          { label: "执行率", num: true, render: function (r) {
            var p = r.amount ? r.used / r.amount : 0;
            return (p > 1 ? '<b class="up">' : "") + F.pct(p, 1) + (p > 1 ? "</b>" : "");
          } },
          { label: "备注", render: function (r) { return '<span class="small muted">' + F.esc(r.remark) + "</span>"; } }],
          d.budgets || []) +
        "</div></div>" +
        '<div class="panel"><div class="panel-title">用户与角色</div><div class="panel-body flush">' +
        F.table([{ label: "账号", key: "username" }, { label: "姓名", key: "display_name" },
          { label: "角色", render: function (r) { return F.tag(r.role, "gray"); } },
          { label: "部门", key: "dept_code" }, { label: "手机", key: "phone" }], d.users || []) +
        "</div></div>";
      document.getElementById("view").innerHTML = html;
      document.querySelectorAll("[data-rule]").forEach(function (cb) {
        cb.addEventListener("change", function () {
          var code = cb.getAttribute("data-rule");
          F.api("PUT", "/api/rules/" + encodeURIComponent(code), { enabled: cb.checked })
            .then(function () { F.toast("规则已" + (cb.checked ? "启用" : "停用") + "：" + code, "ok"); })
            .catch(function (e) { cb.checked = !cb.checked; F.toast(e.message, "err"); });
        });
      });
      document.querySelectorAll("[data-rule-val]").forEach(function (inp) {
        inp.addEventListener("change", function () {
          var code = inp.getAttribute("data-rule-val");
          F.api("PUT", "/api/rules/" + encodeURIComponent(code), { value: Number(inp.value) })
            .then(function () { F.toast("阈值已更新：" + code + " = " + inp.value, "ok"); })
            .catch(function (e) { F.toast(e.message, "err"); });
        });
      });
      F.setStatus("基础设置 · " + (d.rules || []).length + " 条业务规则");
      F.setSide('<div class="side-block"><div class="hd">当前登录</div><div class="bd">' +
        F.kv("账号", F.esc(localStorage.getItem("fq_user") || "")) +
        F.kv("姓名", F.esc(localStorage.getItem("fq_name") || "")) +
        F.kv("角色", F.esc(localStorage.getItem("fq_role_label") || "")) +
        "</div></div>" +
        '<div class="side-block"><div class="hd">规则口径提示</div><div class="bd small muted" style="line-height:1.9">' +
        "规则调整立即生效并写入操作日志：三单匹配容差影响结算判定，请购免审批金额影响提交路径，" +
        "资质与效期预警天数影响驾驶舱预警清单。</div></div>");
    });
  });

  /* ---------------------------------------------------------- 日志 */
  F.register("logs", function () {
    F.api("GET", "/api/logs").then(function (list) {
      document.getElementById("view").innerHTML =
        '<div class="panel"><div class="panel-title">操作日志' +
        '<span class="panel-actions small muted">最近 200 条</span></div><div class="panel-body flush">' +
        F.table([
          { label: "时间", render: function (r) { return '<span class="small muted">' + F.esc(r.created_at) + "</span>"; } },
          { label: "操作员", key: "username" },
          { label: "动作", render: function (r) { return F.tag(r.action, "blue"); } },
          { label: "详情", render: function (r) { return '<span class="small">' + F.esc(r.detail || "—") + "</span>"; } }
        ], list, { empty: "暂无日志" }) + "</div></div>";
      F.setStatus("操作日志 · " + list.length + " 条");
    });
  });

  /* ---------------------------------------------------------- 启动 */
  function boot() {
    if (!localStorage.getItem(TOKEN_KEY)) {
      location.href = "./login.html";
      return;
    }
    var lg = document.getElementById("btnLogout");
    if (lg) {
      lg.addEventListener("click", function () {
        F.api("POST", "/api/auth/logout", {}).catch(function () {}).then(function () {
          localStorage.removeItem(TOKEN_KEY);
          localStorage.removeItem("fq_user");
          location.href = "./login.html";
        });
      });
    }
    var foot = document.getElementById("opFoot");
    if (foot) {
      foot.textContent = "操作员：" + (localStorage.getItem("fq_name") || "") +
        "（" + (localStorage.getItem("fq_role_label") || "") + "）";
    }
    F.reload().then(function () {
      window.addEventListener("hashchange", render);
      if (!location.hash) location.hash = "dashboard";
      render();
      F.setStatus("系统就绪 · 演示数据为确定性生成");
    }).catch(function (e) {
      F.toast("初始化失败：" + e.message, "err");
    });
  }

  F.reload = function () {
    return F.api("GET", "/api/bootstrap").then(function (d) {
      F.state.boot = d;
      var a = document.getElementById("pipeLabel");
      if (a) a.textContent = "在途采购：" + F.wan(d.kpi.openAmount);
      var r = document.getElementById("wonLabel");
      if (r) r.textContent = "本月到货：" + F.wan(d.kpi.monthReceive);
      localStorage.setItem("fq_role", d.user.role);
      return d;
    });
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})(window, document);

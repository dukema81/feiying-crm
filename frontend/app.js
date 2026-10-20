/* 飞鹰 CRM · 前端框架、销售驾驶舱、基础设置与日志（原生 JS，零依赖） */
(function (window, document) {
  "use strict";

  var F = window.F = {};
  var TOKEN_KEY = "fy_token";

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

  var TAGS = {
    "待分配": "gray", "跟进中": "blue", "已转客户": "green", "无效": "gray", "公海": "gold",
    "初步接触": "gray", "需求确认": "blue", "方案报价": "gold", "商务谈判": "gold",
    "赢单": "green", "输单": "red", "进行中": "blue", "搁置": "gray",
    "草稿": "gray", "待审批": "gold", "已批准": "green", "已驳回": "red", "已发送": "blue",
    "已接受": "green", "已失效": "gray", "待签署": "gold", "已签署": "blue", "执行中": "blue",
    "已完成": "green", "已终止": "red", "待受理": "gold", "处理中": "blue", "待确认": "gold",
    "已解决": "green", "已关闭": "gray", "未收": "gold", "部分收款": "blue", "已收": "green",
    "逾期": "red", "部分逾期": "red", "正常": "green", "临期": "gold", "超时": "red",
    "活跃": "green", "沉睡": "gold", "流失": "red", "启用": "green", "停用": "gray", "吊销": "red",
    "优质": "green", "健康": "blue", "待经营": "gold", "流失风险": "red",
    "进行中2": "blue"
  };
  F.tag = function (s, cls) {
    return '<span class="tag ' + (cls || TAGS[s] || "gray") + '">' + F.esc(s) + "</span>";
  };
  F.scoreBadge = function (score) {
    var s = Number(score || 0);
    var cls = s >= 80 ? "green" : (s >= 60 ? "blue" : (s >= 40 ? "gold" : "red"));
    return '<span class="score ' + cls + '">' + s.toFixed(0) + "</span>";
  };
  F.slaTag = function (state) {
    var cls = state === "超时" ? "red" : (state === "临期" ? "gold" : (state === "已完成" ? "green" : "blue"));
    return '<span class="tag ' + cls + '">' + F.esc(state) + "</span>";
  };
  F.stagePill = function (stage, idx) {
    return '<span class="pill s' + (idx === undefined ? 0 : idx) + '">' + F.esc(stage) + "</span>";
  };

  /* ---------------------------------------------------------- 请求 */
  F.raw = function (method, path, body, headers) {
    var h = { "Content-Type": "application/json" };
    var tk = localStorage.getItem(TOKEN_KEY);
    if (tk) { h.Authorization = "Bearer " + tk; h["X-Fy-Token"] = tk; }
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
    F._toastUntil = Date.now() + 6000;   // 6 秒内不让页面摘要覆盖掉操作结果
    el.style.color = kind === "err" ? "#ffb3a7" : (kind === "ok" ? "#9ee6b8" : "");
    clearTimeout(F._t);
    F._t = setTimeout(function () { el.style.color = ""; }, 8000);
  };
  F.setStatus = function (t) {
    var el = document.getElementById("statusMsg");
    if (!el) return;
    if (F._toastUntil && Date.now() < F._toastUntil) return;   // 正在展示操作结果，摘要让位
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
    { grp: "营销获客", items: [["dashboard", "销售驾驶舱"], ["leads", "线索池"], ["campaigns", "市场活动"]] },
    { grp: "客户经营", items: [["customers", "客户档案"], ["opportunities", "商机看板"],
      ["activities", "跟进记录"]] },
    { grp: "交易与回款", items: [["quotes", "报价管理"], ["contracts", "合同管理"],
      ["payments", "回款管理"]] },
    { grp: "客户服务", items: [["tickets", "服务工单"]] },
    { grp: "分析", items: [["reports", "报表分析"]] },
    { grp: "系统", items: [["integration", "集成中心"], ["settings", "基础设置"], ["logs", "操作日志"]] }
  ];

  var MENU = TREE.map(function (g) { return [g.grp, g.items.map(function (i) { return i[0]; })]; });

  var TITLE = {
    dashboard: "销售驾驶舱", leads: "线索池", campaigns: "市场活动", customers: "客户档案",
    opportunities: "商机看板", activities: "跟进记录", quotes: "报价管理", contracts: "合同管理",
    payments: "回款管理", tickets: "服务工单", reports: "报表分析", integration: "集成中心",
    settings: "基础设置", logs: "操作日志"
  };
  F.TITLE = TITLE;

  function paintNav(route) {
    var tree = document.getElementById("tree");
    var boot = F.state.boot || {};
    var todo = (boot.todos || []).length;
    var badgeFor = { dashboard: todo, leads: (boot.kpi || {}).leadCount || 0,
      tickets: (boot.kpi || {}).ticketOverdue || 0, payments: (boot.kpi || {}).overdueCount || 0 };
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
      '<span class="muted small">飞鹰 CRM / ' + F.esc(TITLE[route] || route) + "</span>";
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
    var colors = opts.colors || ["#1f7a8c", "#c8963e"];
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

  // 漏斗条：按金额占比画横向梯形，右侧带转化率
  F.funnelBars = function (stages, conversion) {
    var max = Math.max.apply(null, stages.map(function (s) { return s.amount; }).concat([1]));
    return '<div class="funnel">' + stages.map(function (s, i) {
      var w = Math.max(8, Math.round(s.amount / max * 100));
      var conv = (conversion || []).filter(function (c) { return c.to === s.stage; })[0];
      return '<div class="fn-row"><div class="fn-name">' + F.esc(s.stage) +
        '<span class="muted small"> ' + F.pct(s.prob, 0) + "</span></div>" +
        '<div class="fn-bar"><i style="width:' + w + '%"></i></div>' +
        '<div class="fn-val">' + F.wan(s.amount) + ' <span class="muted small">' + s.count + " 个</span></div>" +
        '<div class="fn-conv">' + (conv ? "↑ " + F.pct(conv.rate, 0) : "—") + "</div></div>";
    }).join("") + "</div>";
  };

  F.empty = function (text) {
    return '<div class="empty-hint">' + F.esc(text || "暂无数据") + "</div>";
  };

  /* ---------------------------------------------------------- 驾驶舱 */
  F.register("dashboard", function () {
    var b = F.state.boot;
    if (!b) return;
    var k = b.kpi;
    var html = '<div class="kpi-grid six">' +
      '<div class="kpi"><div class="k-label">在谈商机（加权）</div><div class="k-value">' +
      F.wan(k.weighted) + '</div><div class="k-sub">' + k.openCount + " 个 · 全额 " + F.wan(k.openAmount) + "</div></div>" +
      '<div class="kpi green"><div class="k-label">本月签约</div><div class="k-value">' +
      F.wan(k.monthWonAmount) + '</div><div class="k-sub">' + k.monthWonCount + " 单 · 累计 " + F.wan(k.wonAmount) + "</div></div>" +
      '<div class="kpi"><div class="k-label">赢单率</div><div class="k-value">' +
      F.pct(k.winRate, 1) + '</div><div class="k-sub">客单价 ' + F.wan(k.avgDeal) + "</div></div>" +
      '<div class="kpi red"><div class="k-label">逾期应收</div><div class="k-value">' +
      F.wan(k.overdueAmount) + '</div><div class="k-sub">' + k.overdueCount + " 期未收</div></div>" +
      '<div class="kpi gold"><div class="k-label">待处理工单</div><div class="k-value">' +
      k.ticketOpen + '</div><div class="k-sub">其中超时 ' + k.ticketOverdue + " 张</div></div>" +
      '<div class="kpi"><div class="k-label">客户 / 在跟线索</div><div class="k-value">' +
      k.customerCount + '</div><div class="k-sub">线索 ' + k.leadCount + " 条</div></div></div>";

    html += '<div class="panel"><div class="panel-title">销售漏斗（按金额）' +
      '<span class="panel-actions small muted">加权金额 ' + F.wan(k.weighted) + "</span></div>" +
      '<div class="panel-body">' + F.funnelBars(b.funnel.stages) + "</div></div>";

    html += '<div class="panel"><div class="panel-title">近 6 个月签约趋势</div><div class="panel-body">' +
      F.lineChart([{ name: "won", data: (b.trend || []).map(function (t) { return t.amount; }) }],
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

    html += '<div class="panel"><div class="panel-title">我的在谈商机</div><div class="panel-body flush">' +
      F.table([
        { label: "商机", render: function (r) { return F.esc(r.name) + '<div class="muted small">' +
          F.esc(r.customerName) + "</div>"; } },
        { label: "阶段", render: function (r) { return F.tag(r.stage); } },
        { label: "金额", num: true, render: function (r) { return F.wan(r.amount); } },
        { label: "加权", num: true, render: function (r) { return F.wan(r.weighted); } },
        { label: "预计结单", render: function (r) {
          return (r.overdue ? '<b class="up">' : "") + F.esc(r.expectCloseDate) + (r.overdue ? "（延期）</b>" : "");
        } }
      ], b.myOpps || [], { empty: "暂无在谈商机" }) + "</div></div>";

    document.getElementById("view").innerHTML = html;

    F.setSide(
      '<div class="side-block"><div class="hd">本月快照</div><div class="bd">' +
      '<div class="side-kv"><span>本月签约</span><b class="up">' + F.wan(k.monthWonAmount) + "</b></div>" +
      '<div class="side-kv"><span>在谈（全额）</span><b>' + F.wan(k.openAmount) + "</b></div>" +
      '<div class="side-kv"><span>累计回款</span><b>' + F.wan(k.paidTotal) + "</b></div>" +
      '<div class="side-kv"><span>合同总额</span><b>' + F.wan(k.contractAmount) + "</b></div>" +
      "</div></div>" +
      '<div class="side-block"><div class="hd">签约 TOP 客户</div><div class="bd">' +
      (b.topCustomers || []).map(function (c) {
        return '<div class="side-kv"><span>' + F.esc(c.name.slice(0, 9)) + "</span><b>" +
          F.wan(c.amount) + "</b></div>";
      }).join("") + "</div></div>" +
      '<div class="side-block"><div class="hd">待领取线索</div><div class="bd">' +
      (b.myLeads || []).slice(0, 5).map(function (l) {
        return '<div class="side-kv"><span>' + F.esc(l.name.slice(0, 9)) + "</span><b>" +
          F.tag(l.status) + "</b></div>";
      }).join("") + "</div></div>" +
      '<div class="side-block"><div class="hd">业务规则</div><div class="bd small muted" style="line-height:1.9">' +
      (b.rules || []).map(function (r) {
        return (r.enabled ? "● " : "○ ") + F.esc(r.name) + "：" + r.value + F.esc(r.unit || "") +
          (r.enabled ? "" : "（停用）");
      }).join("<br>") + "</div></div>");
    F.setStatus("销售驾驶舱 · 数据截至 " + b.today);
  });

  /* ---------------------------------------------------------- 设置 */
  F.register("settings", function () {
    F.api("GET", "/api/settings").then(function (d) {
      var role = localStorage.getItem("fy_role") || "";
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
        '<div class="panel"><div class="panel-title">团队与用户</div><div class="panel-body">' +
        '<div class="small muted" style="margin-bottom:8px">销售团队</div>' +
        F.table([{ label: "编码", key: "code" }, { label: "名称", key: "name" },
          { label: "区域", key: "region" }, { label: "负责人", key: "leader" },
          { label: "说明", render: function (r) { return '<span class="small muted">' + F.esc(r.remark) + "</span>"; } }],
          d.teams || []) +
        '<div class="small muted" style="margin:12px 0 8px">用户与角色</div>' +
        F.table([{ label: "账号", key: "username" }, { label: "姓名", key: "display_name" },
          { label: "角色", render: function (r) { return F.tag(r.role, "gray"); } },
          { label: "团队", key: "team_code" }, { label: "手机", key: "phone" }], d.users || []) +
        "</div></div>" +
        '<div class="panel"><div class="panel-title">销售目标</div><div class="panel-body flush">' +
        F.table([{ label: "期间", key: "period" }, { label: "负责人", key: "owner" },
          { label: "目标额", num: true, render: function (r) { return F.money(r.amount); } },
          { label: "备注", key: "remark" }], d.targets || []) + "</div></div>";
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
        '<div class="side-kv"><span>账号</span><b>' + F.esc(localStorage.getItem("fy_user") || "") + "</b></div>" +
        '<div class="side-kv"><span>姓名</span><b>' + F.esc(localStorage.getItem("fy_name") || "") + "</b></div>" +
        '<div class="side-kv"><span>角色</span><b>' + F.esc(localStorage.getItem("fy_role_label") || "") + "</b></div>" +
        "</div></div>" +
        '<div class="side-block"><div class="hd">规则口径提示</div><div class="bd small muted" style="line-height:1.9">' +
        "规则调整立即生效并写入操作日志；查重线、折扣审批线改动会影响新建单据的校验，已在途单据不受影响。</div></div>");
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
          localStorage.removeItem("fy_user");
          location.href = "./login.html";
        });
      });
    }
    var foot = document.getElementById("opFoot");
    if (foot) {
      foot.textContent = "操作员：" + (localStorage.getItem("fy_name") || "") +
        "（" + (localStorage.getItem("fy_role_label") || "") + "）";
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
      if (a) a.textContent = "在谈商机：" + F.wan(d.kpi.openAmount);
      var r = document.getElementById("wonLabel");
      if (r) r.textContent = "本月签约：" + F.wan(d.kpi.monthWonAmount);
      localStorage.setItem("fy_role", d.user.role);
      return d;
    });
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})(window, document);

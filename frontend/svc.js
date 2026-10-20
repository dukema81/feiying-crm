/* 飞鹰 CRM · 服务工单、市场活动、报表分析 */
(function (window, document) {
  "use strict";
  var F = window.F;

  function me() { return (F.state.boot && F.state.boot.user) || {}; }

  /* ============================================================ 服务工单 */
  F.register("tickets", function () {
    var st = { status: "全部", priority: "全部", kw: "", overdue: false };

    function draw() {
      F.api("GET", "/api/tickets?" + F.qs({ status: st.status, priority: st.priority, kw: st.kw,
        overdue: st.overdue ? 1 : "", pageSize: 200 })).then(function (d) {
        var s = d.stats || {};
        var sla = s.sla || {};
        var chips = ["全部", "待受理", "处理中", "待确认", "已解决", "已关闭"].map(function (k) {
          return '<button class="chip ' + (st.status === k ? "on" : "") + '" data-st="' + k + '">' + k +
            "<b>" + (k === "全部" ? d.total : ((s.status || {})[k] || 0)) + "</b></button>";
        }).join("");
        var html = '<div class="kpi-grid four">' +
          '<div class="kpi red"><div class="k-label">SLA 超时</div><div class="k-value">' +
          (sla["超时"] || 0) + "</div><div class='k-sub'>临期 " + (sla["临期"] || 0) + " 张</div></div>" +
          '<div class="kpi gold"><div class="k-label">待受理</div><div class="k-value">' +
          ((s.status || {})["待受理"] || 0) + "</div></div>" +
          '<div class="kpi"><div class="k-label">处理中</div><div class="k-value">' +
          ((s.status || {})["处理中"] || 0) + "</div></div>" +
          '<div class="kpi green"><div class="k-label">平均满意度</div><div class="k-value">' +
          (d.avgSatisfaction ? d.avgSatisfaction.toFixed(1) : "—") + '<span class="small muted"> / 5</span></div></div>' +
          "</div>" +
          '<div class="panel"><div class="panel-title">服务工单' +
          '<span class="panel-actions">' +
          '<input id="tkKw" type="text" placeholder="工单号 / 标题 / 客户" value="' + F.esc(st.kw) + '" style="width:180px">' +
          '<select id="tkPri">' + ["全部", "P1", "P2", "P3"].map(function (p) {
            return '<option' + (p === st.priority ? " selected" : "") + ">" + p + "</option>";
          }).join("") + "</select>" +
          '<label class="small"><input type="checkbox" id="tkOver"' + (st.overdue ? " checked" : "") +
          "> 只看超时</label>" +
          '<button class="btn sm" id="tkSearch">查询</button>' +
          '<button class="btn sm primary" id="tkNew">+ 新建工单</button></span></div>' +
          '<div class="panel-body"><div class="chips">' + chips + "</div></div>" +
          '<div class="panel-body flush">' +
          F.table([
            { label: "工单号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
            { label: "客户 / 标题", render: function (r) { return F.esc(r.customerName) +
              '<div class="muted small">' + F.esc(r.title) + "</div>"; } },
            { label: "类别", render: function (r) { return F.tag(r.category, "gray"); } },
            { label: "优先级", render: function (r) {
              return F.tag(r.priority, r.priority === "P1" ? "red" : (r.priority === "P2" ? "gold" : "gray")); } },
            { label: "状态", render: function (r) { return F.tag(r.status); } },
            { label: "SLA", render: function (r) { return F.slaTag(r.slaState); } },
            { label: "剩余", num: true, render: function (r) {
              if (r.slaState === "已完成") return "—";
              var h = r.slaLeftHours;
              return '<b class="' + (h < 0 ? "up" : (h < 2 ? "flat" : "")) + '">' +
                (h < 0 ? "超 " + Math.abs(h).toFixed(1) : h.toFixed(1)) + " h</b>";
            } },
            { label: "负责人", render: function (r) { return F.esc(r.ownerName || "—"); } },
            { label: "创建", render: function (r) { return '<span class="small muted">' +
              F.esc((r.createdAt || "").slice(5, 16)) + "</span>"; } }
          ], d.list, { click: function (r) { return r.no; }, empty: "暂无工单" }) + "</div></div>";
        document.getElementById("view").innerHTML = html;
        document.getElementById("tkSearch").addEventListener("click", function () {
          st.kw = document.getElementById("tkKw").value.trim();
          st.priority = document.getElementById("tkPri").value;
          st.overdue = document.getElementById("tkOver").checked;
          draw();
        });
        document.getElementById("tkNew").addEventListener("click", newTicket);
        document.querySelectorAll("[data-st]").forEach(function (b) {
          b.addEventListener("click", function () { st.status = b.getAttribute("data-st"); draw(); });
        });
        F.bindRows(document, openTicket);
        F.setStatus("服务工单 · " + d.total + " 张 · 超时 " + (sla["超时"] || 0) + " 张");
        F.setSide('<div class="side-block"><div class="hd">SLA 口径</div><div class="bd">' +
          '<div class="side-kv"><span>P1 系统不可用</span><b>4 小时</b></div>' +
          '<div class="side-kv"><span>P2 功能异常</span><b>8 小时</b></div>' +
          '<div class="side-kv"><span>P3 咨询/需求</span><b>24 小时</b></div>' +
          "</div></div>" +
          '<div class="side-block"><div class="hd">优先级分布</div><div class="bd">' +
          Object.keys(s.priority || {}).sort().map(function (k) {
            return '<div class="side-kv"><span>' + k + "</span><b>" + s.priority[k] + "</b></div>";
          }).join("") + "</div></div>");
      });
    }

    function newTicket() {
      F.api("GET", "/api/customers?pageSize=300").then(function (cs) {
        var opts = (cs.list || []).map(function (c) {
          return '<option value="' + F.esc(c.code) + '">' + F.esc(c.name) + "</option>";
        }).join("");
        var body = '<div class="form-grid">' +
          '<label>客户 *</label><select id="tkCust">' + opts + "</select>" +
          '<label>标题 *</label><input id="tkTitle" type="text" placeholder="如 客户数据导入报错">' +
          '<label>类别</label><select id="tkCat"><option>故障</option><option>咨询</option>' +
          "<option>投诉</option><option>需求</option></select>" +
          '<label>优先级</label><select id="tkP"><option>P3</option><option selected>P2</option>' +
          "<option>P1</option></select>" +
          "</div>" +
          '<div class="form-row" style="margin-top:8px"><label>问题描述</label></div>' +
          '<textarea id="tkDesc" rows="3" style="width:100%" placeholder="现象、影响范围、复现步骤"></textarea>' +
          '<div class="small muted" style="margin-top:8px">提交后按优先级自动计算 SLA 解决时限，超时会进入预警。</div>';
        F.dialog("新建工单", body, '<button class="btn" data-close14="1">取消</button>' +
          '<button class="btn primary" id="tkSave">提交</button>');
        document.querySelector("[data-close14]").addEventListener("click", F.closeDialog);
        document.getElementById("tkSave").addEventListener("click", function () {
          F.api("POST", "/api/tickets", {
            customerCode: document.getElementById("tkCust").value,
            title: document.getElementById("tkTitle").value.trim(),
            category: document.getElementById("tkCat").value,
            priority: document.getElementById("tkP").value,
            description: document.getElementById("tkDesc").value.trim()
          }).then(function (r) {
            F.closeDialog();
            F.toast("工单已创建：" + r.no + "，SLA 截止 " + r.resolveDue, "ok");
            draw(); F.reload();
          }).catch(function (e) { F.toast(e.message, "err"); });
        });
      });
    }

    function openTicket(no) {
      F.api("GET", "/api/tickets/" + encodeURIComponent(no)).then(function (d) {
        var logs = (d.logs || []).map(function (l) {
          return '<div class="tl-item"><span class="tl-time">' + F.esc(l.created_at) + "</span>" +
            F.tag(l.action, "blue") + ' <span>' + F.esc(l.content) + "</span>" +
            '<span class="small muted"> · ' + F.esc(l.operator) + "</span></div>";
        }).join("");
        var html = '<div class="detail-head"><div><div class="dh-title">' + F.esc(d.title) + "</div>" +
          '<div class="muted small">' + F.esc(d.no) + " · " + F.esc(d.customerName) + " · " +
          F.esc(d.category) + "</div></div><div class='dh-tags'>" + F.tag(d.status) +
          F.tag(d.priority, d.priority === "P1" ? "red" : "gold") + F.slaTag(d.slaState) + "</div></div>" +
          '<div class="kpi-grid four" style="margin:10px 0">' +
          '<div class="kpi"><div class="k-label">受理时限</div><div class="k-value" style="font-size:14px">' +
          F.esc(d.responseDue) + "</div></div>" +
          '<div class="kpi gold"><div class="k-label">解决时限</div><div class="k-value" style="font-size:14px">' +
          F.esc(d.resolveDue) + "</div></div>" +
          '<div class="kpi ' + (d.slaLeftHours < 0 ? "red" : "green") + '"><div class="k-label">剩余</div>' +
          '<div class="k-value" style="font-size:16px">' +
          (d.slaState === "已完成" ? "已完成" : d.slaLeftHours.toFixed(1) + " h") + "</div></div>" +
          '<div class="kpi"><div class="k-label">满意度</div><div class="k-value" style="font-size:16px">' +
          (d.satisfaction || "—") + "</div></div></div>" +
          '<div class="note">' + F.esc(d.description || "未填写描述") + "</div>" +
          (d.resolution ? '<div class="ok-box">处理结论：' + F.esc(d.resolution) + "</div>" : "") +
          '<div class="section-title">处理轨迹</div><div class="timeline">' + (logs || F.empty("暂无")) + "</div>";
        var foot = '<button class="btn" data-close15="1">关闭</button>' +
          '<button class="btn" id="tkComment">回复</button>';
        if (d.status === "待受理") foot += '<button class="btn primary" id="tkAccept">受理</button>';
        if (d.status === "处理中" || d.status === "待受理") {
          foot += '<button class="btn primary" id="tkResolve">解决</button>';
        }
        if (d.status === "已解决" || d.status === "待确认") {
          foot += '<button class="btn primary" id="tkClose">关闭并评价</button>';
        }
        F.dialog("工单 " + d.no, html, foot);
        document.querySelector("[data-close15]").addEventListener("click", F.closeDialog);
        function post(action, payload, ok) {
          F.api("POST", "/api/tickets/" + d.no + "/" + action, payload || {}).then(function () {
            F.closeDialog(); F.toast(ok, "ok"); draw(); F.reload();
          }).catch(function (e) { F.toast(e.message, "err"); });
        }
        var a = document.getElementById("tkAccept");
        if (a) a.addEventListener("click", function () { post("accept", { comment: "已受理" }, "已受理"); });
        var rs = document.getElementById("tkResolve");
        if (rs) rs.addEventListener("click", function () {
          var txt = window.prompt("处理结论（必填）", "已定位原因并修复，请客户验证");
          if (!txt) return;
          post("resolve", { resolution: txt }, "工单已解决");
        });
        var cl = document.getElementById("tkClose");
        if (cl) cl.addEventListener("click", function () {
          var sat = window.prompt("客户满意度（1-5）", "5");
          if (sat === null) return;
          post("close", { satisfaction: Number(sat) }, "工单已关闭");
        });
        document.getElementById("tkComment").addEventListener("click", function () {
          var txt = window.prompt("回复内容", "已收到，正在排查");
          if (!txt) return;
          post("comment", { content: txt }, "已回复");
        });
      });
    }

    draw();
  });

  /* ============================================================ 市场活动 */
  F.register("campaigns", function () {
    function draw() {
      F.api("GET", "/api/campaigns").then(function (d) {
        var totalCost = (d.list || []).reduce(function (a, r) { return a + r.cost; }, 0);
        var totalWon = (d.list || []).reduce(function (a, r) { return a + r.wonAmount; }, 0);
        var totalLeads = (d.list || []).reduce(function (a, r) { return a + r.leads; }, 0);
        var html = '<div class="kpi-grid four">' +
          '<div class="kpi"><div class="k-label">市场投入</div><div class="k-value">' + F.wan(totalCost) + "</div></div>" +
          '<div class="kpi green"><div class="k-label">归因签约额</div><div class="k-value">' + F.wan(totalWon) + "</div></div>" +
          '<div class="kpi gold"><div class="k-label">整体 ROI</div><div class="k-value">' +
          (totalCost ? ((totalWon - totalCost) / totalCost * 100).toFixed(0) + "%" : "—") + "</div></div>" +
          '<div class="kpi"><div class="k-label">线索 / 单线索成本</div><div class="k-value">' +
          totalLeads + '<span class="small muted"> / ' + (totalLeads ? F.num(totalCost / totalLeads, 0) : "—") +
          " 元</span></div></div></div>" +
          '<div class="panel"><div class="panel-title">市场活动与投入产出' +
          '<span class="panel-actions"><button class="btn sm primary" id="cpNew">+ 新建活动</button></span></div>' +
          '<div class="panel-body flush">' +
          F.table([
            { label: "活动", render: function (r) { return F.esc(r.name) + '<div class="muted small mono">' +
              F.esc(r.code) + "</div>"; } },
            { label: "类型", render: function (r) { return F.tag(r.kind, "gray"); } },
            { label: "投放周期", render: function (r) { return '<span class="small">' + F.esc(r.startDate) +
              " ~ " + F.esc(r.endDate) + "</span>"; } },
            { label: "预算", num: true, render: function (r) { return F.wan(r.budget); } },
            { label: "实际投入", num: true, render: function (r) { return F.wan(r.cost); } },
            { label: "预算执行", render: function (r) {
              return '<span class="progress"><i style="width:' + Math.round(r.budgetUsage * 100) + '%"></i></span> ' +
                F.pct(r.budgetUsage, 0); } },
            { label: "线索", num: true, render: function (r) { return r.leads; } },
            { label: "单线索成本", num: true, render: function (r) { return F.num(r.cpl, 0); } },
            { label: "归因签约", num: true, render: function (r) { return F.wan(r.wonAmount); } },
            { label: "ROI", num: true, render: function (r) {
              return '<b class="' + (r.roi > 0 ? "down" : "up") + '">' + (r.roi * 100).toFixed(0) + "%</b>"; } },
            { label: "状态", render: function (r) { return F.tag(r.status); } }
          ], d.list, { empty: "暂无市场活动" }) + "</div></div>" +
          '<div class="panel"><div class="panel-title">投入产出对比</div><div class="panel-body">' +
          F.barChart((d.list || []).map(function (r) {
            return { label: r.code.replace("CP-2026-", ""), value: r.wonAmount,
              label2: F.wan(r.wonAmount), color: "#2b9eb3" };
          }), { height: 170 }) + "</div></div>";
        document.getElementById("view").innerHTML = html;
        document.getElementById("cpNew").addEventListener("click", function () {
          var body = '<div class="form-grid">' +
            '<label>活动名称 *</label><input id="cpName" type="text">' +
            '<label>类型</label><select id="cpKind"><option>线上投放</option><option>展会</option>' +
            "<option>内容营销</option><option>渠道合作</option><option>老客推荐</option></select>" +
            '<label>渠道</label><input id="cpChannel" type="text" value="微信公众号">' +
            '<label>预算</label><input id="cpBudget" type="number" value="50000">' +
            '<label>实际投入</label><input id="cpCost" type="number" value="0">' +
            '<label>目标线索</label><input id="cpTarget" type="number" value="60">' +
            "</div>";
          F.dialog("新建市场活动", body, '<button class="btn" data-close16="1">取消</button>' +
            '<button class="btn primary" id="cpSave">保存</button>');
          document.querySelector("[data-close16]").addEventListener("click", F.closeDialog);
          document.getElementById("cpSave").addEventListener("click", function () {
            F.api("POST", "/api/campaigns", {
              name: document.getElementById("cpName").value.trim(),
              kind: document.getElementById("cpKind").value,
              channel: document.getElementById("cpChannel").value.trim(),
              budget: Number(document.getElementById("cpBudget").value || 0),
              cost: Number(document.getElementById("cpCost").value || 0),
              targetLeads: Number(document.getElementById("cpTarget").value || 0)
            }).then(function (r) {
              F.closeDialog(); F.toast("活动已创建：" + r.code, "ok"); draw();
            }).catch(function (e) { F.toast(e.message, "err"); });
          });
        });
        F.setStatus("市场活动 · " + d.total + " 个 · 投入 " + F.wan(totalCost) +
          " · 归因签约 " + F.wan(totalWon));
      });
    }
    draw();
  });

  /* ============================================================ 报表 */
  F.register("reports", function () {
    var cur = "funnel";
    var TABS = [["funnel", "销售漏斗"], ["performance", "业绩排行"], ["source", "来源转化"],
      ["forecast", "销售预测"], ["aging", "应收账龄"], ["service", "服务分析"]];

    function draw() {
      F.api("GET", "/api/reports").then(function (d) {
        var html = '<div class="tabs" id="rTabs">' + TABS.map(function (t) {
          return '<button class="' + (t[0] === cur ? "on" : "") + '" data-tab="' + t[0] + '">' + t[1] + "</button>";
        }).join("") + "</div><div id='rBody'></div>";
        document.getElementById("view").innerHTML = html;
        document.querySelectorAll("#rTabs button").forEach(function (b) {
          b.addEventListener("click", function () { cur = b.getAttribute("data-tab"); draw(); });
        });
        var body = document.getElementById("rBody");
        var f = d.funnel;
        if (cur === "funnel") {
          body.innerHTML = '<div class="kpi-grid four">' +
            '<div class="kpi"><div class="k-label">在谈金额</div><div class="k-value">' + F.wan(f.openAmount) + "</div></div>" +
            '<div class="kpi gold"><div class="k-label">加权预测</div><div class="k-value">' +
            F.wan(f.stages.reduce(function (a, s) { return a + s.weighted; }, 0)) + "</div></div>" +
            '<div class="kpi green"><div class="k-label">赢单率</div><div class="k-value">' + F.pct(f.winRate, 1) + "</div></div>" +
            '<div class="kpi"><div class="k-label">平均客单</div><div class="k-value">' + F.wan(f.avgDeal) + "</div></div></div>" +
            '<div class="panel"><div class="panel-title">阶段漏斗与相邻转化</div><div class="panel-body">' +
            F.funnelBars(f.stages, f.conversion) + "</div></div>" +
            '<div class="panel"><div class="panel-title">各阶段金额分布</div><div class="panel-body">' +
            F.barChart(f.stages.map(function (s) {
              return { label: s.stage, value: s.amount, label2: F.wan(s.amount), color: "#2b9eb3" };
            }), { height: 170 }) + "</div></div>" +
            '<div class="panel"><div class="panel-title">负责人漏斗' +
            '<span class="panel-actions small muted">赢率预警线 ' + F.pct(f.threshold || 0.35, 0) + "</span></div>" +
            '<div class="panel-body flush">' + F.table([
              { label: "负责人", key: "ownerName" },
              { label: "在谈数", num: true, key: "count" },
              { label: "在谈金额", num: true, render: function (r) { return F.wan(r.amount); } },
              { label: "平均单产", num: true, render: function (r) {
                return F.wan(r.count ? r.amount / r.count : 0); } }
            ], f.byOwner || []) + "</div></div>";
        } else if (cur === "performance") {
          var p = d.performance;
          body.innerHTML = '<div class="kpi-grid three">' +
            '<div class="kpi"><div class="k-label">账期</div><div class="k-value" style="font-size:18px">' +
            F.esc(p.period) + "</div></div>" +
            '<div class="kpi green"><div class="k-label">目标合计</div><div class="k-value">' + F.wan(p.totalTarget) + "</div></div>" +
            '<div class="kpi gold"><div class="k-label">签约合计</div><div class="k-value">' + F.wan(p.totalWon) + "</div></div></div>" +
            '<div class="panel"><div class="panel-title">业绩排行与目标达成</div><div class="panel-body flush">' +
            F.table([
              { label: "销售", key: "ownerName" },
              { label: "目标", num: true, render: function (r) { return F.wan(r.target); } },
              { label: "签约额", num: true, render: function (r) { return F.wan(r.wonAmount); } },
              { label: "达成率", render: function (r) {
                return '<span class="progress"><i style="width:' + Math.min(100, Math.round(r.rate * 100)) +
                  '%"></i></span> ' + F.pct(r.rate, 1); } },
              { label: "单数", num: true, key: "wonCount" },
              { label: "客单价", num: true, render: function (r) { return F.wan(r.avgDeal); } },
              { label: "在谈", num: true, render: function (r) { return r.openCount + " / " + F.wan(r.openAmount); } },
              { label: "加权", num: true, render: function (r) { return F.wan(r.weighted); } },
              { label: "回款", num: true, render: function (r) { return F.wan(r.paidAmount); } }
            ], p.list, { empty: "暂无数据" }) + "</div></div>" +
            '<div class="panel"><div class="panel-title">签约额对比</div><div class="panel-body">' +
            F.barChart(p.list.map(function (r) {
              return { label: r.ownerName.slice(0, 3), value: r.wonAmount, label2: F.wan(r.wonAmount),
                color: "#1e8449" };
            }), { height: 160 }) + "</div></div>";
        } else if (cur === "source") {
          var s = d.source;
          body.innerHTML = '<div class="panel"><div class="panel-title">线索来源转化</div><div class="panel-body flush">' +
            F.table([
              { label: "来源", render: function (r) { return F.tag(r.source, "gray"); } },
              { label: "线索数", num: true, key: "leads" },
              { label: "转客户", num: true, key: "converted" },
              { label: "转化率", render: function (r) {
                return '<span class="progress"><i style="width:' + Math.round(r.conversionRate * 100) +
                  '%"></i></span> ' + F.pct(r.conversionRate, 1); } },
              { label: "赢单数", num: true, key: "wonCount" },
              { label: "签约额", num: true, render: function (r) { return F.wan(r.wonAmount); } },
              { label: "平均客单", num: true, render: function (r) { return F.wan(r.avgDeal); } }
            ], s.list || []) + "</div></div>" +
            '<div class="panel"><div class="panel-title">各来源签约额</div><div class="panel-body">' +
            F.barChart((s.list || []).map(function (r) {
              return { label: r.source, value: r.wonAmount, label2: F.wan(r.wonAmount), color: "#c8963e" };
            }), { height: 170 }) + "</div></div>";
        } else if (cur === "forecast") {
          var fc = d.forecast;
          body.innerHTML = '<div class="kpi-grid three">' +
            '<div class="kpi"><div class="k-label">预测总额（全额）</div><div class="k-value">' +
            F.wan(fc.total.amount) + "</div></div>" +
            '<div class="kpi gold"><div class="k-label">加权预测</div><div class="k-value">' +
            F.wan(fc.total.weighted) + "</div></div>" +
            '<div class="kpi green"><div class="k-label">商机数</div><div class="k-value">' +
            fc.total.count + "</div></div></div>" +
            '<div class="panel"><div class="panel-title">滚动预测（加权 / 乐观 / 悲观）</div><div class="panel-body">' +
            F.lineChart([
              { name: "weighted", data: fc.months.map(function (m) { return m.weighted; }) },
              { name: "optimistic", data: fc.months.map(function (m) { return m.optimistic; }) }
            ], { labels: fc.months.map(function (m) { return m.month.slice(5) + "月"; }),
              colors: ["#1f7a8c", "#c8963e"] }) + "</div></div>" +
            '<div class="panel"><div class="panel-title">分月明细</div><div class="panel-body flush">' +
            F.table([
              { label: "月份", key: "month" },
              { label: "商机数", num: true, key: "count" },
              { label: "全额", num: true, render: function (r) { return F.money(r.amount); } },
              { label: "加权", num: true, render: function (r) { return F.money(r.weighted); } },
              { label: "悲观", num: true, render: function (r) { return F.money(r.pessimistic); } }
            ], fc.months) + "</div></div>";
        } else if (cur === "aging") {
          var ag = d.aging;
          var buckets = ag.buckets || {};
          body.innerHTML = '<div class="kpi-grid three">' +
            '<div class="kpi"><div class="k-label">未收合计</div><div class="k-value">' + F.wan(ag.totalUnpaid) + "</div></div>" +
            '<div class="kpi red"><div class="k-label">其中逾期</div><div class="k-value">' + F.wan(ag.overdue) + "</div></div>" +
            '<div class="kpi gold"><div class="k-label">逾期占比</div><div class="k-value">' +
            (ag.totalUnpaid ? F.pct(ag.overdue / ag.totalUnpaid, 1) : "—") + "</div></div></div>" +
            '<div class="panel"><div class="panel-title">账龄分布</div><div class="panel-body">' +
            '<div class="funnel-mini">' + Object.keys(buckets).map(function (k) {
              return '<div class="fm"><div class="fm-v">' + F.wan(buckets[k]) + "</div>" +
                '<div class="fm-l">' + k + "</div></div>";
            }).join("") + "</div></div></div>" +
            '<div class="panel"><div class="panel-title">逾期 TOP 客户</div><div class="panel-body flush">' +
            F.table([{ label: "客户", key: "customerName" },
              { label: "逾期金额", num: true, render: function (r) { return F.money(r.amount); } },
              { label: "期数", num: true, key: "count" }], ag.byCustomer || []) + "</div></div>";
        } else {
          var t = d.tickets;
          body.innerHTML = '<div class="kpi-grid three">' +
            '<div class="kpi green"><div class="k-label">平均满意度</div><div class="k-value">' +
            (t.avgSatisfaction ? t.avgSatisfaction.toFixed(1) : "—") + "</div></div>" +
            '<div class="kpi"><div class="k-label">平均解决时长</div><div class="k-value">' +
            (t.avgResolveHours ? t.avgResolveHours.toFixed(1) + " h" : "—") + "</div></div>" +
            '<div class="kpi gold"><div class="k-label">工单总量</div><div class="k-value">' +
            (t.byPriority || []).reduce(function (a, r) { return a + r.c; }, 0) + "</div></div></div>" +
            '<div class="panel"><div class="panel-title">按优先级 / 类别分布</div><div class="panel-body">' +
            '<div class="funnel-mini">' + (t.byPriority || []).map(function (r) {
              return '<div class="fm"><div class="fm-v">' + r.c + "</div><div class='fm-l'>" + r.priority + "</div></div>";
            }).join("") + (t.byCategory || []).map(function (r) {
              return '<div class="fm"><div class="fm-v">' + r.c + "</div><div class='fm-l'>" + r.category + "</div></div>";
            }).join("") + "</div></div></div>";
        }
        F.setStatus("报表分析 · " + (TABS.filter(function (x) { return x[0] === cur; })[0] || ["", ""])[1]);
      });
    }
    draw();
  });
})(window, document);

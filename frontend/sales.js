/* 飞鹰 CRM · 线索、客户 360、商机看板、跟进记录 */
(function (window, document) {
  "use strict";
  var F = window.F;

  function me() { return (F.state.boot && F.state.boot.user) || {}; }
  function isManager() {
    var r = me().role;
    return r === "admin" || r === "sales_director";
  }

  /* ============================================================ 线索池 */
  F.register("leads", function () {
    var st = { status: "全部", grade: "全部", kw: "" };

    function draw() {
      F.api("GET", "/api/leads?" + F.qs({ status: st.status, grade: st.grade, kw: st.kw, pageSize: 100 }))
        .then(function (d) {
          var stats = d.stats || {};
          var chips = ["全部", "待分配", "跟进中", "公海", "已转客户", "无效"].map(function (s) {
            return '<button class="chip ' + (st.status === s ? "on" : "") + '" data-st="' + s + '">' +
              s + '<b>' + (s === "全部" ? d.total : (stats[s] || 0)) + "</b></button>";
          }).join("");
          var html = '<div class="panel"><div class="panel-title">线索池' +
            '<span class="panel-actions">' +
            '<input id="fKw" type="text" placeholder="公司 / 联系人 / 手机" value="' + F.esc(st.kw) + '" style="width:190px">' +
            '<select id="fGrade">' + ["全部", "A", "B", "C"].map(function (g) {
              return '<option' + (g === st.grade ? " selected" : "") + ">" + g + "</option>";
            }).join("") + "</select>" +
            '<button class="btn sm" id="btnSearch">查询</button>' +
            '<button class="btn sm primary" id="lNew">+ 新建线索</button></span></div>' +
            '<div class="panel-body"><div class="chips">' + chips + "</div></div>" +
            '<div class="panel-body flush">' +
            F.table([
              { label: "编号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
              { label: "公司", render: function (r) { return F.esc(r.name) + '<div class="muted small">' +
                F.esc(r.contact) + " · " + F.esc(r.phone) + "</div>"; } },
              { label: "来源", render: function (r) { return F.tag(r.source, "gray"); } },
              { label: "等级", render: function (r) {
                return F.tag(r.grade, r.grade === "A" ? "red" : (r.grade === "B" ? "gold" : "gray")); } },
              { label: "预算", num: true, render: function (r) { return F.wan(r.budget); } },
              { label: "状态", render: function (r) { return F.tag(r.status); } },
              { label: "负责人", render: function (r) { return F.esc(r.ownerName || "—"); } },
              { label: "闲置", num: true, render: function (r) {
                if (r.status !== "跟进中") return "—";
                var d2 = r.idleDays === null ? "未跟进" : r.idleDays + " 天";
                return (r.idleDays !== null && r.idleDays > 20) ? '<b class="up">' + d2 + "</b>" : d2;
              } }
            ], d.list, { click: function (r) { return r.no; }, empty: "没有匹配的线索" }) +
            "</div></div>";
          document.getElementById("view").innerHTML = html;
          document.getElementById("btnSearch").addEventListener("click", function () {
            st.kw = document.getElementById("fKw").value.trim();
            st.grade = document.getElementById("fGrade").value;
            draw();
          });
          document.getElementById("fKw").addEventListener("keydown", function (e) {
            if (e.key === "Enter") document.getElementById("btnSearch").click();
          });
          document.getElementById("lNew").addEventListener("click", newLead);
          document.querySelectorAll("[data-st]").forEach(function (b) {
            b.addEventListener("click", function () { st.status = b.getAttribute("data-st"); draw(); });
          });
          F.bindRows(document, openLead);
          F.setStatus("线索池 · " + d.total + " 条（待分配 " + (d.unassigned || 0) +
            " / 公海 " + (d.poolCount || 0) + "）");
          F.setSide('<div class="side-block"><div class="hd">线索漏斗</div><div class="bd">' +
            ["待分配", "跟进中", "已转客户", "公海", "无效"].map(function (k) {
              return '<div class="side-kv"><span>' + k + "</span><b>" + (stats[k] || 0) + "</b></div>";
            }).join("") + "</div></div>" +
            '<div class="side-block"><div class="hd">规则</div><div class="bd small muted" style="line-height:1.9">' +
            "· 建单时按手机号/邮箱/公司名查重<br>· 超过 " +
            ((F.state.boot.rules || []).filter(function (r) { return r.code === "pool_days"; })[0] || {}).value +
            " 天未跟进自动回收公海<br>· 公海线索任何销售可领取</div></div>");
        });
    }

    function newLead() {
      var body = '<div class="form-grid">' +
        '<label>公司名称 *</label><input id="nName" type="text" placeholder="如 苏州某某机械有限公司">' +
        '<label>联系人</label><input id="nContact" type="text">' +
        '<label>手机号</label><input id="nPhone" type="text" placeholder="用于查重">' +
        '<label>邮箱</label><input id="nEmail" type="text">' +
        '<label>来源</label><select id="nSource">' + ["官网表单", "展会", "线上投放", "内容营销",
          "渠道合作", "老客推荐", "电话拜访"].map(function (s) { return "<option>" + s + "</option>"; }).join("") + "</select>" +
        '<label>行业</label><input id="nIndustry" type="text">' +
        '<label>区域</label><select id="nRegion">' + ["华东", "华南", "华北", "华中", "西南", "西北", "东北"]
          .map(function (s) { return "<option>" + s + "</option>"; }).join("") + "</select>" +
        '<label>预算（元）</label><input id="nBudget" type="number" value="200000">' +
        '<label>负责人</label><select id="nOwner"><option value="">（待分配）</option>' +
        (isManager() ? '<option value="liuyang">刘洋</option><option value="wangfang">王芳</option>' : "") +
        "</select></div>" +
        '<div class="form-row" style="margin-top:10px"><label>需求描述</label></div>' +
        '<textarea id="nDemand" rows="2" style="width:100%" placeholder="客户的核心诉求，便于分级与跟进"></textarea>' +
        '<div class="small muted" id="dupHint" style="margin-top:8px"></div>';
      F.dialog("新建线索", body,
        '<button class="btn" data-close2="1">取消</button><button class="btn primary" id="nSave">保存</button>');
      var dlg = document.getElementById("dialog");
      dlg.querySelector("[data-close2]").addEventListener("click", F.closeDialog);
      var phone = document.getElementById("nPhone");
      var name = document.getElementById("nName");
      function checkDup() {
        if (!phone.value && !name.value) return;
        F.api("GET", "/api/leads/check-dup?" + F.qs({ phone: phone.value, name: name.value }))
          .then(function (r) {
            var hint = document.getElementById("dupHint");
            if (!r.dups || !r.dups.length) { hint.innerHTML = '<span class="down">未发现重复</span>'; return; }
            hint.innerHTML = '<span class="up">疑似重复：' + r.dups.map(function (x) {
              return F.esc(x.name) + "（" + F.esc(x.reason) + "）";
            }).join("；") + "</span>";
          });
      }
      phone.addEventListener("blur", checkDup);
      name.addEventListener("blur", checkDup);
      document.getElementById("nSave").addEventListener("click", function () {
        var payload = {
          name: name.value.trim(), contact: document.getElementById("nContact").value.trim(),
          phone: phone.value.trim(), email: document.getElementById("nEmail").value.trim(),
          source: document.getElementById("nSource").value, industry: document.getElementById("nIndustry").value.trim(),
          region: document.getElementById("nRegion").value,
          budget: Number(document.getElementById("nBudget").value || 0),
          demand: document.getElementById("nDemand").value.trim(),
          owner: document.getElementById("nOwner").value, force: true
        };
        F.api("POST", "/api/leads", payload).then(function (r) {
          F.closeDialog();
          F.toast("线索已创建：" + r.no + "（等级 " + r.grade + "）", "ok");
          draw();
          F.reload();
        }).catch(function (e) { F.toast(e.message, "err"); });
      });
    }

    function openLead(no) {
      F.api("GET", "/api/leads/" + encodeURIComponent(no)).then(function (d) {
        var acts = (d.activities || []).map(function (a) {
          return '<div class="tl-item"><span class="tl-time">' + F.esc(a.happenAt) + "</span>" +
            F.tag(a.kind, "blue") + " <b>" + F.esc(a.subject) + "</b>" +
            '<div class="small muted">' + F.esc(a.content) + "</div></div>";
        }).join("") || F.empty("暂无跟进");
        var body = '<div class="detail-head"><div><div class="dh-title">' + F.esc(d.name) + "</div>" +
          '<div class="muted small">' + F.esc(d.no) + " · " + F.esc(d.source) + " · " +
          F.esc(d.industry || "行业未填") + " · " + F.esc(d.region || "区域未填") + "</div></div>" +
          '<div class="dh-tags">' + F.tag(d.status) + F.tag("等级 " + d.grade, "gold") + "</div></div>" +
          '<div class="kpi-grid three" style="margin:10px 0">' +
          '<div class="kpi"><div class="k-label">预算</div><div class="k-value">' + F.wan(d.budget) + "</div></div>" +
          '<div class="kpi gold"><div class="k-label">闲置天数</div><div class="k-value">' +
          (d.idleDays === null ? "—" : d.idleDays) + "</div></div>" +
          '<div class="kpi green"><div class="k-label">负责人</div><div class="k-value" style="font-size:15px">' +
          F.esc(d.ownerName || "待分配") + "</div></div></div>" +
          '<div class="form-row"><label>联系人</label>' + F.esc(d.contact || "—") +
          '<label>手机</label>' + F.esc(d.phone || "—") + '<label>邮箱</label>' + F.esc(d.email || "—") + "</div>" +
          '<div class="note">' + F.esc(d.demand || "未填写需求") + "</div>" +
          (d.dups && d.dups.length ? '<div class="warn-box">查重提示：' + d.dups.map(function (x) {
            return F.esc(x.name) + "（" + F.esc(x.reason) + "）";
          }).join("；") + "</div>" : "") +
          '<div class="section-title">跟进时间线</div><div class="timeline">' + acts + "</div>";

        var foot = '<button class="btn" data-close3="1">关闭</button>' +
          '<button class="btn" id="ldFollow">写跟进</button>';
        if (d.status === "公海") foot += '<button class="btn primary" id="ldClaim">领取线索</button>';
        if (d.status === "待分配" && isManager()) foot += '<button class="btn primary" id="ldAssign">分配</button>';
        if (d.status === "跟进中") {
          foot += '<button class="btn primary" id="ldConvert">转客户</button>' +
            '<button class="btn danger" id="ldInvalid">标记无效</button>' +
            '<button class="btn" id="ldRecycle">回收公海</button>';
        }
        F.dialog("线索 " + d.no, body, foot);
        document.querySelector("[data-close3]").addEventListener("click", F.closeDialog);
        function act(path, payload, okText) {
          F.api("POST", path, payload).then(function () {
            F.closeDialog(); F.toast(okText, "ok"); draw(); F.reload();
          }).catch(function (e) { F.toast(e.message, "err"); });
        }
        var btnClaim = document.getElementById("ldClaim");
        if (btnClaim) btnClaim.addEventListener("click", function () {
          act("/api/leads/" + d.no + "/claim", {}, "已领取，请尽快首次跟进");
        });
        var btnConvert = document.getElementById("ldConvert");
        if (btnConvert) btnConvert.addEventListener("click", function () {
          F.api("POST", "/api/leads/" + d.no + "/convert", {}).then(function (r) {
            F.closeDialog();
            F.toast("已转为客户 " + r.customerCode, "ok");
            draw(); F.reload();
            F.go("customers", { code: r.customerCode });
          }).catch(function (e) { F.toast(e.message, "err"); });
        });
        var btnInvalid = document.getElementById("ldInvalid");
        if (btnInvalid) btnInvalid.addEventListener("click", function () {
          var reason = window.prompt("请填写无效原因（必填）", "预算不足，暂无采购计划");
          if (reason === null) return;
          act("/api/leads/" + d.no + "/invalid", { reason: reason }, "已标记无效");
        });
        var btnRecycle = document.getElementById("ldRecycle");
        if (btnRecycle) btnRecycle.addEventListener("click", function () {
          act("/api/leads/" + d.no + "/recycle", { reason: "手工回收" }, "已回收到公海");
        });
        var btnAssign = document.getElementById("ldAssign");
        if (btnAssign) btnAssign.addEventListener("click", function () {
          var owner = window.prompt("分配给哪个账号？（liuyang / wangfang）", "liuyang");
          if (!owner) return;
          act("/api/leads/" + d.no + "/assign", { owner: owner }, "已分配给 " + owner);
        });
        document.getElementById("ldFollow").addEventListener("click", function () {
          F.closeDialog();
          F.followDialog("lead", d.no, draw);
        });
      });
    }

    draw();
  });

  /* ============================================================ 客户档案 */
  F.register("customers", function (params) {
    var st = { kw: "", level: "全部", status: "全部" };

    function draw() {
      F.api("GET", "/api/customers?" + F.qs({ kw: st.kw, level: st.level, status: st.status, pageSize: 200 }))
        .then(function (d) {
          var html = '<div class="panel"><div class="panel-title">客户档案' +
            '<span class="panel-actions">' +
            '<input id="cKw" type="text" placeholder="名称 / 编码 / 电话" value="' + F.esc(st.kw) + '" style="width:180px">' +
            '<select id="cLevel">' + ["全部", "A", "B", "C"].map(function (g) {
              return '<option' + (g === st.level ? " selected" : "") + ">" + g + "</option>";
            }).join("") + "</select>" +
            '<select id="cStatus">' + ["全部", "活跃", "沉睡", "流失"].map(function (g) {
              return '<option' + (g === st.status ? " selected" : "") + ">" + g + "</option>";
            }).join("") + "</select>" +
            '<button class="btn sm" id="cSearch">查询</button>' +
            '<a class="btn sm" id="cExport" href="api/export/customers.csv" target="_blank">导出 CSV</a>' +
            '<button class="btn sm primary" id="cNew">+ 新建客户</button></span></div>' +
            '<div class="panel-body flush">' +
            F.table([
              { label: "编码", render: function (r) { return '<span class="mono small">' + F.esc(r.code) + "</span>"; } },
              { label: "客户名称", render: function (r) { return F.esc(r.name) + '<div class="muted small">' +
                F.esc(r.industry) + " · " + F.esc(r.region) + "</div>"; } },
              { label: "等级", render: function (r) { return F.tag(r.level, "gold"); } },
              { label: "健康分", render: function (r) { return F.scoreBadge(r.score) + ' <span class="small muted">' +
                F.esc(r.scoreLevel) + "</span>"; } },
              { label: "在谈商机", num: true, render: function (r) {
                return r.openOpps + ' <span class="small muted">' + F.wan(r.openAmount) + "</span>"; } },
              { label: "合同额", num: true, render: function (r) { return F.wan(r.contractAmount); } },
              { label: "回款", num: true, render: function (r) { return F.wan(r.paidAmount); } },
              { label: "工单", num: true, render: function (r) {
                return r.openTickets ? '<b class="up">' + r.openTickets + "</b>" : "0"; } },
              { label: "状态", render: function (r) { return F.tag(r.status); } },
              { label: "负责人", render: function (r) { return F.esc(r.ownerName); } }
            ], d.list, { click: function (r) { return r.code; }, empty: "没有匹配的客户" }) +
            "</div></div>";
          document.getElementById("view").innerHTML = html;
          document.getElementById("cSearch").addEventListener("click", function () {
            st.kw = document.getElementById("cKw").value.trim();
            st.level = document.getElementById("cLevel").value;
            st.status = document.getElementById("cStatus").value;
            draw();
          });
          document.getElementById("cKw").addEventListener("keydown", function (e) {
            if (e.key === "Enter") document.getElementById("cSearch").click();
          });
          document.getElementById("cNew").addEventListener("click", newCustomer);
          document.getElementById("cExport").addEventListener("click", function (e) {
            e.preventDefault();
            F.api("GET", "/api/auth/me").then(function () {
              window.open("api/export/customers.csv?token=" +
                encodeURIComponent(localStorage.getItem("fy_token") || ""), "_blank");
            });
          });
          F.bindRows(document, function (code) { openCustomer(code); });
          var lv = (d.stats || {}).level || {};
          var stt = (d.stats || {}).status || {};
          F.setStatus("客户档案 · " + d.total + " 家");
          F.setSide('<div class="side-block"><div class="hd">客户结构</div><div class="bd">' +
            Object.keys(lv).sort().map(function (k) {
              return '<div class="side-kv"><span>' + k + " 级</span><b>" + lv[k] + " 家</b></div>";
            }).join("") + Object.keys(stt).map(function (k) {
              return '<div class="side-kv"><span>' + k + "</span><b>" + stt[k] + " 家</b></div>";
            }).join("") + "</div></div>" +
            '<div class="side-block"><div class="hd">健康分口径</div><div class="bd small muted" style="line-height:1.9">' +
            "跟进新鲜度 30 + 累计回款 40 + 在谈商机 20 + 满意度 10，逾期回款每笔扣 8 分。</div></div>");
          if (params && params.code) openCustomer(params.code);
        });
    }

    function newCustomer() {
      var body = '<div class="form-grid">' +
        '<label>客户名称 *</label><input id="kName" type="text">' +
        '<label>简称</label><input id="kShort" type="text">' +
        '<label>行业</label><input id="kIndustry" type="text" value="装备制造">' +
        '<label>规模</label><select id="kScale"><option>大型</option><option selected>中型</option><option>小型</option></select>' +
        '<label>区域</label><select id="kRegion">' + ["华东", "华南", "华北", "华中", "西南", "西北", "东北"]
          .map(function (s) { return "<option>" + s + "</option>"; }).join("") + "</select>" +
        '<label>等级</label><select id="kLevel"><option>A</option><option selected>B</option><option>C</option></select>' +
        '<label>来源</label><select id="kSource">' + ["老客推荐", "展会", "官网表单", "线上投放", "内容营销", "渠道合作"]
          .map(function (s) { return "<option>" + s + "</option>"; }).join("") + "</select>" +
        '<label>电话</label><input id="kPhone" type="text">' +
        '<label>授信额度</label><input id="kCredit" type="number" value="200000">' +
        "</div>";
      F.dialog("新建客户", body, '<button class="btn" data-close4="1">取消</button>' +
        '<button class="btn primary" id="kSave">保存</button>');
      document.querySelector("[data-close4]").addEventListener("click", F.closeDialog);
      document.getElementById("kSave").addEventListener("click", function () {
        F.api("POST", "/api/customers", {
          name: document.getElementById("kName").value.trim(),
          shortName: document.getElementById("kShort").value.trim(),
          industry: document.getElementById("kIndustry").value.trim(),
          scale: document.getElementById("kScale").value,
          region: document.getElementById("kRegion").value,
          level: document.getElementById("kLevel").value,
          source: document.getElementById("kSource").value,
          phone: document.getElementById("kPhone").value.trim(),
          creditLimit: Number(document.getElementById("kCredit").value || 0)
        }).then(function (r) {
          F.closeDialog(); F.toast("客户已创建：" + r.code, "ok"); draw(); F.reload();
        }).catch(function (e) { F.toast(e.message, "err"); });
      });
    }

    function openCustomer(code) {
      F.api("GET", "/api/customers/" + encodeURIComponent(code)).then(function (d) {
        var s = d.stats || {};
        var html = '<div class="detail-head"><div><div class="dh-title">' + F.esc(d.name) + "</div>" +
          '<div class="muted small">' + F.esc(d.code) + " · " + F.esc(d.industry) + " · " +
          F.esc(d.region) + " · " + F.esc(d.scale) + " · " + F.esc(d.source) + "</div></div>" +
          '<div class="dh-tags">' + F.tag(d.status) + F.tag(d.level + " 级", "gold") +
          F.scoreBadge(d.score) + "</div></div>" +
          '<div class="kpi-grid six" style="margin:10px 0">' +
          '<div class="kpi"><div class="k-label">在谈商机</div><div class="k-value" style="font-size:17px">' +
          F.wan(s.openAmount) + "</div></div>" +
          '<div class="kpi green"><div class="k-label">已签合同</div><div class="k-value" style="font-size:17px">' +
          F.wan(s.contractAmount) + "</div></div>" +
          '<div class="kpi"><div class="k-label">累计回款</div><div class="k-value" style="font-size:17px">' +
          F.wan(s.paidTotal) + "</div></div>" +
          '<div class="kpi red"><div class="k-label">逾期应收</div><div class="k-value" style="font-size:17px">' +
          F.wan(s.overdueAmount) + "</div></div>" +
          '<div class="kpi gold"><div class="k-label">未结工单</div><div class="k-value" style="font-size:17px">' +
          s.openTickets + "</div></div>" +
          '<div class="kpi"><div class="k-label">满意度</div><div class="k-value" style="font-size:17px">' +
          (s.avgSatisfaction ? s.avgSatisfaction.toFixed(1) + " / 5" : "—") + "</div></div></div>";

        html += '<div class="tabs" id="cTabs">' +
          ["联系人", "商机", "报价", "合同", "工单", "时间线"].map(function (t, i) {
            return '<button class="' + (i === 0 ? "on" : "") + '" data-tab="' + i + '">' + t + "</button>";
          }).join("") + "</div><div id='cTabBody'></div>";

        var panels = [];
        panels.push(F.table([
          { label: "姓名", key: "name" }, { label: "职务", key: "title" },
          { label: "手机", key: "phone" }, { label: "邮箱", key: "email" },
          { label: "微信", key: "wechat" },
          { label: "主联系人", render: function (r) { return r.is_primary ? F.tag("是", "green") : "—"; } }
        ], d.contacts || [], { empty: "暂无联系人" }));
        panels.push(F.table([
          { label: "商机", render: function (r) { return F.esc(r.name) + '<div class="muted small mono">' +
            F.esc(r.no) + "</div>"; } },
          { label: "阶段", render: function (r) { return F.tag(r.stage); } },
          { label: "金额", num: true, render: function (r) { return F.wan(r.amount); } },
          { label: "预计结单", key: "expectCloseDate" },
          { label: "负责人", render: function (r) { return F.esc(r.ownerName); } }
        ], d.opportunities || [], { empty: "暂无商机" }));
        panels.push(F.table([
          { label: "报价单", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
          { label: "金额", num: true, render: function (r) { return F.wan(r.amount); } },
          { label: "折扣", num: true, render: function (r) { return r.discountPct.toFixed(1) + "%"; } },
          { label: "状态", render: function (r) { return F.tag(r.status); } },
          { label: "有效期", key: "validUntil" }
        ], d.quotes || [], { empty: "暂无报价" }));
        panels.push(F.table([
          { label: "合同", render: function (r) { return F.esc(r.title) + '<div class="muted small mono">' +
            F.esc(r.no) + "</div>"; } },
          { label: "金额", num: true, render: function (r) { return F.wan(r.amount); } },
          { label: "已收", num: true, render: function (r) { return F.wan(r.paidAmount); } },
          { label: "进度", render: function (r) {
            return '<span class="progress"><i style="width:' + Math.round(r.progress * 100) + '%"></i></span> ' +
              F.pct(r.progress, 0); } },
          { label: "状态", render: function (r) { return F.tag(r.status); } }
        ], d.contracts || [], { empty: "暂无合同" }));
        panels.push(F.table([
          { label: "工单", render: function (r) { return F.esc(r.title) + '<div class="muted small mono">' +
            F.esc(r.no) + "</div>"; } },
          { label: "优先级", render: function (r) { return F.tag(r.priority, r.priority === "P1" ? "red" : "gold"); } },
          { label: "状态", render: function (r) { return F.tag(r.status); } },
          { label: "SLA", render: function (r) { return F.slaTag(r.slaState); } },
          { label: "创建", render: function (r) { return '<span class="small muted">' +
            F.esc(r.createdAt) + "</span>"; } }
        ], d.tickets || [], { empty: "暂无工单" }));
        panels.push('<div class="timeline">' + ((d.activities || []).map(function (a) {
          return '<div class="tl-item"><span class="tl-time">' + F.esc(a.happenAt) + "</span>" +
            F.tag(a.kind, "blue") + ' <b>' + F.esc(a.subject) + "</b>" +
            '<span class="small muted"> · ' + F.esc(a.ownerName) + "</span>" +
            '<div class="small muted">' + F.esc(a.content) + "</div></div>";
        }).join("") || F.empty("暂无跟进记录")) + "</div>");

        F.dialog("客户 360 · " + d.code, html,
          '<button class="btn" data-close5="1">关闭</button>' +
          '<button class="btn" id="cuFollow">写跟进</button>' +
          '<button class="btn primary" id="cuOpp">建商机</button>');
        var body = document.getElementById("cTabBody");
        function show(i) {
          body.innerHTML = panels[i];
          document.querySelectorAll("#cTabs button").forEach(function (b) {
            b.className = Number(b.getAttribute("data-tab")) === i ? "on" : "";
          });
        }
        show(0);
        document.querySelectorAll("#cTabs button").forEach(function (b) {
          b.addEventListener("click", function () { show(Number(b.getAttribute("data-tab"))); });
        });
        document.querySelector("[data-close5]").addEventListener("click", F.closeDialog);
        document.getElementById("cuFollow").addEventListener("click", function () {
          F.closeDialog(); F.followDialog("customer", d.code, draw);
        });
        document.getElementById("cuOpp").addEventListener("click", function () {
          F.closeDialog(); newOpp(d.code);
        });
      });
    }

    function newOpp(code) {
      F.api("GET", "/api/customers/" + encodeURIComponent(code)).then(function (c) {
        var body = '<div class="form-grid">' +
          '<label>客户</label><input type="text" value="' + F.esc(c.name) + '" disabled>' +
          '<label>商机名称 *</label><input id="oName" type="text" value="' + F.esc(c.shortName) + ' CRM 项目">' +
          '<label>金额 *</label><input id="oAmount" type="number" value="200000">' +
          '<label>预计结单</label><input id="oClose" type="date" value="' + F.addDays(45) + '">' +
          '<label>竞品</label><input id="oComp" type="text" placeholder="如 销售易 / 自研">' +
          '<label>决策人</label><input id="oDm" type="text" placeholder="如 王建国 信息总监">' +
          "</div>";
        F.dialog("新建商机", body, '<button class="btn" data-close6="1">取消</button>' +
          '<button class="btn primary" id="oSave">保存</button>');
        document.querySelector("[data-close6]").addEventListener("click", F.closeDialog);
        document.getElementById("oSave").addEventListener("click", function () {
          F.api("POST", "/api/opportunities", {
            name: document.getElementById("oName").value.trim(), customerCode: code,
            amount: Number(document.getElementById("oAmount").value || 0),
            expectCloseDate: document.getElementById("oClose").value,
            competitor: document.getElementById("oComp").value.trim(),
            decisionMaker: document.getElementById("oDm").value.trim()
          }).then(function (r) {
            F.closeDialog(); F.toast("商机已创建：" + r.no, "ok");
            F.go("opportunities");
          }).catch(function (e) { F.toast(e.message, "err"); });
        });
      });
    }

    draw();
  });

  /* ============================================================ 商机看板 */
  F.register("opportunities", function () {
    var st = { view: "board", owner: "", kw: "" };
    var STAGES = ["初步接触", "需求确认", "方案报价", "商务谈判", "赢单", "输单"];

    function draw() {
      F.api("GET", "/api/opportunities?" + F.qs({ owner: st.owner, kw: st.kw, pageSize: 200 }))
        .then(function (d) {
          var head = '<div class="panel"><div class="panel-title">商机看板' +
            '<span class="panel-actions">' +
            '<input id="oKw" type="text" placeholder="商机 / 客户 / 编号" value="' + F.esc(st.kw) + '" style="width:180px">' +
            '<select id="oOwner"><option value="">全部负责人</option>' +
            ["liuyang", "wangfang", "zhangwei"].map(function (o) {
              return '<option value="' + o + '"' + (st.owner === o ? " selected" : "") + ">" + o + "</option>";
            }).join("") + "</select>" +
            '<button class="btn sm" id="oSearch">查询</button>' +
            '<button class="btn sm' + (st.view === "board" ? " primary" : "") + '" id="vBoard">看板</button>' +
            '<button class="btn sm' + (st.view === "list" ? " primary" : "") + '" id="vList">列表</button>' +
            "</span></div>" +
            '<div class="panel-body"><div class="funnel-mini">' +
            d.funnel.stages.map(function (s) {
              return '<div class="fm"><div class="fm-v">' + F.wan(s.amount) + "</div>" +
                '<div class="fm-l">' + F.esc(s.stage) + " · " + s.count + "</div></div>";
            }).join("") + "</div></div></div>";

          var body;
          if (st.view === "board") {
            body = '<div class="board">' + STAGES.map(function (sg) {
              var items = (d.list || []).filter(function (o) { return o.stage === sg; });
              var sum = items.reduce(function (a, o) { return a + o.amount; }, 0);
              return '<div class="col"><div class="col-hd">' + F.esc(sg) +
                '<span>' + items.length + " · " + F.wan(sum) + "</span></div>" +
                items.map(function (o) {
                  return '<div class="card" data-opp="' + F.esc(o.no) + '">' +
                    '<div class="card-t">' + F.esc(o.name) + "</div>" +
                    '<div class="card-c">' + F.esc(o.customerName) + "</div>" +
                    '<div class="card-m"><b>' + F.wan(o.amount) + "</b>" +
                    '<span>' + F.pct(o.probability, 0) + " · " + F.wan(o.weighted) + "</span></div>" +
                    '<div class="card-f">' + F.esc(o.ownerName || "") +
                    (o.overdue ? ' <span class="tag red">延期</span>' : "") +
                    ' <span class="muted">' + F.esc((o.expectCloseDate || "").slice(5)) + "</span></div></div>";
                }).join("") + "</div>";
            }).join("") + "</div>";
          } else {
            body = '<div class="panel"><div class="panel-body flush">' + F.table([
              { label: "编号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
              { label: "商机", render: function (r) { return F.esc(r.name) + '<div class="muted small">' +
                F.esc(r.customerName) + "</div>"; } },
              { label: "阶段", render: function (r) { return F.tag(r.stage); } },
              { label: "金额", num: true, render: function (r) { return F.wan(r.amount); } },
              { label: "概率", num: true, render: function (r) { return F.pct(r.probability, 0); } },
              { label: "加权", num: true, render: function (r) { return F.wan(r.weighted); } },
              { label: "预计结单", render: function (r) {
                return (r.overdue ? '<b class="up">' : "") + F.esc(r.expectCloseDate) + (r.overdue ? "</b>" : ""); } },
              { label: "负责人", render: function (r) { return F.esc(r.ownerName); } },
              { label: "状态", render: function (r) { return F.tag(r.status); } }
            ], d.list, { click: function (r) { return r.no; }, empty: "暂无商机" }) + "</div></div>";
          }
          document.getElementById("view").innerHTML = head + body;
          document.getElementById("oSearch").addEventListener("click", function () {
            st.kw = document.getElementById("oKw").value.trim();
            st.owner = document.getElementById("oOwner").value;
            draw();
          });
          document.getElementById("vBoard").addEventListener("click", function () { st.view = "board"; draw(); });
          document.getElementById("vList").addEventListener("click", function () { st.view = "list"; draw(); });
          document.querySelectorAll("[data-opp]").forEach(function (el) {
            el.addEventListener("click", function () { openOpp(el.getAttribute("data-opp")); });
          });
          F.bindRows(document, openOpp);
          F.setStatus("商机 · 在谈 " + d.funnel.openCount + " 个 / 全额 " + F.wan(d.funnel.openAmount) +
            " · 赢单率 " + F.pct(d.funnel.winRate, 1));
          F.setSide('<div class="side-block"><div class="hd">漏斗（含转化）</div><div class="bd">' +
            d.funnel.stages.map(function (s) {
              return '<div class="side-kv"><span>' + F.esc(s.stage) + " · " + s.count + " 个</span><b>" +
                F.wan(s.amount) + "</b></div>";
            }).join("") + "</div></div>" +
            '<div class="side-block"><div class="hd">结单情况</div><div class="bd">' +
            '<div class="side-kv"><span>赢单</span><b class="down">' + d.funnel.wonCount + " / " +
            F.wan(d.funnel.wonAmount) + "</b></div>" +
            '<div class="side-kv"><span>输单</span><b class="up">' + d.funnel.lostCount + " / " +
            F.wan(d.funnel.lostAmount) + "</b></div>" +
            '<div class="side-kv"><span>平均客单</span><b>' + F.wan(d.funnel.avgDeal) + "</b></div>" +
            "</div></div>");
        });
    }

    function openOpp(no) {
      F.api("GET", "/api/opportunities/" + encodeURIComponent(no)).then(function (d) {
        var canAct = ["admin", "sales_director", "sales"].indexOf(me().role) >= 0;
        var logs = (d.stageLogs || []).map(function (l) {
          return '<div class="tl-item"><span class="tl-time">' + F.esc(l.created_at) + "</span>" +
            F.esc(l.from_stage || "创建") + " → <b>" + F.esc(l.to_stage) + "</b>" +
            '<span class="small muted"> · ' + F.esc(l.operator) + " " + F.esc(l.remark || "") + "</span></div>";
        }).join("");
        var acts = (d.activities || []).slice(0, 8).map(function (a) {
          return '<div class="tl-item"><span class="tl-time">' + F.esc(a.happenAt) + "</span>" +
            F.tag(a.kind, "blue") + " " + F.esc(a.subject) +
            '<div class="small muted">' + F.esc(a.content) + "</div></div>";
        }).join("");
        var html = '<div class="detail-head"><div><div class="dh-title">' + F.esc(d.name) + "</div>" +
          '<div class="muted small">' + F.esc(d.no) + " · " + F.esc(d.customerName) + " · " +
          F.esc(d.ownerName) + "</div></div><div class='dh-tags'>" + F.tag(d.stage) +
          (d.overdue ? F.tag("已延期", "red") : "") + "</div></div>" +
          '<div class="kpi-grid four" style="margin:10px 0">' +
          '<div class="kpi"><div class="k-label">金额</div><div class="k-value">' + F.wan(d.amount) + "</div></div>" +
          '<div class="kpi gold"><div class="k-label">赢率 / 加权</div><div class="k-value" style="font-size:17px">' +
          F.pct(d.probability, 0) + " · " + F.wan(d.weighted) + "</div></div>" +
          '<div class="kpi"><div class="k-label">预计结单</div><div class="k-value" style="font-size:17px">' +
          F.esc(d.expectCloseDate || "—") + "</div></div>" +
          '<div class="kpi green"><div class="k-label">距结单</div><div class="k-value" style="font-size:17px">' +
          (d.daysToClose === null ? "—" : d.daysToClose + " 天") + "</div></div></div>" +
          '<div class="form-row small"><label>竞品</label>' + F.esc(d.competitor || "—") +
          '<label>决策人</label>' + F.esc(d.decisionMaker || "—") +
          '<label>来源</label>' + F.esc(d.source || "—") + "</div>" +
          '<div class="section-title">阶段闸口</div><div class="gate">' +
          ["需求确认", "方案报价", "商务谈判", "赢单"].map(function (s) {
            var miss = (d.stageGate || {})[s] || [];
            return '<div class="gate-row"><b>' + F.esc(s) + "</b>" +
              (miss.length ? '<span class="tag red">缺 ' + F.esc(miss.join("、")) + "</span>"
                : '<span class="tag green">可进入</span>') + "</div>";
          }).join("") + "</div>" +
          '<div class="section-title">推进阶段</div>' +
          (canAct ? '<div class="form-row" id="stageBtns">' + (d.canAdvance || []).map(function (s) {
            return '<button class="btn sm" data-stage="' + F.esc(s) + '">→ ' + F.esc(s) + "</button>";
          }).join("") + '<button class="btn sm danger" id="oLose">标记输单</button></div>'
            : '<div class="small muted">当前角色可查看，不能推进阶段</div>') +
          '<div class="section-title">阶段轨迹</div><div class="timeline">' + (logs || F.empty("暂无")) + "</div>" +
          '<div class="section-title">最近跟进</div><div class="timeline">' + (acts || F.empty("暂无跟进")) + "</div>";
        F.dialog("商机 " + d.no, html,
          '<button class="btn" data-close7="1">关闭</button>' +
          '<button class="btn" id="oFollow">写跟进</button>');
        document.querySelector("[data-close7]").addEventListener("click", F.closeDialog);
        document.getElementById("oFollow").addEventListener("click", function () {
          F.closeDialog(); F.followDialog("opportunity", d.no, draw);
        });
        document.querySelectorAll("[data-stage]").forEach(function (b) {
          b.addEventListener("click", function () {
            var target = b.getAttribute("data-stage");
            var payload = { stage: target };
            if (target === "商务谈判") {
              var comp = window.prompt("竞品情况（进入商务谈判必填）", d.competitor || "销售易");
              if (comp === null) return;
              payload.competitor = comp;
              var dm = window.prompt("决策人（必填）", d.decisionMaker || "");
              if (dm === null) return;
              payload.decisionMaker = dm;
            }
            if (target === "赢单") {
              var reason = window.prompt("赢单要点（写入轨迹）", "价格与服务优于竞品");
              if (reason === null) return;
              payload.reason = reason;
            }
            F.api("POST", "/api/opportunities/" + d.no + "/stage", payload).then(function () {
              F.closeDialog();
              F.toast("已推进到「" + target + "」", "ok");
              draw(); F.reload();
            }).catch(function (e) {
              F.toast(e.message, "err");
            });
          });
        });
        var lose = document.getElementById("oLose");
        if (lose) lose.addEventListener("click", function () {
          var reason = window.prompt("输单原因（必填）", "预算被削减，选择自研");
          if (!reason) return;
          F.api("POST", "/api/opportunities/" + d.no + "/close", { result: "lose", reason: reason })
            .then(function () { F.closeDialog(); F.toast("已标记输单", "ok"); draw(); F.reload(); })
            .catch(function (e) { F.toast(e.message, "err"); });
        });
      });
    }

    draw();
  });

  /* ============================================================ 跟进记录 */
  F.register("activities", function () {
    var st = { kind: "全部" };
    function draw() {
      F.api("GET", "/api/activities?" + F.qs({ kind: st.kind })).then(function (d) {
        var chips = ["全部", "电话", "拜访", "邮件", "会议", "微信"].map(function (k) {
          return '<button class="chip ' + (st.kind === k ? "on" : "") + '" data-k="' + k + '">' + k +
            "<b>" + (k === "全部" ? d.total : (d.byKind[k] || 0)) + "</b></button>";
        }).join("");
        var html = '<div class="panel"><div class="panel-title">跟进记录' +
          '<span class="panel-actions"><button class="btn sm primary" id="aNew">+ 新建跟进</button></span></div>' +
          '<div class="panel-body"><div class="chips">' + chips + "</div></div>" +
          '<div class="panel-body flush">' +
          F.table([
            { label: "时间", render: function (r) { return '<span class="small muted">' + F.esc(r.happenAt) + "</span>"; } },
            { label: "对象", render: function (r) {
              return F.tag(r.objType === "lead" ? "线索" : (r.objType === "opportunity" ? "商机" :
                (r.objType === "ticket" ? "工单" : "客户")), "gray") + " " + F.esc(r.objName);
            } },
            { label: "方式", render: function (r) { return F.tag(r.kind, "blue"); } },
            { label: "主题", key: "subject" },
            { label: "内容", render: function (r) { return '<span class="small">' +
              F.esc((r.content || "").slice(0, 40)) + (r.content && r.content.length > 40 ? "…" : "") + "</span>"; } },
            { label: "时长", num: true, render: function (r) { return r.durationMin + " 分"; } },
            { label: "结果", render: function (r) { return F.esc(r.result || "—"); } },
            { label: "负责人", render: function (r) { return F.esc(r.ownerName); } }
          ], d.list, { empty: "暂无跟进记录" }) + "</div></div>";
        document.getElementById("view").innerHTML = html;
        document.getElementById("aNew").addEventListener("click", function () {
          F.api("GET", "/api/customers?pageSize=200").then(function (cs) {
            F.followDialog("customer", (cs.list[0] || {}).code || "", draw, cs.list);
          });
        });
        document.querySelectorAll("[data-k]").forEach(function (b) {
          b.addEventListener("click", function () { st.kind = b.getAttribute("data-k"); draw(); });
        });
        F.setStatus("跟进记录 · " + d.total + " 条");
        F.setSide('<div class="side-block"><div class="hd">跟进方式分布</div><div class="bd">' +
          Object.keys(d.byKind).map(function (k) {
            return '<div class="side-kv"><span>' + k + "</span><b>" + d.byKind[k] + "</b></div>";
          }).join("") + "</div></div>" +
          '<div class="side-block"><div class="hd">小提示</div><div class="bd small muted" style="line-height:1.9">' +
          "跟进会回写客户的最近联系时间，直接影响客户健康分与公海回收判断。</div></div>");
      });
    }
    draw();
  });

  /* ============================================================ 通用跟进弹层 */
  F.followDialog = function (objType, objNo, done, custList) {
    F.api("GET", "/api/customers?pageSize=200").then(function (cs) {
      var opts = (custList || cs.list || []).map(function (c) {
        return '<option value="' + F.esc(c.code) + '"' + (c.code === objNo ? " selected" : "") + ">" +
          F.esc(c.name) + "</option>";
      }).join("");
      var body = '<div class="form-grid">' +
        '<label>关联类型</label><select id="fType">' +
        ["customer", "lead", "opportunity", "ticket"].map(function (t) {
          return '<option value="' + t + '"' + (t === objType ? " selected" : "") + ">" + t + "</option>";
        }).join("") + "</select>" +
        '<label>关联客户</label><select id="fCust">' + opts + "</select>" +
        '<label>方式</label><select id="fKind">' + ["电话", "拜访", "邮件", "会议", "微信", "任务"]
          .map(function (k) { return "<option>" + k + "</option>"; }).join("") + "</select>" +
        '<label>时长（分钟）</label><input id="fDur" type="number" value="30">' +
        '<label>时间</label><input id="fWhen" type="datetime-local" value="' +
        new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) + '">' +
        "</div>" +
        '<div class="form-row" style="margin-top:8px"><label>主题 *</label></div>' +
        '<input id="fSub" type="text" style="width:100%" value="需求沟通">' +
        '<div class="form-row" style="margin-top:8px"><label>内容</label></div>' +
        '<textarea id="fCon" rows="3" style="width:100%" placeholder="客户反馈、关键结论、下一步"></textarea>' +
        '<div class="form-row" style="margin-top:8px"><label>下一步计划</label>' +
        '<input id="fNext" type="text" style="flex:1" placeholder="如 下周三发送正式报价"></div>';
      F.dialog("写跟进", body, '<button class="btn" data-close8="1">取消</button>' +
        '<button class="btn primary" id="fSave">保存</button>');
      document.querySelector("[data-close8]").addEventListener("click", F.closeDialog);
      document.getElementById("fSave").addEventListener("click", function () {
        var target = objNo;
        if (document.getElementById("fType").value !== objType) target = objNo;
        var when = document.getElementById("fWhen").value;
        F.api("POST", "/api/activities", {
          objType: objType, objNo: target,
          kind: document.getElementById("fKind").value,
          subject: document.getElementById("fSub").value.trim() || "需求沟通",
          content: document.getElementById("fCon").value.trim(),
          happenAt: when ? when.replace("T", " ") + ":00" : undefined,
          durationMin: Number(document.getElementById("fDur").value || 30),
          nextPlan: document.getElementById("fNext").value.trim()
        }).then(function () {
          F.closeDialog(); F.toast("跟进已记录", "ok");
          if (done) done();
          F.reload();
        }).catch(function (e) { F.toast(e.message, "err"); });
      });
    });
  };
})(window, document);

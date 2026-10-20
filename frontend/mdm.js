/* 飞泉 SCM · 供应商档案（360）与物料主数据 */
(function (window, document) {
  "use strict";
  var F = window.F;

  function me() { return (F.state.boot && F.state.boot.user) || {}; }
  function canWrite() {
    var r = me().role;
    return r === "admin" || r === "purchase_director" || r === "buyer" || r === "planner";
  }
  function canApprove() {
    var r = me().role;
    return r === "admin" || r === "purchase_director";
  }
  F.canWrite = canWrite;
  F.canApprove = canApprove;
  F.me = me;

  F.showErr = function (e) {
    var msg = e && e.message ? e.message : String(e);
    if (e && e.body && e.body.dups && e.body.dups.length) {
      msg += "：" + e.body.dups.map(function (d) {
        return (d.name || d.code) + "（" + (d.reason || "重复") + "）";
      }).join("；");
    }
    if (e && e.body && e.body.missing && e.body.missing.length) {
      msg += "（" + e.body.missing.join("、") + "）";
    }
    F.toast(msg, "err");
    return msg;
  };

  /* ============================================================ 供应商 */
  F.register("suppliers", function () {
    var st = { status: "全部", level: "全部", kw: "" };

    function draw() {
      F.api("GET", "/api/suppliers?" + F.qs({ status: st.status, level: st.level, kw: st.kw }))
        .then(function (d) {
          var counts = { "全部": d.total };
          d.list.forEach(function (s) { counts[s.status] = (counts[s.status] || 0) + 1; });
          var chips = ["全部", "待准入", "已准入", "观察", "冻结"].map(function (s) {
            return '<button class="chip ' + (st.status === s ? "on" : "") + '" data-st="' + s + '">' +
              s + "<b>" + (counts[s] || 0) + "</b></button>";
          }).join("");
          var html = '<div class="panel"><div class="panel-title">供应商档案' +
            '<span class="panel-actions">' +
            '<input id="fKw" type="text" placeholder="名称 / 编码 / 联系人" value="' + F.esc(st.kw) +
            '" style="width:180px">' +
            '<select id="fLevel">' + ["全部", "A", "B", "C", "D"].map(function (v) {
              return '<option' + (v === st.level ? " selected" : "") + ">" + v + "</option>";
            }).join("") + "</select>" +
            '<button class="btn sm" id="btnSearch">查询</button>' +
            (canWrite() ? '<button class="btn sm primary" id="sNew">+ 新建供应商</button>' : "") +
            "</span></div>" +
            '<div class="panel-body"><div class="chips">' + chips + "</div></div>" +
            '<div class="panel-body flush">' +
            F.table([
              { label: "编码", render: function (r) { return '<span class="mono small">' + F.esc(r.code) + "</span>"; } },
              { label: "供应商", render: function (r) { return '<b>' + F.esc(r.name) + "</b>" +
                '<div class="muted small">' + F.esc(r.category) + " · " + F.esc(r.contact || "—") +
                " · 账期 " + r.paymentTerms + " 天 · 提前期 " + r.leadDays + " 天</div>"; } },
              { label: "等级", render: function (r) { return F.levelTag(r.level); } },
              { label: "综合分", num: true, render: function (r) { return F.scoreBadge(r.score); } },
              { label: "资质", render: function (r) {
                var t = r.qualCount + " 项";
                if (r.qualWorst === "过期") return '<b class="up">' + t + "（有过期）</b>";
                if (r.qualWorst === "临期") return '<span class="up">' + t + "（临期）</span>";
                return t;
              } },
              { label: "采购额", num: true, render: function (r) { return F.wan(r.poAmount); } },
              { label: "状态", render: function (r) { return F.tag(r.status); } }
            ], d.list, { click: function (r) { return r.code; }, empty: "没有匹配的供应商" }) +
            "</div></div>";
          document.getElementById("view").innerHTML = html;
          document.getElementById("btnSearch").addEventListener("click", function () {
            st.kw = document.getElementById("fKw").value.trim();
            st.level = document.getElementById("fLevel").value;
            draw();
          });
          document.getElementById("fKw").addEventListener("keydown", function (e) {
            if (e.key === "Enter") document.getElementById("btnSearch").click();
          });
          var nb = document.getElementById("sNew");
          if (nb) nb.addEventListener("click", newSupplier);
          document.querySelectorAll("[data-st]").forEach(function (b) {
            b.addEventListener("click", function () { st.status = b.getAttribute("data-st"); draw(); });
          });
          F.bindRows(document, function (code) { openSupplier(code); });
          F.setStatus("供应商档案 · " + d.total + " 家（已准入 " + (counts["已准入"] || 0) + "）");
          var byLevel = {};
          d.list.forEach(function (s) { byLevel[s.level] = (byLevel[s.level] || 0) + 1; });
          F.setSide('<div class="side-block"><div class="hd">等级分布</div><div class="bd">' +
            ["A", "B", "C", "D"].map(function (l) {
              return F.kv(l + " 级", (byLevel[l] || 0) + " 家");
            }).join("") + "</div></div>" +
            '<div class="side-block"><div class="hd">评级口径</div><div class="bd small muted" style="line-height:1.9">' +
            "综合分 = 交付及时率 35 + 到货合格率 35 + 价格竞争力 15 + 协同响应 15<br>" +
            "A ≥ 85 · B ≥ 70 · C ≥ 55 · D &lt; 55；资质过期或多次逾期发票会被冻结/限单。</div></div>");
        });
    }

    function newSupplier() {
      var body = '<div class="form-grid">' +
        '<label>供应商全称 *</label><input id="nName" type="text" placeholder="工商全称，如 苏州某某电子科技有限公司">' +
        '<label>简称</label><input id="nShort" type="text">' +
        '<label>类别</label><select id="nCat">' + ["电子件", "结构件", "包材", "五金", "辅料", "设备", "服务", "其他"]
          .map(function (s) { return "<option>" + s + "</option>"; }).join("") + "</select>" +
        '<label>税号</label><input id="nTax" type="text" placeholder="用于唯一性校验">' +
        '<label>联系人</label><input id="nContact" type="text">' +
        '<label>电话</label><input id="nPhone" type="text">' +
        '<label>区域</label><select id="nRegion">' + ["苏州", "昆山", "上海", "无锡", "常州", "南京", "杭州",
          "宁波", "合肥", "东莞", "青岛", "其他"].map(function (s) { return "<option>" + s + "</option>"; })
          .join("") + "</select>" +
        '<label>账期（天）</label><input id="nTerms" type="number" value="30">' +
        '<label>提前期（天）</label><input id="nLead" type="number" value="15">' +
        '<label>产能说明</label><input id="nCap" type="text">' +
        "</div>" +
        '<div class="small muted" id="dupHint" style="margin-top:8px"></div>';
      F.dialog("新建供应商", body,
        '<button class="btn" data-close2="1">取消</button><button class="btn primary" id="nSave">保存并提交准入</button>');
      var dlg = document.getElementById("dialog");
      dlg.querySelector("[data-close2]").addEventListener("click", F.closeDialog);
      var nameEl = document.getElementById("nName");
      var taxEl = document.getElementById("nTax");
      function checkDup() {
        if (nameEl.value.trim().length < 4) return;
        F.api("GET", "/api/suppliers?kw=" + encodeURIComponent(nameEl.value.trim()))
          .then(function (r) {
            var hit = (r.list || []).filter(function (s) { return s.name.indexOf(nameEl.value.trim()) >= 0; });
            var hint = document.getElementById("dupHint");
            hint.innerHTML = hit.length
              ? '<span class="up">已有同名/相似供应商：' + hit.map(function (s) {
                return F.esc(s.name) + "（" + s.code + "）"; }).join("；") + "</span>"
              : '<span class="down">未发现重复</span>';
          });
      }
      nameEl.addEventListener("blur", checkDup);
      document.getElementById("nSave").addEventListener("click", function () {
        var payload = {
          name: nameEl.value.trim(), shortName: document.getElementById("nShort").value.trim(),
          category: document.getElementById("nCat").value, taxNo: taxEl.value.trim(),
          contact: document.getElementById("nContact").value.trim(),
          phone: document.getElementById("nPhone").value.trim(),
          region: document.getElementById("nRegion").value,
          paymentTerms: Number(document.getElementById("nTerms").value || 30),
          leadDays: Number(document.getElementById("nLead").value || 15),
          capacity: document.getElementById("nCap").value.trim()
        };
        F.api("POST", "/api/suppliers", payload).then(function (r) {
          F.closeDialog();
          F.toast("供应商已创建：" + r.code + "（待准入）", "ok");
          draw();
        }).catch(function (e) { F.showErr(e); });
      });
    }

    function openSupplier(code) {
      F.api("GET", "/api/suppliers/" + encodeURIComponent(code)).then(function (s) {
        var tabs = [["qual", "资质"], ["perf", "绩效"], ["po", "订单"], ["rc", "收货"], ["iv", "发票"]];
        var body = '<div class="detail-head"><div class="dh-title">' + F.esc(s.name) +
          ' <span class="mono small muted">' + F.esc(s.code) + "</span></div>" +
          '<div class="dh-tags">' + F.levelTag(s.level) + " " + F.tag(s.status) + " " +
          F.tag(s.qualWorst === "过期" ? "过期" : s.qualWorst) + " " + F.scoreBadge(s.score) + "</div></div>" +
          '<div class="form-grid" style="margin-top:6px">' +
          '<div><span class="muted small">类别</span><br>' + F.esc(s.category) + "</div>" +
          '<div><span class="muted small">联系人</span><br>' + F.esc(s.contact || "—") + " " + F.esc(s.phone || "") + "</div>" +
          '<div><span class="muted small">账期 / 提前期</span><br>' + s.paymentTerms + " 天 / " + s.leadDays + " 天</div>" +
          '<div><span class="muted small">采购额 / 订单数</span><br>' + F.wan(s.poAmount) + " / " + s.poCount + " 单</div>" +
          '<div><span class="muted small">到货准时率</span><br>' + F.pct(s.onTimeRate, 0) + "</div>" +
          '<div><span class="muted small">在途订单</span><br>' + s.openPoCount + " 单</div>" +
          "</div>" +
          '<div class="chips" style="margin:10px 0" id="supTabs">' + tabs.map(function (t, i) {
            return '<button class="chip ' + (i === 0 ? "on" : "") + '" data-tab="' + t[0] + '">' + t[1] + "</button>";
          }).join("") + "</div><div id='supBody'></div>";
        var foot = (canApprove() ? '<button class="btn" id="sQual">登记资质</button>' +
          '<button class="btn" id="sScore">录入绩效</button>' +
          (s.status === "已准入" ? '<button class="btn" id="sFreeze">冻结</button>' :
            '<button class="btn primary" id="sApprove">准入通过</button>') : "") +
          '<button class="btn" data-close3="1">关闭</button>';
        F.dialog("供应商 360 · " + s.name, body, foot);
        var dlg = document.getElementById("dialog");
        dlg.querySelector("[data-close3]").addEventListener("click", F.closeDialog);

        function pane(key) {
          var el = document.getElementById("supBody");
          if (key === "qual") {
            el.innerHTML = F.table([
              { label: "资质", key: "name" },
              { label: "证书号", render: function (r) { return '<span class="mono small">' + F.esc(r.no || "—") + "</span>"; } },
              { label: "发证日", key: "issuedAt" },
              { label: "到期日", key: "expireAt" },
              { label: "状态", render: function (r) { return F.tag(r.state); } }
            ], s.quals, { empty: "尚未登记资质（准入前必须登记）" });
          } else if (key === "perf") {
            el.innerHTML = F.table([
              { label: "期间", key: "period" },
              { label: "交付及时率", num: true, render: function (r) { return F.pct(r.deliveryRate, 1); } },
              { label: "质量合格率", num: true, render: function (r) { return F.pct(r.qualityRate, 2); } },
              { label: "价格指数", num: true, render: function (r) {
                var v = r.priceIndex;
                return (v > 1.03 ? '<span class="up">' + v.toFixed(2) + "</span>" : v.toFixed(2));
              } },
              { label: "响应达标", num: true, render: function (r) { return F.pct(r.responseRate, 0); } },
              { label: "综合分", num: true, render: function (r) { return F.scoreBadge(r.score); } },
              { label: "等级", render: function (r) { return F.levelTag(r.level); } }
            ], s.scores, { empty: "尚无绩效记录" });
          } else if (key === "po") {
            el.innerHTML = F.table([
              { label: "订单", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
              { label: "标题", render: function (r) { return F.esc(r.title); } },
              { label: "金额", num: true, render: function (r) { return F.wan(r.amount); } },
              { label: "状态", render: function (r) { return F.tag(r.status); } },
              { label: "到货进度", num: true, render: function (r) {
                return F.pct(r.orderedQty ? r.receivedQty / r.orderedQty : 0, 0);
              } },
              { label: "承诺到货", key: "promiseDate" }
            ], s.orders, { empty: "暂无采购订单" });
          } else if (key === "rc") {
            el.innerHTML = F.table([
              { label: "收货单", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
              { label: "订单", render: function (r) { return '<span class="mono small">' + F.esc(r.poNo) + "</span>"; } },
              { label: "到货日", key: "receivedAt" },
              { label: "质检", render: function (r) { return F.tag(r.inspectResult || "待检"); } },
              { label: "状态", render: function (r) { return F.tag(r.status); } }
            ], s.receipts, { empty: "暂无收货记录" });
          } else {
            el.innerHTML = F.table([
              { label: "发票", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
              { label: "订单", render: function (r) { return '<span class="mono small">' + F.esc(r.poNo) + "</span>"; } },
              { label: "金额", num: true, render: function (r) { return F.money(r.amount); } },
              { label: "匹配", render: function (r) { return F.tag(r.matchResult || "待匹配"); } },
              { label: "状态", render: function (r) { return F.tag(r.status); } },
              { label: "到期", key: "dueDate" }
            ], s.invoices, { empty: "暂无发票" });
          }
        }
        pane("qual");
        document.querySelectorAll("#supTabs [data-tab]").forEach(function (b) {
          b.addEventListener("click", function () {
            document.querySelectorAll("#supTabs [data-tab]").forEach(function (x) { x.className = "chip"; });
            b.className = "chip on";
            pane(b.getAttribute("data-tab"));
          });
        });

        var qb = document.getElementById("sQual");
        if (qb) qb.addEventListener("click", function () { addQual(s.code, draw); });
        var sb = document.getElementById("sScore");
        if (sb) sb.addEventListener("click", function () { addScore(s.code, draw); });
        var ab = document.getElementById("sApprove");
        if (ab) ab.addEventListener("click", function () {
          F.api("POST", "/api/suppliers/" + s.code + "/status", { status: "已准入" })
            .then(function () { F.closeDialog(); F.toast("已准入：" + s.name, "ok"); draw(); })
            .catch(function (e) { F.showErr(e); });
        });
        var fb = document.getElementById("sFreeze");
        if (fb) fb.addEventListener("click", function () {
          F.api("POST", "/api/suppliers/" + s.code + "/status", { status: "冻结" })
            .then(function () { F.closeDialog(); F.toast("已冻结：" + s.name, "ok"); draw(); })
            .catch(function (e) { F.showErr(e); });
        });
        F.setStatus("供应商 360 · " + s.name);
      }).catch(function (e) { F.showErr(e); });
    }
    F.openSupplier = openSupplier;

    function addQual(code, after) {
      F.dialog("登记资质",
        '<div class="form-grid"><label>资质名称 *</label><input id="qName" type="text" placeholder="如 ISO9001 质量体系">' +
        '<label>证书号</label><input id="qNo" type="text"><label>发证日</label>' +
        '<input id="qIssued" type="date" value="' + F.today() + '">' +
        '<label>到期日 *</label><input id="qExpire" type="date" value="' + F.addDays(365) + '"></div>',
        '<button class="btn" data-close4="1">取消</button><button class="btn primary" id="qSave">保存</button>');
      var dlg = document.getElementById("dialog");
      dlg.querySelector("[data-close4]").addEventListener("click", F.closeDialog);
      document.getElementById("qSave").addEventListener("click", function () {
        var name = document.getElementById("qName").value.trim();
        if (!name) { F.toast("请填写资质名称", "err"); return; }
        F.api("POST", "/api/suppliers/" + code + "/quals", {
          name: name, no: document.getElementById("qNo").value.trim(),
          issuedAt: document.getElementById("qIssued").value,
          expireAt: document.getElementById("qExpire").value
        }).then(function (r) {
          F.closeDialog();
          F.toast("资质已登记（" + r.state + "）", "ok");
          if (after) after();
        }).catch(function (e) { F.showErr(e); });
      });
    }

    function addScore(code, after) {
      F.dialog("录入季度绩效",
        '<div class="form-grid"><label>期间</label><input id="pPeriod" type="text" value="2026-Q4">' +
        '<label>交付及时率（0~1）</label><input id="pDelivery" type="number" step="0.01" value="0.95">' +
        '<label>质量合格率（0~1）</label><input id="pQuality" type="number" step="0.01" value="0.98">' +
        '<label>价格指数（1=持平）</label><input id="pPrice" type="number" step="0.01" value="1.00">' +
        '<label>响应达标率（0~1）</label><input id="pResp" type="number" step="0.01" value="0.90">' +
        "</div><div class='small muted' style='margin-top:8px'>综合分 = 交付 35% + 质量 35% + 价格 15% + 响应 15%</div>",
        '<button class="btn" data-close5="1">取消</button><button class="btn primary" id="pSave">算分并保存</button>');
      var dlg = document.getElementById("dialog");
      dlg.querySelector("[data-close5]").addEventListener("click", F.closeDialog);
      document.getElementById("pSave").addEventListener("click", function () {
        F.api("POST", "/api/suppliers/" + code + "/score", {
          period: document.getElementById("pPeriod").value.trim(),
          deliveryRate: Number(document.getElementById("pDelivery").value),
          qualityRate: Number(document.getElementById("pQuality").value),
          priceIndex: Number(document.getElementById("pPrice").value),
          responseRate: Number(document.getElementById("pResp").value)
        }).then(function (r) {
          F.closeDialog();
          F.toast("绩效已录入：得分 " + r.score + "（" + r.level + " 级）", "ok");
          if (after) after();
        }).catch(function (e) { F.showErr(e); });
      });
    }
    draw();
  });

  /* ============================================================ 物料 */
  F.register("materials", function () {
    var st = { kw: "", abc: "全部" };

    function draw() {
      F.api("GET", "/api/materials?" + F.qs({ kw: st.kw, abc: st.abc })).then(function (d) {
        var counts = { "全部": d.total, "A": 0, "B": 0, "C": 0 };
        d.list.forEach(function (m) { counts[m.abc] = (counts[m.abc] || 0) + 1; });
        var chips = ["全部", "A", "B", "C"].map(function (a) {
          return '<button class="chip ' + (st.abc === a ? "on" : "") + '" data-abc="' + a + '">' +
            (a === "全部" ? "全部" : a + " 类") + "<b>" + (counts[a] || 0) + "</b></button>";
        }).join("");
        var html = '<div class="panel"><div class="panel-title">物料主数据' +
          '<span class="panel-actions">' +
          '<input id="fKw" type="text" placeholder="编码 / 名称 / 规格" value="' + F.esc(st.kw) +
          '" style="width:180px">' +
          '<button class="btn sm" id="btnSearch">查询</button>' +
          (canWrite() ? '<button class="btn sm primary" id="mNew">+ 新建物料</button>' +
            '<button class="btn sm" id="mAbc">重算 ABC</button>' : "") +
          "</span></div>" +
          '<div class="panel-body"><div class="chips">' + chips + "</div></div>" +
          '<div class="panel-body flush">' +
          F.table([
            { label: "编码", render: function (r) { return '<span class="mono small">' + F.esc(r.code) + "</span>"; } },
            { label: "物料", render: function (r) { return '<b>' + F.esc(r.name) + "</b>" +
              '<div class="muted small">' + F.esc(r.spec) + "</div>"; } },
            { label: "分类", render: function (r) { return F.tag(r.abc, r.abc === "A" ? "green" : (r.abc === "B" ? "blue" : "gray")); } },
            { label: "单位", render: function (r) { return F.esc(r.unit); } },
            { label: "标准价", num: true, render: function (r) { return F.money(r.standardPrice); } },
            { label: "最近成交", num: true, render: function (r) { return F.money(r.lastPrice); } },
            { label: "现存量", num: true, render: function (r) {
              return F.qty(r.onHand) + ' <span class="muted small">' + F.esc(r.unit) + "</span>";
            } },
            { label: "库存状态", render: function (r) { return F.tag(r.stockState || "正常"); } },
            { label: "覆盖天数", num: true, render: function (r) {
              return r.coverageDays === null || r.coverageDays === undefined ? "—" : F.qty(r.coverageDays);
            } }
          ], d.list, { click: function (r) { return r.code; }, empty: "没有匹配的物料" }) +
          "</div></div>";
        document.getElementById("view").innerHTML = html;
        document.getElementById("btnSearch").addEventListener("click", function () {
          st.kw = document.getElementById("fKw").value.trim();
          draw();
        });
        document.getElementById("fKw").addEventListener("keydown", function (e) {
          if (e.key === "Enter") document.getElementById("btnSearch").click();
        });
        document.querySelectorAll("[data-abc]").forEach(function (b) {
          b.addEventListener("click", function () { st.abc = b.getAttribute("data-abc"); draw(); });
        });
        var nb = document.getElementById("mNew");
        if (nb) nb.addEventListener("click", newMaterial);
        var ab = document.getElementById("mAbc");
        if (ab) ab.addEventListener("click", function () {
          F.api("POST", "/api/materials/abc-recalc", {}).then(function (r) {
            F.toast("ABC 已重算：" + r.total + " 个物料，" + r.changed + " 个分类变化", "ok");
            draw();
          }).catch(function (e) { F.showErr(e); });
        });
        F.bindRows(document, function (code) { openMaterial(code); });
        F.setStatus("物料主数据 · " + d.total + " 项（A 类 " + (counts.A || 0) + " / B 类 " +
          (counts.B || 0) + "）");
        F.setSide('<div class="side-block"><div class="hd">分类口径</div><div class="bd small muted" style="line-height:1.9">' +
          "ABC 按年耗用金额（标准价 × 日均耗用 × 365）降序累计：<br>A ≤ 70% · B ≤ 90% · C 其余<br>" +
          "A 类重点管控库存与供应商，C 类可用较粗的补货策略。</div></div>" +
          '<div class="side-block"><div class="hd">补货参数</div><div class="bd small muted" style="line-height:1.9">' +
          "补货点 = 日均耗用 × 采购提前期 + 安全库存<br>低于安全库存判「低于安全库存」，低于补货点判「待补货」。</div></div>");
      });
    }

    function newMaterial() {
      var body = '<div class="form-grid">' +
        '<label>物料名称 *</label><input id="nName" type="text">' +
        '<label>规格型号</label><input id="nSpec" type="text">' +
        '<label>单位</label><input id="nUnit" type="text" value="个">' +
        '<label>类别</label><select id="nCat">' + ["电子件", "结构件", "包材", "五金", "辅料", "设备件", "耗材", "其他"]
          .map(function (s) { return "<option>" + s + "</option>"; }).join("") + "</select>" +
        '<label>标准价（元）</label><input id="nPrice" type="number" step="0.01" value="0">' +
        '<label>采购提前期（天）</label><input id="nLead" type="number" value="10">' +
        '<label>安全库存</label><input id="nSafety" type="number" value="0">' +
        '<label>最大库存</label><input id="nMax" type="number" value="0">' +
        '<label>最小起订量</label><input id="nMoq" type="number" value="0">' +
        '<label>日均耗用</label><input id="nDaily" type="number" value="0">' +
        "</div>" +
        '<div class="small muted" id="dupHint" style="margin-top:8px"></div>';
      F.dialog("新建物料", body,
        '<button class="btn" data-close2="1">取消</button>' +
        '<button class="btn primary" id="nSave">保存</button>');
      var dlg = document.getElementById("dialog");
      dlg.querySelector("[data-close2]").addEventListener("click", F.closeDialog);
      var nameEl = document.getElementById("nName");
      var specEl = document.getElementById("nSpec");
      function checkDup() {
        if (!nameEl.value.trim() && !specEl.value.trim()) return;
        F.api("GET", "/api/materials/check-dup?" + F.qs({ name: nameEl.value.trim(), spec: specEl.value.trim() }))
          .then(function (r) {
            var hint = document.getElementById("dupHint");
            hint.innerHTML = (r.dups && r.dups.length)
              ? '<span class="up">疑似重复：' + r.dups.slice(0, 3).map(function (x) {
                return F.esc(x.name) + "（" + F.esc(x.code) + "，" + F.esc(x.reason) + "）"; }).join("；") + "</span>"
              : '<span class="down">未发现重复</span>';
          }).catch(function () {});
      }
      nameEl.addEventListener("blur", checkDup);
      specEl.addEventListener("blur", checkDup);
      document.getElementById("nSave").addEventListener("click", function () {
        var payload = {
          name: nameEl.value.trim(), spec: specEl.value.trim(), unit: document.getElementById("nUnit").value.trim(),
          category: document.getElementById("nCat").value,
          standardPrice: Number(document.getElementById("nPrice").value || 0),
          leadDays: Number(document.getElementById("nLead").value || 10),
          safetyStock: Number(document.getElementById("nSafety").value || 0),
          maxStock: Number(document.getElementById("nMax").value || 0),
          minOrderQty: Number(document.getElementById("nMoq").value || 0),
          avgDailyUsage: Number(document.getElementById("nDaily").value || 0)
        };
        F.api("POST", "/api/materials", payload).then(function (r) {
          F.closeDialog();
          F.toast("物料已创建：" + r.code, "ok");
          draw();
        }).catch(function (e) {
          if (e.status === 409 && e.body && e.body.dups) {
            if (window.confirm(e.message + "\n\n仍要新建吗？")) {
              payload.force = true;
              F.api("POST", "/api/materials", payload).then(function (r) {
                F.closeDialog(); F.toast("物料已创建：" + r.code, "ok"); draw();
              }).catch(function (e2) { F.showErr(e2); });
              return;
            }
          }
          F.showErr(e);
        });
      });
    }

    function openMaterial(code) {
      F.api("GET", "/api/materials/" + encodeURIComponent(code)).then(function (m) {
        var body = '<div class="detail-head"><div class="dh-title">' + F.esc(m.name) +
          ' <span class="mono small muted">' + F.esc(m.code) + "</span></div>" +
          '<div class="dh-tags">' + F.tag(m.abc, m.abc === "A" ? "green" : (m.abc === "B" ? "blue" : "gray")) +
          " " + F.tag(m.state || "正常") + "</div></div>" +
          '<div class="form-grid" style="margin-top:6px">' +
          "<div><span class='muted small'>规格</span><br>" + F.esc(m.spec) + "</div>" +
          "<div><span class='muted small'>单位 / 类别</span><br>" + F.esc(m.unit) + " / " + F.esc(m.category) + "</div>" +
          "<div><span class='muted small'>标准价 / 最近成交</span><br>" + F.money(m.standardPrice) + " / " + F.money(m.lastPrice) + "</div>" +
          "<div><span class='muted small'>现存量 / 安全库存</span><br>" + F.qty(m.onHand) + " / " + F.qty(m.safetyStock) + "</div>" +
          "<div><span class='muted small'>补货点 / 覆盖天数</span><br>" + F.qty(m.reorderPoint) + " / " +
          (m.coverageDays === null ? "—" : F.qty(m.coverageDays)) + "</div>" +
          "<div><span class='muted small'>提前期 / 主供</span><br>" + m.leadDays + " 天 / " + F.esc(m.mainSupplier || "—") + "</div>" +
          "</div>" +
          '<div class="section-title" style="margin-top:12px">价格记录</div>' +
          F.table([{ label: "生效日", key: "effective_at" },
            { label: "供应商", render: function (r) { return F.esc(r.supplier_code || "—"); } },
            { label: "价格", num: true, render: function (r) { return F.money(r.price); } },
            { label: "来源", render: function (r) { return F.tag(r.source, "gray"); } },
            { label: "备注", render: function (r) { return '<span class="small muted">' + F.esc(r.remark || "—") + "</span>"; } }],
            m.prices, { empty: "暂无价格记录" }) +
          '<div class="section-title" style="margin-top:12px">分仓库存</div>' +
          F.table([{ label: "仓库", key: "warehouse" }, { label: "批次", key: "batch" },
            { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
            { label: "成本", num: true, render: function (r) { return F.money(r.unit_cost); } },
            { label: "入库日", key: "in_date" }, { label: "有效期", render: function (r) { return F.esc(r.expire_at || "—"); } }],
            m.stock, { empty: "暂无库存" }) +
          '<div class="section-title" style="margin-top:12px">最近出入库</div>' +
          F.table([{ label: "时间", render: function (r) { return '<span class="small muted">' + F.esc(r.created_at) + "</span>"; } },
            { label: "类型", render: function (r) { return F.tag(r.type); } },
            { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
            { label: "仓库", key: "warehouse" }, { label: "来源单", key: "ref_no" }],
            m.moves, { empty: "暂无流水" });
        F.dialog("物料详情 · " + m.name, body, '<button class="btn" data-close3="1">关闭</button>');
        var dlg = document.getElementById("dialog");
        dlg.querySelector("[data-close3]").addEventListener("click", F.closeDialog);
      }).catch(function (e) { F.showErr(e); });
    }
    F.openMaterial = openMaterial;
    draw();
  });
})(window, document);

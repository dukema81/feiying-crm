/* 飞泉 SCM · 库存台账与库存作业（流水 / 调拨 / 盘点 / 调整） */
(function (window, document) {
  "use strict";
  var F = window.F;

  function me() { return (F.state.boot && F.state.boot.user) || {}; }
  function canStock() {
    var r = me().role;
    return r === "admin" || r === "warehouse" || r === "quality";
  }
  function whs() {
    var c = F.mdmCache || {};
    if (c.whs) return Promise.resolve(c.whs);
    return F.api("GET", "/api/warehouses").then(function (d) { c.whs = d; return d; });
  }
  function whOptions(sel, withAll) {
    return (withAll ? '<option value="全部">全部仓库</option>' : "") + (F.state.__whs || [])
      .map(function (w) {
        return '<option value="' + F.esc(w.code) + '"' + (sel === w.code ? " selected" : "") + ">" +
          F.esc(w.code + " " + w.name) + "</option>";
      }).join("");
  }
  function loadWhs() {
    return whs().then(function (list) {
      F.state.__whs = list;
      return list;
    });
  }

  /* ============================================================ 库存台账 */
  F.register("stock", function () {
    var st = { state: "全部", wh: "全部", kw: "", view: "summary", expiry: false };

    function draw() {
      Promise.all([
        loadWhs(),
        F.api("GET", "/api/stock/summary?" + F.qs({ kw: st.kw })),
        F.api("GET", "/api/stock/shortage"),
        st.view === "batch"
          ? F.api("GET", "/api/stock?" + F.qs({ kw: st.kw, warehouse: st.wh,
              state: st.state, expiry: st.expiry ? "近效期" : "全部" }))
          : Promise.resolve(null)
      ]).then(function (res) {
        var sum = res[1], short = res[2], batch = res[3];
        var counts = sum.counts || {};
        var expiringCount = ((F.state.boot && F.state.boot.kpi) || {}).expiringCount || 0;
        var kpi = '<div class="kpi-grid four">' +
          '<div class="kpi"><div class="k-label">库存金额</div><div class="k-value">' + F.wan(sum.amount) +
          '</div><div class="k-sub">' + sum.total + " 个物料</div></div>" +
          '<div class="kpi red"><div class="k-label">缺料 / 低库存</div><div class="k-value">' +
          ((counts["缺货"] || 0) + (counts["低于安全库存"] || 0)) +
          '</div><div class="k-sub">待补货 ' + (counts["待补货"] || 0) + " · 超储 " +
          (counts["超储"] || 0) + "</div></div>" +
          '<div class="kpi gold"><div class="k-label">补货建议金额</div><div class="k-value">' +
          F.wan(short.amount) + '</div><div class="k-sub">' + short.total + " 项待补货</div></div>" +
          '<div class="kpi green"><div class="k-label">库存健康度</div><div class="k-value">' +
          F.pct(sum.total ? (counts["正常"] || 0) / sum.total : 0, 0) +
          '</div><div class="k-sub">正常 ' + (counts["正常"] || 0) + " 项</div></div></div>";

        var chips = ["全部", "正常", "待补货", "低于安全库存", "缺货", "超储"].map(function (s) {
          return '<button class="chip ' + (st.state === s ? "on" : "") + '" data-state="' + s + '">' +
            s + "<b>" + (s === "全部" ? sum.total : (counts[s] || 0)) + "</b></button>";
        }).join("");

        var tabs = '<div class="tabs">' +
          '<button class="' + (st.view === "summary" ? "on" : "") + '" data-view="summary">物料汇总</button>' +
          '<button class="' + (st.view === "batch" ? "on" : "") + '" data-view="batch">批次明细</button>' +
          "</div>";

        var html = kpi + '<div class="panel"><div class="panel-title">库存台账' +
          '<span class="panel-actions">' +
          '<input id="sKw" type="text" placeholder="物料编码 / 名称 / 批次" value="' + F.esc(st.kw) +
          '" style="width:180px"><select id="sWh" style="width:150px">' + whOptions(st.wh, true) + "</select>" +
          '<label class="small" style="margin:0 6px"><input type="checkbox" id="sExpiry"' +
          (st.expiry ? " checked" : "") + "> 只看近效期</label>" +
          '<button class="btn sm" id="sSearch">查询</button>' +
          "</span></div>" +
          '<div class="panel-body"><div class="chips">' + chips + "</div></div>" +
          '<div class="panel-body" style="padding-bottom:0">' + tabs + "</div>";

        var rowsList = sum.list.filter(function (x) {
          return st.state === "全部" || x.state === st.state;
        });
        if (st.view === "summary") {
          html += '<div class="panel-body flush">' + F.table([
            { label: "物料", render: function (r) {
              return '<b>' + F.esc(r.name) + '</b><div class="muted small mono">' + F.esc(r.code) +
                " · " + F.esc(r.spec || "") + "</div>";
            } },
            { label: "ABC", render: function (r) { return F.levelTag(r.abc); } },
            { label: "现存量", num: true, render: function (r) {
              return F.qty(r.onHand) + " " + F.esc(r.unit);
            } },
            { label: "可用量", num: true, render: function (r) {
              return r.locked ? '<span class="down">' + F.qty(r.available) + "</span>" : F.qty(r.available);
            } },
            { label: "安全库存", num: true, render: function (r) { return F.qty(r.safetyStock); } },
            { label: "补货点", num: true, render: function (r) { return F.qty(r.reorderPoint); } },
            { label: "覆盖天数", num: true, render: function (r) {
              return r.coverageDays === null ? "—" : '<b class="' + (r.coverageDays < 7 ? "up" : "") +
                '">' + F.qty(r.coverageDays) + "</b> 天";
            } },
            { label: "库存金额", num: true, render: function (r) { return F.money(r.amount); } },
            { label: "状态", render: function (r) { return F.tag(r.state); } }
          ], rowsList, { click: function (r) { return r.code; }, empty: "没有匹配的库存" }) + "</div></div>";
        } else {
          var brows = ((batch && batch.list) || []).filter(function (x) {
            return st.wh === "全部" || x.warehouse === st.wh;
          });
          html += '<div class="panel-body flush">' + F.table([
            { label: "物料", render: function (r) {
              return F.esc(r.materialName) + '<div class="muted small mono">' + F.esc(r.materialCode) +
                "</div>";
            } },
            { label: "仓库", key: "warehouse" },
            { label: "批次", render: function (r) { return '<span class="mono small">' +
              F.esc(r.batch || "—") + "</span>"; } },
            { label: "数量", num: true, render: function (r) {
              return F.qty(r.qty) + " " + F.esc(r.unit);
            } },
            { label: "单位成本", num: true, render: function (r) { return F.money(r.unitCost); } },
            { label: "金额", num: true, render: function (r) { return F.money(r.amount); } },
            { label: "入库日", key: "inDate" },
            { label: "库龄", num: true, render: function (r) { return r.ageDays + " 天"; } },
            { label: "有效期", render: function (r) {
              if (!r.expireAt) return '<span class="muted">—</span>';
              return F.tag(r.expiryState) + '<div class="muted small">' + F.esc(r.expireAt) + "</div>";
            } },
            { label: "状态", render: function (r) { return F.tag(r.state); } }
          ], brows, { empty: "没有匹配的批次" }) + "</div></div>";
        }
        html += "</div>";

        html += '<div class="panel"><div class="panel-title">缺料与补货建议' +
          '<span class="panel-actions">' +
          (F.canWrite() && short.total
            ? '<button class="btn sm primary" id="sToReq">按建议生成请购</button>' : "") +
          '<span class="small muted" style="margin-left:8px">预计金额 ' + F.money(short.amount) +
          "</span></span></div>" +
          '<div class="panel-body flush">' + F.table([
            { label: "物料", render: function (r) {
              return F.esc(r.name) + '<div class="muted small mono">' + F.esc(r.code) + "</div>";
            } },
            { label: "现存量", num: true, render: function (r) { return F.qty(r.onHand) + " " + F.esc(r.unit); } },
            { label: "安全库存", num: true, render: function (r) { return F.qty(r.safetyStock); } },
            { label: "建议补货", num: true, render: function (r) {
              return '<b class="up">' + F.qty(r.suggestQty) + "</b>";
            } },
            { label: "覆盖天数", num: true, render: function (r) {
              return r.coverageDays === null ? "—" : F.qty(r.coverageDays) + " 天";
            } },
            { label: "建议下单", key: "suggestDate" },
            { label: "主供应商", render: function (r) { return F.esc(r.mainSupplier || "—"); } },
            { label: "预计金额", num: true, render: function (r) { return F.money(r.estAmount); } },
            { label: "状态", render: function (r) { return F.tag(r.state); } }
          ], short.list, { empty: "库存健康，暂无补货建议" }) + "</div></div>";

        document.getElementById("view").innerHTML = html;

        document.getElementById("sSearch").addEventListener("click", function () {
          st.kw = document.getElementById("sKw").value.trim();
          st.wh = document.getElementById("sWh").value;
          st.expiry = document.getElementById("sExpiry").checked;
          draw();
        });
        document.getElementById("sKw").addEventListener("keydown", function (e) {
          if (e.key === "Enter") document.getElementById("sSearch").click();
        });
        document.getElementById("sWh").addEventListener("change", function () {
          st.wh = this.value;
          if (st.view === "batch") draw();
        });
        document.getElementById("sExpiry").addEventListener("change", function () {
          st.expiry = this.checked;
          if (st.view === "batch") { st.view = "batch"; draw(); }
        });
        document.querySelectorAll("[data-state]").forEach(function (b) {
          b.addEventListener("click", function () { st.state = b.getAttribute("data-state"); draw(); });
        });
        document.querySelectorAll("[data-view]").forEach(function (b) {
          b.addEventListener("click", function () { st.view = b.getAttribute("data-view"); draw(); });
        });
        var tr = document.getElementById("sToReq");
        if (tr) tr.addEventListener("click", function () { toReq(short.list); });
        F.bindRows(document, function (code) { openMat(code); });

        var sideDist;
        if (batch && batch.byWarehouse && batch.byWarehouse.length) {
          sideDist = '<div class="side-block"><div class="hd">库容分布</div><div class="bd">' +
            batch.byWarehouse.map(function (w) {
              return F.kv(w.warehouse + "（" + w.c + " 行）", F.wan(w.amount));
            }).join("") + "</div></div>";
        } else {
          var abcCnt = { A: 0, B: 0, C: 0 };
          sum.list.forEach(function (x) { abcCnt[x.abc] = (abcCnt[x.abc] || 0) + 1; });
          sideDist = '<div class="side-block"><div class="hd">ABC 结构</div><div class="bd">' +
            F.kv("A 类（重点管控）", abcCnt.A + " 项") + F.kv("B 类", abcCnt.B + " 项") +
            F.kv("C 类", abcCnt.C + " 项") +
            '<div class="small muted" style="margin-top:6px">切换到「批次明细」可按仓查看库容。</div>' +
            "</div></div>";
        }
        F.setSide(sideDist +
          '<div class="side-block"><div class="hd">库存状态口径</div><div class="bd small muted" style="line-height:1.9">' +
          "补货点 = 日均耗用 × 提前期 + 安全库存（向上取整）<br>" +
          "现存量 = 0 → 缺货；低于安全库存 / 低于补货点 → 待补货；高于最大库存 → 超储。<br>" +
          "覆盖天数 = 现存量 ÷ 日均耗用。</div></div>" +
          '<div class="side-block"><div class="hd">近效期批次</div><div class="bd">' +
          (expiringCount ? '<div class="side-kv"><span>近效期 / 已过期批次</span><b class="up">' +
            expiringCount + "</b></div>" +
            '<div class="small muted" style="margin-top:6px">可在上方勾选「只看近效期」并切到批次明细定位。</div>'
            : '<div class="muted small">没有近效期库存</div>') + "</div></div>");
        F.setStatus("库存台账 · " + sum.total + " 个物料 / 金额 " + F.money(sum.amount) +
          " · 缺料 " + short.total + " 项");
      }).catch(function (e) { F.showErr(e); });
    }

    function openMat(code) {
      F.api("GET", "/api/stock?" + F.qs({ kw: code })).then(function (d) {
        var rs = d.list.filter(function (x) { return x.materialCode === code; });
        var body = '<div class="detail-head"><div class="dh-title">' + F.esc(code) + "</div>" +
          '<div class="dh-tags">' + (rs.length ? F.tag(rs[0].state) : "") +
          '<span class="tag gray">合计 ' + F.money(d.amount) + "</span></div></div>" +
          F.table([
            { label: "仓库", key: "warehouse" },
            { label: "批次", render: function (r) { return '<span class="mono small">' +
              F.esc(r.batch || "—") + "</span>"; } },
            { label: "数量", num: true, render: function (r) { return F.qty(r.qty) + " " + F.esc(r.unit); } },
            { label: "占用", num: true, render: function (r) { return F.qty(r.locked); } },
            { label: "单位成本", num: true, render: function (r) { return F.money(r.unitCost); } },
            { label: "金额", num: true, render: function (r) { return F.money(r.amount); } },
            { label: "库龄", num: true, render: function (r) { return r.ageDays + " 天"; } },
            { label: "有效期", render: function (r) {
              return r.expireAt ? F.tag(r.expiryState) + ' <span class="small muted">' + F.esc(r.expireAt) +
                "</span>" : '<span class="muted">—</span>';
            } }
          ], rs, { empty: "该物料暂无库存" });
        F.dialog("库存明细 · " + code, body,
          '<button class="btn" data-close2="1">关闭</button>' +
          (canStock() ? '<button class="btn primary" data-adjust="' + F.esc(code) + '">库存调整</button>' : ""));
        document.getElementById("dialog").querySelector("[data-close2]")
          .addEventListener("click", F.closeDialog);
        var ad = document.getElementById("dialog").querySelector("[data-adjust]");
        if (ad) ad.addEventListener("click", function () {
          F.closeDialog();
          F.go("stockops", { tab: "adjust", code: code });
        });
      }).catch(function (e) { F.showErr(e); });
    }

    function toReq(list) {
      var rowsHtml = list.map(function (r, i) {
        return '<tr><td><input type="checkbox" class="pk" data-i="' + i + '" checked></td>' +
          "<td>" + F.esc(r.name) + '<div class="muted small mono">' + F.esc(r.code) + "</div></td>" +
          '<td class="num">' + F.qty(r.onHand) + "</td>" +
          '<td class="num">' + F.qty(r.suggestQty) + "</td>" +
          '<td><input type="number" class="rq" data-i="' + i + '" value="' + r.suggestQty +
          '" style="width:110px"></td></tr>';
      }).join("");
      F.dialog("按补货建议生成请购", '<div class="small muted" style="margin-bottom:8px">' +
        "将选中物料按建议数量生成一张请购草稿，可在请购单页面继续提交审批。</div>" +
        "<table class='grid-table'><thead><tr><th style='width:40px'></th><th>物料</th>" +
        "<th class='num'>现存量</th><th class='num'>建议量</th><th>请购数量</th></tr></thead><tbody>" +
        rowsHtml + "</tbody></table>",
        '<button class="btn" data-close2="1">取消</button>' +
        '<button class="btn primary" id="rqSave">生成请购</button>');
      document.getElementById("dialog").querySelector("[data-close2]")
        .addEventListener("click", F.closeDialog);
      document.getElementById("rqSave").addEventListener("click", function () {
        var items = [];
        document.querySelectorAll("#dialog .pk").forEach(function (cb) {
          if (!cb.checked) return;
          var i = Number(cb.getAttribute("data-i"));
          var qty = Number(document.querySelector('#dialog .rq[data-i="' + i + '"]').value || 0);
          if (qty > 0) items.push({ materialCode: list[i].code, qty: qty });
        });
        if (!items.length) { F.toast("请至少选择一行并填写数量", "err"); return; }
        F.api("POST", "/api/requisitions", { dept: "计划部", purpose: "缺料补货（安全库存补足）",
          needDate: F.addDays(10), items: items }).then(function (r) {
          F.closeDialog();
          F.toast("请购草稿已生成：" + r.no + "（" + F.money(r.amount) + "）", "ok");
          F.go("requisitions");
        }).catch(function (e) { F.showErr(e); });
      });
    }

    draw();
  });

  /* ============================================================ 库存作业 */
  F.register("stockops", function (params) {
    var st = { tab: (params && params.tab) || "moves", kw: "", type: "全部" };

    function draw() {
      loadWhs().then(function () {
        var tabs = [["moves", "出入库流水"], ["transfers", "仓间调拨"], ["stocktakes", "库存盘点"],
          ["adjust", "库存调整"]].map(function (t) {
          return '<button class="' + (st.tab === t[0] ? "on" : "") + '" data-tab="' + t[0] + '">' +
            t[1] + "</button>";
        }).join("");
        var html = '<div class="panel"><div class="panel-title">库存作业' +
          '<span class="panel-actions small muted">' + (canStock() ? "当前角色可执行库存作业" :
            "当前角色只读，库存作业需仓管 / 质检角色") + "</span></div>" +
          '<div class="panel-body" style="padding-bottom:0"><div class="tabs">' + tabs + "</div></div>" +
          '<div class="panel-body" id="opsBody">加载中…</div></div>';
        document.getElementById("view").innerHTML = html;
        document.querySelectorAll("[data-tab]").forEach(function (b) {
          b.addEventListener("click", function () { st.tab = b.getAttribute("data-tab"); draw(); });
        });
        if (st.tab === "moves") return drawMoves();
        if (st.tab === "transfers") return drawTransfers();
        if (st.tab === "stocktakes") return drawStocktakes();
        return drawAdjust();
      });
    }

    function drawMoves() {
      F.api("GET", "/api/moves?" + F.qs({ kw: st.kw, type: st.type })).then(function (d) {
        var box = document.getElementById("opsBody");
        box.innerHTML = '<div class="kpi-grid three" style="margin-bottom:10px">' +
          '<div class="kpi green"><div class="k-label">入库数量合计</div><div class="k-value">' +
          F.qty(d.inQty) + "</div><div class='k-sub'>" + d.total + " 笔流水</div></div>" +
          '<div class="kpi gold"><div class="k-label">出库数量合计</div><div class="k-value">' +
          F.qty(d.outQty) + "</div><div class='k-sub'>含领用 / 调拨 / 盘亏</div></div>" +
          '<div class="kpi"><div class="k-label">净变动</div><div class="k-value">' +
          F.qty(d.inQty - d.outQty) + "</div><div class='k-sub'>按数量口径</div></div></div>" +
          '<div class="chips" style="margin-bottom:10px">' +
          ["全部"].concat(d.types).map(function (t) {
            return '<button class="chip ' + (st.type === t ? "on" : "") + '" data-type="' + t + '">' +
              t + "</button>";
          }).join("") + "</div>" +
          '<div style="display:flex;gap:8px;margin-bottom:8px">' +
          '<input id="mKw" type="text" placeholder="物料 / 单号" value="' + F.esc(st.kw) +
          '" style="width:200px"><button class="btn sm" id="mSearch">查询</button>' +
          '<span class="small muted" style="align-self:center">共 ' + d.total +
          " 笔，显示最近 60 笔</span></div>" +
          '<div style="margin:0 -14px -14px">' + F.table([
            { label: "时间", render: function (r) { return '<span class="small muted">' +
              F.esc(r.created_at) + "</span>"; } },
            { label: "流水号", render: function (r) { return '<span class="mono small">' +
              F.esc(r.no) + "</span>"; } },
            { label: "类型", render: function (r) { return F.tag(r.type); } },
            { label: "物料", render: function (r) { return F.esc(r.material_name) +
              '<div class="muted small mono">' + F.esc(r.material_code) + "</div>"; } },
            { label: "仓库", key: "warehouse" },
            { label: "批次", render: function (r) { return '<span class="mono small">' +
              F.esc(r.batch || "—") + "</span>"; } },
            { label: "数量", num: true, render: function (r) {
              var out = /出库|盘亏/.test(r.type);
              return '<b class="' + (out ? "down" : "up") + '">' + (out ? "−" : "+") + F.qty(r.qty) + "</b>";
            } },
            { label: "金额", num: true, render: function (r) { return F.money(r.cost); } },
            { label: "来源单据", render: function (r) { return r.ref_no
              ? '<span class="mono small">' + F.esc(r.ref_no) + "</span>" : "—"; } },
            { label: "原因", render: function (r) { return '<span class="small muted">' +
              F.esc(r.reason || "—") + "</span>"; } },
            { label: "操作员", render: function (r) { return F.esc(r.operator || "—"); } }
          ], d.list.slice(0, 60), { empty: "暂无流水" }) + "</div>";
        document.getElementById("mSearch").addEventListener("click", function () {
          st.kw = document.getElementById("mKw").value.trim(); draw();
        });
        document.querySelectorAll("[data-type]").forEach(function (b) {
          b.addEventListener("click", function () { st.type = b.getAttribute("data-type"); draw(); });
        });
        F.setStatus("出入库流水 · " + d.total + " 笔");
        F.setSide('<div class="side-block"><div class="hd">流水口径</div><div class="bd small muted" ' +
          'style="line-height:1.9">采购入库来自收货质检过账；领用出库、盘盈盘亏由库存作业与盘点生成；' +
          "调拨会同时写入调出仓与调入仓两条流水，方向以类型的「出库 / 入库」判定。</div></div>");
      }).catch(function (e) { F.showErr(e); });
    }

    function drawTransfers() {
      F.api("GET", "/api/transfers").then(function (d) {
        var box = document.getElementById("opsBody");
        box.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;' +
          'margin-bottom:8px"><div class="small muted">调拨单共 ' + d.total + " 张</div>" +
          (canStock() ? '<button class="btn sm primary" id="tNew">+ 新建调拨</button>' : "") + "</div>" +
          '<div style="margin:0 -14px -14px">' + F.table([
            { label: "单号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
            { label: "调出 → 调入", render: function (r) {
              return F.esc(r.fromWh) + ' <span class="muted">→</span> ' + F.esc(r.toWh);
            } },
            { label: "明细", num: true, render: function (r) { return r.itemCount + " 行"; } },
            { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
            { label: "状态", render: function (r) { return F.tag(r.status); } },
            { label: "申请人", render: function (r) { return F.esc(r.applicant || "—"); } },
            { label: "审批人", render: function (r) { return F.esc(r.approver || "—"); } },
            { label: "创建时间", render: function (r) { return '<span class="small muted">' +
              F.esc(r.createdAt) + "</span>"; } },
            { label: "操作", render: function (r) {
              if (!canStock()) return "—";
              var btn = [];
              if (r.status === "草稿") btn.push('<button class="btn xs" data-ap="' + F.esc(r.no) + '">审批</button>');
              if (r.status === "已审批") btn.push('<button class="btn xs primary" data-post="' +
                F.esc(r.no) + '">执行调拨</button>');
              return btn.join(" ") || "—";
            } }
          ], d.list, { click: function (r) { return r.no; }, empty: "暂无调拨单" }) + "</div>";
        var nb = document.getElementById("tNew");
        if (nb) nb.addEventListener("click", newTransfer);
        F.bindRows(document, function (no) { openTransfer(no, d.list); });
        document.querySelectorAll("[data-ap]").forEach(function (b) {
          b.addEventListener("click", function (ev) {
            ev.stopPropagation();
            F.api("POST", "/api/transfers/" + encodeURIComponent(b.getAttribute("data-ap")) + "/approve", {})
              .then(function () { F.toast("调拨单已审批", "ok"); draw(); })
              .catch(function (e) { F.showErr(e); });
          });
        });
        document.querySelectorAll("[data-post]").forEach(function (b) {
          b.addEventListener("click", function (ev) {
            ev.stopPropagation();
            if (!window.confirm("执行调拨将立即扣减调出仓库存并增加调入仓库存，确认执行？")) return;
            F.api("POST", "/api/transfers/" + encodeURIComponent(b.getAttribute("data-post")) + "/post", {})
              .then(function () { F.toast("调拨已执行，库存已过账", "ok"); draw(); })
              .catch(function (e) { F.showErr(e); });
          });
        });
        F.setStatus("仓间调拨 · " + d.total + " 张");
        F.setSide('<div class="side-block"><div class="hd">调拨流程</div><div class="bd small muted" ' +
          'style="line-height:1.9">草稿 → 已审批 → 已完成<br>仓管 / 管理员新建时直接进入已审批；' +
          "执行时逐行校验调出仓库存，任一不足则整单失败、不做部分过账。</div></div>");
      }).catch(function (e) { F.showErr(e); });
    }

    function newTransfer() {
      F.api("GET", "/api/materials").then(function (md) {
        var opts = md.list.map(function (m) {
          return '<option value="' + F.esc(m.code) + '">' + F.esc(m.code + " " + m.name) + "</option>";
        }).join("");
        F.dialog("新建调拨单", '<div class="form-grid">' +
          '<label>调出仓</label><select id="tFrom">' + whOptions("", false) + "</select>" +
          '<label>调入仓</label><select id="tTo">' + whOptions("", false) + "</select>" +
          '<label>备注</label><input id="tRemark" type="text" placeholder="如：生产备料移库"></div>' +
          '<div class="section-title" style="margin-top:10px">调拨明细</div><div id="tLines"></div>' +
          '<button class="btn sm" id="tAdd" style="margin-top:8px">+ 增加一行</button>',
          '<button class="btn" data-close2="1">取消</button>' +
          '<button class="btn primary" id="tSave">保存</button>');
        document.getElementById("dialog").querySelector("[data-close2]")
          .addEventListener("click", F.closeDialog);
        function addLine() {
          var row = document.createElement("div");
          row.className = "t-line";
          row.style.cssText = "display:flex;gap:8px;margin-bottom:6px";
          row.innerHTML = '<select class="tlMat" style="flex:1">' + opts + "</select>" +
            '<input class="tlQty" type="number" value="10" style="width:120px">';
          document.getElementById("tLines").appendChild(row);
        }
        addLine();
        document.getElementById("tAdd").addEventListener("click", addLine);
        document.getElementById("tSave").addEventListener("click", function () {
          var items = [];
          document.querySelectorAll("#tLines .t-line").forEach(function (row) {
            var code = row.querySelector(".tlMat").value;
            var qty = Number(row.querySelector(".tlQty").value || 0);
            if (code && qty > 0) items.push({ materialCode: code, qty: qty });
          });
          F.api("POST", "/api/transfers", {
            fromWh: document.getElementById("tFrom").value,
            toWh: document.getElementById("tTo").value,
            remark: document.getElementById("tRemark").value.trim(),
            items: items
          }).then(function (r) {
            F.closeDialog();
            F.toast("调拨单已创建：" + r.no + "（" + r.status + "）", "ok");
            draw();
          }).catch(function (e) { F.showErr(e); });
        });
      });
    }

    function openTransfer(no, list) {
      var r = list.filter(function (x) { return x.no === no; })[0];
      if (!r) return;
      F.dialog("调拨单 " + no, '<div class="detail-head"><div class="dh-title">' + F.esc(r.fromWh) +
        ' → ' + F.esc(r.toWh) + '</div><div class="dh-tags">' + F.tag(r.status) + "</div></div>" +
        '<div class="form-grid" style="grid-template-columns:110px 1fr 110px 1fr;margin-bottom:10px">' +
        '<label>申请人</label><div>' + F.esc(r.applicant || "—") + "</div>" +
        '<label>审批人</label><div>' + F.esc(r.approver || "—") + "</div>" +
        '<label>备注</label><div>' + F.esc(r.remark || "—") + "</div>" +
        '<label>创建时间</label><div class="small muted">' + F.esc(r.createdAt) + "</div></div>" +
        F.table([
          { label: "物料", render: function (i) { return F.esc(i.materialName) +
            '<div class="muted small mono">' + F.esc(i.materialCode) + "</div>"; } },
          { label: "数量", num: true, render: function (i) { return F.qty(i.qty) + " " + F.esc(i.unit); } }
        ], r.items || [], { empty: "无明细" }),
        '<button class="btn" data-close2="1">关闭</button>');
      document.getElementById("dialog").querySelector("[data-close2]")
        .addEventListener("click", F.closeDialog);
    }

    function drawStocktakes() {
      F.api("GET", "/api/stocktakes").then(function (d) {
        var box = document.getElementById("opsBody");
        box.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;' +
          'margin-bottom:8px"><div class="small muted">盘点单共 ' + d.total + " 张</div>" +
          (canStock() ? '<button class="btn sm primary" id="kNew">+ 发起盘点</button>' : "") + "</div>" +
          '<div style="margin:0 -14px -14px">' + F.table([
            { label: "单号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
            { label: "仓库", key: "warehouse" },
            { label: "明细", num: true, render: function (r) { return r.itemCount + " 行"; } },
            { label: "差异行", num: true, render: function (r) {
              return r.diffCount ? '<b class="up">' + r.diffCount + "</b>" : "0";
            } },
            { label: "差异金额", num: true, render: function (r) {
              return r.diffAmount ? '<b class="' + (r.diffAmount > 0 ? "up" : "down") + '">' +
                F.money(r.diffAmount) + "</b>" : "0.00";
            } },
            { label: "状态", render: function (r) { return F.tag(r.status); } },
            { label: "发起人", render: function (r) { return F.esc(r.applicant || "—"); } },
            { label: "完成人", render: function (r) { return F.esc(r.approver || "—"); } },
            { label: "操作", render: function (r) {
              if (!canStock() || r.status === "已完成") return "—";
              return '<button class="btn xs primary" data-finish="' + F.esc(r.no) + '">录入实盘</button>';
            } }
          ], d.list, { click: function (r) { return r.no; }, empty: "暂无盘点单" }) + "</div>";
        var nb = document.getElementById("kNew");
        if (nb) nb.addEventListener("click", newStocktake);
        F.bindRows(document, function (no) { openStocktake(no, d.list); });
        document.querySelectorAll("[data-finish]").forEach(function (b) {
          b.addEventListener("click", function (ev) {
            ev.stopPropagation();
            var no = b.getAttribute("data-finish");
            finishStocktake(no, d.list.filter(function (x) { return x.no === no; })[0]);
          });
        });
        F.setStatus("库存盘点 · " + d.total + " 张");
        F.setSide('<div class="side-block"><div class="hd">盘点口径</div><div class="bd small muted" ' +
          'style="line-height:1.9">发起盘点即按所选仓库快照全部批次账面数量；录入实盘后差异不为 0 的行' +
          "会写盘盈 / 盘亏流水并直接调整库存，差异金额同步记入盘点单。</div></div>");
      }).catch(function (e) { F.showErr(e); });
    }

    function newStocktake() {
      F.dialog("发起盘点", '<div class="form-grid">' +
        '<label>盘点仓库</label><select id="kWh">' + whOptions("", false) + "</select>" +
        '<label>备注</label><input id="kRemark" type="text" placeholder="如：Q4 季度全盘"></div>' +
        '<div class="small muted" style="margin-top:8px">发起后按该仓库现有库存批次生成盘点行。</div>',
        '<button class="btn" data-close2="1">取消</button>' +
        '<button class="btn primary" id="kSave">发起盘点</button>');
      document.getElementById("dialog").querySelector("[data-close2]")
        .addEventListener("click", F.closeDialog);
      document.getElementById("kSave").addEventListener("click", function () {
        F.api("POST", "/api/stocktakes", {
          warehouse: document.getElementById("kWh").value,
          remark: document.getElementById("kRemark").value.trim()
        }).then(function (r) {
          F.closeDialog();
          F.toast("盘点单已发起：" + r.no + "（" + r.lines + " 行）", "ok");
          draw();
        }).catch(function (e) { F.showErr(e); });
      });
    }

    function openStocktake(no, list) {
      var r = list.filter(function (x) { return x.no === no; })[0];
      if (!r) return;
      F.dialog("盘点单 " + no, '<div class="detail-head"><div class="dh-title">' + F.esc(r.warehouse) +
        '</div><div class="dh-tags">' + F.tag(r.status) + '<span class="tag gray">差异 ' +
        F.money(r.diffAmount) + "</span></div></div>" +
        F.table([
          { label: "物料", render: function (i) { return F.esc(i.materialName) +
            '<div class="muted small mono">' + F.esc(i.materialCode) + "</div>"; } },
          { label: "批次", render: function (i) { return '<span class="mono small">' +
            F.esc(i.batch || "—") + "</span>"; } },
          { label: "账面", num: true, render: function (i) { return F.qty(i.bookQty); } },
          { label: "实盘", num: true, render: function (i) { return F.qty(i.realQty); } },
          { label: "差异", num: true, render: function (i) {
            return i.diffQty ? '<b class="' + (i.diffQty > 0 ? "up" : "down") + '">' +
              F.qty(i.diffQty) + "</b>" : "0";
          } },
          { label: "差异金额", num: true, render: function (i) { return F.money(i.cost * i.diffQty); } }
        ], r.items || [], { empty: "无盘点行" }),
        '<button class="btn" data-close2="1">关闭</button>');
      document.getElementById("dialog").querySelector("[data-close2]")
        .addEventListener("click", F.closeDialog);
    }

    function finishStocktake(no, r) {
      if (!r) return;
      var rowsHtml = (r.items || []).map(function (i, idx) {
        return "<tr><td>" + F.esc(i.materialName) + '<div class="muted small mono">' + F.esc(i.materialCode) +
          '</div></td><td class="mono small">' + F.esc(i.batch || "—") + '</td><td class="num">' +
          F.qty(i.bookQty) + '</td><td><input type="number" class="kv-real" data-i="' + idx +
          '" value="' + i.bookQty + '" style="width:110px"></td><td class="num kv-diff" data-i="' + idx +
          '">0</td></tr>';
      }).join("");
      F.dialog("录入实盘 · " + no, '<div class="small muted" style="margin-bottom:8px">' +
        "修改实盘数量后提交，差异行会自动写盘盈 / 盘亏流水。</div>" +
        "<table class='grid-table'><thead><tr><th>物料</th><th>批次</th><th class='num'>账面</th>" +
        "<th>实盘</th><th class='num'>差异</th></tr></thead><tbody>" + rowsHtml + "</tbody></table>",
        '<button class="btn" data-close2="1">取消</button>' +
        '<button class="btn primary" id="kFinish">完成盘点</button>');
      document.getElementById("dialog").querySelector("[data-close2]")
        .addEventListener("click", F.closeDialog);
      document.querySelectorAll("#dialog .kv-real").forEach(function (inp) {
        inp.addEventListener("input", function () {
          var i = Number(inp.getAttribute("data-i"));
          var it = r.items[i];
          var diff = Number(inp.value || 0) - Number(it.bookQty || 0);
          var cell = document.querySelector('#dialog .kv-diff[data-i="' + i + '"]');
          cell.textContent = diff === 0 ? "0" : (diff > 0 ? "+" : "") + F.qty(diff);
          cell.className = "num kv-diff " + (diff > 0 ? "up" : diff < 0 ? "down" : "");
        });
      });
      document.getElementById("kFinish").addEventListener("click", function () {
        var items = [];
        document.querySelectorAll("#dialog .kv-real").forEach(function (inp) {
          var i = Number(inp.getAttribute("data-i"));
          items.push({ materialCode: r.items[i].materialCode, batch: r.items[i].batch,
            realQty: Number(inp.value || 0) });
        });
        F.api("POST", "/api/stocktakes/" + encodeURIComponent(no) + "/finish", { items: items })
          .then(function (res) {
            F.closeDialog();
            F.toast("盘点已完成，差异金额 " + F.money(res.diffAmount), "ok");
            draw();
          }).catch(function (e) { F.showErr(e); });
      });
    }

    function drawAdjust() {
      var code = (F.state.params && F.state.params.code) || "";
      F.api("GET", "/api/materials").then(function (md) {
        var opts = md.list.map(function (m) {
          return '<option value="' + F.esc(m.code) + '"' + (m.code === code ? " selected" : "") + ">" +
            F.esc(m.code + " " + m.name + "（" + m.unit + "）") + "</option>";
        }).join("");
        var box = document.getElementById("opsBody");
        if (!canStock()) {
          box.innerHTML = '<div class="warn-box">当前角色（' + F.esc(me().role_label || me().role) +
            "）没有库存作业权限，库存调整需仓管 / 质检 / 管理员角色。</div>";
          F.setStatus("库存调整 · 无权限");
          return;
        }
        box.innerHTML = '<div class="form-grid" style="max-width:760px">' +
          '<label>物料</label><select id="aMat">' + opts + "</select>" +
          '<label>仓库</label><select id="aWh">' + whOptions("", false) + "</select>" +
          '<label>调整类型</label><select id="aType">' +
          ["盘盈", "盘亏", "领用出库", "其他入库"].map(function (t) {
            return "<option>" + t + "</option>";
          }).join("") + "</select>" +
          '<label>批次</label><input id="aBatch" type="text" placeholder="留空自动生成">' +
          '<label>数量</label><input id="aQty" type="number" value="1">' +
          '<label>原因</label><input id="aReason" type="text" placeholder="如：线边仓退料 / 试制领用">' +
          "</div>" +
          '<div style="margin-top:12px"><button class="btn primary" id="aSave">提交调整</button>' +
          '<span class="small muted" style="margin-left:10px">' +
          "盘亏 / 领用出库会校验库存充足；每次调整都会写一条流水并推送 stock.adjusted 事件。</span></div>";
        document.getElementById("aSave").addEventListener("click", function () {
          F.api("POST", "/api/stock/adjust", {
            materialCode: document.getElementById("aMat").value,
            warehouse: document.getElementById("aWh").value,
            type: document.getElementById("aType").value,
            batch: document.getElementById("aBatch").value.trim(),
            qty: Number(document.getElementById("aQty").value || 0),
            reason: document.getElementById("aReason").value.trim()
          }).then(function (r) {
            F.toast("库存已调整：" + r.type + " " + r.materialCode + " " + F.qty(r.qty), "ok");
            draw();
          }).catch(function (e) { F.showErr(e); });
        });
        F.setStatus("库存调整 · 手工过账入口");
        F.setSide('<div class="side-block"><div class="hd">可用类型</div><div class="bd small muted" ' +
          'style="line-height:1.9">盘盈 / 其他入库 → 增加库存；盘亏 / 领用出库 → 减少库存。<br>' +
          "采购入库请走收货质检页面的「入库过账」，仓间移库请用调拨单，避免口径混乱。</div></div>");
      }).catch(function (e) { F.showErr(e); });
    }

    draw();
  });
})(window, document);

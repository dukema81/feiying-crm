/* 飞泉 SCM · 请购、询价比价、采购订单、收货质检 */
(function (window, document) {
  "use strict";
  var F = window.F;

  var cache = { mats: null, sups: null, whs: null };
  function mats() {
    if (cache.mats) return Promise.resolve(cache.mats);
    return F.api("GET", "/api/materials").then(function (d) { cache.mats = d.list; return d.list; });
  }
  function sups() {
    if (cache.sups) return Promise.resolve(cache.sups);
    return F.api("GET", "/api/suppliers").then(function (d) { cache.sups = d.list; return d.list; });
  }
  function whs() {
    if (cache.whs) return Promise.resolve(cache.whs);
    return F.api("GET", "/api/warehouses").then(function (d) { cache.whs = d; return d; });
  }
  F.mdmCache = cache;

  /* ============================================================ 请购单 */
  F.register("requisitions", function () {
    var st = { status: "全部", kw: "" };

    function draw() {
      F.api("GET", "/api/requisitions?" + F.qs({ status: st.status, kw: st.kw })).then(function (d) {
        var counts = { "全部": d.total };
        d.list.forEach(function (r) { counts[r.status] = (counts[r.status] || 0) + 1; });
        var chips = ["全部", "草稿", "待审批", "已审批", "已转单", "已驳回"].map(function (s) {
          return '<button class="chip ' + (st.status === s ? "on" : "") + '" data-st="' + s + '">' + s +
            "<b>" + (counts[s] || 0) + "</b></button>";
        }).join("");
        var html = '<div class="panel"><div class="panel-title">请购单' +
          '<span class="panel-actions"><input id="fKw" type="text" placeholder="单号 / 用途 / 部门" value="' +
          F.esc(st.kw) + '" style="width:180px">' +
          '<button class="btn sm" id="btnSearch">查询</button>' +
          (F.canWrite() ? '<button class="btn sm primary" id="rNew">+ 新建请购</button>' : "") +
          "</span></div>" +
          '<div class="panel-body"><div class="chips">' + chips + "</div></div>" +
          '<div class="panel-body flush">' +
          F.table([
            { label: "单号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
            { label: "部门 / 用途", render: function (r) { return F.esc(r.dept) + ' <span class="muted small">' +
              F.esc(r.purpose) + "</span>"; } },
            { label: "需求日期", key: "needDate" },
            { label: "明细", num: true, render: function (r) { return r.itemCount + " 行"; } },
            { label: "金额", num: true, render: function (r) { return F.money(r.amount); } },
            { label: "状态", render: function (r) { return F.tag(r.status); } },
            { label: "申请人", render: function (r) { return F.esc(r.applicantName || r.applicant); } },
            { label: "转单", render: function (r) { return r.convertedNo
              ? '<span class="mono small">' + F.esc(r.convertedNo) + "</span>" : "—"; } }
          ], d.list, { click: function (r) { return r.no; }, empty: "没有匹配的请购单" }) +
          "</div></div>";
        document.getElementById("view").innerHTML = html;
        document.getElementById("btnSearch").addEventListener("click", function () {
          st.kw = document.getElementById("fKw").value.trim(); draw();
        });
        document.getElementById("fKw").addEventListener("keydown", function (e) {
          if (e.key === "Enter") document.getElementById("btnSearch").click();
        });
        document.querySelectorAll("[data-st]").forEach(function (b) {
          b.addEventListener("click", function () { st.status = b.getAttribute("data-st"); draw(); });
        });
        var nb = document.getElementById("rNew");
        if (nb) nb.addEventListener("click", newReq);
        F.bindRows(document, openReq);
        F.setStatus("请购单 · " + d.total + " 张（待审批 " + (counts["待审批"] || 0) + "）");
        F.setSide('<div class="side-block"><div class="hd">流程</div><div class="bd small muted" style="line-height:1.9">' +
          "草稿 → 待审批 → 已审批 → 转采购订单 / 发起询价<br>" +
          "低于「请购免审批金额」的请购由总监提交时自动通过；批准时校验部门季度预算。</div></div>");
      });
    }

    function newReq() {
      mats().then(function (list) {
        var opts = list.map(function (m) {
          return '<option value="' + F.esc(m.code) + '">' + F.esc(m.code + " " + m.name + "（" + m.unit + "）") + "</option>";
        }).join("");
        var body = '<div class="form-grid">' +
          '<label>需求部门</label><select id="nDept">' + ["计划部", "生产部", "研发部", "仓储部"]
            .map(function (s) { return "<option>" + s + "</option>"; }).join("") + "</select>" +
          '<label>需求日期</label><input id="nNeed" type="date" value="' + F.addDays(14) + '">' +
          '<label>用途</label><input id="nPurpose" type="text" value="Q4 量产备料">' +
          '<label>备注</label><input id="nRemark" type="text">' +
          "</div>" +
          '<div class="section-title" style="margin-top:10px">明细</div>' +
          '<div id="lines"></div><button class="btn sm" id="addLine" style="margin-top:8px">+ 增加一行</button>';
        F.dialog("新建请购", body,
          '<button class="btn" data-close2="1">取消</button><button class="btn primary" id="nSave">保存草稿</button>');
        var dlg = document.getElementById("dialog");
        dlg.querySelector("[data-close2]").addEventListener("click", F.closeDialog);
        var idx = 0;
        function addLine() {
          idx += 1;
          var row = document.createElement("div");
          row.className = "form-row";
          row.style.cssText = "display:flex;gap:8px;margin-bottom:6px";
          row.innerHTML = '<select class="lnMat" style="flex:1">' + opts + "</select>" +
            '<input class="lnQty" type="number" placeholder="数量" style="width:110px" value="100">' +
            '<input class="lnPrice" type="number" step="0.01" placeholder="估价" style="width:110px">';
          document.getElementById("lines").appendChild(row);
          var sel = row.querySelector(".lnMat");
          sel.addEventListener("change", function () {
            var m = list.filter(function (x) { return x.code === sel.value; })[0];
            if (m) row.querySelector(".lnPrice").value = m.standardPrice;
          });
          var first = list[0];
          if (first) { sel.value = first.code; row.querySelector(".lnPrice").value = first.standardPrice; }
        }
        addLine();
        document.getElementById("addLine").addEventListener("click", addLine);
        document.getElementById("nSave").addEventListener("click", function () {
          var items = [];
          document.querySelectorAll("#lines .form-row").forEach(function (row) {
            var code = row.querySelector(".lnMat").value;
            var qty = Number(row.querySelector(".lnQty").value || 0);
            if (code && qty > 0) {
              items.push({ materialCode: code, qty: qty,
                estPrice: Number(row.querySelector(".lnPrice").value || 0) });
            }
          });
          if (!items.length) { F.toast("请至少填写一行有效明细", "err"); return; }
          F.api("POST", "/api/requisitions", {
            dept: document.getElementById("nDept").value,
            needDate: document.getElementById("nNeed").value,
            purpose: document.getElementById("nPurpose").value.trim(),
            remark: document.getElementById("nRemark").value.trim(),
            items: items
          }).then(function (r) {
            F.closeDialog();
            F.toast("请购已创建：" + r.no + "（" + F.money(r.amount) + "）", "ok");
            draw();
          }).catch(function (e) { F.showErr(e); });
        });
      });
    }

    function openReq(no) {
      F.api("GET", "/api/requisitions/" + encodeURIComponent(no)).then(function (r) {
        var body = '<div class="detail-head"><div class="dh-title">' + F.esc(r.no) + " " + F.esc(r.purpose) +
          '</div><div class="dh-tags">' + F.tag(r.status) + "</div></div>" +
          '<div class="form-grid" style="margin-top:6px">' +
          "<div><span class='muted small'>部门</span><br>" + F.esc(r.dept) + "</div>" +
          "<div><span class='muted small'>申请人</span><br>" + F.esc(r.applicantName || r.applicant) + "</div>" +
          "<div><span class='muted small'>需求日期</span><br>" + F.esc(r.needDate) + "</div>" +
          "<div><span class='muted small'>金额</span><br>" + F.money(r.amount) + "</div>" +
          "<div><span class='muted small'>审批人</span><br>" + F.esc(r.approverName || "—") + "</div>" +
          "<div><span class='muted small'>关联单据</span><br>" + F.esc(r.convertedNo || "—") + "</div>" +
          "</div>" + (r.rejectReason ? '<div class="warn-box" style="margin-top:8px">驳回原因：' +
            F.esc(r.rejectReason) + "</div>" : "") +
          '<div class="section-title" style="margin-top:10px">明细</div>' +
          F.table([
            { label: "物料", render: function (x) { return F.esc(x.materialCode) + " " + F.esc(x.materialName); } },
            { label: "规格", render: function (x) { return '<span class="small muted">' + F.esc(x.spec) + "</span>"; } },
            { label: "数量", num: true, render: function (x) { return F.qty(x.qty) + " " + F.esc(x.unit); } },
            { label: "估价", num: true, render: function (x) { return F.money(x.estPrice); } },
            { label: "金额", num: true, render: function (x) { return F.money(x.amount); } }
          ], r.items);
        var acts = [];
        if (r.status === "草稿") acts.push('<button class="btn primary" id="aSubmit">提交审批</button>');
        if (r.status === "待审批" && F.canApprove()) {
          acts.push('<button class="btn primary" id="aApprove">批准</button>');
          acts.push('<button class="btn" id="aReject">驳回</button>');
        }
        if (r.status === "已审批") {
          acts.push('<button class="btn primary" id="aToPo">转采购订单</button>');
          acts.push('<button class="btn" id="aToRfq">发起询价</button>');
        }
        if (["草稿", "待审批", "已审批"].indexOf(r.status) >= 0) {
          acts.push('<button class="btn" id="aCancel">取消请购</button>');
        }
        F.dialog("请购单 " + r.no, body, acts.join("") + '<button class="btn" data-close3="1">关闭</button>');
        var dlg = document.getElementById("dialog");
        dlg.querySelector("[data-close3]").addEventListener("click", F.closeDialog);

        function act(id, fn) { var b = document.getElementById(id); if (b) b.addEventListener("click", fn); }
        act("aSubmit", function () {
          F.api("POST", "/api/requisitions/" + r.no + "/submit", {}).then(function (x) {
            F.closeDialog();
            F.toast(x.auto ? "已自动通过（低于免审批金额）" : "已提交，等待审批", "ok");
            draw();
          }).catch(function (e) { F.showErr(e); });
        });
        act("aApprove", function () {
          F.api("POST", "/api/requisitions/" + r.no + "/approve", {}).then(function () {
            F.closeDialog(); F.toast("已批准：" + r.no, "ok"); draw();
          }).catch(function (e) { F.showErr(e); });
        });
        act("aReject", function () {
          var why = window.prompt("驳回原因（至少 2 个字）", "预算不足，改为分批发起");
          if (why === null) return;
          F.api("POST", "/api/requisitions/" + r.no + "/reject", { reason: why }).then(function () {
            F.closeDialog(); F.toast("已驳回", "ok"); draw();
          }).catch(function (e) { F.showErr(e); });
        });
        act("aCancel", function () {
          F.api("POST", "/api/requisitions/" + r.no + "/cancel", {}).then(function () {
            F.closeDialog(); F.toast("已取消", "ok"); draw();
          }).catch(function (e) { F.showErr(e); });
        });
        act("aToPo", function () { toPo(r); });
        act("aToRfq", function () { toRfq(r); });
      }).catch(function (e) { F.showErr(e); });
    }

    function toPo(r) {
      sups().then(function (list) {
        var ok = list.filter(function (s) { return s.status === "已准入"; });
        if (!ok.length) { F.toast("没有已准入的供应商，请先完成准入", "err"); return; }
        var body = '<div class="form-grid"><label>供应商 *</label><select id="pSup">' +
          ok.map(function (s) {
            return '<option value="' + s.code + '">' + F.esc(s.name + "（" + s.level + " 级 · 账期 " +
              s.paymentTerms + " 天）") + "</option>";
          }).join("") + "</select>" +
          '<label>承诺到货</label><input id="pPromise" type="date" value="' + F.addDays(20) + '">' +
          '<label>价格口径</label><select id="pMode"><option value="est">按请购估价</option>' +
          '<option value="standard">按物料标准价</option></select></div>' +
          '<div class="small muted" style="margin-top:8px">转单后生成采购订单草稿，需再提交审批才能下单。</div>';
        F.dialog("转采购订单", body,
          '<button class="btn" data-close4="1">取消</button><button class="btn primary" id="pSave">生成订单</button>');
        var dlg = document.getElementById("dialog");
        dlg.querySelector("[data-close4]").addEventListener("click", F.closeDialog);
        document.getElementById("pSave").addEventListener("click", function () {
          F.api("POST", "/api/requisitions/" + r.no + "/to-order", {
            supplierCode: document.getElementById("pSup").value,
            promiseDate: document.getElementById("pPromise").value,
            priceMode: document.getElementById("pMode").value
          }).then(function (x) {
            F.closeDialog();
            F.toast("已生成采购订单：" + x.poNo, "ok");
            draw();
            F.go("orders");
          }).catch(function (e) { F.showErr(e); });
        });
      });
    }

    function toRfq(r) {
      sups().then(function (list) {
        var ok = list.filter(function (s) { return s.status === "已准入"; });
        var body = '<div class="small muted" style="margin-bottom:8px">勾选参与询价的供应商（至少 2 家）</div>' +
          ok.map(function (s, i) {
            return '<label style="display:block;margin-bottom:4px"><input type="checkbox" class="rfqSup" value="' +
              F.esc(s.code) + '"' + (i < 3 ? " checked" : "") + "> " + F.esc(s.name) + "（" +
              s.level + " 级）</label>";
          }).join("") +
          '<div class="form-grid" style="margin-top:8px"><label>报价截止</label>' +
          '<input id="rfqDeadline" type="date" value="' + F.addDays(7) + '"></div>';
        F.dialog("发起询价", body,
          '<button class="btn" data-close5="1">取消</button><button class="btn primary" id="rfqSave">创建询价单</button>');
        var dlg = document.getElementById("dialog");
        dlg.querySelector("[data-close5]").addEventListener("click", F.closeDialog);
        document.getElementById("rfqSave").addEventListener("click", function () {
          var codes = [];
          document.querySelectorAll(".rfqSup").forEach(function (cb) {
            if (cb.checked) codes.push(cb.value);
          });
          F.api("POST", "/api/requisitions/" + r.no + "/to-rfq", {
            supplierCodes: codes, deadline: document.getElementById("rfqDeadline").value
          }).then(function (x) {
            F.closeDialog();
            F.toast("询价单已创建：" + x.rfqNo, "ok");
            F.go("rfqs");
          }).catch(function (e) { F.showErr(e); });
        });
      });
    }
    F.openReq = openReq;
    draw();
  });

  /* ============================================================ 询价比价 */
  F.register("rfqs", function () {
    function draw() {
      F.api("GET", "/api/rfqs").then(function (d) {
        var html = '<div class="panel"><div class="panel-title">询价比价' +
          '<span class="panel-actions small muted">报价家数不足 ' +
          ((F.state.boot.rules || []).filter(function (r) { return r.code === "rfq_min_suppliers"; })[0] || {}).value +
          " 家不允许定标</span></div><div class='panel-body flush'>" +
          F.table([
            { label: "询价单", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
            { label: "标题", render: function (r) { return F.esc(r.title) +
              '<div class="muted small">请购 ' + F.esc(r.reqNo || "—") + "</div>"; } },
            { label: "报价家数", num: true, render: function (r) { return r.quoteCount; } },
            { label: "最低报价", num: true, render: function (r) { return r.bestAmount ? F.money(r.bestAmount) : "—"; } },
            { label: "价差", num: true, render: function (r) { return r.spread ? F.money(r.spread) : "—"; } },
            { label: "定标", render: function (r) { return r.awardedSupplier
              ? F.esc(r.awardedSupplier) + '<div class="muted small">' + F.money(r.awardedAmount) + "</div>" : "—"; } },
            { label: "截止", key: "deadline" },
            { label: "状态", render: function (r) { return F.tag(r.status); } }
          ], d.list, { click: function (r) { return r.no; }, empty: "暂无询价单（可从请购单发起）" }) +
          "</div></div>";
        document.getElementById("view").innerHTML = html;
        F.bindRows(document, openRfq);
        F.setStatus("询价比价 · " + d.total + " 张");
        F.setSide('<div class="side-block"><div class="hd">比价口径</div><div class="bd small muted" style="line-height:1.9">' +
          "· 定标前至少 2 家有效报价<br>· 定标后自动按标准价占比分摊生成采购订单<br>" +
          "· 报价含税到厂价，价格指数 = 成交价 ÷ 市场均价</div></div>");
      });
    }

    function openRfq(no) {
      F.api("GET", "/api/rfqs/" + encodeURIComponent(no)).then(function (r) {
        var min = r.minSuppliers || 2;
        var body = '<div class="detail-head"><div class="dh-title">' + F.esc(r.no) + " " + F.esc(r.title) +
          '</div><div class="dh-tags">' + F.tag(r.status) + "</div></div>" +
          '<div class="form-grid" style="margin-top:6px">' +
          "<div><span class='muted small'>关联请购</span><br>" + F.esc(r.reqNo || "—") + "</div>" +
          "<div><span class='muted small'>报价截止</span><br>" + F.esc(r.deadline) + "</div>" +
          "<div><span class='muted small'>采购员</span><br>" + F.esc(r.ownerName || r.owner) + "</div>" +
          "<div><span class='muted small'>最少报价家数</span><br>" + min + " 家</div></div>" +
          '<div class="section-title" style="margin-top:10px">询价明细</div>' +
          F.table([{ label: "物料", render: function (x) { return F.esc(x.materialCode) + " " + F.esc(x.materialName); } },
            { label: "数量", num: true, render: function (x) { return F.qty(x.qty) + " " + F.esc(x.unit); } }], r.items) +
          '<div class="section-title" style="margin-top:10px">供应商报价</div>' +
          F.table([
            { label: "供应商", render: function (x) { return F.esc(x.supplierName) +
              (x.awarded ? ' <span class="tag green">定标</span>' : ""); } },
            { label: "报价", num: true, render: function (x) { return F.money(x.amount); } },
            { label: "交期（天）", num: true, render: function (x) { return x.leadDays; } },
            { label: "报价值", render: function (x) {
              if (!r.bestAmount) return "—";
              var diff = x.amount - r.bestAmount;
              return diff <= 0 ? '<span class="down">最低</span>' : '<span class="up">+' + F.money(diff) + "</span>";
            } },
            { label: "备注", render: function (x) { return '<span class="small muted">' + F.esc(x.remark || "—") + "</span>"; } }
          ], r.quotes, { empty: "尚无报价" });
        var acts = [];
        if (r.status === "询价中") {
          acts.push('<button class="btn" id="qAdd">登记报价</button>');
          if (F.canApprove()) acts.push('<button class="btn primary" id="qAward">定标并生成订单</button>');
        }
        F.dialog("询价单 " + r.no, body, acts.join("") + '<button class="btn" data-close3="1">关闭</button>');
        var dlg = document.getElementById("dialog");
        dlg.querySelector("[data-close3]").addEventListener("click", F.closeDialog);
        var qa = document.getElementById("qAdd");
        if (qa) {
          qa.addEventListener("click", function () {
            var opts = (r.supplierOptions || []).map(function (s) {
              return '<option value="' + F.esc(s.code) + '">' + F.esc(s.name + "（" + s.level + " 级）") + "</option>";
            }).join("");
            F.dialog("登记报价",
              '<div class="form-grid"><label>供应商</label><select id="qSup">' + opts + "</select>" +
              '<label>报价金额（元）</label><input id="qAmount" type="number" step="0.01">' +
              '<label>交期（天）</label><input id="qLead" type="number" value="15">' +
              '<label>有效期（天）</label><input id="qValid" type="number" value="30">' +
              '<label>备注</label><input id="qRemark" type="text" placeholder="含税到厂价"></div>',
              '<button class="btn" data-close4="1">取消</button><button class="btn primary" id="qSave">保存</button>');
            var d2 = document.getElementById("dialog");
            d2.querySelector("[data-close4]").addEventListener("click", F.closeDialog);
            document.getElementById("qSave").addEventListener("click", function () {
              F.api("POST", "/api/rfqs/" + r.no + "/quotes", {
                supplierCode: document.getElementById("qSup").value,
                amount: Number(document.getElementById("qAmount").value || 0),
                leadDays: Number(document.getElementById("qLead").value || 0),
                validDays: Number(document.getElementById("qValid").value || 30),
                remark: document.getElementById("qRemark").value.trim()
              }).then(function () {
                F.closeDialog(); F.toast("报价已登记", "ok"); openRfq(no); draw();
              }).catch(function (e) { F.showErr(e); });
            });
          });
        }
        var aw = document.getElementById("qAward");
        if (aw) {
          aw.addEventListener("click", function () {
            if (!r.quotes.length) { F.toast("还没有报价，不能定标", "err"); return; }
            var opts = r.quotes.map(function (q, i) {
              return '<option value="' + F.esc(q.supplierCode) + '"' + (i === 0 ? " selected" : "") + ">" +
                F.esc(q.supplierName + " · " + F.money(q.amount)) + "</option>";
            }).join("");
            F.dialog("定标", '<div class="form-grid"><label>定标供应商</label><select id="aSup">' + opts +
              "</select></div><div class='small muted' style='margin-top:8px'>定标后自动生成采购订单草稿。</div>",
              '<button class="btn" data-close5="1">取消</button><button class="btn primary" id="aSave">确认定标</button>');
            var d3 = document.getElementById("dialog");
            d3.querySelector("[data-close5]").addEventListener("click", F.closeDialog);
            document.getElementById("aSave").addEventListener("click", function () {
              F.api("POST", "/api/rfqs/" + r.no + "/award", { supplierCode: document.getElementById("aSup").value })
                .then(function (x) {
                  F.closeDialog();
                  F.toast("已定标：" + x.supplier + "，生成订单 " + x.poNo, "ok");
                  draw();
                  F.go("orders");
                }).catch(function (e) { F.showErr(e); });
            });
          });
        }
      }).catch(function (e) { F.showErr(e); });
    }
    draw();
  });

  /* ============================================================ 采购订单 */
  F.register("orders", function () {
    var st = { status: "全部", kw: "", overdue: false };

    function draw() {
      F.api("GET", "/api/orders?" + F.qs({ status: st.status, kw: st.kw, overdue: st.overdue ? 1 : 0 }))
        .then(function (d) {
          var counts = { "全部": d.total };
          d.list.forEach(function (o) { counts[o.status] = (counts[o.status] || 0) + 1; });
          var chips = ["全部", "草稿", "待审批", "已下单", "部分到货", "全部到货", "已结算"].map(function (s) {
            return '<button class="chip ' + (st.status === s ? "on" : "") + '" data-st="' + s + '">' + s +
              "<b>" + (counts[s] || 0) + "</b></button>";
          }).join("");
          var html = '<div class="panel"><div class="panel-title">采购订单' +
            '<span class="panel-actions"><input id="fKw" type="text" placeholder="单号 / 标题 / 供应商" value="' +
            F.esc(st.kw) + '" style="width:180px">' +
            '<label class="small"><input type="checkbox" id="fOver"' + (st.overdue ? " checked" : "") +
            "> 只看逾期</label>" +
            '<button class="btn sm" id="btnSearch">查询</button>' +
            (F.canWrite() ? '<button class="btn sm primary" id="oNew">+ 新建订单</button>' : "") +
            "</span></div>" +
            '<div class="panel-body"><div class="chips">' + chips +
            (d.overdueCount ? '<span class="tag red">逾期 ' + d.overdueCount + " 单</span>" : "") + "</div></div>" +
            '<div class="panel-body flush">' +
            F.table([
              { label: "订单号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
              { label: "供应商 / 标题", render: function (r) { return '<b>' + F.esc(r.supplierName) + "</b>" +
                '<div class="muted small">' + F.esc(r.title) + " · " + r.itemCount + " 行</div>"; } },
              { label: "金额", num: true, render: function (r) { return F.money(r.amount); } },
              { label: "到货进度", render: function (r) {
                var p = Math.round((r.receiveRate || 0) * 100);
                return '<div class="progress"><i style="width:' + p + '%"></i></div><span class="small muted">' +
                  p + "% · " + F.qty(r.receivedQty) + "/" + F.qty(r.orderedQty) + "</span>";
              } },
              { label: "承诺到货", render: function (r) {
                return r.overdue ? '<b class="up">' + F.esc(r.promiseDate) + "（逾期 " + r.delayDays + " 天）</b>"
                  : F.esc(r.promiseDate);
              } },
              { label: "匹配", render: function (r) { return r.matchResult ? F.tag(r.matchResult) : "—"; } },
              { label: "状态", render: function (r) { return F.tag(r.status); } }
            ], d.list, { click: function (r) { return r.no; }, empty: "没有匹配的采购订单" }) +
            "</div></div>";
          document.getElementById("view").innerHTML = html;
          document.getElementById("btnSearch").addEventListener("click", function () {
            st.kw = document.getElementById("fKw").value.trim();
            st.overdue = document.getElementById("fOver").checked;
            draw();
          });
          document.getElementById("fKw").addEventListener("keydown", function (e) {
            if (e.key === "Enter") document.getElementById("btnSearch").click();
          });
          document.querySelectorAll("[data-st]").forEach(function (b) {
            b.addEventListener("click", function () { st.status = b.getAttribute("data-st"); draw(); });
          });
          var nb = document.getElementById("oNew");
          if (nb) nb.addEventListener("click", newOrder);
          F.bindRows(document, openOrder);
          F.setStatus("采购订单 · " + d.total + " 单（在途 " + (counts["已下单"] || 0) +
            (counts["部分到货"] ? " · 部分到货 " + counts["部分到货"] : "") + "）");
          F.setSide('<div class="side-block"><div class="hd">状态机</div><div class="bd small muted" style="line-height:1.9">' +
            "草稿 → 待审批 → 已下单 → 部分到货 → 全部到货 → 已结算<br>" +
            "· 只能前进，可跨级<br>· 下单需审批（超审批线须总监）<br>· 全部到货才能结算，结算需三单匹配通过</div></div>");
        });
    }

    function newOrder() {
      Promise.all([mats(), sups(), whs()]).then(function (arr) {
        var list = arr[0];
        var ok = arr[1].filter(function (s) { return s.status === "已准入"; });
        if (!ok.length) { F.toast("没有已准入的供应商", "err"); return; }
        var opts = list.map(function (m) {
          return '<option value="' + F.esc(m.code) + '">' + F.esc(m.code + " " + m.name + "（" + m.unit + "）") + "</option>";
        }).join("");
        var body = '<div class="form-grid">' +
          '<label>供应商 *</label><select id="nSup">' + ok.map(function (s) {
            return '<option value="' + F.esc(s.code) + '">' + F.esc(s.name) + "</option>";
          }).join("") + "</select>" +
          '<label>标题</label><input id="nTitle" type="text" value="产线备料采购">' +
          '<label>承诺到货</label><input id="nPromise" type="date" value="' + F.addDays(20) + '">' +
          '<label>备注</label><input id="nRemark" type="text">' +
          "</div>" +
          '<div class="section-title" style="margin-top:10px">明细</div><div id="lines"></div>' +
          '<button class="btn sm" id="addLine" style="margin-top:8px">+ 增加一行</button>';
        F.dialog("新建采购订单", body,
          '<button class="btn" data-close2="1">取消</button><button class="btn primary" id="nSave">保存草稿</button>');
        var dlg = document.getElementById("dialog");
        dlg.querySelector("[data-close2]").addEventListener("click", F.closeDialog);
        function addLine() {
          var row = document.createElement("div");
          row.className = "form-row";
          row.style.cssText = "display:flex;gap:8px;margin-bottom:6px";
          row.innerHTML = '<select class="lnMat" style="flex:1">' + opts + "</select>" +
            '<input class="lnQty" type="number" placeholder="数量" style="width:110px" value="100">' +
            '<input class="lnPrice" type="number" step="0.01" placeholder="单价" style="width:110px">';
          document.getElementById("lines").appendChild(row);
          var sel = row.querySelector(".lnMat");
          function sync() {
            var m = list.filter(function (x) { return x.code === sel.value; })[0];
            if (m) row.querySelector(".lnPrice").value = m.standardPrice;
          }
          sel.addEventListener("change", sync);
          if (list[0]) { sel.value = list[0].code; sync(); }
        }
        addLine();
        document.getElementById("addLine").addEventListener("click", addLine);
        document.getElementById("nSave").addEventListener("click", function () {
          var items = [];
          document.querySelectorAll("#lines .form-row").forEach(function (row) {
            var code = row.querySelector(".lnMat").value;
            var qty = Number(row.querySelector(".lnQty").value || 0);
            if (code && qty > 0) {
              items.push({ materialCode: code, qty: qty, price: Number(row.querySelector(".lnPrice").value || 0) });
            }
          });
          if (!items.length) { F.toast("请至少填写一行有效明细", "err"); return; }
          F.api("POST", "/api/orders", {
            supplierCode: document.getElementById("nSup").value,
            title: document.getElementById("nTitle").value.trim(),
            promiseDate: document.getElementById("nPromise").value,
            remark: document.getElementById("nRemark").value.trim(),
            items: items
          }).then(function (r) {
            F.closeDialog();
            F.toast("采购订单已创建：" + r.no + "（" + F.money(r.amount) + "）", "ok");
            draw();
          }).catch(function (e) { F.showErr(e); });
        });
      });
    }

    function openOrder(no) {
      F.api("GET", "/api/orders/" + encodeURIComponent(no)).then(function (o) {
        var gateHtml = "";
        ["待审批", "已下单", "全部到货", "已结算"].forEach(function (k) {
          var miss = (o.gate || {})[k] || [];
          if (miss.length) {
            gateHtml += '<div class="gate-row"><b>' + k + "</b>：缺 " + F.esc(miss.join("、")) + "</div>";
          }
        });
        var body = '<div class="detail-head"><div class="dh-title">' + F.esc(o.no) + " " + F.esc(o.title) +
          '</div><div class="dh-tags">' + F.tag(o.status) + " " +
          (o.overdue ? '<span class="tag red">逾期 ' + o.delayDays + " 天</span>" : "") +
          (o.matchResult ? F.tag(o.matchResult) : "") + "</div></div>" +
          '<div class="form-grid" style="margin-top:6px">' +
          "<div><span class='muted small'>供应商</span><br>" + F.esc(o.supplierName) + "</div>" +
          "<div><span class='muted small'>金额</span><br>" + F.money(o.amount) + "</div>" +
          "<div><span class='muted small'>到货进度</span><br>" + F.pct(o.receiveRate, 1) + "（" +
          F.qty(o.receivedQty) + "/" + F.qty(o.orderedQty) + "）</div>" +
          "<div><span class='muted small'>承诺到货</span><br>" + F.esc(o.promiseDate) + "</div>" +
          "<div><span class='muted small'>已收 / 已开票</span><br>" + F.money(o.receivedAmount) + " / " +
          F.money(o.invoicedAmount) + "</div>" +
          "<div><span class='muted small'>审批人</span><br>" + F.esc(o.approverName || "—") + "</div>" +
          "</div>" +
          (gateHtml ? '<div class="gate" style="margin-top:8px">' + gateHtml + "</div>" : "") +
          (o.match && o.match.result ? '<div class="note" style="margin-top:8px">三单匹配：' +
            F.tag(o.match.result) + " 差异 " + F.money(o.match.diff) + "（" + F.pct(o.match.rate, 2) +
            "，容差 " + F.pct(o.tolerance, 0) + "）</div>" : "") +
          '<div class="section-title" style="margin-top:10px">采购明细</div>' +
          F.table([
            { label: "物料", render: function (x) { return F.esc(x.materialCode) + " " + F.esc(x.materialName); } },
            { label: "规格", render: function (x) { return '<span class="small muted">' + F.esc(x.spec) + "</span>"; } },
            { label: "数量", num: true, render: function (x) { return F.qty(x.qty) + " " + F.esc(x.unit); } },
            { label: "单价", num: true, render: function (x) { return F.money(x.price); } },
            { label: "金额", num: true, render: function (x) { return F.money(x.amount); } },
            { label: "已收", num: true, render: function (x) { return F.qty(x.receivedQty); } }
          ], o.items) +
          '<div class="section-title" style="margin-top:10px">收货与发票</div>' +
          F.table([
            { label: "收货单", render: function (x) { return '<span class="mono small">' + F.esc(x.no) + "</span>"; } },
            { label: "到货日", key: "receivedAt" }, { label: "入库", key: "posterAt" },
            { label: "状态", render: function (x) { return F.tag(x.status); } }
          ], o.receipts, { empty: "尚无收货" }) +
          (o.invoices && o.invoices.length ? F.table([
            { label: "发票", render: function (x) { return '<span class="mono small">' + F.esc(x.no) + "</span>"; } },
            { label: "金额", num: true, render: function (x) { return F.money(x.amount); } },
            { label: "匹配", render: function (x) { return F.tag(x.matchResult || "待匹配"); } },
            { label: "状态", render: function (x) { return F.tag(x.status); } }
          ], o.invoices) : "");

        var acts = [];
        if (o.canAdvance && o.canAdvance.length && F.canWrite()) {
          acts.push('<button class="btn primary" id="oAdvance">推进到 ' + F.esc(o.canAdvance[0]) + "</button>");
        }
        if (["已下单", "部分到货"].indexOf(o.status) >= 0 &&
          ["admin", "warehouse", "quality", "purchase_director"].indexOf(F.me().role) >= 0) {
          acts.push('<button class="btn" id="oReceive">到货登记</button>');
        }
        if (["草稿", "待审批", "已下单", "部分到货"].indexOf(o.status) >= 0) {
          acts.push('<button class="btn" id="oCancel">取消订单</button>');
        }
        F.dialog("采购订单 " + o.no, body, acts.join("") + '<button class="btn" data-close3="1">关闭</button>');
        var dlg = document.getElementById("dialog");
        dlg.querySelector("[data-close3]").addEventListener("click", F.closeDialog);

        var adv = document.getElementById("oAdvance");
        if (adv) {
          adv.addEventListener("click", function () {
            var targets = o.canAdvance.filter(function (s) { return s !== "已取消"; });
            var pick = targets[0];
            if (targets.length > 1) {
              var i = window.prompt("推进到哪个状态？可选：" + targets.join(" / "), targets[0]);
              if (i === null) return;
              pick = i.trim();
              if (targets.indexOf(pick) < 0) { F.toast("可选状态：" + targets.join(" / "), "err"); return; }
            }
            F.api("POST", "/api/orders/" + o.no + "/stage", { target: pick }).then(function (r) {
              F.closeDialog();
              F.toast("订单已推进：" + r.from + " → " + r.status, "ok");
              F.reload().then(draw);
            }).catch(function (e) { F.showErr(e); });
          });
        }
        var rc = document.getElementById("oReceive");
        if (rc) {
          rc.addEventListener("click", function () {
            whs().then(function (list) {
              F.dialog("到货登记",
                '<div class="form-grid"><label>收货仓库</label><select id="wWh">' + list.map(function (w) {
                  return '<option value="' + F.esc(w.code) + '">' + F.esc(w.name) + "</option>";
                }).join("") + "</select></div>" +
                '<div class="small muted" style="margin-top:8px">默认按订单剩余数量全收，可在收货单里做质检与不良登记。</div>',
                '<button class="btn" data-close4="1">取消</button><button class="btn primary" id="wSave">生成收货单</button>');
              var d2 = document.getElementById("dialog");
              d2.querySelector("[data-close4]").addEventListener("click", F.closeDialog);
              document.getElementById("wSave").addEventListener("click", function () {
                F.api("POST", "/api/orders/" + o.no + "/receive", {
                  warehouse: document.getElementById("wWh").value
                }).then(function (r) {
                  F.closeDialog();
                  F.toast("收货单已创建：" + r.receiptNo + "，请质检后入库", "ok");
                  draw();
                  F.go("receipts");
                }).catch(function (e) { F.showErr(e); });
              });
            });
          });
        }
        var cn2 = document.getElementById("oCancel");
        if (cn2) {
          cn2.addEventListener("click", function () {
            var why = window.prompt("取消原因（至少 2 个字）", "需求变更，暂缓采购");
            if (why === null) return;
            F.api("POST", "/api/orders/" + o.no + "/cancel", { reason: why }).then(function () {
              F.closeDialog(); F.toast("订单已取消", "ok"); draw();
            }).catch(function (e) { F.showErr(e); });
          });
        }
      }).catch(function (e) { F.showErr(e); });
    }
    F.openOrder = openOrder;
    draw();
  });

  /* ============================================================ 收货质检 */
  F.register("receipts", function () {
    var st = { status: "全部", kw: "" };

    function draw() {
      F.api("GET", "/api/receipts?" + F.qs({ status: st.status, kw: st.kw })).then(function (d) {
        var counts = { "全部": d.total };
        d.list.forEach(function (r) { counts[r.status] = (counts[r.status] || 0) + 1; });
        var chips = ["全部", "待质检", "已质检", "已入库", "已退货"].map(function (s) {
          return '<button class="chip ' + (st.status === s ? "on" : "") + '" data-st="' + s + '">' + s +
            "<b>" + (counts[s] || 0) + "</b></button>";
        }).join("");
        var html = '<div class="panel"><div class="panel-title">收货与质检' +
          '<span class="panel-actions"><input id="fKw" type="text" placeholder="收货单 / 订单 / 供应商" value="' +
          F.esc(st.kw) + '" style="width:200px">' +
          '<button class="btn sm" id="btnSearch">查询</button></span></div>' +
          '<div class="panel-body"><div class="chips">' + chips + "</div></div>" +
          '<div class="panel-body flush">' +
          F.table([
            { label: "收货单", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>" +
              '<div class="muted small">' + F.esc(r.poNo) + "</div>"; } },
            { label: "供应商", key: "supplierName" },
            { label: "仓库", key: "warehouse" },
            { label: "到货日", key: "receivedAt" },
            { label: "合格 / 不良", num: true, render: function (r) {
              return F.qty(r.okQty) + " / " + (r.ngQty ? '<span class="up">' + F.qty(r.ngQty) + "</span>" : 0);
            } },
            { label: "合格率", num: true, render: function (r) { return F.pct(r.passRate, 1); } },
            { label: "质检结论", render: function (r) { return r.inspectResult ? F.tag(r.inspectResult) : "—"; } },
            { label: "状态", render: function (r) { return F.tag(r.status); } }
          ], d.list, { click: function (r) { return r.no; }, empty: "没有匹配的收货单" }) +
          "</div></div>";
        document.getElementById("view").innerHTML = html;
        document.getElementById("btnSearch").addEventListener("click", function () {
          st.kw = document.getElementById("fKw").value.trim(); draw();
        });
        document.getElementById("fKw").addEventListener("keydown", function (e) {
          if (e.key === "Enter") document.getElementById("btnSearch").click();
        });
        document.querySelectorAll("[data-st]").forEach(function (b) {
          b.addEventListener("click", function () { st.status = b.getAttribute("data-st"); draw(); });
        });
        F.bindRows(document, openReceipt);
        F.setStatus("收货质检 · " + d.total + " 张（待质检 " + (counts["待质检"] || 0) + "）");
        F.setSide('<div class="side-block"><div class="hd">质检口径</div><div class="bd small muted" style="line-height:1.9">' +
          "· 不良率 = 0 → 合格<br>· 0 &lt; 不良率 ≤ 三单容差 → 让步接收<br>" +
          "· 超过容差 → 退货<br>· 只有合格品入库，不良品留在收货单上做退货处理</div></div>");
      });
    }

    function openReceipt(no) {
      F.api("GET", "/api/receipts/" + encodeURIComponent(no)).then(function (r) {
        var body = '<div class="detail-head"><div class="dh-title">' + F.esc(r.no) +
          '</div><div class="dh-tags">' + F.tag(r.status) +
          (r.inspectResult ? F.tag(r.inspectResult) : "") + "</div></div>" +
          '<div class="form-grid" style="margin-top:6px">' +
          "<div><span class='muted small'>采购订单</span><br>" + F.esc(r.poNo) + "</div>" +
          "<div><span class='muted small'>供应商</span><br>" + F.esc(r.supplierName) + "</div>" +
          "<div><span class='muted small'>收货仓库</span><br>" + F.esc(r.warehouse) + "</div>" +
          "<div><span class='muted small'>到货日</span><br>" + F.esc(r.receivedAt) + "</div>" +
          "<div><span class='muted small'>质检员</span><br>" + F.esc(r.inspectedName || "—") + "</div>" +
          "<div><span class='muted small'>入库时间</span><br>" + F.esc(r.postedAt || "—") + "</div></div>" +
          '<div class="section-title" style="margin-top:10px">收货明细</div>' +
          F.table([
            { label: "物料", render: function (x) { return F.esc(x.materialCode) + " " + F.esc(x.materialName); } },
            { label: "到货", num: true, render: function (x) { return F.qty(x.qty); } },
            { label: "合格", num: true, render: function (x) { return F.qty(x.okQty); } },
            { label: "不良", num: true, render: function (x) { return F.qty(x.ngQty); } },
            { label: "单价", num: true, render: function (x) { return F.money(x.price); } },
            { label: "批次", render: function (x) { return F.esc(x.batch || "—"); } },
            { label: "有效期", render: function (x) { return F.esc(x.expireAt || "—"); } }
          ], r.items);
        var acts = [];
        if (r.status === "待质检") acts.push('<button class="btn primary" id="cInspect">质检</button>');
        if (r.status === "已质检") acts.push('<button class="btn primary" id="cPost">入库过账</button>');
        if (r.status !== "已退货") acts.push('<button class="btn" id="cReturn">退货</button>');
        F.dialog("收货单 " + r.no, body, acts.join("") + '<button class="btn" data-close3="1">关闭</button>');
        var dlg = document.getElementById("dialog");
        dlg.querySelector("[data-close3]").addEventListener("click", F.closeDialog);

        var ins = document.getElementById("cInspect");
        if (ins) {
          ins.addEventListener("click", function () {
            var rows = r.items.map(function (x) {
              return '<div class="form-row" style="display:flex;gap:6px;align-items:center;margin-bottom:6px" data-mid="' +
                x.id + '"><span style="flex:1">' + F.esc(x.materialCode) + " " + F.esc(x.materialName) +
                '（到货 ' + F.qty(x.qty) + "）</span>" +
                '<input class="okQty" type="number" step="0.01" value="' + x.qty + '" style="width:90px" title="合格数">' +
                '<input class="ngQty" type="number" step="0.01" value="0" style="width:90px" title="不良数">' +
                '<input class="batch" type="text" placeholder="批次" value="B' + F.today().slice(5, 7) +
                '001" style="width:110px"></div>';
            }).join("");
            F.dialog("到货质检",
              '<div class="small muted" style="margin-bottom:6px">合格数 + 不良数 = 到货数量</div>' + rows,
              '<button class="btn" data-close4="1">取消</button><button class="btn primary" id="iSave">提交质检</button>');
            var d2 = document.getElementById("dialog");
            d2.querySelector("[data-close4]").addEventListener("click", F.closeDialog);
            document.getElementById("iSave").addEventListener("click", function () {
              var items = [];
              document.querySelectorAll("[data-mid]").forEach(function (row) {
                items.push({
                  id: Number(row.getAttribute("data-mid")),
                  okQty: Number(row.querySelector(".okQty").value || 0),
                  ngQty: Number(row.querySelector(".ngQty").value || 0),
                  batch: row.querySelector(".batch").value.trim()
                });
              });
              F.api("POST", "/api/receipts/" + r.no + "/inspect", { items: items }).then(function (x) {
                F.closeDialog();
                F.toast("质检完成：" + x.result + "（合格率 " + F.pct(x.passRate, 1) + "）", "ok");
                draw();
              }).catch(function (e) { F.showErr(e); });
            });
          });
        }
        var po = document.getElementById("cPost");
        if (po) {
          po.addEventListener("click", function () {
            F.api("POST", "/api/receipts/" + r.no + "/post", {}).then(function (x) {
              F.closeDialog();
              F.toast("已入库：" + x.lines + " 行", "ok");
              F.reload().then(draw);
            }).catch(function (e) { F.showErr(e); });
          });
        }
        var rt = document.getElementById("cReturn");
        if (rt) {
          rt.addEventListener("click", function () {
            var why = window.prompt("退货原因（至少 2 个字）", "来料不良，整批退回");
            if (why === null) return;
            F.api("POST", "/api/receipts/" + r.no + "/return", { reason: why }).then(function () {
              F.closeDialog(); F.toast("已退货", "ok"); draw();
            }).catch(function (e) { F.showErr(e); });
          });
        }
      }).catch(function (e) { F.showErr(e); });
    }
    F.openReceipt = openReceipt;
    draw();
  });
})(window, document);

/* 飞鹰 CRM · 报价、合同、回款 */
(function (window, document) {
  "use strict";
  var F = window.F;

  function me() { return (F.state.boot && F.state.boot.user) || {}; }
  function canApprove() {
    var r = me().role;
    return r === "admin" || r === "sales_director";
  }

  function customerOptions(cb) {
    F.api("GET", "/api/customers?pageSize=300").then(function (d) {
      cb((d.list || []).map(function (c) {
        return '<option value="' + F.esc(c.code) + '">' + F.esc(c.name) + "</option>";
      }).join(""));
    });
  }

  /* ============================================================ 报价 */
  F.register("quotes", function () {
    var st = { status: "全部", kw: "" };

    function draw() {
      F.api("GET", "/api/quotes?" + F.qs({ status: st.status, kw: st.kw, pageSize: 200 }))
        .then(function (d) {
          var stats = d.stats || {};
          var chips = ["全部", "草稿", "待审批", "已批准", "已发送", "已接受", "已驳回"].map(function (s) {
            return '<button class="chip ' + (st.status === s ? "on" : "") + '" data-st="' + s + '">' +
              s + "<b>" + (s === "全部" ? d.total : (stats[s] || 0)) + "</b></button>";
          }).join("");
          var html = '<div class="panel"><div class="panel-title">报价管理' +
            '<span class="panel-actions">' +
            '<input id="qKw" type="text" placeholder="编号 / 客户 / 标题" value="' + F.esc(st.kw) + '" style="width:180px">' +
            '<button class="btn sm" id="qSearch">查询</button>' +
            '<button class="btn sm primary" id="qNew">+ 新建报价</button></span></div>' +
            '<div class="panel-body"><div class="chips">' + chips + "</div></div>" +
            '<div class="panel-body flush">' +
            F.table([
              { label: "编号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
              { label: "客户 / 标题", render: function (r) { return F.esc(r.customerName) +
                '<div class="muted small">' + F.esc(r.title) + "</div>"; } },
              { label: "标准额", num: true, render: function (r) { return F.wan(r.listAmount); } },
              { label: "报价额", num: true, render: function (r) { return F.wan(r.amount); } },
              { label: "折扣", num: true, render: function (r) {
                return r.discountPct > 0 ? '<b class="' + (r.discountPct > 15 ? "up" : "") + '">' +
                  r.discountPct.toFixed(1) + "%</b>" : "—"; } },
              { label: "状态", render: function (r) { return F.tag(r.status); } },
              { label: "有效期", key: "validUntil" },
              { label: "负责人", render: function (r) { return F.esc(r.ownerName); } }
            ], d.list, { click: function (r) { return r.no; }, empty: "暂无报价单" }) + "</div></div>";
          document.getElementById("view").innerHTML = html;
          document.getElementById("qSearch").addEventListener("click", function () {
            st.kw = document.getElementById("qKw").value.trim(); draw();
          });
          document.getElementById("qNew").addEventListener("click", newQuote);
          document.querySelectorAll("[data-st]").forEach(function (b) {
            b.addEventListener("click", function () { st.status = b.getAttribute("data-st"); draw(); });
          });
          F.bindRows(document, openQuote);
          F.setStatus("报价管理 · " + d.total + " 张（待审批 " + (stats["待审批"] || 0) + "）");
          F.setSide('<div class="side-block"><div class="hd">折扣审批线</div><div class="bd small muted" style="line-height:1.9">' +
            "折扣率 = 1 − 报价额 / 标准价。<br>超过规则阈值（默认 15%）自动进入「待审批」，销售总监批准后才能发送给客户。<br>" +
            "低于阈值可直接发送。</div></div>");
        });
    }

    function newQuote() {
      customerOptions(function (opts) {
        (function () {
          var body = '<div class="form-grid">' +
            '<label>客户 *</label><select id="qCust">' + opts + "</select>" +
            '<label>报价标题</label><input id="qTitle" type="text" value="CRM 系统报价单">' +
            '<label>有效期至</label><input id="qValid" type="date" value="' + F.addDays(30) + '">' +
            '<label>备注</label><input id="qRemark" type="text" placeholder="如 含 1 年运维">' +
            "</div>" +
            '<div class="section-title">报价明细</div>' +
            '<div id="qLines"></div>' +
            '<button class="btn sm" id="qAdd">+ 添加一行</button>' +
            '<div class="calc-box" id="qCalc"></div>';
          F.dialog("新建报价", body, '<button class="btn" data-close9="1">取消</button>' +
            '<button class="btn primary" id="qSave">保存</button>');
          document.querySelector("[data-close9]").addEventListener("click", F.closeDialog);
          var products = [];
          F.api("GET", "/api/products").then(function (r) {
            products = r.list;
            addLine(); addLine();
          }).catch(function () {
            products = [{ code: "P-CRM-PRO", name: "飞鹰 CRM 专业版", price: 158000 },
              { code: "P-IMP", name: "实施服务包", price: 2400 }];
            addLine(); addLine();
          });

          function addLine() {
            var i = document.querySelectorAll("#qLines .qline").length;
            var div = document.createElement("div");
            div.className = "qline form-row";
            div.innerHTML = '<select class="lnProd">' + (products.length ? products.map(function (p) {
              return '<option value="' + F.esc(p.code) + '" data-price="' + p.price + '">' +
                F.esc(p.name) + "（标准价 " + F.num(p.price, 0) + "）</option>";
            }).join("") : '<option value="P-CRM-PRO" data-price="158000">飞鹰 CRM 专业版</option>') + "</select>" +
              '<input class="lnQty" type="number" value="1" style="width:80px" title="数量">' +
              '<input class="lnPrice" type="number" style="width:130px" title="成交单价">' +
              '<button class="btn sm" data-del="1">删除</button>';
            document.getElementById("qLines").appendChild(div);
            var sel = div.querySelector(".lnProd");
            var price = div.querySelector(".lnPrice");
            function sync() {
              var p = sel.options[sel.selectedIndex];
              price.value = p ? p.getAttribute("data-price") : 0;
              calc();
            }
            sel.addEventListener("change", sync);
            div.querySelector(".lnQty").addEventListener("input", calc);
            price.addEventListener("input", calc);
            div.querySelector("[data-del]").addEventListener("click", function () {
              if (document.querySelectorAll("#qLines .qline").length > 1) { div.remove(); calc(); }
            });
            sync();
          }

          function calc() {
            var list = 0, amt = 0;
            document.querySelectorAll("#qLines .qline").forEach(function (ln) {
              var sel = ln.querySelector(".lnProd");
              var p = sel.options[sel.selectedIndex];
              var lp = p ? Number(p.getAttribute("data-price")) : 0;
              var q = Number(ln.querySelector(".lnQty").value || 0);
              var pr = Number(ln.querySelector(".lnPrice").value || 0);
              list += lp * q; amt += pr * q;
            });
            var rate = list ? (1 - amt / list) : 0;
            var box = document.getElementById("qCalc");
            if (!box) return;
            box.innerHTML = "标准额 <b>" + F.money(list) + "</b> ｜ 报价额 <b>" + F.money(amt) +
              "</b> ｜ 折扣 <b class='" + (rate > 0.15 ? "up" : "") + "'>" + (rate * 100).toFixed(1) +
              "%</b>" + (rate > 0.15 ? ' <span class="tag gold">超审批线，保存后需总监批准</span>' : "");
          }

          document.getElementById("qAdd").addEventListener("click", addLine);
          document.getElementById("qSave").addEventListener("click", function () {
            var lines = [];
            document.querySelectorAll("#qLines .qline").forEach(function (ln) {
              var sel = ln.querySelector(".lnProd");
              lines.push({ productCode: sel.value, qty: Number(ln.querySelector(".lnQty").value || 0),
                price: Number(ln.querySelector(".lnPrice").value || 0) });
            });
            F.api("POST", "/api/quotes", {
              customerCode: document.getElementById("qCust").value,
              title: document.getElementById("qTitle").value.trim(),
              validUntil: document.getElementById("qValid").value,
              remark: document.getElementById("qRemark").value.trim(), lines: lines
            }).then(function (r) {
              F.closeDialog();
              F.toast("报价已创建：" + r.no + "（" + r.status + "，折扣 " + r.discountPct.toFixed(1) + "%）", "ok");
              draw();
            }).catch(function (e) { F.toast(e.message, "err"); });
          });
        })();
      });
    }

    function openQuote(no) {
      F.api("GET", "/api/quotes/" + encodeURIComponent(no)).then(function (d) {
        var lines = F.table([
          { label: "序", render: function (r) { return r.seq; } },
          { label: "产品", render: function (r) { return F.esc(r.product_name) + ' <span class="muted small mono">' +
            F.esc(r.product_code) + "</span>"; } },
          { label: "数量", num: true, render: function (r) { return F.num(r.qty, 0); } },
          { label: "标准价", num: true, render: function (r) { return F.money(r.list_price); } },
          { label: "成交价", num: true, render: function (r) { return F.money(r.price); } },
          { label: "金额", num: true, render: function (r) { return F.money(r.amount); } }
        ], d.lines || []);
        var html = '<div class="detail-head"><div><div class="dh-title">' + F.esc(d.title) + "</div>" +
          '<div class="muted small">' + F.esc(d.no) + " · " + F.esc(d.customerName) +
          (d.oppNo ? " · " + F.esc(d.oppNo) : "") + "</div></div>" +
          '<div class="dh-tags">' + F.tag(d.status) + "</div></div>" +
          '<div class="kpi-grid four" style="margin:10px 0">' +
          '<div class="kpi"><div class="k-label">标准额</div><div class="k-value" style="font-size:17px">' +
          F.money(d.listAmount) + "</div></div>" +
          '<div class="kpi green"><div class="k-label">报价额</div><div class="k-value" style="font-size:17px">' +
          F.money(d.amount) + "</div></div>" +
          '<div class="kpi gold"><div class="k-label">折扣率</div><div class="k-value" style="font-size:17px">' +
          d.discountPct.toFixed(1) + "%</div><div class='k-sub'>审批线 " +
          (d.threshold * 100).toFixed(0) + "%</div></div>" +
          '<div class="kpi"><div class="k-label">有效期</div><div class="k-value" style="font-size:17px">' +
          F.esc(d.validUntil) + "</div></div></div>" + lines +
          (d.rejectReason ? '<div class="warn-box">驳回原因：' + F.esc(d.rejectReason) + "</div>" : "") +
          '<div class="small muted" style="margin-top:8px">负责人 ' + F.esc(d.ownerName) +
          (d.approverName ? " · 审批人 " + F.esc(d.approverName) : "") + "</div>";
        var foot = '<button class="btn" data-close10="1">关闭</button>';
        if (d.status === "待审批" && canApprove()) {
          foot += '<button class="btn danger" id="qReject">驳回</button>' +
            '<button class="btn primary" id="qApprove">批准</button>';
        }
        if (d.status === "草稿" || d.status === "已批准") foot += '<button class="btn primary" id="qSend">发送给客户</button>';
        if (d.status === "已发送") foot += '<button class="btn primary" id="qAccept">客户已接受</button>';
        F.dialog("报价 " + d.no, html, foot);
        document.querySelector("[data-close10]").addEventListener("click", F.closeDialog);
        function post(path, payload, ok) {
          F.api("POST", path, payload || {}).then(function () {
            F.closeDialog(); F.toast(ok, "ok"); draw(); F.reload();
          }).catch(function (e) { F.toast(e.message, "err"); });
        }
        var a = document.getElementById("qApprove");
        if (a) a.addEventListener("click", function () { post("/api/quotes/" + d.no + "/approve", {}, "已批准"); });
        var rj = document.getElementById("qReject");
        if (rj) rj.addEventListener("click", function () {
          var reason = window.prompt("驳回原因（必填）", "折扣过低，需再谈");
          if (!reason) return;
          post("/api/quotes/" + d.no + "/reject", { reason: reason }, "已驳回");
        });
        var sd = document.getElementById("qSend");
        if (sd) sd.addEventListener("click", function () { post("/api/quotes/" + d.no + "/send", {}, "已发送"); });
        var ac = document.getElementById("qAccept");
        if (ac) ac.addEventListener("click", function () { post("/api/quotes/" + d.no + "/accept", {}, "已标记客户接受"); });
      });
    }

    draw();
  });

  /* ============================================================ 合同 */
  F.register("contracts", function () {
    var st = { status: "全部", kw: "" };

    function draw() {
      F.api("GET", "/api/contracts?" + F.qs({ status: st.status, kw: st.kw, pageSize: 200 }))
        .then(function (d) {
          var stats = d.stats || {};
          var chips = ["全部", "待签署", "已签署", "执行中", "已完成", "已终止"].map(function (s) {
            return '<button class="chip ' + (st.status === s ? "on" : "") + '" data-st="' + s + '">' +
              s + "<b>" + (s === "全部" ? d.total : (stats[s] || 0)) + "</b></button>";
          }).join("");
          var html = '<div class="panel"><div class="panel-title">合同管理' +
            '<span class="panel-actions">' +
            '<input id="tKw" type="text" placeholder="编号 / 客户 / 标题" value="' + F.esc(st.kw) + '" style="width:180px">' +
            '<button class="btn sm" id="tSearch">查询</button>' +
            '<button class="btn sm primary" id="tNew">+ 新建合同</button></span></div>' +
            '<div class="panel-body"><div class="chips">' + chips + "</div></div>" +
            '<div class="panel-body flush">' +
            F.table([
              { label: "合同号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
              { label: "客户 / 标题", render: function (r) { return F.esc(r.customerName) +
                '<div class="muted small">' + F.esc(r.title) + "</div>"; } },
              { label: "金额", num: true, render: function (r) { return F.wan(r.amount); } },
              { label: "已收", num: true, render: function (r) { return F.wan(r.paidAmount); } },
              { label: "逾期", num: true, render: function (r) {
                return r.overdueAmount > 0 ? '<b class="up">' + F.wan(r.overdueAmount) + "</b>" : "—"; } },
              { label: "回款进度", render: function (r) {
                return '<span class="progress"><i style="width:' + Math.round(r.progress * 100) + '%"></i></span> ' +
                  F.pct(r.progress, 0); } },
              { label: "签署日", key: "signDate" },
              { label: "状态", render: function (r) { return F.tag(r.status); } },
              { label: "负责人", render: function (r) { return F.esc(r.ownerName); } }
            ], d.list, { click: function (r) { return r.no; }, empty: "暂无合同" }) + "</div></div>";
          document.getElementById("view").innerHTML = html;
          document.getElementById("tSearch").addEventListener("click", function () {
            st.kw = document.getElementById("tKw").value.trim(); draw();
          });
          document.getElementById("tNew").addEventListener("click", newContract);
          document.querySelectorAll("[data-st]").forEach(function (b) {
            b.addEventListener("click", function () { st.status = b.getAttribute("data-st"); draw(); });
          });
          F.bindRows(document, openContract);
          var total = (d.list || []).reduce(function (a, r) { return a + r.amount; }, 0);
          var paid = (d.list || []).reduce(function (a, r) { return a + r.paidAmount; }, 0);
          F.setStatus("合同管理 · " + d.total + " 份 · 合同额 " + F.wan(total) + " · 已收 " + F.wan(paid));
          F.setSide('<div class="side-block"><div class="hd">合同概况</div><div class="bd">' +
            '<div class="side-kv"><span>合同总额</span><b>' + F.wan(total) + "</b></div>" +
            '<div class="side-kv"><span>已回款</span><b class="down">' + F.wan(paid) + "</b></div>" +
            '<div class="side-kv"><span>回款率</span><b>' +
            (total ? F.pct(paid / total, 1) : "—") + "</b></div>" +
            '<div class="side-kv"><span>待签署</span><b>' + (stats["待签署"] || 0) + "</b></div>" +
            "</div></div>");
        });
    }

    function newContract() {
      customerOptions(function (opts) {
        var body = '<div class="form-grid">' +
          '<label>客户 *</label><select id="tCust">' + opts + "</select>" +
          '<label>合同标题</label><input id="tTitle" type="text" value="CRM 年度服务合同">' +
          '<label>合同金额 *</label><input id="tAmount" type="number" value="238000">' +
          '<label>签署日期</label><input id="tSign" type="date" value="' + F.today() + '">' +
          '<label>付款条件</label><select id="tTerms"><option value="3-4-3">3-4-3（签约 30/60/90 天）</option>' +
          '<option value="5-5">5-5（两期）</option><option value="10">一次性付清</option></select>' +
          '<label>关联商机</label><input id="tOpp" type="text" placeholder="选填，如 OPP20261020-0001">' +
          "</div>" +
          '<div class="small muted" style="margin-top:8px">保存后按付款条件自动生成回款计划，签署后商机自动推进为赢单。</div>';
        F.dialog("新建合同", body, '<button class="btn" data-close11="1">取消</button>' +
          '<button class="btn primary" id="tSave">保存</button>');
        document.querySelector("[data-close11]").addEventListener("click", F.closeDialog);
        document.getElementById("tSave").addEventListener("click", function () {
          F.api("POST", "/api/contracts", {
            customerCode: document.getElementById("tCust").value,
            title: document.getElementById("tTitle").value.trim(),
            amount: Number(document.getElementById("tAmount").value || 0),
            signDate: document.getElementById("tSign").value,
            paymentTerms: document.getElementById("tTerms").value,
            oppNo: document.getElementById("tOpp").value.trim()
          }).then(function (r) {
            F.closeDialog(); F.toast("合同已创建：" + r.no + "（待签署）", "ok");
            draw(); F.reload();
          }).catch(function (e) { F.toast(e.message, "err"); });
        });
      });
    }

    function openContract(no) {
      F.api("GET", "/api/contracts/" + encodeURIComponent(no)).then(function (d) {
        var plans = F.table([
          { label: "期次", render: function (r) { return "第 " + r.seq + " 期"; } },
          { label: "应收日期", key: "due_date" },
          { label: "应收", num: true, render: function (r) { return F.money(r.amount); } },
          { label: "已收", num: true, render: function (r) { return F.money(r.paidAmount); } },
          { label: "未收", num: true, render: function (r) { return F.money(r.leftAmount); } },
          { label: "状态", render: function (r) { return F.tag(r.status); } },
          { label: "逾期", num: true, render: function (r) {
            return r.overdueDays ? '<b class="up">' + r.overdueDays + " 天</b>" : "—"; } }
        ], d.plans || [], { empty: "无回款计划" });
        var pays = F.table([
          { label: "收款单", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
          { label: "日期", key: "pay_date" },
          { label: "金额", num: true, render: function (r) { return F.money(r.amount); } },
          { label: "方式", key: "method" },
          { label: "经办", key: "operator" }
        ], d.payments || [], { empty: "暂无收款记录" });
        var html = '<div class="detail-head"><div><div class="dh-title">' + F.esc(d.title) + "</div>" +
          '<div class="muted small">' + F.esc(d.no) + " · " + F.esc(d.customerName) + " · 付款条件 " +
          F.esc(d.paymentTerms) + "</div></div><div class='dh-tags'>" + F.tag(d.status) + "</div></div>" +
          '<div class="kpi-grid five" style="margin:10px 0">' +
          '<div class="kpi"><div class="k-label">合同金额</div><div class="k-value" style="font-size:16px">' +
          F.wan(d.amount) + "</div></div>" +
          '<div class="kpi green"><div class="k-label">已回款</div><div class="k-value" style="font-size:16px">' +
          F.wan(d.paidAmount) + "</div></div>" +
          '<div class="kpi gold"><div class="k-label">未收</div><div class="k-value" style="font-size:16px">' +
          F.wan(d.unpaidAmount) + "</div></div>" +
          '<div class="kpi red"><div class="k-label">逾期</div><div class="k-value" style="font-size:16px">' +
          F.wan(d.overdueAmount) + "</div></div>" +
          '<div class="kpi"><div class="k-label">回款进度</div><div class="k-value" style="font-size:16px">' +
          F.pct(d.progress, 0) + "</div></div></div>" +
          '<div class="section-title">回款计划</div>' + plans +
          '<div class="section-title">收款记录</div>' + pays;
        var foot = '<button class="btn" data-close12="1">关闭</button>';
        if (d.status === "待签署") foot += '<button class="btn primary" id="ctSign">签署合同</button>';
        if (d.status !== "已完成" && d.status !== "已终止") {
          foot += '<button class="btn" id="ctPay">登记收款</button>';
        }
        if (canApprove() && d.status !== "已完成" && d.status !== "已终止") {
          foot += '<button class="btn danger" id="ctTerm">终止</button>';
        }
        F.dialog("合同 " + d.no, html, foot);
        document.querySelector("[data-close12]").addEventListener("click", F.closeDialog);
        var sg = document.getElementById("ctSign");
        if (sg) sg.addEventListener("click", function () {
          F.api("POST", "/api/contracts/" + d.no + "/sign", { signDate: F.today() })
            .then(function () {
              F.closeDialog(); F.toast("合同已签署，回款计划已按签署日重排", "ok");
              draw(); F.reload();
            }).catch(function (e) { F.toast(e.message, "err"); });
        });
        var py = document.getElementById("ctPay");
        if (py) py.addEventListener("click", function () {
          F.closeDialog(); payDialog(d.no, draw);
        });
        var tm = document.getElementById("ctTerm");
        if (tm) tm.addEventListener("click", function () {
          var reason = window.prompt("终止原因（必填）", "客户项目终止");
          if (!reason) return;
          F.api("POST", "/api/contracts/" + d.no + "/terminate", { reason: reason })
            .then(function () { F.closeDialog(); F.toast("合同已终止", "ok"); draw(); F.reload(); })
            .catch(function (e) { F.toast(e.message, "err"); });
        });
      });
    }

    draw();
  });

  /* ============================================================ 回款 */
  function payDialog(contractNo, done) {
    F.api("GET", "/api/contracts?pageSize=300").then(function (cs) {
      var list = (cs.list || []).filter(function (c) {
        return c.status !== "已终止" && c.unpaidAmount > 0;
      });
      var opts = list.map(function (c) {
        return '<option value="' + F.esc(c.no) + '"' + (c.no === contractNo ? " selected" : "") + ">" +
          F.esc(c.customerName) + " · 未收 " + F.num(c.unpaidAmount, 2) + "</option>";
      }).join("");
      var body = '<div class="form-grid">' +
        '<label>合同 *</label><select id="pContract">' + opts + "</select>" +
        '<label>收款金额 *</label><input id="pAmount" type="number" value="' + (function () {
          var c = list.filter(function (x) { return x.no === contractNo; })[0] || list[0];
          return c ? Math.round(c.unpaidAmount) : 50000;
        })() + '">' +
        '<label>收款日期</label><input id="pDate" type="date" value="' + F.today() + '">' +
        '<label>方式</label><select id="pMethod"><option>银行转账</option><option>银行承兑</option>' +
        '<option>现金</option><option>支付宝/微信</option></select>' +
        '<label>备注</label><input id="pRemark" type="text" placeholder="如 第二期款">' +
        "</div>" +
        '<div class="small muted" style="margin-top:8px">不指定期次时按到期日先后自动核销（FIFO）。</div>';
      F.dialog("登记收款", body, '<button class="btn" data-close13="1">取消</button>' +
        '<button class="btn primary" id="pSave">保存</button>');
      document.querySelector("[data-close13]").addEventListener("click", F.closeDialog);
      document.getElementById("pSave").addEventListener("click", function () {
        F.api("POST", "/api/payments", {
          contractNo: document.getElementById("pContract").value,
          amount: Number(document.getElementById("pAmount").value || 0),
          payDate: document.getElementById("pDate").value,
          method: document.getElementById("pMethod").value,
          remark: document.getElementById("pRemark").value.trim()
        }).then(function (r) {
          F.closeDialog();
          F.toast("已登记收款 " + F.money(r.amount) + "，剩余未收 " + F.money(r.unpaidAmount), "ok");
          if (done) done();
          F.reload();
        }).catch(function (e) { F.toast(e.message, "err"); });
      });
    });
  }
  F.payDialog = payDialog;

  F.register("payments", function () {
    var st = { overdue: false, status: "全部" };

    function draw() {
      F.api("GET", "/api/payments/plans?" + F.qs({ overdue: st.overdue ? 1 : "", status: st.status, pageSize: 200 }))
        .then(function (d) {
          F.api("GET", "/api/payments?kw=").then(function (pay) {
            var aging = d.aging || {};
            var agingHtml = Object.keys(aging).map(function (k) {
              return '<div class="fm"><div class="fm-v">' + F.wan(aging[k]) + "</div>" +
                '<div class="fm-l">' + k + "</div></div>";
            }).join("");
            var html = '<div class="kpi-grid four">' +
              '<div class="kpi"><div class="k-label">未收合计</div><div class="k-value">' +
              F.wan(d.totalUnpaid) + "</div></div>" +
              '<div class="kpi red"><div class="k-label">逾期未收</div><div class="k-value">' +
              F.wan(d.totalOverdue) + "</div></div>" +
              '<div class="kpi green"><div class="k-label">本期已收</div><div class="k-value">' +
              F.wan(pay.totalAmount) + "</div></div>" +
              '<div class="kpi gold"><div class="k-label">收款笔数</div><div class="k-value">' +
              pay.total + "</div></div></div>" +
              '<div class="panel"><div class="panel-title">应收账龄</div><div class="panel-body">' +
              '<div class="funnel-mini">' + agingHtml + "</div></div></div>" +
              '<div class="panel"><div class="panel-title">回款计划' +
              '<span class="panel-actions">' +
              '<label class="small"><input type="checkbox" id="fOver"' + (st.overdue ? " checked" : "") +
              '> 只看逾期</label>' +
              '<button class="btn sm primary" id="pNew">+ 登记收款</button></span></div>' +
              '<div class="panel-body flush">' +
              F.table([
                { label: "合同", render: function (r) { return '<span class="mono small">' + F.esc(r.contractNo) + "</span>"; } },
                { label: "客户", key: "customerName" },
                { label: "期次", render: function (r) { return "第 " + r.seq + " 期"; } },
                { label: "应收日", key: "dueDate" },
                { label: "应收", num: true, render: function (r) { return F.money(r.amount); } },
                { label: "已收", num: true, render: function (r) { return F.money(r.paidAmount); } },
                { label: "未收", num: true, render: function (r) { return F.money(r.leftAmount); } },
                { label: "状态", render: function (r) { return F.tag(r.status); } },
                { label: "逾期", num: true, render: function (r) {
                  return r.overdueDays ? '<b class="up">' + r.overdueDays + " 天</b>" : "—"; } }
              ], d.list, { empty: "没有待收计划" }) + "</div></div>" +
              '<div class="panel"><div class="panel-title">收款流水</div><div class="panel-body flush">' +
              F.table([
                { label: "收款单", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
                { label: "合同", render: function (r) { return '<span class="mono small">' + F.esc(r.contractNo) + "</span>"; } },
                { label: "客户", key: "customerName" },
                { label: "金额", num: true, render: function (r) { return F.money(r.amount); } },
                { label: "日期", key: "payDate" },
                { label: "方式", key: "method" },
                { label: "经办", key: "operator" }
              ], pay.list, { empty: "暂无收款" }) + "</div></div>";
            document.getElementById("view").innerHTML = html;
            document.getElementById("fOver").addEventListener("change", function (e) {
              st.overdue = e.target.checked; draw();
            });
            document.getElementById("pNew").addEventListener("click", function () {
              payDialog("", draw);
            });
            F.setStatus("回款管理 · 未收 " + F.wan(d.totalUnpaid) + " · 逾期 " + F.wan(d.totalOverdue));
            F.setSide('<div class="side-block"><div class="hd">账龄口径</div><div class="bd small muted" style="line-height:1.9">' +
              "按回款计划应收日与今天之差分档：未到期 / 1-30 / 31-60 / 61-90 / 90 天以上。<br>" +
              "收款按到期日先进先出核销，未收清零后期次自动转「已收」，全部收齐合同转「已完成」。</div></div>");
          });
        });
    }
    draw();
  });
})(window, document);

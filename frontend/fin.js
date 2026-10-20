/* 飞泉 SCM · 结算付款（三单匹配 / 付款 / 应付账龄）与报表分析 */
(function (window, document) {
  "use strict";
  var F = window.F;

  function me() { return (F.state.boot && F.state.boot.user) || {}; }
  function canFinance() {
    var r = me().role;
    return r === "admin" || r === "finance" || r === "purchase_director";
  }

  /* ============================================================ 结算付款 */
  F.register("invoices", function () {
    var st = { status: "全部", kw: "" };

    function draw() {
      Promise.all([
        F.api("GET", "/api/invoices?" + F.qs({ status: st.status, kw: st.kw })),
        F.api("GET", "/api/payables")
      ]).then(function (res) {
        var d = res[0], pay = res[1];
        var counts = { "全部": d.total };
        d.list.forEach(function (r) { counts[r.status] = (counts[r.status] || 0) + 1; });
        var paid = d.list.reduce(function (a, r) { return a + Number(r.paidAmount || 0); }, 0);
        var diffCnt = d.list.filter(function (r) { return r.matchResult === "金额差异超限"; }).length;

        var kpi = '<div class="kpi-grid four">' +
          '<div class="kpi gold"><div class="k-label">待付 / 应付余额</div><div class="k-value">' +
          F.wan(pay.due) + '</div><div class="k-sub">' + pay.total + " 张未结清发票</div></div>" +
          '<div class="kpi red"><div class="k-label">逾期应付</div><div class="k-value">' +
          F.wan(pay.overdue) + "</div><div class='k-sub'>账龄口径按到期日+30 天</div></div>" +
          '<div class="kpi"><div class="k-label">差异挂起</div><div class="k-value">' + diffCnt +
          '</div><div class="k-sub">容差 ' + F.pct(d.tolerance, 1) + "</div></div>" +
          '<div class="kpi green"><div class="k-label">已付款金额</div><div class="k-value">' +
          F.wan(paid) + '</div><div class="k-sub">发票共 ' + d.total + " 张</div></div></div>";

        var chips = ["全部", "待匹配", "待付款", "已付款", "差异挂起"].map(function (s) {
          return '<button class="chip ' + (st.status === s ? "on" : "") + '" data-st="' + s + '">' + s +
            "<b>" + (counts[s] || 0) + "</b></button>";
        }).join("");

        var html = kpi + '<div class="panel"><div class="panel-title">发票与三单匹配' +
          '<span class="panel-actions">' +
          '<input id="iKw" type="text" placeholder="发票号 / 订单号 / 供应商" value="' + F.esc(st.kw) +
          '" style="width:200px"><button class="btn sm" id="iSearch">查询</button>' +
          (canFinance() ? '<button class="btn sm primary" id="iNew">+ 登记发票</button>' : "") +
          "</span></div>" +
          '<div class="panel-body"><div class="chips">' + chips + "</div></div>" +
          '<div class="panel-body flush">' + F.table([
            { label: "发票号", render: function (r) {
              return '<span class="mono small">' + F.esc(r.no) + '</span><div class="muted small">' +
                F.esc(r.invoiceNo || "—") + "</div>";
            } },
            { label: "采购订单", render: function (r) { return '<span class="mono small">' +
              F.esc(r.poNo) + "</span>"; } },
            { label: "供应商", render: function (r) { return F.esc(r.supplierName); } },
            { label: "发票金额", num: true, render: function (r) { return F.money(r.amount); } },
            { label: "已付", num: true, render: function (r) {
              return r.paidAmount ? F.money(r.paidAmount) : '<span class="muted">0.00</span>';
            } },
            { label: "差异", num: true, render: function (r) {
              var v = Number(r.diffAmount || 0);
              return (v ? '<b class="' + (v > 0 ? "up" : "down") + '">' + F.money(v) + "</b>"
                : '<span class="muted">0.00</span>') + '<div class="muted small">' + F.pct(r.diffRate, 2) +
                "</div>";
            } },
            { label: "匹配结果", render: function (r) { return F.tag(r.matchResult || "未匹配"); } },
            { label: "到期日", render: function (r) {
              return F.esc(r.dueDate || "—") + (r.overdueDays > 0
                ? '<div class="small up">逾期 ' + r.overdueDays + " 天</div>" : "");
            } },
            { label: "状态", render: function (r) { return F.tag(r.status); } },
            { label: "操作", render: function (r) {
              if (!canFinance()) return "—";
              var b = ['<button class="btn xs" data-view="' + F.esc(r.no) + '">三单对照</button>'];
              if (r.matchResult !== "通过") b.push('<button class="btn xs" data-match="' +
                F.esc(r.no) + '">重新匹配</button>');
              if (r.matchResult === "通过" && r.status !== "已付款") b.push(
                '<button class="btn xs primary" data-pay="' + F.esc(r.no) + '">付款</button>');
              return b.join(" ");
            } }
          ], d.list, { click: function (r) { return r.no; }, empty: "暂无发票" }) + "</div></div>";

        html += '<div class="panel"><div class="panel-title">应付账龄分析' +
          '<span class="panel-actions small muted">到期日 ' + pay.total + " 张 / 余额 " +
          F.money(pay.due) + "</span></div>" +
          '<div class="panel-body">' + F.barChart(pay.buckets.map(function (b, i) {
            return { label: b.bucket, label2: F.wan(b.amount), value: b.amount,
              color: ["#6aa9a0", "#2b9eb3", "#c8963e", "#d98a5f", "#c0504d"][i % 5] };
          }), { height: 170 }) + "</div>" +
          '<div class="panel-body flush">' + F.table([
            { label: "发票号", render: function (r) { return '<span class="mono small">' +
              F.esc(r.no) + "</span>"; } },
            { label: "供应商", key: "supplierName" },
            { label: "未付金额", num: true, render: function (r) {
              return F.money(Number(r.amount) - Number(r.paidAmount));
            } },
            { label: "到期日", key: "dueDate" },
            { label: "逾期天数", num: true, render: function (r) {
              return r.overdueDays > 0 ? '<b class="up">' + r.overdueDays + "</b>" : "—";
            } },
            { label: "账龄", render: function (r) { return F.tag(r.payState); } }
          ], pay.list, { empty: "没有未结清发票" }) + "</div></div>";

        document.getElementById("view").innerHTML = html;

        document.getElementById("iSearch").addEventListener("click", function () {
          st.kw = document.getElementById("iKw").value.trim(); draw();
        });
        document.getElementById("iKw").addEventListener("keydown", function (e) {
          if (e.key === "Enter") document.getElementById("iSearch").click();
        });
        document.querySelectorAll("[data-st]").forEach(function (b) {
          b.addEventListener("click", function () { st.status = b.getAttribute("data-st"); draw(); });
        });
        var nb = document.getElementById("iNew");
        if (nb) nb.addEventListener("click", newInvoice);
        F.bindRows(document, function (no) { triple(no, d.list); });
        document.querySelectorAll("[data-view]").forEach(function (b) {
          b.addEventListener("click", function (ev) {
            ev.stopPropagation();
            triple(b.getAttribute("data-view"), d.list);
          });
        });
        document.querySelectorAll("[data-match]").forEach(function (b) {
          b.addEventListener("click", function (ev) {
            ev.stopPropagation();
            F.api("POST", "/api/invoices/" + encodeURIComponent(b.getAttribute("data-match")) + "/match", {})
              .then(function (r) {
                F.toast("三单匹配：" + r.match.result + "（差异 " + F.money(r.match.diff) + "）",
                  r.match.result === "通过" ? "ok" : "err");
                draw();
              }).catch(function (e) { F.showErr(e); });
          });
        });
        document.querySelectorAll("[data-pay]").forEach(function (b) {
          b.addEventListener("click", function (ev) {
            ev.stopPropagation();
            payDialog(b.getAttribute("data-pay"), d.list);
          });
        });
        F.setStatus("结算付款 · " + d.total + " 张发票 / 待付 " + F.money(pay.due));
      }).catch(function (e) { F.showErr(e); });
    }

    function triple(no, list) {
      var r = list.filter(function (x) { return x.no === no; })[0];
      if (!r) return;
      var tol = 0.02;
      var inTol = Math.abs(Number(r.diffRate || 0)) <= tol;
      var body = '<div class="detail-head"><div class="dh-title">' + F.esc(r.no) + " · " +
        F.esc(r.supplierName) + '</div><div class="dh-tags">' + F.tag(r.matchResult || "未匹配") +
        F.tag(r.status) + "</div></div>" +
        '<div class="kpi-grid three" style="margin-bottom:10px">' +
        '<div class="kpi"><div class="k-label">订单金额</div><div class="k-value">' +
        F.money(r.poAmount) + '</div><div class="k-sub">' + F.esc(r.poNo) + "</div></div>" +
        '<div class="kpi"><div class="k-label">收货金额</div><div class="k-value">' +
        F.money(r.receivedAmount) + '</div><div class="k-sub">质检合格入库口径</div></div>' +
        '<div class="kpi ' + (inTol ? "green" : "red") + '"><div class="k-label">发票金额</div>' +
        '<div class="k-value">' + F.money(r.amount) + '</div><div class="k-sub">差异率 ' +
        F.pct(r.diffRate, 2) + " / 容差 " + F.pct(tol, 1) + "</div></div></div>" +
        F.table([
          { label: "项目", key: "k" },
          { label: "数值", num: true, render: function (x) { return x.v; } }
        ], [
          { k: "发票号码", v: F.esc(r.invoiceNo || "—") },
          { k: "开票日期", v: F.esc(r.invoiceDate || "—") },
          { k: "税率", v: F.pct(r.taxRate, 0) },
          { k: "差异金额", v: F.money(r.diffAmount) },
          { k: "匹配判定", v: F.tag(r.matchResult || "未匹配") },
          { k: "到期日", v: F.esc(r.dueDate || "—") },
          { k: "已付金额", v: F.money(r.paidAmount) },
          { k: "付款状态", v: F.tag(r.payState) }
        ]) +
        '<div class="note" style="margin-top:10px">匹配口径：|发票额 − 收货额| ÷ 收货额 ≤ 容差即通过；' +
        "无收货或无发票时分别返回「无收货」「无发票」，需先补收货或补登记发票。</div>";
      F.dialog("三单对照 · " + no, body, '<button class="btn" data-close2="1">关闭</button>');
      document.getElementById("dialog").querySelector("[data-close2]")
        .addEventListener("click", F.closeDialog);
    }

    function newInvoice() {
      F.api("GET", "/api/orders?status=全部").then(function (od) {
        var pool = od.list.filter(function (o) {
          return ["已下单", "部分到货", "全部到货"].indexOf(o.status) >= 0;
        });
        if (!pool.length) { F.toast("没有可登记发票的订单（需已下单 / 到货中）", "err"); return; }
        var opts = pool.map(function (o) {
          return '<option value="' + F.esc(o.no) + '" data-amt="' + o.receivedAmount + '" data-po="' +
            o.amount + '">' + F.esc(o.no + " · " + o.supplierName + " · 订单 " + F.money(o.amount) +
            " / 收货 " + F.money(o.receivedAmount)) + "</option>";
        }).join("");
        F.dialog("登记发票", '<div class="form-grid">' +
          '<label>采购订单</label><select id="vPo" style="grid-column:span 3">' + opts + "</select>" +
          '<label>发票号码</label><input id="vNo" type="text" placeholder="如 03210045">' +
          '<label>开票日期</label><input id="vDate" type="date" value="' + F.today() + '">' +
          '<label>发票金额</label><input id="vAmt" type="number" step="0.01">' +
          '<label>税率</label><input id="vTax" type="number" step="0.01" value="0.13">' +
          '<label>账期（天）</label><input id="vTerms" type="number" value="30">' +
          '<label>备注</label><input id="vRemark" type="text"></div>' +
          '<div class="small muted" style="margin-top:8px">登记时自动做三单匹配：发票金额与收货金额差异在容差内' +
          "则进入「待付款」，否则「差异挂起」。</div>",
          '<button class="btn" data-close2="1">取消</button>' +
          '<button class="btn primary" id="vSave">登记并匹配</button>');
        var dlg = document.getElementById("dialog");
        dlg.querySelector("[data-close2]").addEventListener("click", F.closeDialog);
        var sel = document.getElementById("vPo");
        function fill() {
          var o = sel.options[sel.selectedIndex];
          if (!o) return;
          var recv = Number(o.getAttribute("data-amt") || 0);
          var po = Number(o.getAttribute("data-po") || 0);
          document.getElementById("vAmt").value = (recv || po).toFixed(2);
        }
        sel.addEventListener("change", fill);
        fill();
        document.getElementById("vSave").addEventListener("click", function () {
          F.api("POST", "/api/invoices", {
            poNo: sel.value,
            invoiceNo: document.getElementById("vNo").value.trim(),
            invoiceDate: document.getElementById("vDate").value,
            amount: Number(document.getElementById("vAmt").value || 0),
            taxRate: Number(document.getElementById("vTax").value || 0.13),
            termsDays: Number(document.getElementById("vTerms").value || 30),
            remark: document.getElementById("vRemark").value.trim()
          }).then(function (r) {
            F.closeDialog();
            F.toast("发票已登记：" + r.no + " · 匹配 " + r.matchResult, r.matchResult === "通过" ? "ok" : "err");
            draw();
          }).catch(function (e) { F.showErr(e); });
        });
      });
    }

    function payDialog(no, list) {
      var r = list.filter(function (x) { return x.no === no; })[0];
      if (!r) return;
      var left = Number(r.amount) - Number(r.paidAmount);
      F.dialog("付款 · " + no, '<div class="form-grid">' +
        '<label>供应商</label><div>' + F.esc(r.supplierName) + "</div>" +
        '<label>发票金额</label><div>' + F.money(r.amount) + "</div>" +
        '<label>已付金额</label><div>' + F.money(r.paidAmount) + "</div>" +
        '<label>本次付款</label><input id="pAmt" type="number" step="0.01" value="' + left.toFixed(2) + '">' +
        "</div>" + '<div class="note" style="margin-top:10px">付款后如付满发票金额，发票状态置为「已付款」；' +
        "订单结算需财务在三单匹配通过后推进到「已结算」。</div>",
        '<button class="btn" data-close2="1">取消</button>' +
        '<button class="btn primary" id="pSave">确认付款</button>');
      document.getElementById("dialog").querySelector("[data-close2]")
        .addEventListener("click", F.closeDialog);
      document.getElementById("pSave").addEventListener("click", function () {
        F.api("POST", "/api/invoices/" + encodeURIComponent(no) + "/pay",
          { amount: Number(document.getElementById("pAmt").value || 0) }).then(function (res) {
          F.closeDialog();
          F.toast("付款已登记：" + F.money(res.paidAmount) + "（" + res.status + "）", "ok");
          draw();
        }).catch(function (e) { F.showErr(e); });
      });
    }

    draw();
  });

  /* ============================================================ 报表分析 */
  F.register("reports", function () {
    F.api("GET", "/api/reports").then(function (d) {
      var k = d.kpi;
      var html = '<div class="kpi-grid six">' +
        '<div class="kpi"><div class="k-label">采购订单</div><div class="k-value">' + k.poCount +
        '</div><div class="k-sub">金额 ' + F.wan(k.poAmount) + "</div></div>" +
        '<div class="kpi green"><div class="k-label">单均采购额</div><div class="k-value">' +
        F.wan(k.avgPoAmount) + '</div><div class="k-sub">不含已取消</div></div>' +
        '<div class="kpi"><div class="k-label">供应商</div><div class="k-value">' + k.supplierCount +
        '</div><div class="k-sub">已准入 ' + k.activeSupplier + "</div></div>" +
        '<div class="kpi"><div class="k-label">库存金额</div><div class="k-value">' +
        F.wan(k.stockAmount) + '</div><div class="k-sub">近 90 天领用 ' + F.wan(k.issueAmount) + "</div></div>" +
        '<div class="kpi red"><div class="k-label">缺料项</div><div class="k-value">' + k.shortageCount +
        '</div><div class="k-sub">含待补货</div></div>' +
        '<div class="kpi gold"><div class="k-label">应付 / 逾期</div><div class="k-value">' +
        F.wan(k.payable) + '</div><div class="k-sub">逾期 ' + F.wan(k.overduePayable) + "</div></div></div>";

      html += '<div class="panel"><div class="panel-title">采购金额趋势（近 6 个月）' +
        '<span class="panel-actions small muted">含未结算、不含已取消</span></div>' +
        '<div class="panel-body">' + F.lineChart([
          { name: "amount", data: d.purchaseTrend.map(function (t) { return t.amount; }) }
        ], { labels: d.purchaseTrend.map(function (t) { return t.month.slice(5) + "月"; }), height: 200 }) +
        "</div></div>";

      html += '<div class="panel"><div class="panel-title">采购金额 · 物料类别</div><div class="panel-body">' +
        F.barChart((d.byCategory || []).map(function (c, i) {
          return { label: c.category, label2: F.wan(c.amount), value: c.amount,
            color: ["#1f7a8c", "#2b9eb3", "#6aa9a0", "#c8963e", "#7a5ea8"][i % 5] };
        }), { height: 170 }) + "</div></div>";

      html += '<div class="panel"><div class="panel-title">供应商绩效 TOP 10' +
        '<span class="panel-actions small muted">交付 35 / 质量 35 / 价格 15 / 协同 15</span></div>' +
        '<div class="panel-body flush">' + F.table([
          { label: "供应商", render: function (r) { return F.esc(r.name) +
            '<div class="muted small mono">' + F.esc(r.code) + "</div>"; } },
          { label: "等级", render: function (r) { return F.levelTag(r.level); } },
          { label: "综合分", num: true, render: function (r) { return F.scoreBadge(r.score); } },
          { label: "交付及时率", num: true, render: function (r) { return F.pct(r.deliveryRate, 1); } },
          { label: "质量合格率", num: true, render: function (r) { return F.pct(r.qualityRate, 1); } },
          { label: "价格指数", num: true, render: function (r) {
            var v = Number(r.priceIndex || 1);
            return '<span class="' + (v > 1.02 ? "up" : v < 0.98 ? "down" : "") + '">' + v.toFixed(3) + "</span>";
          } },
          { label: "近 90 天准时率", num: true, render: function (r) { return F.pct(r.onTimeRate, 0); } },
          { label: "采购额", num: true, render: function (r) { return F.money(r.poAmount); } },
          { label: "订单数", num: true, render: function (r) { return r.poCount; } },
          { label: "状态", render: function (r) { return F.tag(r.status); } }
        ], d.suppliers || [], { empty: "暂无供应商绩效" }) + "</div></div>";

      html += '<div class="panel"><div class="panel-title">库存周转（近 90 天）</div><div class="panel-body flush">' +
        F.table([
          { label: "物料类别", key: "category" },
          { label: "出库金额", num: true, render: function (r) { return F.money(r.issueAmount); } },
          { label: "库存金额", num: true, render: function (r) { return F.money(r.stockAmount); } },
          { label: "周转次数", num: true, render: function (r) {
            return '<b>' + Number(r.times || 0).toFixed(2) + "</b>";
          } },
          { label: "周转天数", num: true, render: function (r) {
            return r.days === null ? "—" : F.qty(r.days) + " 天";
          } }
        ], d.turnover || [], { empty: "暂无周转数据" }) + "</div></div>";

      html += '<div class="panel"><div class="panel-title">到货准时率（按月）</div><div class="panel-body">' +
        F.lineChart([{ name: "rate", data: d.onTime.map(function (t) { return Number(t.rate || 0) * 100; }) }],
          { labels: d.onTime.map(function (t) { return t.month.slice(5) + "月"; }), height: 160 }) +
        '<div class="small muted">口径：收货日期 ≤ 订单承诺日期视为准时；当月无收货时按 0 处理。</div></div></div>';

      html += '<div class="panel"><div class="panel-title">重点物料价格波动' +
        '<span class="panel-actions small muted">价格指数 = 最新成交价 ÷ 标准价</span></div>' +
        '<div class="panel-body flush">' + F.table([
          { label: "物料", render: function (r) { return F.esc(r.name) +
            '<div class="muted small mono">' + F.esc(r.code) + "</div>"; } },
          { label: "标准价", num: true, render: function (r) { return F.money(r.standard); } },
          { label: "最新成交价", num: true, render: function (r) { return F.money(r.latest); } },
          { label: "价格指数", num: true, render: function (r) {
            var v = Number(r.index || 1);
            return '<b class="' + (v > 1 ? "up" : "down") + '">' + v.toFixed(3) + "</b>";
          } },
          { label: "节约率", num: true, render: function (r) {
            return F.pct(r.saving, 2);
          } },
          { label: "最近成交", render: function (r) {
            return (r.history || []).slice(0, 3).map(function (h) {
              return '<span class="small muted">' + F.esc(h.at) + " · " + F.money(h.price) + "</span>";
            }).join("<br>");
          } }
        ], d.price || [], { empty: "暂无价格记录" }) + "</div></div>";

      html += '<div class="panel"><div class="panel-title">缺料清单</div><div class="panel-body flush">' +
        F.table([
          { label: "物料", render: function (r) { return F.esc(r.name) +
            '<div class="muted small mono">' + F.esc(r.code) + "</div>"; } },
          { label: "现存量", num: true, render: function (r) { return F.qty(r.onHand) + " " + F.esc(r.unit); } },
          { label: "安全库存", num: true, render: function (r) { return F.qty(r.safetyStock); } },
          { label: "建议补货", num: true, render: function (r) {
            return '<b class="up">' + F.qty(r.suggestQty) + "</b>";
          } },
          { label: "预计金额", num: true, render: function (r) { return F.money(r.estAmount); } },
          { label: "状态", render: function (r) { return F.tag(r.state); } }
        ], d.shortages || [], { empty: "没有缺料" }) + "</div></div>";

      html += '<div class="panel"><div class="panel-title">应付账龄' +
        '<span class="panel-actions small muted">余额 ' + F.money(d.payables.due) + " / 逾期 " +
        F.money(d.payables.overdue) + "</span></div><div class='panel-body flush'>" +
        F.table([
          { label: "发票号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
          { label: "供应商", key: "supplierName" },
          { label: "未付金额", num: true, render: function (r) {
            return F.money(Number(r.amount) - Number(r.paidAmount));
          } },
          { label: "到期日", key: "dueDate" },
          { label: "逾期", num: true, render: function (r) {
            return r.overdueDays > 0 ? '<b class="up">' + r.overdueDays + " 天</b>" : "—";
          } }
        ], d.payables.list || [], { empty: "没有未结清发票" }) + "</div></div>";

      document.getElementById("view").innerHTML = html;
      F.setStatus("报表分析 · 9 个模块 · 三单匹配容差 " + F.pct(d.tolerance, 1));
      F.setSide('<div class="side-block"><div class="hd">口径说明</div><div class="bd small muted" ' +
        'style="line-height:1.9">采购趋势按订单下单月份归集；周转次数 = 近 90 天出库金额 ÷ 期末库存金额，' +
        "周转天数按月折算；准时率按收货日期与承诺日期比对；应付账龄按到期日之后的天数分档。</div></div>" +
        '<div class="side-block"><div class="hd">报表用途</div><div class="bd small muted" style="line-height:1.9">' +
        "采购额与类别结构用于预算复盘；供应商绩效用于年度评审与配额调整；缺料与效期用于补货排程；" +
        "价格波动用于议价与标准价维护。</div></div>");
    }).catch(function (e) { F.showErr(e); });
  });
})(window, document);

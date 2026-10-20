/* 飞泉 SCM · 离线 DEMO 数据层：拦截 fetch，在浏览器内存中实现与后端同口径的读写 */
(function () {
  "use strict";
  if (!window.__DEMO__ || !window.DB) return;

  var NOW = new Date();
  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  function today() {
    return NOW.getFullYear() + "-" + pad(NOW.getMonth() + 1) + "-" + pad(NOW.getDate());
  }
  function now() { return today() + " " + pad(NOW.getHours()) + ":" + pad(NOW.getMinutes()) + ":00"; }
  function addDays(n) {
    var d = new Date(NOW.getTime() + n * 86400000);
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }
  function r2(v) { return Math.round((Number(v || 0) + 1e-9) * 100) / 100; }
  function clone(x) { return JSON.parse(JSON.stringify(x)); }
  function nextSeq(list, prefix) {
    var max = 0;
    list.forEach(function (x) {
      var m = String(x.no || "").match(new RegExp(prefix + "\\d{8}-(\\d+)"));
      if (m) max = Math.max(max, Number(m[1]));
    });
    return max + 1;
  }
  function docNo(list, prefix) {
    return prefix + today().replace(/-/g, "") + "-" +
      ("000" + nextSeq(list, prefix)).slice(-4);
  }
  function log(action, detail) {
    DB.logs.unshift({ username: DB.me.username, action: action, detail: detail || "",
      created_at: now() });
    if (DB.logs.length > 200) DB.logs.pop();
    DB.__changeId = (DB.__changeId || (DB.integ.sync.changes.length
      ? DB.integ.sync.changes[DB.integ.sync.changes.length - 1].id : 0)) + 1;
    DB.integ.sync.changes.push({ id: DB.__changeId, obj_type: "", obj_no: "", op: "upsert",
      actor: DB.me.username, payload: "{}", changed_at: now() });
    DB.integ.overview.changes = DB.integ.sync.changes.length;
  }

  /* 深拷贝快照为可变工作区 */
  var DB = window.DB;
  DB.me = { username: "admin", displayName: "系统管理员", role: "admin",
    roleLabel: "系统管理员", perms: ["read", "write", "approve", "stock", "finance", "admin"] };
  DB.boot.user = { username: "admin", role: "admin", roleLabel: "系统管理员" };
  DB.suppliers.list.forEach(function (s) { DB.supD[s.code] = DB.supD[s.code] || s; });
  DB.orders.list.forEach(function (o) { DB.orderD[o.no] = DB.orderD[o.no] || o; });
  DB.reqs.list.forEach(function (r) { DB.reqD[r.no] = DB.reqD[r.no] || r; });
  DB.rfqs.list.forEach(function (r) { DB.rfqD[r.no] = DB.rfqD[r.no] || r; });
  DB.receipts.list.forEach(function (r) { DB.receiptD[r.no] = DB.receiptD[r.no] || r; });
  DB.materials.list.forEach(function (m) { DB.matD[m.code] = DB.matD[m.code] || m; });
  DB.__keySeq = DB.integ.keys.list.reduce(function (a, k) { return Math.max(a, k.id); }, 0);
  DB.__hookSeq = DB.integ.webhooks.list.reduce(function (a, k) { return Math.max(a, k.id); }, 0);
  DB.__dlvSeq = DB.integ.deliveries.list.reduce(function (a, k) { return Math.max(a, k.id); }, 0);

  var PO_FLOW = ["草稿", "待审批", "已下单", "部分到货", "全部到货", "已结算"];

  function poIndex(s) { return PO_FLOW.indexOf(s); }

  function match3(poAmount, recvAmount, invAmount, tol) {
    tol = tol === undefined ? 0.02 : tol;
    if (!recvAmount || recvAmount <= 0) return { result: "无收货", diff: 0, rate: 0 };
    if (!invAmount || invAmount <= 0) return { result: "无发票", diff: 0, rate: 0 };
    var diff = r2(invAmount - recvAmount);
    var rate = Math.abs(diff) / recvAmount;
    return { result: rate <= tol + 1e-9 ? "通过" : "金额差异超限", diff: diff, rate: Math.round(rate * 10000) / 10000 };
  }

  function stockState(qty, safety, reorder, maxStock) {
    if (qty <= 0) return "缺货";
    if (qty < safety) return "低于安全库存";
    if (reorder && qty <= reorder) return "待补货";
    if (maxStock && qty > maxStock) return "超储";
    return "正常";
  }

  function refreshKpi() {
    var k = DB.boot.kpi;
    k.openAmount = 0; k.openCount = 0; k.pendingApprove = 0;
    DB.orders.list.forEach(function (o) {
      if (["已下单", "部分到货", "待审批", "草稿"].indexOf(o.status) >= 0) {
        k.openAmount += o.amount; k.openCount += 1;
      }
      if (o.status === "待审批") k.pendingApprove += 1;
    });
    k.openAmount = r2(k.openAmount);
    k.pendingInvoice = DB.invoices.list.filter(function (i) { return i.status !== "已付款"; }).length;
    k.overduePayable = DB.payables.overdue;
    k.shortageCount = DB.shortage.total;
    DB.reloadHooks && DB.reloadHooks.forEach(function (f) { f(); });
  }

  /* ------------------------------------------------ 路由表 */
  var ROUTES = [];
  function route(method, re, fn) { ROUTES.push([method, re, fn]); }
  function ok(data) { return { status: 200, body: { ok: true, data: data } }; }
  function err(status, message) { return { status: status, body: { error: message } }; }

  function findReq(no) { return DB.reqD[no]; }
  function findOrder(no) { return DB.orderD[no]; }
  function findRfq(no) { return DB.rfqD[no]; }
  function findReceipt(no) { return DB.receiptD[no]; }
  function findMat(code) { return DB.matD[code]; }
  function findSup(code) { return DB.supD[code]; }
  function findInvoice(no) { return DB.invoices.list.filter(function (x) { return x.no === no; })[0]; }

  /* 认证 */
  route("POST", /^api\/auth\/login$/, function () {
    return ok({ token: "demo-token", username: "admin", displayName: "系统管理员",
      role: "admin", roleLabel: "系统管理员" });
  });
  route("POST", /^api\/auth\/logout$/, function () { return ok({ loggedOut: true }); });
  route("GET", /^api\/auth\/me$/, function () { return ok(DB.me); });
  route("GET", /^api\/bootstrap$/, function () { return ok(DB.boot); });
  route("GET", /^api\/health$/, function () {
    return ok({ status: "up", version: "1.0.0-demo", time: now(), uptime: 0,
      suppliers: DB.suppliers.total, materials: DB.materials.total, journal: "demo" });
  });

  /* 供应商 */
  route("GET", /^api\/suppliers$/, function (m, q) {
    var list = DB.suppliers.list;
    if (q.status && q.status !== "全部") list = list.filter(function (s) { return s.status === q.status; });
    if (q.level && q.level !== "全部") list = list.filter(function (s) { return s.level === q.level; });
    if (q.kw) list = list.filter(function (s) { return (s.name + s.code).indexOf(q.kw) >= 0; });
    return ok({ list: list, total: list.length, statusList: DB.suppliers.statusList });
  });
  route("POST", /^api\/suppliers$/, function (m, q, b) {
    var dup = DB.suppliers.list.filter(function (s) { return s.name === b.name; })[0];
    if (dup) return err(409, "疑似重复供应商：" + dup.name);
    var code = "SUP-" + ("000" + (DB.suppliers.total + DB.__supSeq)).slice(-4);
    DB.__supSeq = (DB.__supSeq || 0) + 1;
    var s = { code: code, name: b.name, shortName: "", category: b.category || "",
      contact: b.contact || "", phone: b.phone || "", status: "待准入", level: "C",
      score: 60, paymentTerms: 30, leadDays: 7, onTimeRate: 0, quals: [] };
    DB.suppliers.list.unshift(s); DB.supD[code] = s;
    DB.suppliers.total += 1; DB.boot.kpi.supplierCount += 1;
    log("新建供应商", b.name);
    return ok({ code: code, status: "待准入" });
  });
  route("GET", /^api\/suppliers\/([\w\-]+)$/, function (m, code) {
    var s = findSup(code);
    return s ? ok(clone(s)) : err(404, "供应商不存在");
  });
  route("PUT", /^api\/suppliers\/([\w\-]+)$/, function (m, code, b) {
    var s = findSup(code);
    if (!s) return err(404, "供应商不存在");
    Object.keys(b).forEach(function (k) { s[k] = b[k]; });
    log("更新供应商", code);
    return ok({ code: code, updated: true });
  });
  route("POST", /^api\/suppliers\/([\w\-]+)\/status$/, function (m, code, b) {
    var s = findSup(code);
    if (!s) return err(404, "供应商不存在");
    if (b.status === "已准入" && !(s.quals || []).length && s.__hasQual !== true)
      return err(400, "准入前需至少登记 1 项资质");
    s.status = b.status;
    log("供应商状态", code + " → " + b.status);
    return ok({ code: code, status: b.status });
  });
  route("POST", /^api\/suppliers\/([\w\-]+)\/quals$/, function (m, code, b) {
    var s = findSup(code);
    if (!s) return err(404, "供应商不存在");
    s.quals = s.quals || [];
    s.quals.push({ id: Date.now(), name: b.name, no: b.no, expireAt: b.expireAt, state: "有效" });
    s.__hasQual = true;
    log("登记资质", code + " " + b.name);
    return ok({ id: 1, state: "有效" });
  });
  route("POST", /^api\/suppliers\/([\w\-]+)\/score$/, function (m, code, b) {
    var s = findSup(code);
    if (!s) return err(404, "供应商不存在");
    var score = r2(100 * (0.35 * (b.deliveryRate || 0) + 0.35 * (b.qualityRate || 0) +
      0.15 * (b.responseRate || 0) + 0.15 * Math.max(0, 1 - Math.abs((b.priceIndex || 1) - 1))));
    s.score = score;
    s.level = score >= 85 ? "A" : score >= 70 ? "B" : score >= 55 ? "C" : "D";
    log("录入绩效", code + " " + score);
    return ok({ score: score, level: s.level });
  });

  /* 物料 */
  route("GET", /^api\/materials$/, function (m, q) {
    var list = DB.materials.list;
    if (q.kw) list = list.filter(function (x) { return (x.code + x.name).indexOf(q.kw) >= 0; });
    if (q.abc && q.abc !== "全部") list = list.filter(function (x) { return x.abc === q.abc; });
    return ok({ list: list, total: list.length });
  });
  route("GET", /^api\/materials\/check-dup$/, function (m, q) {
    var dups = DB.materials.list.filter(function (x) { return q.name && x.name === q.name; });
    return ok({ dups: dups.map(function (x) { return { code: x.code, name: x.name }; }) });
  });
  route("POST", /^api\/materials$/, function (m, q, b) {
    if (findMat(b.code)) return err(409, "物料编码已存在：" + b.code);
    var mt = { code: b.code, name: b.name, spec: b.spec || "", unit: b.unit || "件",
      category: b.category || "", abc: "C", standardPrice: Number(b.standardPrice || 0),
      lastPrice: Number(b.standardPrice || 0), safetyStock: Number(b.safetyStock || 0),
      maxStock: Number(b.maxStock || 0), avgDailyUsage: Number(b.avgDailyUsage || 0),
      leadDays: Number(b.leadDays || 7), status: "启用", onHand: 0, coverageDays: null };
    DB.materials.list.unshift(mt); DB.matD[b.code] = mt;
    DB.materials.total += 1; DB.boot.kpi.materialCount += 1;
    log("新建物料", b.code + " " + b.name);
    return ok({ code: b.code });
  });
  route("GET", /^api\/materials\/([\w\-]+)$/, function (m, code) {
    var mt = findMat(code);
    if (!mt) return err(404, "物料不存在");
    var d = clone(mt);
    d.prices = []; d.stock = DB.stock.list.filter(function (x) { return x.materialCode === code; });
    d.moves = DB.moves.list.filter(function (x) { return x.material_code === code; }).slice(0, 20);
    d.recentPo = []; d.suppliers = [];
    return ok(d);
  });
  route("PUT", /^api\/materials\/([\w\-]+)$/, function (m, code, b) {
    var mt = findMat(code);
    if (!mt) return err(404, "物料不存在");
    Object.keys(b).forEach(function (k) { mt[k] = b[k]; });
    log("更新物料", code);
    return ok({ code: code, updated: true });
  });
  route("POST", /^api\/materials\/abc-recalc$/, function () {
    return ok({ total: DB.materials.total, changed: 0,
      detail: DB.materials.list.map(function (x) {
        return { code: x.code, name: x.name, amount: x.standardPrice * 365, abc: x.abc };
      }) });
  });
  route("GET", /^api\/warehouses$/, function () { return ok(clone(DB.warehouses)); });

  /* 请购 */
  function reqListView(r) {
    return { no: r.no, dept: r.dept, purpose: r.purpose, needDate: r.needDate,
      amount: r.amount, status: r.status, applicant: r.applicant,
      applicantName: r.applicantName || r.applicant, itemCount: r.items.length,
      convertedNo: r.convertedNo || "" };
  }
  route("GET", /^api\/requisitions$/, function (m, q) {
    var list = DB.reqs.list.map(function (r) { return reqListView(DB.reqD[r.no] || r); });
    if (q.status && q.status !== "全部") list = list.filter(function (x) { return x.status === q.status; });
    if (q.kw) list = list.filter(function (x) {
      return (x.no + x.purpose + x.dept).indexOf(q.kw) >= 0; });
    return ok({ list: list, total: list.length });
  });
  route("POST", /^api\/requisitions$/, function (m, q, b) {
    if (!(b.items || []).length) return err(400, "请购至少需要一行物料明细");
    var no = docNo(Object.keys(DB.reqD).map(function (k) { return DB.reqD[k]; }), "PR");
    var amount = r2(b.items.reduce(function (a, i) {
      var mt = findMat(i.materialCode);
      return a + i.qty * (i.estPrice || (mt && mt.standardPrice) || 0);
    }, 0));
    var r = { no: no, dept: b.dept || "计划部", purpose: b.purpose || "物料请购",
      needDate: b.needDate || addDays(14), amount: amount, status: "草稿",
      applicant: DB.me.username, applicantName: DB.me.displayName,
      approver: "", rejectReason: "", convertedNo: "", remark: b.remark || "",
      items: b.items.map(function (i, idx) {
        var mt = findMat(i.materialCode) || {};
        return { id: idx + 1, materialCode: i.materialCode, materialName: mt.name || i.materialCode,
          spec: mt.spec || "", unit: mt.unit || "件", qty: i.qty,
          estPrice: i.estPrice || mt.standardPrice || 0, amount: r2(i.qty * (i.estPrice || mt.standardPrice || 0)) };
      }) };
    DB.reqD[no] = r; DB.reqs.list.unshift(reqListView(r));
    log("新建请购", no + " 金额 " + amount);
    return ok({ no: no, amount: amount, status: "草稿" });
  });
  route("GET", /^api\/requisitions\/([\w\-]+)$/, function (m, no) {
    var r = findReq(no);
    return r ? ok(clone(r)) : err(404, "请购单不存在");
  });
  route("POST", /^api\/requisitions\/([\w\-]+)\/submit$/, function (m, no) {
    var r = findReq(no);
    if (!r) return err(404, "请购单不存在");
    if (r.status !== "草稿") return err(400, "只有草稿可以提交（当前 " + r.status + "）");
    r.status = r.amount <= 5000 ? "已审批" : "待审批";
    if (r.status === "已审批") r.approver = "（免审批金额内自动通过）";
    syncReq(r);
    log("提交请购", no);
    return ok({ no: no, status: r.status });
  });
  function syncReq(r) {
    DB.reqs.list = DB.reqs.list.map(function (x) { return x.no === r.no ? reqListView(r) : x; });
  }
  route("POST", /^api\/requisitions\/([\w\-]+)\/approve$/, function (m, no, b) {
    var r = findReq(no);
    if (!r) return err(404, "请购单不存在");
    if (r.status !== "待审批") return err(400, "只有待审批可以批准（当前 " + r.status + "）");
    r.status = "已审批"; r.approver = DB.me.displayName;
    syncReq(r); log("批准请购", no);
    return ok({ no: no, status: "已审批" });
  });
  route("POST", /^api\/requisitions\/([\w\-]+)\/reject$/, function (m, no, b) {
    var r = findReq(no);
    if (!r) return err(404, "请购单不存在");
    r.status = "已驳回"; r.rejectReason = (b && b.reason) || "";
    syncReq(r); log("驳回请购", no);
    return ok({ no: no, status: "已驳回" });
  });
  route("POST", /^api\/requisitions\/([\w\-]+)\/cancel$/, function (m, no) {
    var r = findReq(no);
    if (!r) return err(404, "请购单不存在");
    r.status = "已取消"; syncReq(r); log("取消请购", no);
    return ok({ no: no, status: "已取消" });
  });
  route("POST", /^api\/requisitions\/([\w\-]+)\/to-order$/, function (m, no) {
    var r = findReq(no);
    if (!r) return err(404, "请购单不存在");
    if (r.status !== "已审批") return err(400, "只有已审批的请购可以转订单（当前 " + r.status + "）");
    var created = createPOFromItems(r.items, r, "");
    r.status = "已转单"; r.convertedNo = created.no; syncReq(r);
    return ok({ no: created.no, amount: created.amount, status: created.status });
  });
  route("POST", /^api\/requisitions\/([\w\-]+)\/to-rfq$/, function (m, no, b) {
    var r = findReq(no);
    if (!r) return err(404, "请购单不存在");
    if (r.status !== "已审批") return err(400, "只有已审批的请购可以发起询价（当前 " + r.status + "）");
    var codes = (b && b.supplierCodes) || [];
    if (codes.length < 2) return err(400, "询价至少需要 2 家供应商（当前 " + codes.length + " 家）");
    var rfqNo = docNo(Object.keys(DB.rfqD).map(function (k) { return DB.rfqD[k]; }), "RFQ");
    var rfq = { no: rfqNo, reqNo: no, title: r.purpose + " 询价比价", status: "询价中",
      deadline: addDays(7), owner: DB.me.username, ownerName: DB.me.displayName,
      awardedSupplier: "", awardedAmount: 0, itemCount: r.items.length, quoteCount: 0,
      bestAmount: 0, bestSupplier: "", spread: 0,
      items: r.items.map(function (i) {
        return { materialCode: i.materialCode, materialName: i.materialName,
          qty: i.qty, unit: i.unit };
      }), quotes: [] };
    DB.rfqD[rfqNo] = rfq; DB.rfqs.list.unshift(rfq);
    r.status = "已转单"; r.convertedNo = rfqNo; syncReq(r);
    log("发起询价", rfqNo);
    return ok({ rfqNo: rfqNo, suppliers: codes, reqStatus: "已转单" });
  });

  /* 询价 */
  route("GET", /^api\/rfqs$/, function () { return ok({ list: DB.rfqs.list, total: DB.rfqs.list.length }); });
  route("GET", /^api\/rfqs\/([\w\-]+)$/, function (m, no) {
    var r = findRfq(no);
    return r ? ok(clone(r)) : err(404, "询价单不存在");
  });
  route("POST", /^api\/rfqs\/([\w\-]+)\/quotes$/, function (m, no, b) {
    var r = findRfq(no);
    if (!r) return err(404, "询价单不存在");
    if (r.status !== "询价中") return err(400, "询价单已" + r.status + "，不能再登记报价");
    var s = findSup(b.supplierCode);
    if (!s) return err(400, "请选择报价供应商");
    var exist = r.quotes.filter(function (x) { return x.supplierCode === b.supplierCode; })[0];
    if (exist) { exist.amount = b.amount; exist.leadDays = b.leadDays || 0; }
    else r.quotes.push({ id: Date.now(), supplierCode: b.supplierCode, supplierName: s.name,
      amount: r2(b.amount), leadDays: b.leadDays || 0, validDays: b.validDays || 30,
      awarded: false, remark: b.remark || "" });
    r.quoteCount = r.quotes.length;
    var amts = r.quotes.map(function (x) { return x.amount; });
    r.bestAmount = Math.min.apply(null, amts);
    r.bestSupplier = r.quotes.filter(function (x) { return x.amount === r.bestAmount; })[0].supplierName;
    r.spread = r2(Math.max.apply(null, amts) - r.bestAmount);
    DB.rfqs.list = DB.rfqs.list.map(function (x) { return x.no === no ? x : x; });
    log("登记报价", no + " " + s.name);
    return ok({ id: 1, supplierCode: b.supplierCode, amount: r2(b.amount) });
  });
  route("POST", /^api\/rfqs\/([\w\-]+)\/award$/, function (m, no, b) {
    var r = findRfq(no);
    if (!r) return err(404, "询价单不存在");
    if (r.status !== "询价中") return err(400, "询价单已" + r.status);
    if (r.quoteCount < 2) return err(400, "报价家数不足，不能定标");
    var code = b.supplierCode;
    var q = r.quotes.filter(function (x) { return x.supplierCode === code; })[0];
    if (!q) return err(400, "该供应商没有报价记录");
    var created = createPOFromItems(r.items, findReq(r.reqNo) || {}, r.no, q.amount);
    r.status = "已定标"; r.awardedSupplier = code; r.awardedAmount = q.amount;
    q.awarded = true;
    log("询价定标", no + " → " + q.supplierName);
    return ok({ rfqNo: no, poNo: created.no, supplier: q.supplierName, amount: q.amount });
  });
  route("POST", /^api\/rfqs\/([\w\-]+)\/cancel$/, function (m, no) {
    var r = findRfq(no);
    if (!r) return err(404, "询价单不存在");
    r.status = "已取消"; log("取消询价", no);
    return ok({ no: no, status: "已取消" });
  });

  /* 采购订单 */
  function createPOFromItems(items, req, rfqNo, totalAmount) {
    var no = docNo(Object.keys(DB.orderD).map(function (k) { return DB.orderD[k]; }), "PO");
    var firstSup = DB.suppliers.list.filter(function (s) { return s.status === "已准入"; })[0];
    var scale = totalAmount && req.amount ? totalAmount / req.amount : 1;
    var poItems = items.map(function (i, idx) {
      var price = totalAmount ? r2((i.estPrice || i.amount / i.qty || 0) * scale) : (i.estPrice || 0);
      return { id: idx + 1, materialCode: i.materialCode, materialName: i.materialName,
        spec: i.spec || "", unit: i.unit || "", qty: i.qty, price: price,
        amount: r2(i.qty * price), receivedQty: 0, promiseDate: req.needDate || "" };
    });
    var amount = r2(poItems.reduce(function (a, i) { return a + i.amount; }, 0));
    var po = { no: no, supplierCode: firstSup ? firstSup.code : "", supplierName: firstSup ? firstSup.name : "",
      reqNo: req.no || "", rfqNo: rfqNo || "", title: (req.purpose || "采购") + "（演示）",
      amount: amount, currency: "CNY", status: "草稿", stageIndex: 0,
      promiseDate: req.needDate || "", owner: DB.me.username, ownerName: DB.me.displayName,
      approver: "", approvedAt: "", orderedAt: "", orderedQty: poItems.reduce(function (a, i) { return a + i.qty; }, 0),
      receivedQty: 0, receivedAmount: 0, invoicedAmount: 0, matchResult: "",
      receiveRate: 0, overdue: false, delayDays: 0, itemCount: poItems.length,
      receiptCount: 0, canAdvance: ["待审批"], items: poItems, receipts: [],
      remark: "", createdAt: now(), gateNotes: [] };
    DB.orderD[no] = po; DB.orders.list.unshift(po);
    DB.orders.total += 1;
    log("新建采购订单", no + " 金额 " + amount);
    refreshKpi();
    return po;
  }
  route("GET", /^api\/orders$/, function (m, q) {
    var list = DB.orders.list;
    if (q.status && q.status !== "全部") list = list.filter(function (o) { return o.status === q.status; });
    if (q.overdue === "1") list = list.filter(function (o) { return o.overdue; });
    if (q.kw) list = list.filter(function (o) {
      return (o.no + o.title + o.supplierName).indexOf(q.kw) >= 0; });
    return ok({ list: list, total: list.length, overdueCount: DB.orders.list.filter(function (o) { return o.overdue; }).length });
  });
  route("POST", /^api\/orders$/, function (m, q, b) {
    var s = findSup(b.supplierCode);
    if (!s) return err(400, "请选择供应商");
    var po = createPOFromItems((b.items || []).map(function (i) {
      var mt = findMat(i.materialCode) || {};
      return { materialCode: i.materialCode, materialName: mt.name || i.materialCode,
        unit: mt.unit || "件", qty: i.qty, estPrice: i.price || mt.standardPrice || 0,
        amount: r2(i.qty * (i.price || mt.standardPrice || 0)) };
    }), { purpose: b.title || "采购", no: "", needDate: b.promiseDate }, "", 0);
    po.supplierCode = s.code; po.supplierName = s.name;
    po.promiseDate = b.promiseDate || "";
    return ok({ no: po.no, amount: po.amount, status: po.status });
  });
  route("GET", /^api\/orders\/([\w\-]+)$/, function (m, no) {
    var o = findOrder(no);
    return o ? ok(clone(o)) : err(404, "订单不存在");
  });
  route("POST", /^api\/orders\/([\w\-]+)\/stage$/, function (m, no, b) {
    var o = findOrder(no);
    if (!o) return err(404, "订单不存在");
    var target = b.target;
    if (o.status === "已结算" || o.status === "已取消") return err(400, "订单已终态，不可变更");
    if (poIndex(target) <= poIndex(o.status)) return err(400, "采购订单只能向前推进（当前 " + o.status + "）");
    if (target === "待审批" && (!o.items.length || o.amount <= 0)) return err(400, "闸口未满足：明细与金额");
    if (target === "已下单") {
      if (!o.approver && !b.force) o.approver = DB.me.displayName;
      var s = findSup(o.supplierCode);
      if (!s || s.status !== "已准入") return err(400, "供应商未通过准入");
      o.orderedAt = now();
    }
    if (target === "全部到货" && o.receivedQty + 1e-6 < o.orderedQty)
      return err(400, "到货数量未达订单数量");
    if (target === "已结算") {
      if (!o.invoicedAmount) return err(400, "尚未登记发票");
      if (o.matchResult !== "通过") return err(400, "三单匹配未通过（" + (o.matchResult || "未匹配") + "）");
      o.closedAt = now();
    }
    o.status = target; o.stageIndex = poIndex(target);
    DB.orders.list = DB.orders.list.slice();
    log("推进订单", no + " → " + target);
    refreshKpi();
    return ok({ no: no, status: target });
  });
  route("POST", /^api\/orders\/([\w\-]+)\/cancel$/, function (m, no, b) {
    var o = findOrder(no);
    if (!o) return err(404, "订单不存在");
    o.status = "已取消"; o.cancelReason = (b && b.reason) || "";
    log("取消订单", no); refreshKpi();
    return ok({ no: no, status: "已取消" });
  });
  route("POST", /^api\/orders\/([\w\-]+)\/receive$/, function (m, no, b) {
    var o = findOrder(no);
    if (!o) return err(404, "订单不存在");
    if (["已下单", "部分到货"].indexOf(o.status) < 0)
      return err(400, "订单当前为「" + o.status + "」，不能登记收货");
    var no2 = docNo(Object.keys(DB.receiptD).map(function (k) { return DB.receiptD[k]; }), "GR");
    var items = (b.items || []).map(function (i, idx) {
      var line = o.items.filter(function (x) { return x.materialCode === i.materialCode; })[0] || {};
      return { id: idx + 1, materialCode: i.materialCode, materialName: line.materialName || i.materialCode,
        unit: line.unit || "件", qty: i.qty, okQty: i.qty, ngQty: 0,
        price: line.price || 0, amount: r2(i.qty * (line.price || 0)),
        batch: i.batch || ("B" + today().replace(/-/g, "").slice(4) + "01"),
        expireAt: i.expireAt || "", remark: "" };
    });
    var qty = items.reduce(function (a, i) { return a + i.qty; }, 0);
    var amount = r2(items.reduce(function (a, i) { return a + i.amount; }, 0));
    var rc = { no: no2, poNo: no, supplierCode: o.supplierCode, supplierName: o.supplierName,
      warehouse: (b.warehouse || "WH-SZ"), status: "待质检", inspectedBy: "",
      inspectResult: "", receivedAt: now(), postedAt: "", okQty: qty, ngQty: 0,
      passRate: 1, items: items, remark: "" };
    DB.receiptD[no2] = rc; DB.receipts.list.unshift(rc);
    o.receivedQty = r2(o.receivedQty + qty);
    o.receivedAmount = r2(o.receivedAmount + amount);
    o.receiveRate = Math.min(1, o.receivedQty / o.orderedQty);
    o.receiptCount += 1;
    o.receipts.unshift({ no: no2, status: "待质检", receivedAt: now(), posterAt: "" });
    if (o.receivedQty + 1e-6 >= o.orderedQty) { o.status = "全部到货"; o.stageIndex = 4; }
    else if (o.status === "已下单") { o.status = "部分到货"; o.stageIndex = 3; }
    log("登记收货", no2 + " " + no);
    refreshKpi();
    return ok({ no: no2, orderStatus: o.status, qty: r2(qty) });
  });

  /* 收货质检 */
  route("GET", /^api\/receipts$/, function (m, q) {
    var list = DB.receipts.list;
    if (q.status && q.status !== "全部") list = list.filter(function (x) { return x.status === q.status; });
    return ok({ list: list, total: list.length,
      statusList: ["全部", "待质检", "已质检", "已入库", "已退货"] });
  });
  route("GET", /^api\/receipts\/([\w\-]+)$/, function (m, no) {
    var r = findReceipt(no);
    return r ? ok(clone(r)) : err(404, "收货单不存在");
  });
  route("POST", /^api\/receipts\/([\w\-]+)\/inspect$/, function (m, no, b) {
    var r = findReceipt(no);
    if (!r) return err(404, "收货单不存在");
    if (r.status !== "待质检") return err(400, "只有待质检可以质检（当前 " + r.status + "）");
    (b.items || []).forEach(function (i) {
      var line = r.items.filter(function (x) { return x.materialCode === i.materialCode; })[0];
      if (line) { line.okQty = i.okQty; line.ngQty = i.ngQty || 0; }
    });
    var okQ = r.items.reduce(function (a, i) { return a + i.okQty; }, 0);
    var ngQ = r.items.reduce(function (a, i) { return a + i.ngQty; }, 0);
    r.okQty = okQ; r.ngQty = ngQ;
    var bad = okQ + ngQ ? ngQ / (okQ + ngQ) : 0;
    r.inspectResult = bad <= 0 ? "合格" : bad <= 0.02 ? "让步接收" : "退货";
    r.inspectedBy = DB.me.username; r.status = "已质检";
    log("质检", no + " " + r.inspectResult);
    return ok({ no: no, result: r.inspectResult, passRate: Math.round((1 - bad) * 10000) / 10000 });
  });
  route("POST", /^api\/receipts\/([\w\-]+)\/post$/, function (m, no) {
    var r = findReceipt(no);
    if (!r) return err(404, "收货单不存在");
    if (r.status !== "已质检") return err(400, "请先完成质检（当前 " + r.status + "）");
    r.status = "已入库"; r.postedAt = now();
    r.items.forEach(function (i) {
      DB.moves.list.unshift({ no: "MV" + today().replace(/-/g, "") + "-" + ("000" + (DB.moves.list.length + 1)).slice(-4),
        type: "采购入库", material_code: i.materialCode, material_name: i.materialName,
        warehouse: r.warehouse, batch: i.batch, qty: i.okQty,
        cost: r2(i.okQty * i.price), ref_no: no, reason: "采购入库", operator: DB.me.username,
        created_at: now() });
    });
    var o = findOrder(r.poNo);
    if (o) o.receipts = o.receipts.map(function (x) {
      return x.no === no ? { no: no, status: "已入库", receivedAt: x.receivedAt, posterAt: now() } : x; });
    log("入库过账", no);
    return ok({ no: no, status: "已入库" });
  });
  route("POST", /^api\/receipts\/([\w\-]+)\/return$/, function (m, no, b) {
    var r = findReceipt(no);
    if (!r) return err(404, "收货单不存在");
    r.status = "已退货"; r.remark = (b && b.reason) || r.remark;
    log("收货退货", no);
    return ok({ no: no, status: "已退货" });
  });

  /* 库存 */
  route("GET", /^api\/stock$/, function (m, q) {
    var list = DB.stock.list;
    if (q.kw) list = list.filter(function (x) {
      return (x.materialCode + x.materialName + (x.batch || "")).indexOf(q.kw) >= 0; });
    if (q.warehouse && q.warehouse !== "全部") list = list.filter(function (x) { return x.warehouse === q.warehouse; });
    if (q.state && q.state !== "全部") list = list.filter(function (x) { return x.state === q.state; });
    if (q.expiry === "近效期") list = list.filter(function (x) {
      return x.expiryState === "近效期" || x.expiryState === "已过期"; });
    return ok({ list: list, total: list.length,
      amount: r2(list.reduce(function (a, x) { return a + x.amount; }, 0)),
      byWarehouse: DB.stock.byWarehouse });
  });
  route("GET", /^api\/stock\/summary$/, function (m, q) {
    var list = DB.stockSummary.list;
    if (q.kw) list = list.filter(function (x) { return (x.code + x.name).indexOf(q.kw) >= 0; });
    return ok({ list: list, total: list.length, amount: DB.stockSummary.amount, counts: DB.stockSummary.counts });
  });
  route("GET", /^api\/stock\/shortage$/, function () { return ok(clone(DB.shortage)); });
  route("GET", /^api\/moves$/, function (m, q) {
    var list = DB.moves.list;
    if (q.kw) list = list.filter(function (x) {
      return (x.material_code + x.material_name + (x.ref_no || "")).indexOf(q.kw) >= 0; });
    if (q.type && q.type !== "全部") list = list.filter(function (x) { return x.type === q.type; });
    var inQ = 0, outQ = 0;
    list.forEach(function (x) {
      var v = Number(x.qty || 0);
      if (/入库/.test(x.type) || x.type === "盘盈") inQ += v;
      if (/出库/.test(x.type) || x.type === "盘亏") outQ += v;
    });
    return ok({ list: list, total: list.length, inQty: r2(inQ), outQty: r2(outQ) });
  });
  route("POST", /^api\/stock\/adjust$/, function (m, q, b) {
    var mt = findMat(b.materialCode);
    if (!mt) return err(400, "物料不存在");
    if (!(b.qty > 0)) return err(400, "数量需大于 0");
    var sign = (b.type === "盘亏" || b.type === "领用出库") ? -1 : 1;
    var row = DB.stock.list.filter(function (x) {
      return x.materialCode === b.materialCode && x.warehouse === b.warehouse; })[0];
    if (sign < 0 && (!row || row.qty < b.qty)) return err(400, "库存不足");
    if (row) { row.qty = r2(row.qty + sign * b.qty); row.amount = r2(row.qty * row.unitCost); }
    DB.moves.list.unshift({ no: "MV" + today().replace(/-/g, "") + "-" + ("000" + (DB.moves.list.length + 1)).slice(-4),
      type: b.type, material_code: b.materialCode, material_name: mt.name,
      warehouse: b.warehouse, batch: b.batch || "", qty: b.qty,
      cost: r2(b.qty * (mt.lastPrice || 0)), ref_no: "", reason: b.reason || "手工调整",
      operator: DB.me.username, created_at: now() });
    log("库存调整", b.type + " " + b.materialCode + " " + b.qty);
    return ok({ materialCode: b.materialCode, warehouse: b.warehouse, type: b.type, qty: r2(b.qty) });
  });

  /* 调拨与盘点 */
  function transferView(t) {
    return { no: t.no, fromWh: t.fromWh, toWh: t.toWh, status: t.status,
      applicant: t.applicant, approver: t.approver, remark: t.remark,
      createdAt: t.createdAt, updatedAt: t.createdAt, itemCount: t.items.length,
      qty: r2(t.items.reduce(function (a, i) { return a + i.qty; }, 0)), items: t.items };
  }
  route("GET", /^api\/transfers$/, function () {
    return ok({ list: DB.transfers.list, total: DB.transfers.list.length });
  });
  route("POST", /^api\/transfers$/, function (m, q, b) {
    if (b.fromWh === b.toWh) return err(400, "调出与调入仓库不能相同");
    if (!(b.items || []).length) return err(400, "调拨单至少需要一行物料");
    var no = "TR" + today().replace(/-/g, "") + "-" + ("000" + (DB.transfers.list.length + 1)).slice(-4);
    var t = { no: no, fromWh: b.fromWh, toWh: b.toWh, status: "已审批",
      applicant: DB.me.username, approver: "", remark: b.remark || "", createdAt: now(),
      items: b.items.map(function (i) {
        var mt = findMat(i.materialCode) || {};
        return { materialCode: i.materialCode, materialName: mt.name || i.materialCode,
          unit: mt.unit || "件", qty: i.qty };
      }) };
    DB.transfers.list.unshift(transferView(t));
    log("新建调拨", no);
    return ok({ no: no, status: "已审批" });
  });
  route("POST", /^api\/transfers\/([\w\-]+)\/approve$/, function (m, no) {
    var t = DB.transfers.list.filter(function (x) { return x.no === no; })[0];
    if (!t) return err(404, "调拨单不存在");
    if (t.status !== "草稿") return err(400, "只有草稿可以审批");
    t.status = "已审批"; t.approver = DB.me.username;
    log("审批调拨", no);
    return ok({ no: no, status: "已审批" });
  });
  route("POST", /^api\/transfers\/([\w\-]+)\/post$/, function (m, no) {
    var t = DB.transfers.list.filter(function (x) { return x.no === no; })[0];
    if (!t) return err(404, "调拨单不存在");
    if (t.status !== "已审批") return err(400, "只有已审批可以执行");
    t.items.forEach(function (i) {
      [t.fromWh, t.toWh].forEach(function (wh, idx) {
        DB.moves.list.unshift({ no: "MV" + today().replace(/-/g, "") + "-" + ("000" + (DB.moves.list.length + 1)).slice(-4),
          type: idx ? "调拨入库" : "调拨出库", material_code: i.materialCode,
          material_name: i.materialName, warehouse: wh, batch: "", qty: i.qty,
          cost: 0, ref_no: no, reason: "仓间调拨", operator: DB.me.username, created_at: now() });
      });
    });
    t.status = "已完成";
    log("执行调拨", no);
    return ok({ no: no, status: "已完成" });
  });
  route("GET", /^api\/stocktakes$/, function () {
    return ok({ list: DB.stocktakes.list, total: DB.stocktakes.list.length });
  });
  route("POST", /^api\/stocktakes$/, function (m, q, b) {
    var no = "ST" + today().replace(/-/g, "") + "-" + ("000" + (DB.stocktakes.list.length + 1)).slice(-4);
    var lines = DB.stock.list.filter(function (x) { return x.warehouse === b.warehouse; })
      .map(function (x, idx) {
        return { materialCode: x.materialCode, materialName: x.materialName, unit: x.unit,
          batch: x.batch, bookQty: x.qty, realQty: x.qty, diffQty: 0, cost: x.unitCost };
      });
    DB.stocktakes.list.unshift({ no: no, warehouse: b.warehouse, status: "草稿",
      applicant: DB.me.username, approver: "", diffAmount: 0, remark: b.remark || "",
      createdAt: now(), updatedAt: now(), itemCount: lines.length, diffCount: 0, items: lines });
    log("发起盘点", no);
    return ok({ no: no, lines: lines.length });
  });
  route("POST", /^api\/stocktakes\/([\w\-]+)\/finish$/, function (m, no, b) {
    var k = DB.stocktakes.list.filter(function (x) { return x.no === no; })[0];
    if (!k) return err(404, "盘点单不存在");
    if (k.status === "已完成") return err(400, "盘点单已完成");
    var diffAmount = 0, diffCount = 0;
    (b.items || []).forEach(function (i) {
      var line = k.items.filter(function (x) { return x.materialCode === i.materialCode; })[0];
      if (!line) return;
      line.realQty = i.realQty;
      line.diffQty = r2(i.realQty - line.bookQty);
      if (line.diffQty !== 0) {
        diffCount += 1;
        diffAmount += line.diffQty * line.cost;
        DB.moves.list.unshift({ no: "MV" + today().replace(/-/g, "") + "-" + ("000" + (DB.moves.list.length + 1)).slice(-4),
          type: line.diffQty > 0 ? "盘盈" : "盘亏", material_code: line.materialCode,
          material_name: line.materialName, warehouse: k.warehouse, batch: line.batch,
          qty: Math.abs(line.diffQty), cost: r2(Math.abs(line.diffQty) * line.cost),
          ref_no: no, reason: "盘点差异", operator: DB.me.username, created_at: now() });
      }
    });
    k.status = "已完成"; k.approver = DB.me.username;
    k.diffAmount = r2(diffAmount); k.diffCount = diffCount;
    log("完成盘点", no + " 差异 " + k.diffAmount);
    return ok({ no: no, status: "已完成", diffAmount: k.diffAmount });
  });

  /* 发票与付款 */
  route("GET", /^api\/invoices$/, function (m, q) {
    var list = DB.invoices.list;
    if (q.status && q.status !== "全部") list = list.filter(function (x) { return x.status === q.status; });
    if (q.kw) list = list.filter(function (x) {
      return (x.no + x.poNo + x.supplierName).indexOf(q.kw) >= 0; });
    return ok({ list: list, total: list.length, tolerance: 0.02,
      statusList: DB.invoices.statusList, summary: DB.invoices.summary });
  });
  route("POST", /^api\/invoices$/, function (m, q, b) {
    var o = findOrder(b.poNo);
    if (!o) return err(400, "采购订单不存在");
    if (["已下单", "部分到货", "全部到货"].indexOf(o.status) < 0)
      return err(400, "订单当前为「" + o.status + "」，不能登记发票");
    if (DB.invoices.list.filter(function (x) { return x.poNo === b.poNo && x.invoiceNo === b.invoiceNo; }).length)
      return err(409, "该订单已登记过同一发票号");
    var amount = Number(b.amount || 0);
    if (amount <= 0) return err(400, "发票金额需大于 0");
    var m3 = match3(o.amount, o.receivedAmount, amount);
    var no = "IV" + today().replace(/-/g, "") + "-" + ("000" + (DB.invoices.list.length + 1)).slice(-4);
    var inv = { no: no, poNo: o.no, supplierCode: o.supplierCode, supplierName: o.supplierName,
      invoiceNo: b.invoiceNo || "", amount: r2(amount), taxRate: b.taxRate || 0.13,
      invoiceDate: b.invoiceDate || today(), dueDate: addDays(b.termsDays || 30),
      status: m3.result === "通过" ? "待付款" : "差异挂起", matchResult: m3.result,
      diffAmount: m3.diff, diffRate: m3.rate, paidAmount: 0, paidAt: "", remark: b.remark || "",
      overdueDays: 0, payState: "待付", poAmount: o.amount, receivedAmount: o.receivedAmount };
    DB.invoices.list.unshift(inv);
    o.invoicedAmount = r2(amount); o.matchResult = m3.result;
    log("登记发票", no + " " + m3.result);
    refreshKpi();
    return ok({ no: no, matchResult: m3.result, diffAmount: m3.diff,
      status: inv.status, dueDate: inv.dueDate });
  });
  route("POST", /^api\/invoices\/([\w\-]+)\/match$/, function (m, no) {
    var inv = findInvoice(no);
    if (!inv) return err(404, "发票不存在");
    var o = findOrder(inv.poNo);
    var m3 = match3(o ? o.amount : 0, o ? o.receivedAmount : 0, inv.amount);
    inv.matchResult = m3.result;
    inv.status = m3.result === "通过" ? "待付款" : "差异挂起";
    inv.diffAmount = m3.diff; inv.diffRate = m3.rate;
    if (o) o.matchResult = m3.result;
    log("三单匹配", no + " → " + m3.result);
    return ok({ no: no, match: m3, status: inv.status });
  });
  route("POST", /^api\/invoices\/([\w\-]+)\/pay$/, function (m, no, b) {
    var inv = findInvoice(no);
    if (!inv) return err(404, "发票不存在");
    if (inv.matchResult !== "通过")
      return err(400, "三单匹配未通过（" + (inv.matchResult || "未匹配") + "），不能付款");
    var amount = Number(b && b.amount || (inv.amount - inv.paidAmount));
    if (amount <= 0) return err(400, "付款金额需大于 0");
    if (amount + inv.paidAmount > inv.amount + 0.01) return err(400, "付款金额超过发票金额");
    inv.paidAmount = r2(inv.paidAmount + amount);
    inv.status = inv.paidAmount + 0.01 >= inv.amount ? "已付款" : "待付款";
    inv.paidAt = inv.status === "已付款" ? now() : "";
    if (inv.status === "已付款") inv.payState = "已付";
    log("付款", no + " " + amount);
    refreshKpi();
    return ok({ no: no, paidAmount: inv.paidAmount, status: inv.status });
  });
  route("GET", /^api\/payables$/, function () { return ok(clone(DB.payables)); });

  /* 报表 / 设置 / 日志 / 用户 */
  route("GET", /^api\/reports$/, function () { return ok(clone(DB.reports)); });
  route("GET", /^api\/settings$/, function () { return ok(clone(DB.settings)); });
  route("PUT", /^api\/rules\/([\w\-]+)$/, function (m, code, b) {
    var rule = DB.settings.rules.filter(function (r) { return r.code === code; })[0];
    if (!rule) return err(404, "规则不存在");
    if (b.enabled !== undefined) rule.enabled = b.enabled ? 1 : 0;
    if (b.value !== undefined) rule.value = b.value;
    log("规则调整", code);
    return ok({ code: code, value: rule.value, enabled: rule.enabled, name: rule.name });
  });
  route("GET", /^api\/logs$/, function () { return ok(DB.logs); });
  route("GET", /^api\/users$/, function () {
    return ok(DB.settings.users || []);
  });

  /* 集成 */
  route("GET", /^api\/integration\/overview$/, function () { return ok(clone(DB.integ.overview)); });
  route("GET", /^api\/integration\/keys$/, function () {
    return ok({ list: DB.integ.keys.list, total: DB.integ.keys.list.length });
  });
  route("POST", /^api\/integration\/keys$/, function (m, q, b) {
    if (!b.name) return err(400, "Key 名称不能为空");
    var plain = "fqk_demo_" + Math.random().toString(36).slice(2, 14);
    var k = { id: ++DB.__keySeq, name: b.name, keyPrefix: plain.slice(0, 12), scope: b.scope || "read",
      owner: DB.me.username, status: "启用", expiresAt: b.expiresAt || "", lastUsedAt: "",
      createdAt: now() };
    DB.integ.keys.list.unshift(k);
    DB.integ.overview.keys += 1;
    log("新建 API Key", b.name);
    return ok({ id: k.id, name: k.name, key: plain, scope: k.scope,
      notice: "明文 Key 只在此次返回（演示环境为模拟值）" });
  });
  route("DELETE", /^api\/integration\/keys\/(\d+)$/, function (m, id) {
    var k = DB.integ.keys.list.filter(function (x) { return x.id === Number(id); })[0];
    if (!k) return err(404, "Key 不存在");
    k.status = "吊销";
    DB.integ.overview.keys = Math.max(0, DB.integ.overview.keys - 1);
    log("吊销 API Key", k.name);
    return ok({ id: Number(id), status: "吊销" });
  });
  route("GET", /^api\/integration\/webhooks$/, function () {
    return ok({ list: DB.integ.webhooks.list, events: DB.integ.webhooks.events });
  });
  route("POST", /^api\/integration\/webhooks$/, function (m, q, b) {
    if (!/^https?:\/\//.test(b.url || "")) return err(400, "回调地址必须以 http:// 或 https:// 开头");
    var h = { id: ++DB.__hookSeq, name: b.name || "未命名", url: b.url,
      events: Array.isArray(b.events) ? b.events.join(",") : (b.events || "*"),
      secret: "demo_secret_" + Math.random().toString(36).slice(2, 10),
      status: b.status || "启用", last_status: "", last_at: "", fail_count: 0,
      deliveryStats: {}, created_at: now() };
    DB.integ.webhooks.list.unshift(h);
    DB.integ.overview.webhooks += 1;
    log("新建 Webhook", h.url);
    return ok(clone(h));
  });
  route("PUT", /^api\/integration\/webhooks\/(\d+)$/, function (m, id, b) {
    var h = DB.integ.webhooks.list.filter(function (x) { return x.id === Number(id); })[0];
    if (!h) return err(404, "Webhook 不存在");
    h.name = b.name || h.name; h.url = b.url || h.url;
    h.events = Array.isArray(b.events) ? b.events.join(",") : (b.events || h.events);
    h.status = b.status || h.status;
    log("更新 Webhook", h.url);
    return ok(clone(h));
  });
  route("DELETE", /^api\/integration\/webhooks\/(\d+)$/, function (m, id) {
    DB.integ.webhooks.list = DB.integ.webhooks.list.filter(function (x) { return x.id !== Number(id); });
    log("删除 Webhook", id);
    return ok({ deleted: Number(id) });
  });
  route("POST", /^api\/integration\/webhooks\/(\d+)\/test$/, function (m, id) {
    DB.__dlvSeq += 1;
    DB.integ.deliveries.list.unshift({ id: DB.__dlvSeq, webhook_id: Number(id), event: "webhook.test",
      payload: { test: true, note: "飞泉 SCM 连通性测试（演示）" },
      signature: "demo_signature", status: "成功", attempts: 1, http_code: 200,
      error: "", next_at: "", created_at: now(), delivered_at: now() });
    DB.integ.overview.deliveries += 1;
    log("测试 Webhook", "#" + id);
    return ok({ queued: true, webhookId: Number(id) });
  });
  route("GET", /^api\/integration\/deliveries$/, function () {
    return ok({ list: DB.integ.deliveries.list, total: DB.integ.deliveries.list.length });
  });
  route("POST", /^api\/integration\/deliveries\/(\d+)\/retry$/, function (m, id) {
    var d = DB.integ.deliveries.list.filter(function (x) { return x.id === Number(id); })[0];
    if (d) d.status = "待投递";
    return ok({ id: Number(id), status: "待投递" });
  });
  route("GET", /^api\/integration\/mappings$/, function () {
    return ok({ list: DB.integ.mappings.list });
  });
  route("POST", /^api\/integration\/mappings$/, function (m, q, b) {
    if (!b.objType || !b.localNo || !b.externalId) return err(400, "objType / localNo / externalId 均必填");
    var exist = DB.integ.mappings.list.filter(function (x) {
      return x.obj_type === b.objType && x.external_id === b.externalId; })[0];
    if (exist) { exist.local_no = b.localNo; return ok({ id: exist.id, updated: true }); }
    DB.integ.mappings.list.unshift({ id: Date.now(), obj_type: b.objType, local_no: b.localNo,
      external_id: b.externalId, system: b.system || "", created_at: now() });
    DB.integ.overview.mappings += 1;
    log("绑定外部 ID", b.objType + " " + b.localNo);
    return ok({ id: 1, updated: false });
  });
  route("GET", /^api\/integration\/resolve$/, function (m, q) {
    var r = DB.integ.mappings.list.filter(function (x) { return x.external_id === q.externalId; })[0];
    return r ? ok(clone(r)) : err(404, "未找到映射");
  });
  route("GET", /^api\/sync\/changes$/, function (m, q) {
    var since = Number(q.since || 0);
    var limit = Math.min(500, Number(q.limit || 200));
    var list = DB.integ.sync.changes.filter(function (x) { return x.id > since; }).slice(0, limit);
    return ok({ changes: list, cursor: list.length ? list[list.length - 1].id : since,
      hasMore: false, count: list.length, serverTime: now() });
  });

  /* fetch 拦截 */
  var _fetch = window.fetch;
  window.fetch = function (input, opt) {
    opt = opt || {};
    var url = String(input);
    var mPath = url.match(/api\/[^?#]+/) || url.match(/^api\/[^?#]+/);
    if (!mPath) return _fetch ? _fetch(input, opt) : Promise.reject(new Error("no fetch"));
    var path = mPath[0].replace(/^\//, "");
    var qs = {};
    var qi = path.indexOf("?");
    if (qi >= 0) {
      path.slice(qi + 1).split("&").forEach(function (kv) {
        if (!kv) return;
        var j = kv.indexOf("=");
        qs[decodeURIComponent(j < 0 ? kv : kv.slice(0, j))] =
          decodeURIComponent(j < 0 ? "" : kv.slice(j + 1));
      });
      path = path.slice(0, qi);
    }
    var method = (opt.method || "GET").toUpperCase();
    var body = {};
    if (opt.body) { try { body = JSON.parse(opt.body); } catch (e) { body = {}; } }
    for (var i = 0; i < ROUTES.length; i++) {
      var r = ROUTES[i];
      if (r[0] !== method) continue;
      var m = path.match(r[1]);
      if (!m) continue;
      var out;
      try {
        out = r[2](m, qs, body);
      } catch (e) {
        out = err(500, "DEMO 内部错误：" + e.message);
      }
      return Promise.resolve({
        status: out.status,
        ok: out.status < 400,
        json: function () { return Promise.resolve(out.body); }
      });
    }
    return Promise.resolve({ status: 404, ok: false,
      json: function () { return Promise.resolve({ error: "DEMO 未模拟该接口：" + method + " " + path }); } });
  };

  /* localStorage 令牌直置，绕过登录页 */
  try {
    localStorage.setItem("fq_token", "demo-token");
    localStorage.setItem("fq_user", "admin");
    localStorage.setItem("fq_name", "系统管理员");
    localStorage.setItem("fq_role", "admin");
    localStorage.setItem("fq_role_label", "系统管理员");
  } catch (e) { /* 隐私模式忽略 */ }
})();

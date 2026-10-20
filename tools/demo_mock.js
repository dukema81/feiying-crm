/* 飞鹰CRM系统 · 离线 DEMO 运行时
 * 1) 伪造登录态（admin），让 app.js 直接进入系统；
 * 2) 拦截 fetch，把 /api/* 路由到内嵌快照 DB；
 * 3) 建线索 / 查重 / 转客户 / 商机阶段推进 / 报价折扣审批 / 合同签署 / 收款核销 /
 *    工单 SLA / 规则启停 都在浏览器内存里真实计算，口径与后端一致，
 *    因此页面上的漏斗、健康分、回款进度、SLA 剩余都会随操作变化。
 * 说明：仅用于演示，不落库、不做多用户鉴权（权限校验已在正式服务端实现）。
 */
(function () {
  "use strict";

  var S = window.DB;
  var TODAY = (S.boot && S.boot.today) || "2026-10-20";

  try {
    localStorage.setItem("fy_token", "demo-offline");
    localStorage.setItem("fy_user", "admin");
    localStorage.setItem("fy_name", "系统管理员");
    localStorage.setItem("fy_role", "admin");
    localStorage.setItem("fy_role_label", "系统管理员");
  } catch (e) { /* file:// 下可能禁用 storage，忽略 */ }

  /* ---------------------------------------------------------- 数值与时间 */
  function n(v) { return Number(v) || 0; }
  function r2(v) { return Math.round((n(v) + 1e-9) * 100) / 100; }
  function r4(v) { return Math.round((n(v) + 1e-9) * 10000) / 10000; }
  function sum(list, key) {
    return list.reduce(function (a, x) { return a + n(key ? x[key] : x); }, 0);
  }
  function p2(x) { return (x < 10 ? "0" : "") + x; }
  function nowStr() {
    var d = new Date();
    return TODAY + " " + p2(d.getHours()) + ":" + p2(d.getMinutes()) + ":" + p2(d.getSeconds());
  }
  function addDays(day, k) {
    var t = Date.parse(day + "T00:00:00");
    if (isNaN(t)) return day;
    var z = new Date(t + k * 86400000);
    return z.getFullYear() + "-" + p2(z.getMonth() + 1) + "-" + p2(z.getDate());
  }
  function daysBetween(a, b) {
    var x = Date.parse(String(a || "").slice(0, 10) + "T00:00:00");
    var y = Date.parse(String(b || "").slice(0, 10) + "T00:00:00");
    if (isNaN(x) || isNaN(y)) return null;
    return Math.round((y - x) / 86400000);
  }
  function hoursLeft(due) {
    var t = Date.parse(String(due || "").replace(" ", "T"));
    if (isNaN(t)) return 0;
    return Math.round(((t - Date.now()) / 3600000) * 100) / 100;
  }

  /* ---------------------------------------------------------- 业务常量 */
  var STAGES = ["初步接触", "需求确认", "方案报价", "商务谈判", "赢单", "输单"];
  var PROB = { "初步接触": 0.1, "需求确认": 0.25, "方案报价": 0.5, "商务谈判": 0.75,
               "赢单": 1, "输单": 0 };
  var GATE = { "需求确认": [["decisionMaker", "决策人"]],
               "方案报价": [["amount", "商机金额"]],
               "商务谈判": [["decisionMaker", "决策人"], ["competitor", "竞品情况"]],
               "赢单": [["contract", "已签署合同"]] };
  var SLA_HOURS = { P1: 4, P2: 8, P3: 24 };

  /* ---------------------------------------------------------- 内存状态 */
  var LEADS = (S.leads.list || []).slice();
  var LEAD_D = S.leadD || {};
  var CUS = (S.customers.list || []).slice();
  var CUS_D = S.custD || {};
  var OPPS = (S.opps.list || []).slice();
  var OPP_D = S.oppD || {};
  var QUOTES = (S.quotes.list || []).slice();
  var QUOTE_D = S.quoteD || {};
  var CTRS = (S.contracts.list || []).slice();
  var CTR_D = S.contractD || {};
  var TICKETS = (S.tickets.list || []).slice();
  var TICKET_D = S.ticketD || {};
  var ACTS = (S.activities.list || []).slice();
  var CAMP = (S.campaigns.list || []).slice();
  var PRODS = (S.products.list || []).slice();
  var RULES = (S.settings.rules || []).slice();
  var LOGS = (S.logs || []).slice();
  var PAYS = (S.payments.list || []).slice();
  var INTEG = {
    keys: (S.integ.keys.list || []).slice(),
    hooks: (S.integ.webhooks.list || []).slice(),
    deliveries: (S.integ.deliveries.list || []).slice(),
    maps: (S.integ.mappings.list || []).slice(),
    changes: (S.integ.sync.changes || []).slice()
  };
  var USERS = (S.settings.users || []).slice();
  var NAME = {};
  USERS.forEach(function (u) { NAME[u.username] = u.display_name; });
  function ownerName(u) { return NAME[u] || u || ""; }

  var PLANS = [];      /* 平铺回款计划，字段同合同详情的 plans */
  Object.keys(CTR_D).forEach(function (no) {
    (CTR_D[no].plans || []).forEach(function (p) { PLANS.push(p); });
  });

  /* 单号流水 */
  var seqs = { LD: 0, OPP: 0, QT: 0, CT: 0, SK: 0, TK: 0, CP: 0, ACT: 0, LOG: 0 };
  function seedSeq(kind, list, key) {
    (list || []).forEach(function (x) {
      var no = String(x[key || "no"] || x.code || "");
      var m = no.match(/-(\d{4,6})$/);
      if (m) seqs[kind] = Math.max(seqs[kind], parseInt(m[1], 10) || 0);
    });
  }
  seedSeq("LD", LEADS); seedSeq("OPP", OPPS); seedSeq("QT", QUOTES);
  seedSeq("CT", CTRS); seedSeq("TK", TICKETS);
  INTEG.deliveries.forEach(function (d) { seqs.SK = Math.max(seqs.SK, n(d.id)); });
  function nextNo(kind) {
    seqs[kind] += 1;
    var day = TODAY.replace(/-/g, "");
    var width = kind === "TK" ? 6 : 4;
    var s = String(seqs[kind]);
    while (s.length < width) s = "0" + s;
    return kind + day + "-" + s;
  }

  function log(action, detail) {
    LOGS.unshift({ id: ++seqs.LOG, username: "admin", action: action, detail: detail,
                   created_at: nowStr() });
  }

  function ruleValue(code, dft) {
    var r = RULES.filter(function (x) { return x.code === code; })[0];
    if (!r || !r.enabled) return dft === undefined ? null : dft;
    return n(r.value);
  }

  /* ---------------------------------------------------------- 规则引擎 */
  function gradeOf(budget, source) {
    var b = n(budget);
    var g = b >= 500000 ? "A" : (b >= 150000 ? "B" : "C");
    if ((source === "展会" || source === "老客推荐") && g !== "A") g = g === "B" ? "A" : "B";
    return g;
  }
  function normPhone(s) { return String(s || "").replace(/[^\d]/g, "").replace(/^(0086|86)(?=\d{11})/, ""); }
  function normCompany(s) {
    var t = String(s || "").toLowerCase().replace(/[\s\-_·,，.。()（）\[\]【】]/g, "");
    ["股份有限公司", "有限责任公司", "有限公司", "集团", "公司"].forEach(function (suf) {
      if (t.length > suf.length && t.slice(-suf.length) === suf) t = t.slice(0, -suf.length);
    });
    ["苏州", "上海", "北京", "深圳", "杭州", "南京", "广州", "无锡", "宁波", "合肥", "武汉", "成都"]
      .forEach(function (pre) {
        if (t.indexOf(pre) === 0 && t.length > pre.length + 1) t = t.slice(pre.length);
      });
    return t;
  }
  function lcs(a, b) {
    var best = 0, prev = [], cur, i, j;
    for (j = 0; j <= b.length; j++) prev[j] = 0;
    for (i = 1; i <= a.length; i++) {
      cur = [0];
      for (j = 1; j <= b.length; j++) {
        cur[j] = a[i - 1] === b[j - 1] ? prev[j - 1] + 1 : 0;
        if (cur[j] > best) best = cur[j];
      }
      prev = cur;
    }
    return best;
  }
  function similarity(a, b) {
    var x = normCompany(a), y = normCompany(b);
    if (!x || !y) return 0;
    if (x === y) return 1;
    var short = x.length <= y.length ? x : y, long = x.length <= y.length ? y : x;
    if (long.indexOf(short) >= 0) return r4(short.length / long.length);
    return r4(lcs(short, long) / long.length);
  }
  function nameAffinity(a, b, th) {
    var sim = similarity(a, b);
    if (sim < th) return 0;
    var x = normCompany(a), y = normCompany(b);
    var short = x.length <= y.length ? x : y, long = x.length <= y.length ? y : x;
    if (short && long.indexOf(short) >= 0) return sim;
    var pre = 0, i;
    for (i = 0; i < Math.min(x.length, y.length); i++) {
      if (x[i] !== y[i]) break;
      pre += 1;
    }
    return pre >= 2 ? sim : 0;
  }
  function dupCandidates(lead) {
    var th = ruleValue("dup_check", 0.62);
    var phone = normPhone(lead.phone), email = String(lead.email || "").toLowerCase();
    var out = [];
    var pools = [["lead", LEADS], ["customer", CUS]];
    pools.forEach(function (pool) {
      pool[1].forEach(function (o) {
        var no = o.no || o.code;
        if (no === (lead.no || lead.code)) return;
        var reasons = [], score = 0;
        if (phone && normPhone(o.phone) === phone) { reasons.push("手机号相同"); score = 1; }
        if (email && o.email && String(o.email).toLowerCase() === email) {
          reasons.push("邮箱相同"); score = Math.max(score, 0.95);
        }
        var sim = nameAffinity(lead.name, o.name, th);
        if (sim >= th) { reasons.push("名称相似 " + Math.round(sim * 100) + "%"); score = Math.max(score, sim); }
        if (reasons.length) {
          out.push({ objType: pool[0], no: no, name: o.name,
                     owner: o.owner || ownerName(o.owner), reason: reasons.join("；"),
                     score: r4(score) });
        }
      });
    });
    out.sort(function (a, b) { return b.score - a.score; });
    return out.slice(0, 5);
  }
  function canMove(cur, next) {
    if (next === "输单") {
      if (cur === "赢单" || cur === "输单") return [false, "已结单的商机不能改结果"];
      return [true, ""];
    }
    var ci = STAGES.indexOf(cur), ni = STAGES.indexOf(next);
    if (ni < 0) return [false, "阶段不存在：" + next];
    if (cur === "赢单" || cur === "输单") return [false, "已结单的商机需重开才能推进"];
    if (ni <= ci) return [false, "商机阶段不能回退（当前 " + cur + "）"];
    return [true, ""];
  }
  function gateMissing(stage, opp, hasContract) {
    var miss = [];
    (GATE[stage] || []).forEach(function (g) {
      if (g[0] === "contract") {
        if (!hasContract) miss.push(g[1]);
      } else if (g[0] === "amount") {
        if (n(opp.amount) <= 0) miss.push(g[1]);
      } else if (!String(opp[g[0]] || "").trim()) {
        miss.push(g[1]);
      }
    });
    return miss;
  }
  function hasContractOf(oppNo) {
    return CTRS.some(function (c) { return c.oppNo === oppNo && c.status !== "已终止"; });
  }
  function planStatus(amount, paid, due) {
    var a = n(amount), p = n(paid);
    if (p >= a - 0.005) return "已收";
    var od = daysBetween(due, TODAY);
    if (p > 0) return (od !== null && od > 0) ? "部分逾期" : "部分收款";
    return (od !== null && od > 0) ? "逾期" : "未收";
  }
  function buildPlans(amount, startDate, terms) {
    var parts = String(terms || "10").split("-").map(function (x) { return n(x); })
      .filter(function (x) { return x > 0; });
    if (!parts.length) parts = [10];
    var total = parts.reduce(function (a, b) { return a + b; }, 0);
    var out = [], left = r2(amount), acc = 0;
    parts.forEach(function (p, i) {
      acc += p;
      var amt = i === parts.length - 1 ? r2(n(amount) - (acc - p) / total * n(amount))
                                       : r2(n(amount) * p / total);
      if (i === parts.length - 1) amt = r2(left - sum(out, "amount"));
      out.push({ seq: i + 1, dueDate: addDays(startDate, 30 * (i + 1)), amount: amt,
                 paidAmount: 0, status: "未收" });
    });
    return out;
  }
  function scoreCustomer(code) {
    var c = CUS.filter(function (x) { return x.code === code; })[0] || { lastFollowAt: "" };
    var idle = c.lastFollowAt ? daysBetween(c.lastFollowAt, TODAY) : 999;
    var fresh = idle === null || idle > 90 ? 0 : Math.max(0, 30 - idle / 3);
    var paid = sum(PAYS.filter(function (p) { return p.customerCode === code; }), "amount");
    var payScore = paid > 0 ? Math.min(40, (Math.log(1 + paid / 10000) / Math.log(31)) * 40) : 0;
    var open = OPPS.filter(function (o) { return o.customerCode === code && o.status === "进行中"; });
    var oppScore = Math.min(20, open.length * 7);
    var overdue = PLANS.filter(function (p) {
      var ct = CTRS.filter(function (x) { return x.no === p.contract_no; })[0] || {};
      return ct.customerCode === code && p.status.indexOf("逾期") >= 0;
    }).length;
    var score = fresh + payScore + oppScore + 10 - Math.min(24, overdue * 8);
    score = Math.max(0, Math.min(100, Math.round(score)));
    return { score: score, paid: r2(paid) };
  }
  function scoreLevel(s) {
    return s >= 80 ? "优质" : (s >= 60 ? "健康" : (s >= 40 ? "待经营" : "流失风险"));
  }
  function funnelOf(list) {
    var stages = STAGES.slice(0, 5).map(function (sg) {
      var rows = list.filter(function (o) { return o.stage === sg; });
      return { stage: sg, count: rows.length, amount: r2(sum(rows, "amount")),
               weighted: r2(sum(rows, "weighted")), prob: PROB[sg] };
    });
    var open = list.filter(function (o) { return o.status === "进行中"; });
    var won = list.filter(function (o) { return o.status === "赢单"; });
    var lost = list.filter(function (o) { return o.status === "输单"; });
    return {
      stages: stages, openCount: open.length, openAmount: r2(sum(open, "amount")),
      wonCount: won.length, wonAmount: r2(sum(won, "amount")),
      lostCount: lost.length, lostAmount: r2(sum(lost, "amount")),
      winRate: won.length + lost.length ? r4(won.length / (won.length + lost.length)) : 0,
      avgDeal: won.length ? r2(sum(won, "amount") / won.length) : 0
    };
  }
  function agingBuckets() {
    var out = { "未到期": 0, "1-30 天": 0, "31-60 天": 0, "61-90 天": 0, "90 天以上": 0 };
    PLANS.forEach(function (p) {
      var left = r2(n(p.amount) - n(p.paidAmount));
      if (left <= 0.005) return;
      var od = daysBetween(p.dueDate, TODAY);
      if (od === null || od <= 0) out["未到期"] = r2(out["未到期"] + left);
      else if (od <= 30) out["1-30 天"] = r2(out["1-30 天"] + left);
      else if (od <= 60) out["31-60 天"] = r2(out["31-60 天"] + left);
      else if (od <= 90) out["61-90 天"] = r2(out["61-90 天"] + left);
      else out["90 天以上"] = r2(out["90 天以上"] + left);
    });
    return out;
  }

  /* ---------------------------------------------------------- 视图拼装 */
  function leadView(r) {
    var idle = r.lastFollowAt ? daysBetween(r.lastFollowAt, TODAY) : null;
    return {
      no: r.no, name: r.name, contact: r.contact || "", phone: r.phone || "",
      email: r.email || "", source: r.source || "", industry: r.industry || "",
      region: r.region || "", budget: r2(r.budget), demand: r.demand || "",
      grade: r.grade || gradeOf(r.budget, r.source), status: r.status || "待分配",
      owner: r.owner || "", ownerName: ownerName(r.owner), creator: r.creator || "admin",
      campaignCode: r.campaignCode || "", convertedCustomer: r.convertedCustomer || "",
      invalidReason: r.invalidReason || "", createdAt: r.createdAt || nowStr(),
      assignedAt: r.assignedAt || "", lastFollowAt: r.lastFollowAt || "",
      nextFollowAt: r.nextFollowAt || "",
      ageDays: daysBetween(r.createdAt || TODAY, TODAY) || 0, idleDays: idle
    };
  }
  function customerRow(r) {
    var open = OPPS.filter(function (o) { return o.customerCode === r.code && o.status === "进行中"; });
    var ct = CTRS.filter(function (c) { return c.customerCode === r.code && c.status !== "已终止"; });
    var sc = scoreCustomer(r.code);
    return {
      code: r.code, name: r.name, shortName: r.shortName || r.name.slice(0, 6),
      industry: r.industry || "", scale: r.scale || "中型", region: r.region || "华东",
      level: r.level || "B", source: r.source || "", owner: r.owner || "admin",
      ownerName: ownerName(r.owner), phone: r.phone || "", website: r.website || "",
      address: r.address || "", creditLimit: r2(r.creditLimit), status: r.status || "活跃",
      score: sc.score, scoreLevel: scoreLevel(sc.score), campaignCode: r.campaignCode || "",
      createdAt: r.createdAt || nowStr(), updatedAt: nowStr(), lastFollowAt: r.lastFollowAt || "",
      idleDays: r.lastFollowAt ? daysBetween(r.lastFollowAt, TODAY) : null,
      openOpps: open.length, openAmount: r2(sum(open, "amount")),
      contractCount: ct.length, contractAmount: r2(sum(ct, "amount")),
      paidAmount: sc.paid,
      openTickets: TICKETS.filter(function (t) {
        return t.customerCode === r.code && ["待受理", "处理中", "待确认"].indexOf(t.status) >= 0;
      }).length
    };
  }
  function oppView(r) {
    return {
      no: r.no, name: r.name, customerCode: r.customerCode, customerName: r.customerName,
      amount: r2(r.amount), stage: r.stage, stageIndex: STAGES.indexOf(r.stage),
      probability: r4(r.probability), weighted: r2(n(r.amount) * n(r.probability)),
      expectCloseDate: r.expectCloseDate || "", owner: r.owner || "admin",
      ownerName: ownerName(r.owner), source: r.source || "", campaignCode: r.campaignCode || "",
      competitor: r.competitor || "", decisionMaker: r.decisionMaker || "",
      status: r.status || "进行中", winReason: r.winReason || "", loseReason: r.loseReason || "",
      nextAction: r.nextAction || "", createdAt: r.createdAt || nowStr(), updatedAt: nowStr(),
      closedAt: r.closedAt || "", lastActivityAt: nowStr(),
      daysToClose: daysBetween(TODAY, r.expectCloseDate || ""),
      overdue: !!(r.expectCloseDate && r.expectCloseDate < TODAY && r.status === "进行中"),
      hasContract: hasContractOf(r.no),
      canAdvance: STAGES.filter(function (s) { return canMove(r.stage, s)[0]; })
    };
  }
  function quoteView(r) {
    var rate = n(r.listAmount) > 0 ? r4(1 - n(r.amount) / n(r.listAmount)) : 0;
    var th = ruleValue("discount_approval", 0.15);
    return {
      no: r.no, oppNo: r.oppNo || "", customerCode: r.customerCode, customerName: r.customerName,
      title: r.title, amount: r2(r.amount), listAmount: r2(r.listAmount), discountRate: rate,
      discountPct: Math.round(rate * 10000) / 100, status: r.status || "草稿",
      validUntil: r.validUntil || "", owner: r.owner || "admin", ownerName: ownerName(r.owner),
      approver: r.approver || "", approverName: ownerName(r.approver),
      approvedAt: r.approvedAt || "", rejectReason: r.rejectReason || "", remark: r.remark || "",
      createdAt: r.createdAt || nowStr(), needApproval: rate > n(th)
    };
  }
  function contractView(r) {
    var plans = r.plans || [];
    var paid = r2(sum(plans, "paidAmount"));
    var overdue = r2(plans.filter(function (p) { return p.status.indexOf("逾期") >= 0; })
      .reduce(function (a, p) { return a + (n(p.amount) - n(p.paidAmount)); }, 0));
    return {
      no: r.no, customerCode: r.customerCode, customerName: r.customerName,
      quoteNo: r.quoteNo || "", oppNo: r.oppNo || "", title: r.title, amount: r2(r.amount),
      signDate: r.signDate || "", startDate: r.startDate || "", endDate: r.endDate || "",
      paymentTerms: r.paymentTerms || "10", status: r.status || "待签署",
      owner: r.owner || "admin", ownerName: ownerName(r.owner), signedAt: r.signedAt || "",
      terminatedAt: r.terminatedAt || "", remark: r.remark || "", createdAt: r.createdAt || nowStr(),
      paidAmount: paid, unpaidAmount: r2(n(r.amount) - paid), overdueAmount: overdue,
      progress: n(r.amount) ? r4(paid / n(r.amount)) : 0, planCount: plans.length,
      paidCount: plans.filter(function (p) { return p.status === "已收"; }).length
    };
  }
  function ticketView(r) {
    var left = r.resolveDue ? hoursLeft(r.resolveDue) : 0;
    var state = r.slaState || "正常";
    if (["已解决", "已关闭"].indexOf(r.status) >= 0) state = "已完成";
    else if (r.resolveDue) state = left < 0 ? "超时" : (left <= 2 ? "临期" : "正常");
    return {
      no: r.no, customerCode: r.customerCode, customerName: r.customerName,
      contractNo: r.contractNo || "", title: r.title, category: r.category || "故障",
      priority: r.priority || "P3", status: r.status || "待受理", owner: r.owner || "chenlu",
      ownerName: ownerName(r.owner), creator: r.creator || "admin",
      description: r.description || "", createdAt: r.createdAt || nowStr(),
      acceptedAt: r.acceptedAt || "", resolvedAt: r.resolvedAt || "", closedAt: r.closedAt || "",
      responseDue: r.responseDue || "", resolveDue: r.resolveDue || "", slaState: state,
      slaLeftHours: left, satisfaction: n(r.satisfaction) || 0, resolution: r.resolution || "",
      ageHours: r.createdAt ? Math.max(0, Math.round(
        ((Date.parse(r.createdAt.replace(" ", "T")) - Date.now()) / 3600000) * -100) / 100) : 0
    };
  }
  function planFlat(p) {
    var ct = CTRS.filter(function (c) { return c.no === p.contract_no; })[0] || {};
    var st = planStatus(p.amount, p.paidAmount, p.dueDate);
    return {
      id: p.id, contractNo: p.contract_no, seq: p.seq, dueDate: p.dueDate,
      amount: r2(p.amount), paidAmount: r2(p.paidAmount),
      leftAmount: r2(n(p.amount) - n(p.paidAmount)), status: st,
      customerCode: ct.customerCode || "", customerName: ct.customerName || "",
      owner: ct.owner || "", ownerName: ownerName(ct.owner),
      overdueDays: st.indexOf("逾期") >= 0 ? (daysBetween(p.dueDate, TODAY) || 0) : 0
    };
  }

  /* ---------------------------------------------------------- 写操作 */
  function createLead(body) {
    if (!String(body.name || "").trim()) return fail("公司名称不能为空");
    if (!String(body.phone || "").trim() && !String(body.email || "").trim()) {
      return fail("手机号与邮箱至少填一个，否则无法查重与跟进");
    }
    var dups = dupCandidates(body);
    if (dups.length && !body.force) {
      var e = fail("疑似重复：" + dups[0].name + "（" + dups[0].reason +
                   "）。确认要新建请加 force=true", 409);
      e.dups = dups;
      e.json = function () {
        return Promise.resolve({ error: "疑似重复：" + dups[0].name + "（" + dups[0].reason +
          "）。确认要新建请加 force=true", dups: dups });
      };
      return e;
    }
    var row = leadView({
      no: nextNo("LD"), name: String(body.name).trim(), contact: body.contact || "",
      phone: body.phone || "", email: body.email || "", source: body.source || "官网表单",
      industry: body.industry || "", region: body.region || "华东", budget: n(body.budget),
      demand: body.demand || "", owner: body.owner || "", createdAt: nowStr(),
      assignedAt: body.owner ? nowStr() : "",
      status: body.owner ? "跟进中" : "待分配"
    });
    row.grade = gradeOf(row.budget, row.source);
    LEADS.unshift(row);
    LEAD_D[row.no] = Object.assign({}, row, { activities: [], poolLogs: [], dups: dups });
    log("新建线索", row.no + " " + row.name);
    return ok(row);
  }

  function leadAction(no, action, body) {
    var row = LEADS.filter(function (x) { return x.no === no; })[0];
    if (!row) return fail("线索不存在", 404);
    if (action === "assign") {
      if (!body.owner) return fail("请指定负责人");
      row.owner = body.owner; row.ownerName = ownerName(body.owner);
      row.status = "跟进中"; row.assignedAt = nowStr();
      log("分配线索", no + " → " + body.owner);
    } else if (action === "claim") {
      row.owner = "admin"; row.ownerName = ownerName("admin");
      row.status = "跟进中"; row.assignedAt = nowStr();
      log("领取线索", no);
    } else if (action === "recycle") {
      row.status = "公海"; row.owner = ""; row.ownerName = "";
      log("回收公海", no);
    } else if (action === "invalid") {
      if (!String(body.reason || "").trim()) return fail("标记无效必须填写原因");
      row.status = "无效"; row.invalidReason = body.reason;
      log("线索无效", no + " " + body.reason);
    } else if (action === "convert") {
      if (row.status === "已转客户") return fail("该线索已转客户：" + row.convertedCustomer);
      if (row.status === "无效") return fail("已标记无效的线索不能转客户");
      var code = "C-" + ("000" + (CUS.length + 1)).slice(-4);
      var c = customerRow({
        code: code, name: row.name, shortName: row.name.slice(0, 6),
        industry: row.industry || "制造业", region: row.region, source: row.source,
        owner: row.owner || "admin", phone: row.phone, level: "B", creditLimit: 0,
        status: "活跃", createdAt: nowStr()
      });
      CUS.unshift(c);
      CUS_D[code] = Object.assign({}, c, {
        contacts: [{ id: 1, customer_code: code, name: row.contact || "待补充", title: "联系人",
                     phone: row.phone, email: row.email, wechat: "", is_primary: 1, remark: "由线索转入" }],
        opportunities: [], quotes: [], contracts: [], activities: [], tickets: [], payments: [],
        stats: { openAmount: 0, contractAmount: 0, paidTotal: 0, overdueAmount: 0,
                 openTickets: 0, avgSatisfaction: 0 }
      });
      row.status = "已转客户"; row.convertedCustomer = code;
      log("线索转客户", no + " → " + code);
      return ok({ customerCode: code, lead: row });
    }
    LEAD_D[no] = Object.assign({}, row, LEAD_D[no] || {}, { activities: (LEAD_D[no] || {}).activities || [] });
    return ok(row);
  }

  function createCustomer(body) {
    if (!String(body.name || "").trim()) return fail("客户名称不能为空");
    var code = "C-" + ("000" + (CUS.length + 1)).slice(-4);
    var c = customerRow({
      code: code, name: String(body.name).trim(), shortName: body.shortName || "",
      industry: body.industry || "", scale: body.scale || "中型", region: body.region || "华东",
      level: body.level || "B", source: body.source || "官网表单", phone: body.phone || "",
      creditLimit: n(body.creditLimit), owner: "admin", status: "活跃", createdAt: nowStr()
    });
    CUS.unshift(c);
    CUS_D[code] = Object.assign({}, c, {
      contacts: [], opportunities: [], quotes: [], contracts: [], activities: [], tickets: [],
      payments: [], stats: { openAmount: 0, contractAmount: 0, paidTotal: 0, overdueAmount: 0,
                             openTickets: 0, avgSatisfaction: 0 }
    });
    log("新建客户", code + " " + c.name);
    return ok(c);
  }

  function createOpp(body) {
    var c = CUS.filter(function (x) { return x.code === body.customerCode; })[0];
    if (!c) return fail("客户不存在：" + body.customerCode, 404);
    if (!String(body.name || "").trim()) return fail("商机名称不能为空");
    if (n(body.amount) <= 0) return fail("商机金额必须大于 0");
    var row = oppView({
      no: nextNo("OPP"), name: String(body.name).trim(), customerCode: c.code,
      customerName: c.name, amount: n(body.amount), stage: "初步接触", probability: PROB["初步接触"],
      expectCloseDate: body.expectCloseDate || "", owner: "admin", source: c.source,
      competitor: body.competitor || "", decisionMaker: body.decisionMaker || "",
      status: "进行中", createdAt: nowStr()
    });
    OPPS.unshift(row);
    OPP_D[row.no] = Object.assign({}, row, {
      stageLogs: [{ id: 1, opp_no: row.no, from_stage: "", to_stage: "初步接触",
                    amount: row.amount, operator: "admin", remark: "商机创建", created_at: nowStr() }],
      activities: [], quotes: [], contracts: [], customer: c,
      stageGate: gateMap(row)
    });
    log("新建商机", row.no + " " + row.name);
    return ok(row);
  }
  function gateMap(opp) {
    var m = {};
    ["需求确认", "方案报价", "商务谈判", "赢单"].forEach(function (s) {
      m[s] = gateMissing(s, opp, hasContractOf(opp.no));
    });
    return m;
  }

  function moveStage(no, body) {
    var row = OPPS.filter(function (x) { return x.no === no; })[0];
    if (!row) return fail("商机不存在", 404);
    var target = body.stage;
    var mv = canMove(row.stage, target);
    if (!mv[0]) return fail(mv[1]);
    var eff = Object.assign({}, row);
    if (body.competitor) eff.competitor = body.competitor;
    if (body.decisionMaker) eff.decisionMaker = body.decisionMaker;
    var miss = gateMissing(target, eff, hasContractOf(no));
    if (miss.length) return fail("进入「" + target + "」前需补齐：" + miss.join("、"));
    row.competitor = eff.competitor; row.decisionMaker = eff.decisionMaker;
    var from = row.stage;
    row.stage = target; row.probability = PROB[target];
    row.weighted = r2(n(row.amount) * n(row.probability));
    row.status = target === "赢单" ? "赢单" : (target === "输单" ? "输单" : "进行中");
    row.closedAt = ["赢单", "输单"].indexOf(target) >= 0 ? nowStr() : "";
    row.updatedAt = nowStr();
    row.canAdvance = STAGES.filter(function (s) { return canMove(row.stage, s)[0]; });
    row.hasContract = hasContractOf(no);
    var d = OPP_D[no] || (OPP_D[no] = {});
    d.stageLogs = (d.stageLogs || []).concat([{ id: (d.stageLogs || []).length + 1, opp_no: no,
      from_stage: from, to_stage: target, amount: row.amount, operator: "admin",
      remark: body.remark || body.reason || "", created_at: nowStr() }]);
    Object.assign(d, row, { stageGate: gateMap(row) });
    log("商机阶段推进", no + " " + from + "→" + target);
    return ok(row);
  }

  function closeOpp(no, body) {
    var row = OPPS.filter(function (x) { return x.no === no; })[0];
    if (!row) return fail("商机不存在", 404);
    if (row.status !== "进行中") return fail("已结单的商机不能重复结单");
    if (body.result === "win") {
      if (row.stage !== "商务谈判") return fail("赢单只能从「商务谈判」进入");
      if (!hasContractOf(no)) return fail("赢单前需先在合同管理签署合同");
      return moveStage(no, { stage: "赢单", reason: body.reason });
    }
    if (!String(body.reason || "").trim()) return fail("输单必须填写原因");
    row.stage = "输单"; row.status = "输单"; row.probability = 0; row.weighted = 0;
    row.loseReason = body.reason; row.closedAt = nowStr();
    row.canAdvance = [];
    var d = OPP_D[no] || (OPP_D[no] = {});
    Object.assign(d, row, { stageGate: gateMap(row) });
    log("商机输单", no + " " + body.reason);
    return ok(row);
  }

  function createQuote(body) {
    var c = CUS.filter(function (x) { return x.code === body.customerCode; })[0];
    if (!c) return fail("客户不存在：" + body.customerCode, 404);
    var lines = (body.lines || []).filter(function (l) { return n(l.qty) > 0; });
    if (!lines.length) return fail("报价明细不能为空");
    var listAmount = 0, amount = 0, out = [];
    lines.forEach(function (l, i) {
      var p = PRODS.filter(function (x) { return x.code === l.productCode; })[0] || {};
      var lp = n(p.price), qty = n(l.qty), pr = n(l.price || lp);
      listAmount += lp * qty; amount += pr * qty;
      out.push({ id: i + 1, quote_no: "", seq: i + 1, product_code: l.productCode,
                 product_name: p.name || l.productCode, qty: qty, list_price: lp, price: pr,
                 amount: r2(pr * qty) });
    });
    var rate = listAmount ? r4(1 - amount / listAmount) : 0;
    var th = n(ruleValue("discount_approval", 0.15));
    var row = quoteView({
      no: nextNo("QT"), customerCode: c.code, customerName: c.name, title: body.title || "报价单",
      amount: r2(amount), listAmount: r2(listAmount), status: rate > th ? "待审批" : "草稿",
      validUntil: body.validUntil || addDays(TODAY, 30), owner: "admin",
      remark: body.remark || "", createdAt: nowStr()
    });
    QUOTES.unshift(row);
    out.forEach(function (l) { l.quote_no = row.no; });
    QUOTE_D[row.no] = Object.assign({}, row, { lines: out, threshold: th });
    log("新建报价", row.no + " 折扣 " + row.discountPct.toFixed(1) + "%");
    return ok(row);
  }

  function quoteAction(no, action, body) {
    var row = QUOTES.filter(function (x) { return x.no === no; })[0];
    if (!row) return fail("报价不存在", 404);
    var d = QUOTE_D[no] || (QUOTE_D[no] = {});
    if (action === "approve") {
      if (row.status !== "待审批") return fail("只有待审批的报价可以批准");
      row.status = "已批准"; row.approver = "admin"; row.approverName = ownerName("admin");
      row.approvedAt = nowStr();
    } else if (action === "reject") {
      if (row.status !== "待审批") return fail("只有待审批的报价可以驳回");
      if (!String(body.reason || "").trim()) return fail("驳回必须填写原因");
      row.status = "已驳回"; row.rejectReason = body.reason;
    } else if (action === "send") {
      if (["草稿", "已批准"].indexOf(row.status) < 0) {
        return fail("当前状态「" + row.status + "」不能发送");
      }
      if (row.needApproval && row.status === "草稿") return fail("折扣超审批线，需先由销售总监批准");
      row.status = "已发送";
    } else if (action === "accept") {
      if (row.status !== "已发送") return fail("只有已发送的报价可以标记客户接受");
      row.status = "已接受";
    } else {
      return fail("不支持的动作：" + action, 404);
    }
    Object.assign(d, row);
    log("报价" + action, no);
    return ok(row);
  }

  function createContract(body) {
    var c = CUS.filter(function (x) { return x.code === body.customerCode; })[0];
    if (!c) return fail("客户不存在：" + body.customerCode, 404);
    if (n(body.amount) <= 0) return fail("合同金额必须大于 0");
    var no = nextNo("CT");
    var plans = buildPlans(n(body.amount), body.signDate || TODAY, body.paymentTerms || "10")
      .map(function (p, i) {
        return { id: PLANS.length + i + 1, contract_no: no, seq: p.seq,
                 due_date: p.dueDate, dueDate: p.dueDate, amount: p.amount,
                 paid_amount: 0, paidAmount: 0, leftAmount: p.amount, status: "未收",
                 overdueDays: 0, remark: "" };
      });
    var row = contractView({
      no: no, customerCode: c.code, customerName: c.name, oppNo: body.oppNo || "",
      quoteNo: body.quoteNo || "", title: body.title || "CRM 服务合同", amount: n(body.amount),
      signDate: body.signDate || TODAY, startDate: body.signDate || TODAY,
      endDate: addDays(body.signDate || TODAY, 365), paymentTerms: body.paymentTerms || "10",
      status: "待签署", owner: "admin", remark: body.remark || "", createdAt: nowStr(),
      plans: plans
    });
    CTRS.unshift(row);
    plans.forEach(function (p) { PLANS.push(p); });
    CTR_D[no] = Object.assign({}, row, { plans: plans, payments: [], customer: c, quote: null });
    log("新建合同", no + " " + row.title);
    return ok(row);
  }

  function contractAction(no, action, body) {
    var row = CTRS.filter(function (x) { return x.no === no; })[0];
    if (!row) return fail("合同不存在", 404);
    var d = CTR_D[no] || (CTR_D[no] = { plans: [], payments: [] });
    if (action === "sign") {
      if (row.status !== "待签署") return fail("只有待签署的合同可以签署");
      var day = body.signDate || TODAY;
      row.status = "已签署"; row.signDate = day; row.startDate = day;
      row.endDate = addDays(day, 365); row.signedAt = nowStr();
      (d.plans || []).forEach(function (p) {          /* 按签署日重排计划 */
        p.dueDate = addDays(day, 30 * p.seq);
        p.due_date = p.dueDate;
      });
      if (row.oppNo) {
        var opp = OPPS.filter(function (o) { return o.no === row.oppNo; })[0];
        if (opp && opp.status === "进行中") moveStage(opp.no, { stage: "赢单", reason: "合同签署" });
      }
    } else if (action === "terminate") {
      if (!String(body.reason || "").trim()) return fail("终止必须填写原因");
      if (row.status === "已完成") return fail("已完成的合同不能终止");
      row.status = "已终止"; row.terminatedAt = nowStr(); row.remark = body.reason;
    } else {
      return fail("不支持的动作：" + action, 404);
    }
    Object.assign(d, row);
    log("合同" + action, no);
    return ok(row);
  }

  function createPayment(body) {
    var row = CTRS.filter(function (x) { return x.no === body.contractNo; })[0];
    if (!row) return fail("合同不存在：" + body.contractNo, 404);
    var ct = CTR_D[body.contractNo] || (CTR_D[body.contractNo] = { plans: [], payments: [] });
    if (row.status === "已终止") return fail("已终止的合同不能登记收款");
    var amount = r2(body.amount);
    if (amount <= 0) return fail("收款金额必须大于 0");
    var plans = ct.plans || [];
    var leftTotal = r2(plans.reduce(function (a, p) { return a + (n(p.amount) - n(p.paidAmount)); }, 0));
    if (amount > leftTotal + 0.01) {
      return fail("收款金额 " + amount.toFixed(2) + " 超过合同未收余额 " + leftTotal.toFixed(2));
    }
    var left = amount;
    plans.slice().sort(function (a, b) { return a.seq - b.seq; }).forEach(function (p) {
      if (left <= 0) return;
      var need = r2(n(p.amount) - n(p.paidAmount));
      if (need <= 0) return;
      var take = Math.min(need, left);
      p.paidAmount = r2(n(p.paidAmount) + take);
      p.paid_amount = p.paidAmount;
      p.leftAmount = r2(n(p.amount) - p.paidAmount);
      p.status = planStatus(p.amount, p.paidAmount, p.dueDate);
      p.overdueDays = p.status.indexOf("逾期") >= 0 ? (daysBetween(p.dueDate, TODAY) || 0) : 0;
      left = r2(left - take);
    });
    var pay = { no: nextNo("SK"), contractNo: row.no, planId: plans[0] ? plans[0].id : 0,
                customerCode: row.customerCode, customerName: row.customerName, amount: amount,
                payDate: body.payDate || TODAY, method: body.method || "银行转账",
                operator: "admin", remark: body.remark || "", createdAt: nowStr() };
    PAYS.unshift(pay);
    d.payments = (d.payments || []).concat([pay]);
    Object.assign(row, contractView(Object.assign({}, row, { plans: plans })));
    if (row.unpaidAmount <= 0.005) row.status = "已完成";
    else if (row.status === "已签署") row.status = "执行中";
    Object.assign(d, row);
    log("登记收款", row.no + " " + amount.toFixed(2));
    return ok({ no: pay.no, amount: amount, unpaidAmount: row.unpaidAmount,
                paidAmount: row.paidAmount, contractNo: row.no });
  }

  function createTicket(body) {
    var c = CUS.filter(function (x) { return x.code === body.customerCode; })[0];
    if (!c) return fail("客户不存在：" + body.customerCode, 404);
    if (!String(body.title || "").trim()) return fail("工单标题不能为空");
    var pr = body.priority || "P3";
    var hrs = n(ruleValue("sla_" + pr.toLowerCase(), SLA_HOURS[pr] || 24));
    var created = nowStr();
    var respDue = new Date(Date.parse(created.replace(" ", "T")) + Math.max(1, hrs / 2) * 3600000);
    var resDue = new Date(Date.parse(created.replace(" ", "T")) + hrs * 3600000);
    var fmt = function (dt) {
      return dt.getFullYear() + "-" + p2(dt.getMonth() + 1) + "-" + p2(dt.getDate()) + " " +
        p2(dt.getHours()) + ":" + p2(dt.getMinutes()) + ":" + p2(dt.getSeconds());
    };
    var row = ticketView({
      no: nextNo("TK"), customerCode: c.code, customerName: c.name, title: body.title,
      category: body.category || "故障", priority: pr, status: "待受理", owner: "chenlu",
      description: body.description || "", createdAt: created,
      responseDue: fmt(respDue), resolveDue: fmt(resDue)
    });
    TICKETS.unshift(row);
    TICKET_D[row.no] = Object.assign({}, row, {
      logs: [{ id: 1, ticket_no: row.no, action: "创建", content: "工单已创建", operator: "admin",
               created_at: created }],
      customer: c
    });
    log("新建工单", row.no + " " + row.title);
    return ok(row);
  }

  function ticketAction(no, action, body) {
    var row = TICKETS.filter(function (x) { return x.no === no; })[0];
    if (!row) return fail("工单不存在", 404);
    var d = TICKET_D[no] || (TICKET_D[no] = { logs: [] });
    var t = nowStr();
    if (action === "accept") {
      if (row.status !== "待受理") return fail("只有待受理的工单可以受理");
      row.status = "处理中"; row.acceptedAt = t;
    } else if (action === "resolve") {
      if (["待受理", "处理中"].indexOf(row.status) < 0) return fail("当前状态不能解决");
      if (!String(body.resolution || "").trim()) return fail("解决工单必须填写处理结论");
      row.status = "已解决"; row.resolvedAt = t; row.resolution = body.resolution;
    } else if (action === "close") {
      if (["已解决", "待确认"].indexOf(row.status) < 0) return fail("只有已解决的工单可以关闭");
      var sat = n(body.satisfaction);
      if (sat < 1 || sat > 5) return fail("满意度需在 1-5 之间");
      row.status = "已关闭"; row.closedAt = t; row.satisfaction = sat;
      row.slaState = "已完成";
    } else if (action === "comment") {
      if (!String(body.content || "").trim()) return fail("回复内容不能为空");
    } else {
      return fail("不支持的动作：" + action, 404);
    }
    d.logs = (d.logs || []).concat([{ id: (d.logs || []).length + 1, ticket_no: no,
      action: { accept: "受理", resolve: "解决", close: "关闭", comment: "跟进" }[action],
      content: body.comment || body.resolution || body.content || "",
      operator: "admin", created_at: t }]);
    Object.assign(d, ticketView(Object.assign({}, row)), { logs: d.logs });
    Object.assign(row, ticketView(Object.assign({}, row)));
    log("工单" + action, no);
    return ok(row);
  }

  function createActivity(body) {
    var name = "";
    if (body.objType === "lead") {
      var l = LEADS.filter(function (x) { return x.no === body.objNo; })[0];
      if (l) { name = l.name; l.lastFollowAt = body.happenAt || nowStr(); }
    } else if (body.objType === "opportunity") {
      var o = OPPS.filter(function (x) { return x.no === body.objNo; })[0];
      if (o) name = o.name;
    } else if (body.objType === "customer") {
      var c = CUS.filter(function (x) { return x.code === body.objNo; })[0];
      if (c) { name = c.name; c.lastFollowAt = body.happenAt || nowStr(); }
    } else if (body.objType === "ticket") {
      var tk = TICKETS.filter(function (x) { return x.no === body.objNo; })[0];
      if (tk) name = tk.title;
    }
    var act = { id: ACTS.length + 1, objType: body.objType, objNo: body.objNo, objName: name,
                kind: body.kind || "电话", subject: body.subject || "需求沟通",
                content: body.content || "", happenAt: (body.happenAt || nowStr()).slice(0, 16),
                durationMin: n(body.durationMin) || 30, owner: "admin", ownerName: ownerName("admin"),
                result: body.result || "", nextPlan: body.nextPlan || "", nextAt: "",
                status: "已完成", createdAt: nowStr() };
    ACTS.unshift(act);
    if (LEAD_D[body.objNo]) {
      LEAD_D[body.objNo].activities = [act].concat(LEAD_D[body.objNo].activities || []);
    }
    if (OPP_D[body.objNo]) {
      OPP_D[body.objNo].activities = [act].concat(OPP_D[body.objNo].activities || []);
    }
    if (CUS_D[body.objNo]) {
      CUS_D[body.objNo].activities = [act].concat(CUS_D[body.objNo].activities || []);
    }
    log("写跟进", body.objType + " " + body.objNo);
    return ok(act);
  }

  function bootData() {
    var b = JSON.parse(JSON.stringify(S.boot));
    var k = b.kpi;
    var open = OPPS.filter(function (o) { return o.status === "进行中"; });
    var won = OPPS.filter(function (o) { return o.status === "赢单"; });
    var lost = OPPS.filter(function (o) { return o.status === "输单"; });
    var month = TODAY.slice(0, 7);
    k.openAmount = r2(sum(open, "amount")); k.openCount = open.length;
    k.weighted = r2(sum(open, "weighted"));
    k.wonAmount = r2(sum(won, "amount")); k.wonCount = won.length;
    var mw = won.filter(function (o) { return String(o.closedAt || "").slice(0, 7) === month; });
    k.monthWonAmount = r2(sum(mw, "amount")); k.monthWonCount = mw.length;
    k.winRate = won.length + lost.length ? r4(won.length / (won.length + lost.length)) : 0;
    k.avgDeal = won.length ? r2(sum(won, "amount") / won.length) : 0;
    k.customerCount = CUS.length; k.leadCount = LEADS.length;
    var overdue = PLANS.filter(function (p) { return planStatus(p.amount, p.paidAmount, p.dueDate).indexOf("逾期") >= 0; });
    k.overdueCount = overdue.length;
    k.overdueAmount = r2(overdue.reduce(function (a, p) { return a + (n(p.amount) - n(p.paidAmount)); }, 0));
    k.ticketOpen = TICKETS.filter(function (t) {
      return ["待受理", "处理中", "待确认"].indexOf(t.status) >= 0; }).length;
    k.ticketOverdue = TICKETS.filter(function (t) { return ticketView(t).slaState === "超时"; }).length;
    k.paidTotal = r2(sum(PAYS, "amount"));
    k.contractAmount = r2(sum(CTRS.filter(function (c) { return c.status !== "已终止"; }), "amount"));
    b.funnel = funnelOf(OPPS);
    b.rules = RULES;
    b.myLeads = LEADS.filter(function (l) {
      return ["待分配", "公海"].indexOf(l.status) >= 0; }).slice(0, 5);
    b.myOpps = open.filter(function (o) { return o.owner === "admin"; }).slice(0, 6);
    return b;
  }

  function reportData() {
    var d = JSON.parse(JSON.stringify(S.reports));
    d.funnel = funnelOf(OPPS);
    d.aging.buckets = agingBuckets();
    d.aging.totalUnpaid = r2(sum(Object.keys(d.aging.buckets).map(function (k) { return d.aging.buckets[k]; })));
    d.aging.overdue = r2(sum(Object.keys(d.aging.buckets)
      .filter(function (k) { return k !== "未到期"; })
      .map(function (k) { return d.aging.buckets[k]; })));
    d.forecast.months = d.forecast.months.map(function (m) {
      var rows = OPPS.filter(function (o) {
        return o.status === "进行中" && String(o.expectCloseDate || "").slice(0, 7) === m.month;
      });
      var amt = r2(sum(rows, "amount"));
      var wt = r2(sum(rows, "weighted"));
      return { month: m.month, count: rows.length, amount: amt, weighted: wt,
               optimistic: r2(amt * 0.85), pessimistic: r2(wt * 0.7) };
    });
    d.forecast.total = {
      amount: r2(sum(d.forecast.months, "amount")),
      weighted: r2(sum(d.forecast.months, "weighted")),
      count: d.forecast.months.reduce(function (a, m) { return a + m.count; }, 0)
    };
    return d;
  }

  /* ---------------------------------------------------------- 响应封装 */
  function ok(data) {
    return { status: 200, ok: true, json: function () { return Promise.resolve({ data: data }); } };
  }
  function fail(msg, code) {
    return { status: code || 400, ok: false, json: function () {
      return Promise.resolve({ error: msg });
    } };
  }
  function parseQuery(qs) {
    var q = {};
    (qs || "").split("&").forEach(function (kv) {
      if (!kv) return;
      var i = kv.indexOf("=");
      var k = decodeURIComponent(i < 0 ? kv : kv.slice(0, i));
      var v = decodeURIComponent(i < 0 ? "" : kv.slice(i + 1));
      q[k] = v;
    });
    return q;
  }
  function pick(list, q, fields) {
    var kw = String(q.kw || "").trim().toLowerCase();
    var out = list.filter(function (x) {
      if (q.status && q.status !== "全部" && x.status !== q.status) return false;
      if (q.grade && q.grade !== "全部" && x.grade !== q.grade) return false;
      if (q.level && q.level !== "全部" && x.level !== q.level) return false;
      if (q.priority && q.priority !== "全部" && x.priority !== q.priority) return false;
      if (q.owner && x.owner !== q.owner) return false;
      if (!kw) return true;
      return fields.some(function (f) { return String(x[f] || "").toLowerCase().indexOf(kw) >= 0; });
    });
    return out;
  }
  function page(list, q) {
    var size = Math.max(1, n(q.pageSize) || 100), cur = Math.max(1, n(q.page) || 1);
    var total = list.length;
    return { list: list.slice((cur - 1) * size, cur * size), total: total, page: cur,
             pageSize: size, pages: Math.max(1, Math.ceil(total / size)) };
  }
  function countBy(list, key) {
    var out = {};
    list.forEach(function (x) { out[x[key]] = (out[x[key]] || 0) + 1; });
    return out;
  }

  /* ---------------------------------------------------------- 路由 */
  function handle(method, path, body) {
    var m = path.match(/^api\/(.*)$/);
    if (!m) return fail("未知接口", 404);
    var rest = m[1].split("?")[0];
    var query = parseQuery(m[1].split("?")[1] || "");

    if (rest === "auth/me") return ok(S.me);
    if (rest === "auth/logout") return ok({ ok: true });
    if (rest === "bootstrap") return ok(bootData());
    if (rest === "health") return ok({ status: "up", demo: true });
    if (rest === "products") return ok({ list: PRODS });

    /* 线索 */
    if (rest === "leads" && method === "GET") {
      var ll = pick(LEADS, query, ["no", "name", "contact", "phone"]);
      var p = page(ll, query);
      p.stats = countBy(LEADS, "status");
      p.poolCount = LEADS.filter(function (x) { return x.status === "公海"; }).length;
      p.unassigned = LEADS.filter(function (x) { return x.status === "待分配"; }).length;
      return ok(p);
    }
    if (rest === "leads" && method === "POST") return createLead(body);
    if (rest === "leads/check-dup") {
      return ok({ dups: dupCandidates({ name: query.name || "", phone: query.phone || "",
                                        email: query.email || "" }) });
    }
    var mla = rest.match(/^leads\/([\w\-]+)\/(\w+)$/);
    if (mla && method === "POST") return leadAction(mla[1], mla[2], body);
    var ml = rest.match(/^leads\/([\w\-]+)$/);
    if (ml) {
      var ld = LEAD_D[ml[1]];
      if (!ld) return fail("线索不存在", 404);
      return ok(Object.assign({}, ld, { dups: dupCandidates(ld) }));
    }

    /* 客户 */
    if (rest === "customers" && method === "GET") {
      var cl = pick(CUS, query, ["code", "name", "phone", "shortName"]);
      var cp = page(cl, query);
      cp.stats = { level: countBy(CUS, "level"), status: countBy(CUS, "status") };
      cp.list = cp.list.map(function (c) { return customerRow(c); });
      return ok(cp);
    }
    if (rest === "customers" && method === "POST") return createCustomer(body);
    var mc = rest.match(/^customers\/([\w\-]+)$/);
    if (mc) {
      var cd = CUS_D[mc[1]];
      if (!cd) return fail("客户不存在", 404);
      var row = customerRow(cd);
      var oppsOf = OPPS.filter(function (o) { return o.customerCode === mc[1]; });
      var ctsOf = CTRS.filter(function (c) { return c.customerCode === mc[1]; });
      return ok(Object.assign({}, cd, row, {
        opportunities: oppsOf,
        quotes: QUOTES.filter(function (q) { return q.customerCode === mc[1]; }),
        contracts: ctsOf,
        tickets: TICKETS.filter(function (t) { return t.customerCode === mc[1]; }),
        payments: PAYS.filter(function (x) { return x.customerCode === mc[1]; }),
        stats: {
          openAmount: r2(sum(oppsOf.filter(function (o) { return o.status === "进行中"; }), "amount")),
          contractAmount: r2(sum(ctsOf.filter(function (c) { return c.status !== "已终止"; }), "amount")),
          paidTotal: r2(sum(PAYS.filter(function (x) { return x.customerCode === mc[1]; }), "amount")),
          overdueAmount: r2(PLANS.filter(function (pl) {
            var ct = CTRS.filter(function (c) { return c.no === pl.contract_no; })[0] || {};
            return ct.customerCode === mc[1] && pl.status.indexOf("逾期") >= 0;
          }).reduce(function (a, pl) { return a + (n(pl.amount) - n(pl.paidAmount)); }, 0)),
          openTickets: TICKETS.filter(function (t) {
            return t.customerCode === mc[1] &&
              ["待受理", "处理中", "待确认"].indexOf(t.status) >= 0; }).length,
          avgSatisfaction: 0
        }
      }));
    }

    /* 商机 */
    if (rest === "opportunities" && method === "GET") {
      var ol = pick(OPPS, query, ["no", "name", "customerName"]);
      var op = page(ol, query);
      op.funnel = funnelOf(OPPS);
      return ok(op);
    }
    if (rest === "opportunities" && method === "POST") return createOpp(body);
    var moa = rest.match(/^opportunities\/([\w\-]+)\/(stage|close)$/);
    if (moa && method === "POST") {
      return moa[2] === "stage" ? moveStage(moa[1], body) : closeOpp(moa[1], body);
    }
    var mo = rest.match(/^opportunities\/([\w\-]+)$/);
    if (mo) {
      var od = OPP_D[mo[1]];
      if (!od) return fail("商机不存在", 404);
      return ok(Object.assign({}, od, {
        quotes: QUOTES.filter(function (q) { return q.oppNo === mo[1]; }),
        contracts: CTRS.filter(function (c) { return c.oppNo === mo[1]; }),
        stageGate: gateMap(od)
      }));
    }

    /* 跟进 */
    if (rest === "activities" && method === "GET") {
      var al = ACTS.slice();
      if (query.kind && query.kind !== "全部") {
        al = al.filter(function (a) { return a.kind === query.kind; });
      }
      if (query.objType) al = al.filter(function (a) { return a.objType === query.objType; });
      if (query.objNo) al = al.filter(function (a) { return a.objNo === query.objNo; });
      return ok({ list: al.slice(0, 300), total: al.length, byKind: countBy(al, "kind") });
    }
    if (rest === "activities" && method === "POST") return createActivity(body);

    /* 报价 */
    if (rest === "quotes" && method === "GET") {
      var ql = pick(QUOTES, query, ["no", "title", "customerName"]);
      var qp = page(ql, query);
      qp.stats = countBy(QUOTES, "status");
      return ok(qp);
    }
    if (rest === "quotes" && method === "POST") return createQuote(body);
    var mqa = rest.match(/^quotes\/([\w\-]+)\/(approve|reject|send|accept)$/);
    if (mqa && method === "POST") return quoteAction(mqa[1], mqa[2], body);
    var mq = rest.match(/^quotes\/([\w\-]+)$/);
    if (mq) {
      var qd = QUOTE_D[mq[1]];
      if (!qd) return fail("报价不存在", 404);
      return ok(qd);
    }

    /* 合同 */
    if (rest === "contracts" && method === "GET") {
      var tl = pick(CTRS, query, ["no", "title", "customerName"]);
      var tp = page(tl, query);
      tp.stats = countBy(CTRS, "status");
      return ok(tp);
    }
    if (rest === "contracts" && method === "POST") return createContract(body);
    var mta = rest.match(/^contracts\/([\w\-]+)\/(sign|terminate)$/);
    if (mta && method === "POST") return contractAction(mta[1], mta[2], body);
    var mt = rest.match(/^contracts\/([\w\-]+)$/);
    if (mt) {
      var td = CTR_D[mt[1]];
      if (!td) return fail("合同不存在", 404);
      return ok(Object.assign({}, td, contractView(td)));
    }

    /* 回款 */
    if (rest === "payments/plans") {
      var flat = PLANS.map(planFlat);
      if (query.overdue === "1") flat = flat.filter(function (x) { return x.status.indexOf("逾期") >= 0; });
      if (query.status && query.status !== "全部") {
        flat = flat.filter(function (x) { return x.status === query.status; });
      }
      flat.sort(function (a, b) { return a.dueDate < b.dueDate ? -1 : 1; });
      var pp = page(flat, query);
      pp.aging = agingBuckets();
      pp.totalUnpaid = r2(sum(flat, "leftAmount"));
      pp.totalOverdue = r2(sum(flat.filter(function (x) {
        return x.status.indexOf("逾期") >= 0; }), "leftAmount"));
      return ok(pp);
    }
    if (rest === "payments" && method === "GET") {
      var kw = String(query.kw || "").toLowerCase();
      var pays = PAYS.filter(function (x) {
        return !kw || [x.no, x.customerName, x.contractNo].join(" ").toLowerCase().indexOf(kw) >= 0;
      });
      return ok({ list: pays.slice(0, 300), total: pays.length, totalAmount: r2(sum(pays, "amount")) });
    }
    if (rest === "payments" && method === "POST") return createPayment(body);

    /* 工单 */
    if (rest === "tickets" && method === "GET") {
      var kl = pick(TICKETS, query, ["no", "title", "customerName"]);
      if (query.overdue === "1") {
        kl = kl.filter(function (t) { return ticketView(t).slaState === "超时"; });
      }
      var kp = page(kl, query);
      var views = TICKETS.map(ticketView);
      kp.stats = { status: countBy(TICKETS, "status"), priority: countBy(TICKETS, "priority"),
                   sla: countBy(views, "slaState") };
      var sats = TICKETS.filter(function (t) { return n(t.satisfaction) > 0; });
      kp.avgSatisfaction = sats.length ? r2(sum(sats, "satisfaction") / sats.length) : 0;
      kp.list = kp.list.map(ticketView);
      return ok(kp);
    }
    if (rest === "tickets" && method === "POST") return createTicket(body);
    var mka = rest.match(/^tickets\/([\w\-]+)\/(accept|resolve|close|comment)$/);
    if (mka && method === "POST") return ticketAction(mka[1], mka[2], body);
    var mk = rest.match(/^tickets\/([\w\-]+)$/);
    if (mk) {
      var kd = TICKET_D[mk[1]];
      if (!kd) return fail("工单不存在", 404);
      return ok(Object.assign({}, kd, ticketView(kd)));
    }

    /* 市场活动 */
    if (rest === "campaigns" && method === "GET") return ok({ list: CAMP, total: CAMP.length });
    if (rest === "campaigns" && method === "POST") {
      var code = "CP-" + TODAY.slice(0, 4) + "-" + ("0" + (CAMP.length + 1)).slice(-2);
      var camp = { code: code, name: body.name || "市场活动", kind: body.kind || "线上投放",
        channel: body.channel || "", startDate: body.startDate || TODAY,
        endDate: body.endDate || TODAY, budget: r2(body.budget), cost: r2(body.cost),
        targetLeads: n(body.targetLeads), owner: "admin", ownerName: ownerName("admin"),
        status: "进行中", remark: body.remark || "", leads: 0, wonAmount: 0, wonCount: 0,
        roi: 0, cpl: 0, budgetUsage: 0, leadRate: 0 };
      CAMP.unshift(camp);
      log("新建市场活动", code + " " + camp.name);
      return ok(camp);
    }

    /* 报表 / 设置 / 日志 */
    if (rest === "reports") return ok(reportData());
    if (rest === "settings") {
      return ok({ rules: RULES, users: USERS, teams: S.settings.teams || [],
                  targets: S.settings.targets || [], integration: S.settings.integration || {} });
    }
    var mr = rest.match(/^rules\/([\w]+)$/);
    if (mr) {
      for (var i = 0; i < RULES.length; i++) {
        if (RULES[i].code !== mr[1]) continue;
        if (body.enabled !== undefined) RULES[i].enabled = body.enabled ? 1 : 0;
        if (body.value !== undefined) RULES[i].value = n(body.value);
        log("修改业务规则", mr[1]);
        return ok(RULES[i]);
      }
      return fail("规则不存在", 404);
    }
    if (rest === "logs") return ok(LOGS.slice(0, 200));

    /* 集成中心 */
    if (rest === "integration/overview") {
      return ok({ keys: INTEG.keys.filter(function (k) { return k.status === "启用"; }).length,
                  webhooks: INTEG.hooks.filter(function (h) { return h.status === "启用"; }).length,
                  deliveries: INTEG.deliveries.length,
                  failed: INTEG.deliveries.filter(function (d) { return d.status === "失败"; }).length,
                  pending: INTEG.deliveries.filter(function (d) { return d.status === "待投递"; }).length,
                  changes: INTEG.changes.length,
                  lastChange: INTEG.changes.length ? INTEG.changes[INTEG.changes.length - 1].changed_at : "",
                  mappings: INTEG.maps.length, recent: INTEG.deliveries.slice(0, 5) });
    }
    if (rest === "integration/keys" && method === "GET") {
      return ok({ list: INTEG.keys, total: INTEG.keys.length });
    }
    if (rest === "integration/keys" && method === "POST") {
      var key = "fyk_demo_" + Math.random().toString(36).slice(2, 14);
      var k = { id: INTEG.keys.length + 1, name: body.name || "演示 Key", scope: body.scope || "read",
                keyPrefix: key.slice(0, 12), status: "启用", expiresAt: body.expiresAt || "",
                lastUsedAt: "", createdAt: nowStr() };
      INTEG.keys.unshift(k);
      log("新建 API Key", k.name);
      return ok(Object.assign({}, k, { key: key }));
    }
    var mkd = rest.match(/^integration\/keys\/(\d+)$/);
    if (mkd && method === "DELETE") {
      INTEG.keys = INTEG.keys.map(function (k) {
        if (String(k.id) === mkd[1]) k.status = "吊销";
        return k;
      });
      return ok({ ok: true });
    }
    if (rest === "integration/webhooks" && method === "GET") {
      return ok({ list: INTEG.hooks, events: ["*", "lead.created", "lead.converted",
        "opportunity.stage_changed", "opportunity.won", "quote.approved", "contract.signed",
        "payment.received", "ticket.created", "ticket.resolved"] });
    }
    if (rest === "integration/webhooks" && method === "POST") {
      var h = { id: INTEG.hooks.length + 1, name: body.name || "演示订阅", url: body.url || "",
                events: body.events || "*", status: "启用", last_status: "未投递", last_at: "",
                createdAt: nowStr(), deliveryStats: {} };
      INTEG.hooks.unshift(h);
      log("新建 Webhook", h.name);
      return ok(h);
    }
    if (/^integration\/webhooks\/\d+\/test$/.test(rest)) {
      INTEG.deliveries.unshift({ id: INTEG.deliveries.length + 1, event: "webhook.test",
        status: "成功", attempts: 1, http_code: 200, error: "",
        created_at: nowStr(), delivered_at: nowStr() });
      return ok({ queued: true });
    }
    if (/^integration\/webhooks\/\d+$/.test(rest) && method === "DELETE") {
      var hid = rest.split("/").pop();
      INTEG.hooks = INTEG.hooks.filter(function (x) { return String(x.id) !== hid; });
      return ok({ ok: true });
    }
    if (rest === "integration/deliveries" && method === "GET") {
      var dl = INTEG.deliveries;
      if (query.status && query.status !== "全部") {
        dl = dl.filter(function (d) { return d.status === query.status; });
      }
      return ok({ list: dl, total: dl.length });
    }
    if (/^integration\/deliveries\/\d+\/retry$/.test(rest)) {
      var did = rest.split("/")[2];
      INTEG.deliveries.forEach(function (d) {
        if (String(d.id) === did) { d.status = "成功"; d.delivered_at = nowStr(); }
      });
      return ok({ ok: true });
    }
    if (rest === "integration/mappings" && method === "GET") return ok({ list: INTEG.maps });
    if (rest === "integration/mappings" && method === "POST") {
      INTEG.maps.unshift({ id: INTEG.maps.length + 1, system: body.system || "ERP",
        obj_type: body.objType || "customer", obj_no: body.objNo || "",
        ext_id: body.extId || "", created_at: nowStr() });
      return ok({ ok: true });
    }
    if (rest === "sync/changes") {
      var since = n(query.since);
      var rows = INTEG.changes.filter(function (c) { return n(c.id) > since; });
      return ok({ changes: rows.slice(0, 100), cursor: INTEG.changes.length,
                  hasMore: false, count: rows.length, serverTime: nowStr() });
    }

    return fail("离线演示版未实现该接口：" + rest, 404);
  }

  /* ---------------------------------------------------------- fetch 拦截 */
  var rawFetch = window.fetch ? window.fetch.bind(window) : null;
  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url) || "";
    var method = ((init && init.method) || "GET").toUpperCase();
    var body = {};
    if (init && init.body) {
      try { body = JSON.parse(init.body); } catch (e) { body = {}; }
    }
    if (/api\//.test(url)) {
      var pure = url.replace(/^[^]*?api\//, "api/");
      try {
        return Promise.resolve(handle(method, pure, body));
      } catch (e) {
        return Promise.resolve(fail(e.message || String(e), 500));
      }
    }
    return rawFetch ? rawFetch(input, init) : Promise.reject(new Error("离线环境无法访问网络"));
  };
})();

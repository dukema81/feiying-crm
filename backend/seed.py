# -*- coding: utf-8 -*-
"""飞泉 SCM · 确定性演示数据（SEED=20261020，日历锚点 2026-10-20）

生成原则
- 随机数固定种子，任何机器上重跑结果一致，便于截图与测试断言；
- 各单据的金额、到货量、发票额之间存在业务关联（能跑通三单匹配）；
- 有意保留少量异常样本：缺货物料、近效期批次、资质临期供应商、差异超限发票，
  让驾驶舱的预警区在演示时不是空的。
"""
import random
from datetime import date, timedelta

import db
import scm

SEED = 20261020
TODAY = date(2026, 10, 20)
RND = random.Random(SEED)


def d(offset):
    return (TODAY + timedelta(days=offset)).isoformat()


def t(offset, hour=10, minute=0):
    return "%s %02d:%02d:00" % (d(offset), hour, minute)


USERS = [
    ("admin", "admin123", "系统管理员", "admin", "IT", "13900000001", "admin@feiquan.cn"),
    ("zhaokun", "fe@2026", "赵 坤", "purchase_director", "采购中心", "13900000002", "zhaokun@feiquan.cn"),
    ("liyan", "fe@2026", "李 燕", "buyer", "采购一部", "13900000003", "liyan@feiquan.cn"),
    ("zhouhao", "fe@2026", "周 浩", "buyer", "采购二部", "13900000004", "zhouhao@feiquan.cn"),
    ("wangjing", "fe@2026", "王 婧", "planner", "计划部", "13900000005", "wangjing@feiquan.cn"),
    ("sunlei", "fe@2026", "孙 磊", "warehouse", "仓储部", "13900000006", "sunlei@feiquan.cn"),
    ("chenqi", "fe@2026", "陈 琪", "quality", "质量部", "13900000007", "chenqi@feiquan.cn"),
    ("huangli", "fe@2026", "黄 莉", "finance", "财务部", "13900000008", "huangli@feiquan.cn"),
]

TEAMS = [
    ("PUR-01", "采购一部", "采购中心", "zhaokun", "电子件与结构件"),
    ("PUR-02", "采购二部", "采购中心", "zhaokun", "包材、辅料与设备"),
    ("PLN-01", "计划部", "供应链", "wangjing", "需求计划与补货"),
    ("WHS-01", "仓储部", "供应链", "sunlei", "三仓与线边库"),
]

RULES = [
    ("match_tolerance", "三单匹配金额容差", "结算", 0.02, "", 1, "发票金额与收货金额差异率上限"),
    ("req_free_limit", "请购免审批金额", "采购", 5000, "元", 1, "低于该金额的请购无需总监审批"),
    ("po_approve_limit", "订单总监审批线", "采购", 50000, "元", 1, "超过该金额的采购订单须采购总监审批"),
    ("qual_warn_days", "资质到期预警", "供应商", 30, "天", 1, "资质在此天数内到期触发预警"),
    ("expiry_warn_days", "批次近效期预警", "库存", 90, "天", 1, "批次在此天数内到期触发预警"),
    ("rfq_min_suppliers", "询价最少供应商数", "采购", 2, "家", 1, "询价单报价家数低于该值不允许定标"),
    ("price_deviation_warn", "价格偏离预警", "采购", 0.05, "", 1, "成交价高于最近均价该比例触发提示"),
    ("stock_cover_days", "库存覆盖天数目标", "库存", 15, "天", 1, "低于该覆盖天数视为待补货"),
]

BUDGETS = [
    ("2026-Q4", "采购中心", 4800000, 3120000, "Q4 直接材料预算"),
    ("2026-Q4", "计划部", 260000, 143000, "计划与备件"),
    ("2026-Q4", "仓储部", 180000, 96000, "包材与耗材"),
    ("2026-Q4", "研发部", 420000, 268000, "样机物料"),
]

WAREHOUSES = [
    ("WH-SZ", "苏州中心仓", "苏州工业园区星湖街 88 号", "sunlei", "启用", "成品与关键件"),
    ("WH-KS", "昆山线边仓", "昆山开发区前进路 12 号", "sunlei", "启用", "产线线边库"),
    ("WH-WX", "无锡中转仓", "无锡新吴区长江路 6 号", "sunlei", "启用", "区域中转"),
]

SUPPLIERS = [
    # code, name, short, category, level, status, region, terms, lead, capacity
    ("SUP-0001", "苏州精工电子科技有限公司", "精工电子", "电子件", "A", "已准入", "苏州", 30, 12, "月产能 80 万件"),
    ("SUP-0002", "昆山恒达精密模具有限公司", "恒达模具", "结构件", "B", "已准入", "昆山", 45, 20, "月产能 120 套"),
    ("SUP-0003", "上海立信包装材料有限公司", "立信包装", "包材", "A", "已准入", "上海", 30, 7, "月产能 300 万只"),
    ("SUP-0004", "无锡迈拓自动化设备有限公司", "迈拓自动化", "设备", "B", "已准入", "无锡", 60, 35, "年产能 200 台"),
    ("SUP-0005", "宁波华翔五金制品有限公司", "华翔五金", "五金", "C", "已准入", "宁波", 30, 15, "月产能 60 万件"),
    ("SUP-0006", "苏州安捷线束有限公司", "安捷线束", "电子件", "A", "已准入", "苏州", 30, 10, "月产能 40 万条"),
    ("SUP-0007", "常州瑞泰塑胶科技有限公司", "瑞泰塑胶", "结构件", "B", "已准入", "常州", 45, 18, "月产能 90 万件"),
    ("SUP-0008", "杭州威创电源技术有限公司", "威创电源", "电子件", "B", "已准入", "杭州", 30, 21, "月产能 15 万套"),
    ("SUP-0009", "苏州新元化工材料有限公司", "新元化工", "辅料", "C", "已准入", "苏州", 30, 9, "月产能 200 吨"),
    ("SUP-0010", "南京中soft信息技术有限公司", "中软信息", "服务", "C", "待准入", "南京", 30, 15, "—"),
    ("SUP-0011", "合肥晶显光电有限公司", "晶显光电", "电子件", "B", "已准入", "合肥", 45, 25, "月产能 12 万片"),
    ("SUP-0012", "东莞立信达五金电子有限公司", "立信达", "五金", "D", "观察", "东莞", 30, 20, "月产能 30 万件"),
    ("SUP-0013", "青岛海川物流设备有限公司", "海川物流", "设备", "C", "冻结", "青岛", 60, 30, "年产能 80 台"),
    ("SUP-0014", "苏州通汇检测服务有限公司", "通汇检测", "服务", "B", "已准入", "苏州", 30, 5, "月检测 500 批次"),
]

MATERIALS = [
    # code, name, spec, unit, category, std price, lead, safety, max, moq, daily
    ("MT-1001", "主控芯片", "STM32F407VGT6", "片", "电子件", 42.50, 30, 1200, 6000, 500, 45),
    ("MT-1002", "电源管理芯片", "TPS5430DDA", "片", "电子件", 12.80, 25, 2000, 9000, 1000, 78),
    ("MT-1003", "贴片电阻", "0603 10K 1%", "只", "电子件", 0.02, 7, 80000, 400000, 20000, 5200),
    ("MT-1004", "贴片电容", "0805 100nF 50V", "只", "电子件", 0.03, 7, 60000, 320000, 20000, 4300),
    ("MT-1005", "连接器", "JST PH2.0-4P", "只", "电子件", 0.85, 12, 15000, 60000, 5000, 860),
    ("MT-1006", "线束组件", "400mm 4P 双头", "条", "电子件", 6.20, 10, 3000, 12000, 1000, 210),
    ("MT-2001", "铝合金外壳", "ADC12 压铸 120×80×35", "件", "结构件", 26.00, 20, 800, 4000, 200, 48),
    ("MT-2002", "注塑上盖", "ABS 阻燃 V0 黑色", "件", "结构件", 8.40, 18, 1500, 7000, 500, 96),
    ("MT-2003", "钣金支架", "SPCC 1.5mm 折弯", "件", "结构件", 11.60, 15, 900, 4500, 300, 55),
    ("MT-2004", "硅胶密封圈", "φ60 邵氏 60A", "只", "结构件", 1.20, 12, 6000, 25000, 2000, 340),
    ("MT-3001", "瓦楞纸箱", "5 层 400×300×250", "只", "包材", 3.80, 5, 4000, 20000, 1000, 260),
    ("MT-3002", "珍珠棉内衬", "EPE 380×280×60", "只", "包材", 1.10, 5, 5000, 26000, 2000, 300),
    ("MT-3003", "说明书", "A5 双面四色", "份", "包材", 0.28, 5, 12000, 60000, 5000, 640),
    ("MT-3004", "防静电袋", "200×300mm", "只", "包材", 0.35, 5, 9000, 45000, 5000, 520),
    ("MT-4001", "三相异步电机", "YE3-90S-4 1.1kW", "台", "设备件", 860.00, 35, 20, 120, 5, 1.2),
    ("MT-4002", "伺服驱动器", "SV660N 750W", "台", "设备件", 1650.00, 35, 12, 80, 3, 0.8),
    ("MT-5001", "工业润滑脂", "2# 锂基 15kg", "桶", "辅料", 320.00, 9, 40, 200, 10, 2.1),
    ("MT-5002", "清洗剂", "环保水基 20L", "桶", "辅料", 185.00, 9, 30, 160, 10, 1.6),
    ("MT-5003", "无尘布", "9×9 寸 100 片/包", "包", "辅料", 26.00, 7, 200, 900, 50, 9.5),
    ("MT-6001", "标准螺钉", "M3×8 十字盘头", "只", "五金", 0.05, 6, 120000, 600000, 50000, 7200),
    ("MT-6002", "自攻螺钉", "M4×12 平尾", "只", "五金", 0.07, 6, 90000, 450000, 50000, 5400),
    ("MT-6003", "弹簧垫圈", "M3 304 不锈钢", "只", "五金", 0.02, 6, 150000, 700000, 50000, 8600),
    ("MT-6004", "铜柱", "M3×10 六角", "只", "五金", 0.18, 8, 40000, 180000, 20000, 2600),
    ("MT-7001", "标签纸", "60×40mm 铜版", "卷", "耗材", 12.50, 6, 600, 2600, 200, 32),
]


def load(cn):
    # ---------------- 账号与组织
    for u, pwd, name, role, dept, phone, mail in USERS:
        cn.execute("INSERT INTO users(username,password,display_name,role,dept_code,phone,email,status,"
                   "created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (u, db.sha256(pwd), name, role, dept, phone, mail, "在职", t(-380, 9)))
    for code, name, dept, leader, remark in TEAMS:
        cn.execute("INSERT INTO teams(code,name,dept,leader,remark) VALUES(?,?,?,?,?)",
                   (code, name, dept, leader, remark))
    for code, name, cat, val, unit, en, remark in RULES:
        cn.execute("INSERT INTO rules(code,name,category,value,unit,enabled,remark) VALUES(?,?,?,?,?,?,?)",
                   (code, name, cat, val, unit, en, remark))
    for period, dept, amount, used, remark in BUDGETS:
        cn.execute("INSERT INTO budgets(period,dept,amount,used,remark) VALUES(?,?,?,?,?)",
                   (period, dept, amount, used, remark))
    for code, name, loc, keeper, status, remark in WAREHOUSES:
        cn.execute("INSERT INTO warehouses(code,name,location,keeper,status,remark) VALUES(?,?,?,?,?,?)",
                   (code, name, loc, keeper, status, remark))

    # ---------------- 物料
    for (code, name, spec, unit, cat, price, lead, safety, mx, moq, daily) in MATERIALS:
        cn.execute("INSERT INTO materials(code,name,spec,unit,category,abc,standard_price,last_price,"
                   "lead_days,safety_stock,max_stock,min_order_qty,avg_daily_usage,main_supplier,status,"
                   "remark,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (code, name, spec, unit, cat, "C", price, scm.r2(price * 0.97), lead, safety, mx, moq,
                    daily, "", "启用", "", t(-360, 9), t(-5, 15)))
        for k in range(RND.randint(2, 4)):
            sup = RND.choice([s for s in SUPPLIERS if s[3] == cat] or SUPPLIERS)
            cn.execute("INSERT INTO material_prices(material_code,supplier_code,price,effective_at,source,"
                       "remark) VALUES(?,?,?,?,?,?)",
                       (code, sup[0], scm.r2(price * (0.92 + RND.random() * 0.16)),
                        d(-90 + k * 25), "询价", ""))
    # 主供关系（按类别第一家有准入资格的供应商）
    for m in MATERIALS:
        sup = [s for s in SUPPLIERS if s[3] == m[4] and s[5] == "已准入"]
        if sup:
            cn.execute("UPDATE materials SET main_supplier=? WHERE code=?", (sup[0][0], m[0]))

    # ---------------- 供应商
    for (code, name, short, cat, level, status, region, terms, lead, cap) in SUPPLIERS:
        cn.execute("INSERT INTO suppliers(code,name,short_name,category,level,status,score,health,tax_no,"
                   "contact,phone,email,address,region,payment_terms,lead_days,capacity,currency,remark,"
                   "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (code, name, short, cat, level, status, 0, "正常",
                    "91320500MA%08d" % RND.randint(1, 99999999),
                    RND.choice(["张", "李", "王", "刘", "陈", "杨"]) + RND.choice(["经理", "主管", "总"]),
                    "138%08d" % RND.randint(1, 99999999), "sales@%s.com" % code.lower(),
                    "%s市工业园 %d 号" % (region, RND.randint(1, 200)),
                    region, terms, lead, cap, "CNY", "", t(-300 + RND.randint(0, 60), 9), t(-3, 16)))
        # 资质：营业执照 + ISO9001 + 行业资质
        quals = [("营业执照", "91320500MA%08d" % RND.randint(1, 99999999), -900, 1),
                 ("ISO9001 质量体系", "ISO-%05d" % RND.randint(1, 99999), -700, 1),
                 ("供应商质量协议", "QA-%04d" % RND.randint(1, 9999), -400, 1)]
        for i, (qname, qno, off, _) in enumerate(quals):
            expire_off = {0: 400, 1: 25, 2: 260}[i] if code == "SUP-0011" else {0: 500, 1: 320, 2: 420}[i]
            if code == "SUP-0013" and i == 1:
                expire_off = -12                     # 过期资质 → 供应商被冻结
            if code == "SUP-0012" and i == 2:
                expire_off = 8                      # 临期
            cn.execute("INSERT INTO supplier_quals(supplier_code,name,no,issued_at,expire_at,remark)"
                       " VALUES(?,?,?,?,?,?)",
                       (code, qname, qno, d(off), d(expire_off), ""))

    # ---------------- 请购 + 询价 + 订单 + 收货 + 发票
    depts = ["计划部", "生产部", "研发部", "仓储部"]
    buyers = ["liyan", "zhouhao"]
    req_no_seq = 0
    po_no_seq = 0
    iv_no_seq = 0
    rc_no_seq = 0
    rfq_no_seq = 0
    po_specs = []

    # 18 张请购：状态分布
    req_states = (["已转单"] * 14 + ["已审批"] * 4 + ["待审批"] * 4 + ["草稿"] * 2
                  + ["已驳回"] * 1 + ["已取消"] * 1)
    RND.shuffle(req_states)                      # 打散状态，订单自然分布在近 5 个月
    for i, st in enumerate(req_states):
        req_no_seq += 1
        no = scm.doc_no("PR", d(-150 + i * 5), req_no_seq)
        mats = RND.sample(MATERIALS, RND.randint(1, 4))
        items = []
        for m in mats:
            daily, moq = float(m[10]), float(m[9])
            qty = round(daily * RND.uniform(8, 22) / moq) * moq or moq
            items.append((m, qty, scm.r2(m[5] * (0.96 + RND.random() * 0.1))))
        amount = scm.sum_amount([{"qty": q, "price": p} for _, q, p in items])
        day = -150 + i * 5
        cn.execute("INSERT INTO requisitions(no,dept,applicant,purpose,need_date,amount,status,approver,"
                   "approved_at,reject_reason,converted_no,remark,created_at,updated_at)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (no, RND.choice(depts), "wangjing", RND.choice(
                       ["Q4 量产备料", "样机试制", "安全库存补货", "产线线边补料", "客户加单"]),
                    d(day + 14), amount, st,
                    "zhaokun" if st in ("已审批", "已转单") else "",
                    t(day + 1, 11) if st in ("已审批", "已转单") else "",
                    "预算不足，改为分批发起" if st == "已驳回" else "",
                    "", "", t(day, 9), t(day + 1, 11)))
        for m, qty, price in items:
            cn.execute("INSERT INTO req_items(req_no,material_code,material_name,spec,unit,qty,est_price,"
                       "amount,remark) VALUES(?,?,?,?,?,?,?,?,?)",
                       (no, m[0], m[1], m[2], m[3], qty, price, scm.r2(qty * price), ""))

        if st != "已转单":
            continue

        # 已转单的请购 → 部分走询价（3 张），其余直接下单
        sup = [s for s in SUPPLIERS if s[5] == "已准入" and s[3] == items[0][0][4]]
        supplier = sup[0] if sup else [s for s in SUPPLIERS if s[5] == "已准入"][0]
        rfq_no = ""
        if i % 6 == 0:
            rfq_no_seq += 1
            rfq_no = scm.doc_no("RFQ", d(day + 2), rfq_no_seq)
            cand = [s for s in SUPPLIERS if s[5] == "已准入" and s[3] == items[0][0][4]][:3]
            if len(cand) < 2:
                cand = [s for s in SUPPLIERS if s[5] == "已准入"][:3]
            awarded = cand[0]
            cn.execute("INSERT INTO rfqs(no,req_no,title,status,deadline,owner,awarded_supplier,"
                       "awarded_amount,remark,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (rfq_no, no, "%s 询价比价" % items[0][0][1], "已定标", d(day + 6),
                        RND.choice(buyers), awarded[0], scm.r2(amount * 0.97), "",
                        t(day + 2, 10), t(day + 6, 15)))
            for m, qty, _ in items:
                cn.execute("INSERT INTO rfq_items(rfq_no,material_code,material_name,qty,unit)"
                           " VALUES(?,?,?,?,?)", (rfq_no, m[0], m[1], qty, m[3]))
            for k, s in enumerate(cand):
                q_amt = scm.r2(amount * (0.97 + k * 0.035))
                cn.execute("INSERT INTO rfq_quotes(rfq_no,supplier_code,supplier_name,amount,lead_days,"
                           "valid_days,awarded,remark,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                           (rfq_no, s[0], s[1], q_amt, s[8], 30, 1 if s[0] == awarded[0] else 0,
                            "含税到厂价", t(day + 4 + k, 14)))
            supplier = awarded

        # 生成采购订单
        po_no_seq += 1
        po_no = scm.doc_no("PO", d(day + 3), po_no_seq)
        po_amount = scm.r2(amount * (0.95 + RND.random() * 0.08))
        stage = ["已结算", "全部到货", "已下单", "部分到货", "已下单", "已结算", "全部到货", "已下单"][po_no_seq % 8]
        promise = day + 3 + supplier[8]
        ordered_qty = sum(q for _, q, _ in items)
        received_qty = 0
        received_amount = 0.0
        match_result = ""
        invoiced = 0.0
        if stage in ("部分到货", "全部到货", "已结算"):
            received_qty = ordered_qty if stage != "部分到货" else round(ordered_qty * 0.6, 2)
            received_amount = scm.r2(po_amount * received_qty / ordered_qty)
        if stage == "已结算":
            invoiced = scm.r2(received_amount * 0.995)
            match_result = "通过"
        cn.execute("INSERT INTO purchase_orders(no,supplier_code,supplier_name,req_no,rfq_no,title,amount,"
                   "currency,status,promise_date,owner,approver,approved_at,ordered_at,ordered_qty,"
                   "received_qty,received_amount,invoiced_amount,match_result,closed_at,cancel_reason,"
                   "remark,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (po_no, supplier[0], supplier[1], no, rfq_no,
                    "%s 采购" % items[0][0][1], po_amount, "CNY", stage, d(promise),
                    RND.choice(buyers), "zhaokun" if po_amount > 50000 else RND.choice(buyers),
                    t(day + 3, 14), t(day + 3, 16), ordered_qty, received_qty, received_amount,
                    invoiced, match_result,
                    t(day + 20, 10) if stage == "已结算" else "",
                    "", "", t(day + 3, 13), t(day + 6, 10)))
        for m, qty, price in items:
            cn.execute("INSERT INTO po_items(po_no,material_code,material_name,spec,unit,qty,price,amount,"
                       "received_qty,promise_date,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (po_no, m[0], m[1], m[2], m[3], qty, price, scm.r2(qty * price),
                        received_qty * qty / ordered_qty if ordered_qty else 0, d(promise), ""))
        po_specs.append((po_no, supplier, items, po_amount, stage, promise, received_amount,
                         received_qty, ordered_qty, day))

        # 收货单
        if stage in ("部分到货", "全部到货", "已结算"):
            rc_no_seq += 1
            rc_no = scm.doc_no("GR", d(promise), rc_no_seq)
            ng = 0 if RND.random() > 0.25 else round(received_qty * 0.01, 2)
            ok = round(received_qty - ng, 2)
            late = 0 if RND.random() < 0.75 else RND.choice([1, 2, 3, 5])
            cn.execute("INSERT INTO receipts(no,po_no,supplier_code,supplier_name,warehouse,status,"
                       "inspected_by,inspect_result,received_at,posted_at,remark,created_at,updated_at)"
                       " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (rc_no, po_no, supplier[0], supplier[1], "WH-SZ",
                        "已入库" if stage != "部分到货" else "已入库",
                        "chenqi", scm.inspect_conclusion(ok, ng), d(promise + late),
                        t(promise + late, 16), "", t(promise + late, 10), t(promise + late, 16)))
            for m, qty, price in items:
                share = qty / ordered_qty if ordered_qty else 0
                it_qty = round(received_qty * share, 2)
                it_ng = round(it_qty * (ng / received_qty if received_qty else 0), 2)
                cn.execute("INSERT INTO receipt_items(receipt_no,material_code,material_name,unit,qty,ok_qty,"
                           "ng_qty,price,amount,batch,expire_at,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (rc_no, m[0], m[1], m[3], it_qty, round(it_qty - it_ng, 2), it_ng, price,
                            scm.r2(it_qty * price), "B%s%s" % (d(promise)[2:4].replace("-", ""),
                                                               "%03d" % RND.randint(1, 999)),
                            d(promise + RND.choice([540, 720, 365, 1080])) if m[4] in ("辅料", "包材") else "",
                            ""))
            # 入库
            for m, qty, price in items:
                share = qty / ordered_qty if ordered_qty else 0
                it_qty = round(received_qty * share, 2)
                if it_qty <= 0:
                    continue
                cn.execute("INSERT INTO stock(material_code,material_name,spec,unit,warehouse,batch,qty,"
                           "locked,unit_cost,in_date,expire_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (m[0], m[1], m[2], m[3], "WH-SZ", "B%s%03d" % (d(promise)[5:7], po_no_seq),
                            it_qty, 0, price, d(promise + late), "", t(promise + late, 17)))
                cn.execute("INSERT INTO stock_moves(no,type,material_code,material_name,warehouse,batch,qty,"
                           "cost,ref_no,reason,operator,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (scm.doc_no("MV", d(promise), rc_no_seq * 10 + 1), "采购入库", m[0], m[1],
                            "WH-SZ", "", it_qty, scm.r2(it_qty * price), rc_no, "收货入库", "sunlei",
                            t(promise, 17)))

        # 发票
        if stage == "已结算":
            iv_no_seq += 1
            iv_no = scm.doc_no("IV", d(day + 22), iv_no_seq)
            diff = scm.r2(received_amount * (0.01 if iv_no_seq % 2 else 0.035))
            inv_amount = scm.r2(received_amount + diff)
            m3 = scm.match3(po_amount, received_amount, inv_amount)
            paid = inv_amount if iv_no_seq % 3 else 0.0
            cn.execute("INSERT INTO invoices(no,po_no,supplier_code,supplier_name,invoice_no,amount,tax_rate,"
                       "invoice_date,due_date,status,match_result,diff_amount,diff_rate,paid_amount,paid_at,"
                       "remark,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (iv_no, po_no, supplier[0], supplier[1], "FP%08d" % RND.randint(1, 99999999),
                        inv_amount, 0.13, d(day + 22), scm.payment_due(d(day + 22), supplier[7]),
                        "已付款" if paid else ("待付款" if m3["result"] == "通过" else "差异挂起"),
                        m3["result"], m3["diff"], m3["rate"], paid,
                        t(day + 26, 15) if paid else "", "", t(day + 22, 11), t(day + 26, 15)))

    # 补几张在途（待审批）与草稿订单，方便演示状态机
    for k, stage in enumerate(["待审批", "草稿", "待审批"]):
        po_no_seq += 1
        sup = SUPPLIERS[(k + 2) % len(SUPPLIERS)]
        mats = RND.sample(MATERIALS, 2)
        items = [(m, max(float(m[9]), round(float(m[9]) * RND.uniform(1, 3))), m[5]) for m in mats]
        amount = scm.sum_amount([{"qty": q, "price": p} for _, q, p in items])
        no = scm.doc_no("PO", d(-6 + k), po_no_seq)
        cn.execute("INSERT INTO purchase_orders(no,supplier_code,supplier_name,req_no,rfq_no,title,amount,"
                   "currency,status,promise_date,owner,approver,approved_at,ordered_at,ordered_qty,"
                   "received_qty,received_amount,invoiced_amount,match_result,closed_at,cancel_reason,"
                   "remark,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (no, sup[0], sup[1], "", "", "%s 采购" % mats[0][1], amount, "CNY", stage,
                    d(30), "liyan", "", "", "", sum(q for _, q, _ in items), 0, 0, 0, "", "", "", "",
                    t(-6 + k, 9), t(-6 + k, 9)))
        for m, qty, price in items:
            cn.execute("INSERT INTO po_items(po_no,material_code,material_name,spec,unit,qty,price,amount,"
                       "received_qty,promise_date,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (no, m[0], m[1], m[2], m[3], qty, price, scm.r2(qty * price), 0, d(30), ""))

    # ---------------- 库存补足：制造缺货、低库存、超储与近效期样本
    # 目标库存 = 安全库存 × 系数；系数 <1 即低于安全库存，0 即缺货
    ratios = {"MT-1001": 0.0, "MT-4002": 0.35, "MT-1006": 0.62, "MT-3001": 1.65, "MT-5002": 0.8}
    for idx, m in enumerate(MATERIALS):
        code, name, spec, unit, cat = m[0], m[1], m[2], m[3], m[4]
        exist = float(db.one(cn, "SELECT COALESCE(SUM(qty),0) q FROM stock WHERE material_code=?",
                             (code,))["q"])
        ratio = ratios.get(code, 0.85 + (idx % 5) * 0.22)
        target = round(float(m[7]) * ratio, 2)
        gap = round(target - exist, 2)
        if gap <= 0:
            continue
        wh = "WH-KS" if idx % 3 == 0 else ("WH-WX" if idx % 3 == 1 else "WH-SZ")
        expire = ""
        if cat in ("辅料", "包材"):
            expire = d(RND.choice([45, 80, 400, 600]))
        batch = "B%s%03d" % (d(-RND.randint(3, 26))[5:7], idx)
        cn.execute("INSERT INTO stock(material_code,material_name,spec,unit,warehouse,batch,qty,locked,"
                   "unit_cost,in_date,expire_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (code, name, spec, unit, wh, batch, gap, round(gap * 0.05, 2),
                    scm.r2(m[5] * 0.97), d(-RND.randint(3, 40)), expire, t(-1, 18)))
        cn.execute("INSERT INTO stock_moves(no,type,material_code,material_name,warehouse,batch,qty,cost,"
                   "ref_no,reason,operator,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (scm.doc_no("MV", d(-3), 500 + idx), "采购入库", code, name, wh, batch, gap,
                    scm.r2(gap * m[5] * 0.97), "", "期初/补货入库", "sunlei", t(-3, 17)))

    # 保证每个物料至少有一条库存记录（缺货物料 qty=0，便于列表展示缺货行）
    for m in MATERIALS:
        if not db.one(cn, "SELECT id FROM stock WHERE material_code=? LIMIT 1", (m[0],)):
            cn.execute("INSERT INTO stock(material_code,material_name,spec,unit,warehouse,batch,qty,locked,"
                       "unit_cost,in_date,expire_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (m[0], m[1], m[2], m[3], "WH-SZ", "B000", 0, 0, scm.r2(m[5] * 0.97),
                        d(-30), "", t(-1, 18)))

    # 领用出库流水（供周转率与消耗趋势）
    mv_seq = 900
    for idx, m in enumerate(MATERIALS):
        daily = float(m[10])
        for k in range(4):
            mv_seq += 1
            day = -80 + k * 20 + RND.randint(0, 8)
            qty = round(daily * 18 * RND.uniform(0.75, 1.25), 2)
            cn.execute("INSERT INTO stock_moves(no,type,material_code,material_name,warehouse,batch,qty,cost,"
                       "ref_no,reason,operator,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (scm.doc_no("MV", d(day), mv_seq), "领用出库", m[0], m[1],
                        "WH-KS" if idx % 3 == 0 else "WH-SZ", "", qty, scm.r2(qty * m[5] * 0.97),
                        "", "产线领用", "sunlei", t(day, 14)))

    # 待匹配 / 差异发票（演示结算工作台的三种状态）
    for k, po in enumerate(db.rows(cn, "SELECT * FROM purchase_orders WHERE status='全部到货' "
                                      "ORDER BY no LIMIT 3")):
        iv_no_seq += 1
        iv_no = scm.doc_no("IV", d(-2 + k), iv_no_seq)
        inv_amount = scm.r2(float(po["received_amount"]) * (1.0 if k == 0 else 1.045))
        m3 = scm.match3(po["amount"], po["received_amount"], inv_amount)
        cn.execute("INSERT INTO invoices(no,po_no,supplier_code,supplier_name,invoice_no,amount,tax_rate,"
                   "invoice_date,due_date,status,match_result,diff_amount,diff_rate,paid_amount,paid_at,"
                   "remark,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (iv_no, po["no"], po["supplier_code"], po["supplier_name"],
                    "FP%08d" % RND.randint(1, 99999999), inv_amount, 0.13, d(-2 + k),
                    scm.payment_due(d(-2 + k), 30),
                    "待匹配" if k == 0 else ("差异挂起" if m3["result"] != "通过" else "待付款"),
                    "" if k == 0 else m3["result"], m3["diff"], m3["rate"], 0, "",
                    "到票待核", t(-2 + k, 9), t(-2 + k, 9)))
        cn.execute("UPDATE purchase_orders SET invoiced_amount=?, match_result=? WHERE no=?",
                   (inv_amount, m3["result"], po["no"]))

    # ---------------- 询价中的比价单（演示报价登记与定标流程）
    open_req = db.one(cn, "SELECT * FROM requisitions WHERE status='已审批' AND (converted_no='' "
                          "OR converted_no IS NULL) ORDER BY no DESC LIMIT 1")
    if open_req:
        rfq_no_seq += 1
        rfq_no = scm.doc_no("RFQ", d(-4), rfq_no_seq)
        cand = [s for s in SUPPLIERS if s[5] == "已准入"][:3]
        cn.execute("INSERT INTO rfqs(no,req_no,title,status,deadline,owner,awarded_supplier,"
                   "awarded_amount,remark,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (rfq_no, open_req["no"], "%s 询价比价" % open_req["purpose"], "询价中", d(3),
                    "liyan", "", 0, "三家比价，重点看交付周期", t(-4, 10), t(-1, 16)))
        for it in db.rows(cn, "SELECT * FROM req_items WHERE req_no=?", (open_req["no"],)):
            cn.execute("INSERT INTO rfq_items(rfq_no,material_code,material_name,qty,unit)"
                       " VALUES(?,?,?,?,?)",
                       (rfq_no, it["material_code"], it["material_name"], it["qty"], it["unit"]))
        for k, s in enumerate(cand):
            q_amt = scm.r2(float(open_req["amount"]) * (0.98 + k * 0.03))
            cn.execute("INSERT INTO rfq_quotes(rfq_no,supplier_code,supplier_name,amount,lead_days,"
                       "valid_days,awarded,remark,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (rfq_no, s[0], s[1], q_amt, s[8], 30, 0,
                        "含税到厂价" if k == 0 else "含税 + 运费", t(-2 + k, 14)))

    # ---------------- 供应商绩效（近 4 个季度）
    for idx, s in enumerate(SUPPLIERS):
        code, name = s[0], s[1]
        base_delivery = {"A": 0.95, "B": 0.88, "C": 0.78, "D": 0.62}.get(s[4], 0.85)
        base_quality = {"A": 0.99, "B": 0.97, "C": 0.94, "D": 0.88}.get(s[4], 0.95)
        for q in range(4):
            dr = scm.r4(min(1.0, base_delivery + RND.uniform(-0.05, 0.05)))
            qr = scm.r4(min(1.0, base_quality + RND.uniform(-0.02, 0.02)))
            pi = scm.r4(1.0 + RND.uniform(-0.08, 0.08))
            rr = scm.r4(min(1.0, 0.9 + RND.uniform(-0.1, 0.1)))
            score = scm.supplier_score(dr, qr, pi, rr)
            cn.execute("INSERT INTO supplier_scores(supplier_code,period,delivery_rate,quality_rate,"
                       "price_index,response_rate,score,level,remark,created_at)"
                       " VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (code, "2026-Q%d" % (3 - q if q < 3 else 4), dr, qr, pi, rr, score,
                        scm.supplier_level(score), "", t(-90 * q - 10, 10)))
    # 最新得分回写供应商主档
    for s in SUPPLIERS:
        last = db.one(cn, "SELECT * FROM supplier_scores WHERE supplier_code=? ORDER BY id DESC LIMIT 1",
                      (s[0],))
        cn.execute("UPDATE suppliers SET score=?, level=?, health=? WHERE code=?",
                   (last["score"], scm.supplier_level(last["score"]),
                    "冻结" if s[5] == "冻结" else ("观察" if s[5] == "观察" else "正常"), s[0]))

    # ---------------- 调拨与盘点
    cn.execute("INSERT INTO transfers(no,from_wh,to_wh,status,applicant,approver,remark,created_at,"
               "updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
               (scm.doc_no("TR", d(-8), 1), "WH-SZ", "WH-KS", "已完成", "sunlei", "zhaokun",
                "线边补料", t(-8, 9), t(-7, 15)))
    for k, m in enumerate(MATERIALS[:3]):
        cn.execute("INSERT INTO transfer_items(transfer_no,material_code,material_name,unit,batch,qty)"
                   " VALUES(?,?,?,?,?,?)",
                   (scm.doc_no("TR", d(-8), 1), m[0], m[1], m[3], "", round(m[8] / 40)))
    cn.execute("INSERT INTO transfers(no,from_wh,to_wh,status,applicant,approver,remark,created_at,"
               "updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
               (scm.doc_no("TR", d(-2), 2), "WH-SZ", "WH-WX", "已审批", "sunlei", "zhaokun",
                "区域中转备货", t(-2, 9), t(-1, 10)))
    for m in MATERIALS[3:5]:
        cn.execute("INSERT INTO transfer_items(transfer_no,material_code,material_name,unit,batch,qty)"
                   " VALUES(?,?,?,?,?,?)",
                   (scm.doc_no("TR", d(-2), 2), m[0], m[1], m[3], "", round(m[8] / 50)))

    cn.execute("INSERT INTO stocktakes(no,warehouse,status,applicant,approver,diff_amount,remark,"
               "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
               (scm.doc_no("ST", d(-15), 1), "WH-SZ", "已完成", "sunlei", "zhaokun", 0,
                "月度循环盘点", t(-15, 9), t(-14, 17)))

    # ---------------- 集成演示数据
    demo_key = "fyk_demo_scm_2026_readonly"
    cn.execute("INSERT INTO api_keys(name,key_prefix,key_hash,scope,owner,status,expires_at,last_used_at,"
               "created_at) VALUES(?,?,?,?,?,?,?,?,?)",
               ("演示只读 Key（ERP 对接）", demo_key[:12], db.sha256(demo_key), "read", "admin", "启用",
                d(180), "", t(-20, 9)))
    cn.execute("INSERT INTO webhooks(name,url,events,secret,status,last_status,last_at,fail_count,"
               "created_at) VALUES(?,?,?,?,?,?,?,?,?)",
               ("WMS 出库回调（示例）", "https://example.com/hooks/scm",
                "receipt.posted,po.stage_changed", "demo-secret-2026", "停用", "", "", 0, t(-20, 10)))

    # ---------------- ABC 分类（按采购金额：A≤70% / B≤90% / C 其余）
    # 用「标准价 × 日均耗用 × 365」估年耗用金额，比历史订单金额更贴近 ABC 的管理口径
    agg = [{"code": m[0], "name": m[1], "amount": float(m[5]) * float(m[10]) * 365} for m in MATERIALS]
    for c in scm.abc_classify(agg):
        cn.execute("UPDATE materials SET abc=? WHERE code=?", (c["abc"], c["code"]))
    for m in db.rows(cn, "SELECT * FROM materials"):
        last = db.one(cn, "SELECT price FROM material_prices WHERE material_code=? "
                          "ORDER BY effective_at DESC, id DESC LIMIT 1", (m["code"],))
        if last:
            cn.execute("UPDATE materials SET last_price=? WHERE code=?", (last["price"], m["code"]))

    # ---------------- 变更流（供增量同步演示）
    for po in db.rows(cn, "SELECT * FROM purchase_orders ORDER BY no"):
        cn.execute("INSERT INTO change_log(obj_type,obj_no,op,actor,payload,changed_at) VALUES(?,?,?,?,?,?)",
                   ("po", po["no"], "upsert", po["owner"] or "system",
                    scm.dumps({"no": po["no"], "status": po["status"], "amount": po["amount"],
                               "supplier": po["supplier_name"]}), po["updated_at"] or t(-1, 10)))
    for sup in db.rows(cn, "SELECT * FROM suppliers ORDER BY code"):
        cn.execute("INSERT INTO change_log(obj_type,obj_no,op,actor,payload,changed_at) VALUES(?,?,?,?,?,?)",
                   ("supplier", sup["code"], "upsert", "system",
                    scm.dumps({"code": sup["code"], "name": sup["name"], "level": sup["level"]}),
                    sup["updated_at"] or t(-1, 10)))

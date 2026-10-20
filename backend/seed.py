# -*- coding: utf-8 -*-
"""飞鹰 CRM · 确定性演示数据（固定种子 20261020，重跑结果一致）

数据设计要点：
- 客户 36 家 / 线索 48 条 / 商机 52 个 / 跟进 160+ 条 / 报价 18 张 / 合同 14 份 / 工单 18 张；
- 商机覆盖「初步接触 → 需求确认 → 方案报价 → 商务谈判 → 赢单 / 输单」全阶段，
  且结单日期横跨未来 4 个月，保证销售预测、漏斗、业绩排行都有真实分母；
- 回款计划按合同分期生成，并刻意留出逾期 / 部分收款，账龄报表才有内容；
- 工单覆盖 P1/P2/P3 与超时 / 临期 / 已解决，SLA 看板可验证；
- 集成侧预置 1 个只读 API Key 与 1 个停用的 Webhook，便于演示对接。
"""
import random
from datetime import date, datetime, timedelta

import crm
import db

SEED = 20261020
TODAY = date(2026, 10, 20)


def d(offset):
    return (TODAY + timedelta(days=offset)).isoformat()


def ts(offset, hour=10, minute=0):
    return (datetime(TODAY.year, TODAY.month, TODAY.day, hour, minute) +
            timedelta(days=offset)).strftime("%Y-%m-%d %H:%M:%S")


USERS = [
    ("admin", "admin123", "系统管理员", "admin", "T-EAST", "13800000000", "admin@feiying.cn"),
    ("zhangwei", "fe@2026", "张伟（销售总监）", "sales_director", "T-EAST", "13800000001", "zhangwei@feiying.cn"),
    ("liuyang", "fe@2026", "刘洋（华东销售）", "sales", "T-EAST", "13800000002", "liuyang@feiying.cn"),
    ("wangfang", "fe@2026", "王芳（华南销售）", "sales", "T-SOUTH", "13800000003", "wangfang@feiying.cn"),
    ("sunqi", "fe@2026", "孙琦（线索专员）", "sdr", "T-EAST", "13800000004", "sunqi@feiying.cn"),
    ("chenlu", "fe@2026", "陈露（客服工程师）", "service", "T-SVC", "13800000005", "chenlu@feiying.cn"),
    ("zhaomin", "fe@2026", "赵敏（财务）", "finance", "T-EAST", "13800000006", "zhaomin@feiying.cn"),
    ("huangli", "fe@2026", "黄丽（市场）", "marketing", "T-MKT", "13800000007", "huangli@feiying.cn"),
]

TEAMS = [
    ("T-EAST", "华东销售一组", "华东", "zhangwei", "覆盖江浙沪皖，主攻制造业与新能源"),
    ("T-SOUTH", "华南销售组", "华南", "zhangwei", "覆盖粤闽，主攻电子与跨境电商"),
    ("T-SVC", "客户成功组", "全国", "chenlu", "售后工单、续费与满意度回访"),
    ("T-MKT", "市场组", "全国", "huangli", "线索获取、活动归因与内容运营"),
]

PRODUCTS = [
    ("P-CRM-STD", "飞鹰 CRM 标准版", "软件", "套", 68000, 12000, "在售", "20 用户以内，含客户/商机/报表"),
    ("P-CRM-PRO", "飞鹰 CRM 专业版", "软件", "套", 158000, 26000, "在售", "50 用户，含审批、集成、数据看板"),
    ("P-CRM-ENT", "飞鹰 CRM 企业版", "软件", "套", 328000, 52000, "在售", "不限用户，私有化部署"),
    ("P-IMP", "实施服务包", "服务", "人天", 2400, 1500, "在售", "含调研、配置、上线陪跑"),
    ("P-TRN", "管理员培训", "服务", "场", 6000, 2600, "在售", "2 天现场培训，20 人以内"),
    ("P-OPS", "年度运维服务", "服务", "年", 36000, 14000, "在售", "7×12 响应，含版本升级"),
    ("P-DEV", "定制开发", "服务", "人天", 3200, 2100, "在售", "接口对接、个性化报表"),
    ("P-BI", "经营分析 BI 包", "软件", "套", 48000, 9000, "在售", "12 张标准看板 + 自助分析"),
]

# (名称, 行业, 区域, 等级, 来源, 负责人, 授信, 规模, 创建天数前, 最后跟进天数前, 状态)
CUSTOMERS = [
    ("苏州精工机械有限公司", "装备制造", "华东", "A", "老客推荐", "liuyang", 800000, "大型", 420, 3, "活跃"),
    ("无锡新能源材料股份有限公司", "新能源", "华东", "A", "展会", "liuyang", 600000, "大型", 380, 8, "活跃"),
    ("杭州智联电子科技有限公司", "电子制造", "华东", "B", "官网表单", "liuyang", 300000, "中型", 300, 15, "活跃"),
    ("南京华泰汽车零部件有限公司", "汽车零部件", "华东", "A", "渠道合作", "liuyang", 700000, "大型", 260, 5, "活跃"),
    ("宁波海川精密模具有限公司", "模具", "华东", "B", "展会", "liuyang", 260000, "中型", 240, 21, "活跃"),
    ("合肥中科仪器有限公司", "仪器仪表", "华东", "C", "线上投放", "liuyang", 120000, "小型", 210, 46, "沉睡"),
    ("上海远景包装材料有限公司", "包装", "华东", "B", "老客推荐", "liuyang", 200000, "中型", 198, 12, "活跃"),
    ("常州新宇轴承有限公司", "通用零部件", "华东", "C", "官网表单", "liuyang", 90000, "小型", 180, 63, "沉睡"),
    ("深圳睿驰智能装备有限公司", "装备制造", "华南", "A", "展会", "wangfang", 900000, "大型", 350, 4, "活跃"),
    ("广州南方物流科技有限公司", "物流", "华南", "B", "内容营销", "wangfang", 320000, "中型", 320, 10, "活跃"),
    ("东莞恒达电子有限公司", "电子制造", "华南", "A", "老客推荐", "wangfang", 650000, "大型", 290, 6, "活跃"),
    ("佛山顺德家电配件有限公司", "家电", "华南", "B", "渠道合作", "wangfang", 240000, "中型", 250, 18, "活跃"),
    ("厦门海丝跨境电商有限公司", "跨境电商", "华南", "B", "线上投放", "wangfang", 180000, "中型", 220, 9, "活跃"),
    ("珠海云图软件有限公司", "软件", "华南", "C", "内容营销", "wangfang", 100000, "小型", 200, 52, "沉睡"),
    ("中山明阳照明科技有限公司", "照明", "华南", "C", "官网表单", "wangfang", 80000, "小型", 175, 71, "沉睡"),
    ("深圳前海智造供应链有限公司", "供应链", "华南", "A", "展会", "wangfang", 520000, "大型", 150, 2, "活跃"),
    ("北京中天能源集团有限公司", "能源", "华北", "A", "渠道合作", "zhangwei", 1200000, "大型", 500, 7, "活跃"),
    ("天津渤海重工有限公司", "装备制造", "华北", "B", "展会", "zhangwei", 400000, "大型", 460, 25, "活跃"),
    ("青岛蓝海水产加工有限公司", "食品加工", "华北", "C", "老客推荐", "zhangwei", 150000, "中型", 400, 38, "活跃"),
    ("济南泉城医药科技有限公司", "医药", "华北", "B", "内容营销", "zhangwei", 280000, "中型", 360, 14, "活跃"),
    ("武汉光谷激光设备有限公司", "激光设备", "华中", "A", "展会", "liuyang", 560000, "大型", 340, 11, "活跃"),
    ("长沙湘江重工有限公司", "装备制造", "华中", "B", "渠道合作", "liuyang", 300000, "大型", 300, 33, "活跃"),
    ("郑州中原冷链物流有限公司", "物流", "华中", "C", "线上投放", "liuyang", 110000, "中型", 260, 58, "沉睡"),
    ("成都天府软件服务有限公司", "软件", "西南", "B", "内容营销", "wangfang", 220000, "中型", 280, 16, "活跃"),
    ("重庆两江汽车电子有限公司", "汽车零部件", "西南", "A", "老客推荐", "wangfang", 480000, "大型", 240, 6, "活跃"),
    ("西安航天精密机电有限公司", "航空航天", "西北", "A", "展会", "zhangwei", 750000, "大型", 300, 19, "活跃"),
    ("沈阳北方重装机械有限公司", "装备制造", "东北", "B", "渠道合作", "zhangwei", 260000, "大型", 320, 44, "沉睡"),
    ("大连港湾船舶配套有限公司", "船舶", "东北", "C", "官网表单", "zhangwei", 95000, "中型", 280, 67, "沉睡"),
    ("苏州工业园区智造云科技有限公司", "工业互联网", "华东", "A", "老客推荐", "liuyang", 680000, "中型", 130, 1, "活跃"),
    ("上海浦东医疗器械有限公司", "医疗器械", "华东", "B", "展会", "liuyang", 210000, "中型", 120, 13, "活跃"),
    ("杭州钱塘新材料有限公司", "新材料", "华东", "B", "线上投放", "liuyang", 190000, "中型", 110, 27, "活跃"),
    ("南京江北新区半导体有限公司", "半导体", "华东", "A", "渠道合作", "zhangwei", 880000, "大型", 100, 3, "活跃"),
    ("深圳宝安机器人有限公司", "机器人", "华南", "B", "展会", "wangfang", 340000, "中型", 95, 20, "活跃"),
    ("广州黄埔生物科技有限公司", "生物科技", "华南", "C", "内容营销", "wangfang", 130000, "中型", 88, 42, "活跃"),
    ("天津滨海新能源装备有限公司", "新能源", "华北", "B", "老客推荐", "zhangwei", 360000, "大型", 76, 8, "活跃"),
    ("苏州吴江纺织机械有限公司", "纺织机械", "华东", "C", "官网表单", "liuyang", 70000, "小型", 64, 55, "流失"),
]

CONTACT_NAMES = ["王建国", "李慧敏", "张海涛", "刘颖", "陈志强", "杨柳", "赵鹏", "孙晓东",
                 "周敏", "吴刚", "郑丽华", "冯磊", "徐静", "马超", "朱琳", "胡斌", "林菁", "郭睿"]
TITLES = ["信息总监", "采购总监", "总经理", "运营经理", "IT 经理", "财务总监", "生产总监"]

# (公司名, 联系人, 手机, 来源, 行业, 区域, 预算, 状态, 负责人, 创建天数前, 活动代码)
LEADS = [
    ("苏州光华精密制造有限公司", "顾明", "13912345601", "官网表单", "装备制造", "华东", 380000, "跟进中", "liuyang", 12, "CP-2026-AUTO"),
    ("无锡太湖传感技术有限公司", "许静", "13912345602", "展会", "传感器", "华东", 260000, "跟进中", "liuyang", 18, "CP-2026-EXPO"),
    ("杭州云栖数据服务有限公司", "tracy", "13912345603", "线上投放", "软件", "华东", 150000, "跟进中", "liuyang", 9, "CP-2026-SEM"),
    ("南京紫金智能装备有限公司", "倪伟", "13912345604", "老客推荐", "装备制造", "华东", 620000, "跟进中", "liuyang", 26, "CP-2026-REF"),
    ("宁波甬江紧固件有限公司", "章丽", "13912345605", "官网表单", "通用零部件", "华东", 90000, "待分配", "", 3, ""),
    ("合肥工业大学科技园有限公司", "戴军", "13912345606", "内容营销", "园区", "华东", 180000, "跟进中", "sunqi", 21, "CP-2026-CONTENT"),
    ("上海松江智慧工厂有限公司", "沈洁", "13912345607", "展会", "智能制造", "华东", 450000, "跟进中", "liuyang", 33, "CP-2026-EXPO"),
    ("常州天宁电机有限公司", "蒋涛", "13912345608", "官网表单", "电机", "华东", 120000, "待分配", "", 2, ""),
    ("温州瓯海眼镜制造有限公司", "洪波", "13912345609", "线上投放", "轻工", "华东", 60000, "无效", "", 40, "CP-2026-SEM"),
    ("绍兴柯桥纺织科技有限公司", "楼颖", "13912345610", "渠道合作", "纺织", "华东", 220000, "已转客户", "liuyang", 60, ""),
    ("深圳龙华精密电子有限公司", "曾强", "13912345611", "展会", "电子制造", "华南", 520000, "跟进中", "wangfang", 15, "CP-2026-EXPO"),
    ("东莞长安模具科技有限公司", "叶敏", "13912345612", "老客推荐", "模具", "华南", 280000, "跟进中", "wangfang", 22, "CP-2026-REF"),
    ("广州天河软件园有限公司", "何静怡", "13912345613", "内容营销", "软件", "华南", 160000, "跟进中", "wangfang", 30, "CP-2026-CONTENT"),
    ("佛山南海家电制造有限公司", "梁伟", "13912345614", "官网表单", "家电", "华南", 340000, "跟进中", "wangfang", 11, ""),
    ("珠海横琴跨境电商有限公司", "苏菲", "13912345615", "线上投放", "跨境电商", "华南", 200000, "跟进中", "wangfang", 7, "CP-2026-SEM"),
    ("中山古镇灯饰有限公司", "罗斌", "13912345616", "展会", "照明", "华南", 85000, "待分配", "", 4, ""),
    ("厦门集美供应链有限公司", "陈嘉", "13912345617", "渠道合作", "供应链", "华南", 260000, "跟进中", "wangfang", 36, ""),
    ("海口南海旅游集团有限公司", "符明", "13912345618", "官网表单", "旅游", "华南", 70000, "公海", "", 75, ""),
    ("深圳南山人工智能有限公司", "雷蕾", "13912345619", "内容营销", "人工智能", "华南", 480000, "跟进中", "wangfang", 5, "CP-2026-CONTENT"),
    ("南宁东盟商贸有限公司", "韦强", "13912345620", "线上投放", "商贸", "华南", 50000, "无效", "", 48, "CP-2026-SEM"),
    ("北京亦庄智能制造有限公司", "田甜", "13912345621", "展会", "智能制造", "华北", 720000, "跟进中", "zhangwei", 19, "CP-2026-EXPO"),
    ("天津滨海新区物流有限公司", "郝强", "13912345622", "老客推荐", "物流", "华北", 300000, "跟进中", "zhangwei", 27, "CP-2026-REF"),
    ("青岛崂山食品机械有限公司", "曲丽", "13912345623", "官网表单", "食品机械", "华北", 130000, "待分配", "", 6, ""),
    ("济南高新生物医药有限公司", "曹阳", "13912345624", "内容营销", "医药", "华北", 250000, "跟进中", "zhangwei", 41, "CP-2026-CONTENT"),
    ("石家庄华北制药设备有限公司", "范伟", "13912345625", "渠道合作", "医药", "华北", 190000, "公海", "", 92, ""),
    ("武汉东湖新技术有限公司", "熊涛", "13912345626", "展会", "光电子", "华中", 560000, "跟进中", "liuyang", 24, "CP-2026-EXPO"),
    ("长沙岳麓智能装备有限公司", "彭静", "13912345627", "老客推荐", "装备制造", "华中", 330000, "跟进中", "liuyang", 38, "CP-2026-REF"),
    ("郑州航空港物流有限公司", "宋强", "13912345628", "线上投放", "物流", "华中", 80000, "无效", "", 55, "CP-2026-SEM"),
    ("南昌赣江新材料有限公司", "万丽", "13912345629", "官网表单", "新材料", "华中", 140000, "待分配", "", 1, ""),
    ("成都高新软件有限公司", "任杰", "13912345630", "内容营销", "软件", "西南", 240000, "跟进中", "wangfang", 16, "CP-2026-CONTENT"),
    ("重庆两江智能装备有限公司", "邹敏", "13912345631", "展会", "装备制造", "西南", 410000, "跟进中", "wangfang", 29, "CP-2026-EXPO"),
    ("昆明云岭农业科技有限公司", "段丽", "13912345632", "线上投放", "农业", "西南", 60000, "公海", "", 68, ""),
    ("贵阳大数据交易有限公司", "龚涛", "13912345633", "渠道合作", "大数据", "西南", 300000, "跟进中", "wangfang", 43, ""),
    ("西安高新电子有限公司", "白静", "13912345634", "展会", "电子", "西北", 380000, "跟进中", "zhangwei", 20, "CP-2026-EXPO"),
    ("兰州西北化工有限公司", "马强", "13912345635", "官网表单", "化工", "西北", 110000, "公海", "", 85, ""),
    ("沈阳铁西装备制造有限公司", "于丽", "13912345636", "渠道合作", "装备制造", "东北", 270000, "跟进中", "zhangwei", 47, ""),
    ("大连金普新区船舶有限公司", "林涛", "13912345637", "老客推荐", "船舶", "东北", 350000, "跟进中", "zhangwei", 52, "CP-2026-REF"),
    ("哈尔滨工业大学科技园有限公司", "尹杰", "13912345638", "内容营销", "园区", "东北", 160000, "公海", "", 96, ""),
    ("苏州相城智能家居有限公司", "陆敏", "13912345639", "线上投放", "智能家居", "华东", 175000, "待分配", "", 2, "CP-2026-SEM"),
    ("上海嘉定汽车服务有限公司", "汪洋", "13912345640", "官网表单", "汽车服务", "华东", 95000, "跟进中", "liuyang", 14, ""),
    ("杭州滨江电商服务有限公司", "金晶", "13912345641", "内容营销", "电商", "华东", 130000, "跟进中", "liuyang", 31, "CP-2026-CONTENT"),
    ("南京江宁智能制造有限公司", "程浩", "13912345642", "展会", "智能制造", "华东", 500000, "跟进中", "liuyang", 17, "CP-2026-EXPO"),
    ("深圳福田金融科技有限公司", "庄敏", "13912345643", "老客推荐", "金融科技", "华南", 640000, "跟进中", "wangfang", 23, "CP-2026-REF"),
    ("广州越秀医疗健康有限公司", "简伟", "13912345644", "渠道合作", "医疗健康", "华南", 210000, "待分配", "", 5, ""),
    ("北京朝阳文化传媒有限公司", "常丽", "13912345645", "线上投放", "文化传媒", "华北", 45000, "无效", "", 60, ""),
    ("天津河西供应链管理有限公司", "贺强", "13912345646", "官网表单", "供应链", "华北", 230000, "待分配", "", 3, ""),
    ("武汉光谷生物城有限公司", "谭静", "13912345647", "展会", "生物", "华中", 420000, "跟进中", "liuyang", 34, "CP-2026-EXPO"),
    ("成都天府新区数字科技有限公司", "温涛", "13912345648", "内容营销", "数字科技", "西南", 190000, "待分配", "", 4, "CP-2026-CONTENT"),
]

CAMPAIGNS = [
    ("CP-2026-EXPO", "2026 中国国际工业博览会", "展会", "线下展位", -60, -40, 320000, 286000, 120, "huangli", "已结束", "9 ㎡ 展位 + 现场演示"),
    ("CP-2026-SEM", "百度/搜狗 搜索投放", "线上投放", "SEM", -90, -1, 180000, 152000, 300, "huangli", "进行中", "按「CRM 系统」等 42 个词投放"),
    ("CP-2026-CONTENT", "制造业数字化白皮书", "内容营销", "内容+直播", -120, -1, 90000, 68000, 200, "huangli", "进行中", "白皮书下载 + 3 场直播"),
    ("CP-2026-REF", "老客户转介绍计划", "老客推荐", "客户成功", -180, -1, 40000, 32000, 80, "chenlu", "进行中", "成交返 5% 服务券"),
    ("CP-2026-CHANNEL", "区域代理商招募", "渠道合作", "渠道", -150, -1, 120000, 96000, 60, "zhangwei", "进行中", "长三角 + 珠三角 12 家代理"),
]

# (商机名, 客户索引, 金额, 阶段, 预计结单天数, 负责人, 竞品, 决策人)
OPPS = [
    ("CRM 专业版 + 实施", 0, 386000, "商务谈判", 12, "liuyang", "销售易", "王建国 信息总监"),
    ("全集团 CRM 升级", 1, 720000, "方案报价", 35, "liuyang", "纷享销客", "李慧敏 采购总监"),
    ("电子事业部 CRM", 2, 268000, "需求确认", 58, "liuyang", "自研", "张海涛 IT 经理"),
    ("售后服务体系数字化", 3, 458000, "商务谈判", 8, "liuyang", "Zoho", "刘颖 运营经理"),
    ("模具订单协同", 4, 196000, "方案报价", 42, "liuyang", "本地集成商", "陈志强 总经理"),
    ("实验室客户管理", 5, 88000, "初步接触", 88, "liuyang", "", "杨柳 主任"),
    ("包装客户全生命周期", 6, 152000, "需求确认", 66, "liuyang", "销售易", "赵鹏 销售总监"),
    ("轴承经销商管理", 7, 76000, "输单", -20, "liuyang", "Excel", "孙晓东 经理"),
    ("智能装备全球营销", 8, 880000, "商务谈判", 15, "wangfang", "Salesforce", "周敏 CIO"),
    ("物流客户 360", 9, 320000, "方案报价", 30, "wangfang", "销售易", "吴刚 运营总监"),
    ("电子代工客户协同", 10, 640000, "商务谈判", 6, "wangfang", "纷享销客", "郑丽华 采购总监"),
    ("家电配件渠道管理", 11, 216000, "需求确认", 52, "wangfang", "自研", "冯磊 渠道经理"),
    ("跨境电商客户运营", 12, 178000, "方案报价", 38, "wangfang", "Zoho", "徐静 电商负责人"),
    ("软件公司销售自动化", 13, 64000, "输单", -35, "wangfang", "HubSpot", "马超 CEO"),
    ("照明工程项目管理", 14, 92000, "输单", -48, "wangfang", "本地集成商", "朱琳 项目经理"),
    ("供应链客户中台", 15, 520000, "方案报价", 26, "wangfang", "销售易", "胡斌 信息总监"),
    ("能源集团大客户管理", 16, 1180000, "商务谈判", 20, "zhangwei", "Salesforce", "林菁 副总裁"),
    ("重工售后服务系统", 17, 396000, "需求确认", 61, "zhangwei", "用友", "郭睿 服务总监"),
    ("水产供应链 CRM", 18, 138000, "初步接触", 95, "zhangwei", "", "王建国 总经理"),
    ("医药代表访客管理", 19, 284000, "方案报价", 44, "zhangwei", "Veeva", "李慧敏 销售副总"),
    ("激光设备销售管理", 20, 548000, "商务谈判", 10, "liuyang", "纷享销客", "张海涛 营销总监"),
    ("重工客户信用管理", 21, 302000, "需求确认", 70, "liuyang", "用友", "刘颖 财务总监"),
    ("冷链客户服务工单", 22, 104000, "输单", -12, "liuyang", "自研", "陈志强 运营经理"),
    ("软件服务续费升级", 23, 216000, "方案报价", 33, "wangfang", "无", "杨柳 客户成功"),
    ("汽车电子项目管理", 24, 468000, "商务谈判", 18, "wangfang", "销售易", "赵鹏 项目总监"),
    ("航天客户保密管理", 25, 742000, "方案报价", 48, "zhangwei", "自研", "孙晓东 信息中心主任"),
    ("重装集团营销平台", 26, 268000, "赢单", -16, "zhangwei", "用友", "周敏 副总裁"),
    ("船舶客户档案治理", 27, 96000, "初步接触", 102, "zhangwei", "", "吴刚 信息科"),
    ("智造云渠道分销", 28, 680000, "商务谈判", 9, "liuyang", "销售易", "郑丽华 COO"),
    ("医疗器械合规销售", 29, 208000, "方案报价", 41, "liuyang", "Veeva", "冯磊 合规总监"),
    ("新材料客户开发", 30, 186000, "需求确认", 55, "liuyang", "自研", "徐静 销售总监"),
    ("半导体大客户直销", 31, 880000, "方案报价", 24, "zhangwei", "Salesforce", "马超 销售副总"),
    ("机器人渠道管理", 32, 342000, "需求确认", 64, "wangfang", "纷享销客", "朱琳 渠道总监"),
    ("生物科技客户运营", 33, 128000, "初步接触", 78, "wangfang", "", "胡斌 市场经理"),
    ("新能源装备售后服务", 34, 358000, "方案报价", 36, "zhangwei", "用友", "林菁 服务总监"),
    ("纺织机械经销商", 35, 68000, "初步接触", 110, "liuyang", "", "郭睿 总经理"),
    ("精工机械客户二期", 0, 210000, "需求确认", 45, "liuyang", "销售易", "王建国 信息总监"),
    ("新能源材料全球营销", 1, 480000, "初步接触", 120, "liuyang", "", "李慧敏 采购总监"),
    ("智联电子服务工单", 2, 96000, "初步接触", 105, "liuyang", "", "张海涛 IT 经理"),
    ("华泰汽车客户门户", 3, 220000, "赢单", -30, "liuyang", "自研", "刘颖 运营经理"),
    ("海川模具报价协同", 4, 88000, "赢单", -45, "liuyang", "本地集成商", "陈志强 总经理"),
    ("睿驰智能海外营销", 8, 380000, "赢单", -22, "wangfang", "Salesforce", "周敏 CIO"),
    ("恒达电子客户中台", 10, 520000, "赢单", -8, "wangfang", "纷享销客", "郑丽华 采购总监"),
    ("南方物流客服系统", 9, 168000, "赢单", -55, "wangfang", "Zoho", "吴刚 运营总监"),
    ("中天能源营销一体化", 16, 960000, "赢单", -40, "zhangwei", "Salesforce", "林菁 副总裁"),
    ("中科仪器客户档案", 5, 72000, "赢单", -66, "liuyang", "无", "杨柳 主任"),
    ("海丝跨境客户运营", 12, 142000, "赢单", -18, "wangfang", "Zoho", "徐静 电商负责人"),
    ("钱塘新材料客户开发", 30, 78000, "输单", -25, "liuyang", "自研", "徐静 销售总监"),
    ("宝安机器人渠道", 32, 188000, "输单", -30, "wangfang", "纷享销客", "朱琳 渠道总监"),
    ("光谷激光客户平台", 20, 420000, "赢单", -70, "liuyang", "纷享销客", "张海涛 营销总监"),
    ("渤海重工营销平台", 17, 286000, "赢单", -95, "zhangwei", "用友", "郭睿 服务总监"),
    ("云图软件销售自动化", 13, 56000, "输单", -80, "wangfang", "HubSpot", "马超 CEO"),
]

TICKETS = [
    ("客户数据导入报错", "故障", "P1", "已解决", "chenlu", 3, 5, 4, "批量导入 3 万条客户时提示编码重复"),
    ("商机看板加载缓慢", "故障", "P2", "处理中", "chenlu", 1, 0, 0, "商机超过 2000 条后看板加载超过 8 秒"),
    ("报表数据与 ERP 不一致", "咨询", "P2", "待受理", "chenlu", 1, 0, 0, "回款金额与财务系统差异约 1.2 万"),
    ("移动端无法上传附件", "故障", "P1", "处理中", "chenlu", 2, 0, 0, "iOS 17 上传图片一直转圈"),
    ("新员工账号开通", "需求", "P3", "已关闭", "chenlu", 9, 20, 5, "新增 5 个销售账号并分配华东组"),
    ("线索分配规则咨询", "咨询", "P3", "已解决", "chenlu", 7, 12, 5, "希望按区域自动分配线索"),
    ("Webhook 未收到事件", "故障", "P1", "已解决", "chenlu", 4, 6, 3, "对接方未返回 2xx，重试 3 次后失败"),
    ("报价单打印格式错乱", "故障", "P2", "待确认", "chenlu", 2, 8, 0, "A4 打印时表头跨页"),
    ("合同回款计划调整", "需求", "P3", "已关闭", "chenlu", 15, 18, 5, "客户要求改为 4 期回款"),
    ("API 调用 401", "咨询", "P2", "已解决", "chenlu", 5, 9, 4, "对接方使用了过期的 API Key"),
    ("商机阶段无法推进", "咨询", "P2", "已解决", "chenlu", 6, 11, 5, "未填决策人导致无法进入商务谈判"),
    ("客户重复数据合并", "需求", "P3", "待受理", "chenlu", 1, 0, 0, "同一客户存在 3 条重复档案"),
    ("系统登录偶发超时", "故障", "P1", "已关闭", "chenlu", 12, 30, 3, "机房网络抖动，已扩容"),
    ("仪表盘指标口径确认", "咨询", "P3", "已解决", "chenlu", 10, 24, 4, "确认「销售净额」不含税"),
    ("工单 SLA 提醒未收到", "故障", "P2", "已解决", "chenlu", 8, 14, 4, "邮件网关限流导致延迟"),
    ("定制报表开发需求", "需求", "P3", "处理中", "chenlu", 3, 0, 0, "需要按行业拆分成交金额"),
    ("通讯录同步失败", "故障", "P2", "待受理", "chenlu", 1, 0, 0, "钉钉通讯录同步报 403"),
    ("续费合同开票信息", "咨询", "P3", "已关闭", "chenlu", 18, 22, 5, "更新开票抬头与税号"),
]


def load(cn):
    rnd = random.Random(SEED)
    for u in USERS:
        cn.execute("INSERT INTO users(username,password,display_name,role,team_code,phone,email,status,created_at)"
                   " VALUES(?,?,?,?,?,?,?,?,?)",
                   (u[0], db.sha256(u[1]), u[2], u[3], u[4], u[5], u[6], "在职", ts(-400)))
    for t in TEAMS:
        cn.execute("INSERT INTO teams(code,name,region,leader,remark) VALUES(?,?,?,?,?)", t)
    for p in PRODUCTS:
        cn.execute("INSERT INTO products(code,name,category,unit,price,cost,status,remark)"
                   " VALUES(?,?,?,?,?,?,?,?)", p)

    # ---- 客户 + 联系人
    cust_codes = []
    for i, c in enumerate(CUSTOMERS):
        code = "C-%04d" % (i + 1)
        cust_codes.append(code)
        cn.execute(
            "INSERT INTO customers(code,name,short_name,industry,scale,region,level,source,owner,phone,"
            "website,address,credit_limit,status,score,campaign_code,created_at,updated_at,last_follow_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (code, c[0], c[0][:6], c[1], c[7], c[2], c[3], c[4], c[5], "0512-6%07d" % (8000000 + i * 137),
             "www.cust%02d.com" % (i + 1), "%s · %s" % (c[2], c[0][:4]), c[6], c[10], 0, "",
             ts(-c[8]), ts(-c[9]), ts(-c[9])))
        n_contact = 1 + (i % 3)
        for k in range(n_contact):
            nm = CONTACT_NAMES[(i * 3 + k) % len(CONTACT_NAMES)]
            cn.execute(
                "INSERT INTO contacts(customer_code,name,title,phone,email,wechat,is_primary,remark,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (code, nm, TITLES[(i + k) % len(TITLES)],
                 "138%08d" % (10000000 + i * 977 + k * 13),
                 "%s%d@cust%02d.com" % ("contact", k + 1, i + 1),
                 "wx_%s_%d" % (code.lower(), k + 1), 1 if k == 0 else 0, "", ts(-c[8])))

    # ---- 线索
    for i, l in enumerate(LEADS):
        no = crm.doc_no("lead", TODAY - timedelta(days=l[9]), i + 1)
        status = l[7]
        owner = l[8] if status in ("跟进中", "已转客户") else ("" if status != "公海" else "")
        converted = ""
        if status == "已转客户":
            # 指向同行业客户，保证「已转客户」有落点
            converted = cust_codes[(i * 7) % 3 + 5]
        cn.execute(
            "INSERT INTO leads(no,name,contact,phone,email,source,industry,region,budget,demand,grade,status,"
            "owner,creator,campaign_code,converted_customer,invalid_reason,created_at,assigned_at,"
            "last_follow_at,next_follow_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (no, l[0], l[1], l[2], "lead%d@example.com" % (i + 1), l[3], l[4], l[5], l[6],
             "希望统一客户档案与商机过程管理，重点关注移动端与报表", crm.grade_of(l[6], l[3]), status,
             owner, "sunqi", l[10], converted,
             "预算不足/暂无采购计划" if status == "无效" else "",
             ts(-l[9]), ts(-l[9] + 1) if owner else "",
             ts(-max(1, l[9] // 3)) if status == "跟进中" else "", ""))
        if status == "公海":
            cn.execute("INSERT INTO pool_logs(lead_no,action,from_owner,to_owner,reason,operator,created_at)"
                       " VALUES(?,?,?,?,?,?,?)",
                       (no, "回收", l[8] or "sunqi", "", "超过 30 天未跟进自动回收", "system", ts(-3)))
        elif owner:
            cn.execute("INSERT INTO pool_logs(lead_no,action,from_owner,to_owner,reason,operator,created_at)"
                       " VALUES(?,?,?,?,?,?,?)",
                       (no, "分配", "", owner, "按区域自动分配", "sunqi", ts(-l[9] + 1)))

    # ---- 商机
    opp_rows = []
    for i, o in enumerate(OPPS):
        no = crm.doc_no("opportunity", TODAY - timedelta(days=abs(o[4]) + 20), i + 1)
        cus = CUSTOMERS[o[1]]
        ccode = cust_codes[o[1]]
        stage = o[3]
        prob = crm.STAGE_PROB[stage]
        status = crm.opp_status(stage)
        created = ts(-(abs(o[4]) + 20))
        closed = ts(-abs(o[4])) if status != "进行中" else ""
        cn.execute(
            "INSERT INTO opportunities(no,name,customer_code,customer_name,amount,stage,probability,"
            "expect_close_date,owner,source,campaign_code,competitor,decision_maker,status,win_reason,"
            "lose_reason,next_action,created_at,updated_at,closed_at,last_activity_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (no, o[0], ccode, cus[0], o[2], stage, prob, d(o[4]), o[5], cus[4],
             "CP-2026-EXPO" if i % 4 == 0 else ("CP-2026-REF" if i % 5 == 0 else ""),
             o[6], o[7], status,
             "价格与服务响应优于竞品" if stage == "赢单" else "",
             "预算被削减/选择自研" if stage == "输单" else "",
             "安排 POC 演示" if status == "进行中" else "", created, ts(-max(1, abs(o[4]) // 2)), closed,
             ts(-max(1, abs(o[4]) // 3))))
        cn.execute("INSERT INTO stage_logs(opp_no,from_stage,to_stage,amount,operator,remark,created_at)"
                   " VALUES(?,?,?,?,?,?,?)", (no, "", "初步接触", o[2], o[5], "商机创建", created))
        if stage != "初步接触":
            cn.execute("INSERT INTO stage_logs(opp_no,from_stage,to_stage,amount,operator,remark,created_at)"
                       " VALUES(?,?,?,?,?,?,?)", (no, "初步接触", stage, o[2], o[5], "阶段推进", ts(-15)))
        opp_rows.append((no, o, ccode, cus))

    # ---- 跟进记录
    kinds = ["电话", "拜访", "邮件", "会议", "微信"]
    subjects = ["需求调研（第一轮）", "方案演示与答疑", "报价沟通", "决策链梳理", "竞品对比说明",
                "POC 环境确认", "商务条款谈判", "高层拜访", "合同条款确认", "回款计划沟通"]
    for idx, (no, o, ccode, cus) in enumerate(opp_rows):
        n = 2 + (idx % 3)
        for k in range(n):
            offset = -(abs(o[4]) + 18 - k * 6)
            kind = kinds[(idx + k) % len(kinds)]
            cn.execute(
                "INSERT INTO activities(obj_type,obj_no,obj_name,kind,subject,content,happen_at,"
                "duration_min,owner,result,next_plan,next_at,status,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("opportunity", no, o[0], kind, subjects[(idx + k) % len(subjects)],
                 "与%s沟通，确认了当前系统痛点与预算范围，客户关注移动端与报表。" % o[7],
                 ts(offset, 9 + k, 30), 45 + k * 15, o[5],
                 "客户认可方案，进入下一环节", "发送正式报价" if k == n - 1 else "",
                 d(o[4]) if k == n - 1 else "", "完成", ts(offset)))
    for idx, ccode in enumerate(cust_codes[:24]):
        cn.execute(
            "INSERT INTO activities(obj_type,obj_no,obj_name,kind,subject,content,happen_at,"
            "duration_min,owner,result,next_plan,next_at,status,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("customer", ccode, CUSTOMERS[idx][0], "电话" if idx % 2 else "拜访",
             "季度客户回访", "回访使用情况，确认续费意愿与增购需求。", ts(-CUSTOMERS[idx][9], 15),
             40, CUSTOMERS[idx][5], "使用正常，暂无问题", "下季度再回访", "", "完成",
             ts(-CUSTOMERS[idx][9])))

    # ---- 报价（取「方案报价 / 商务谈判」的商机）
    quote_no_by_opp = {}
    qi = 0
    for no, o, ccode, cus in opp_rows:
        if o[3] not in ("方案报价", "商务谈判"):
            continue
        qi += 1
        qno = crm.doc_no("quote", TODAY - timedelta(days=abs(o[4]) // 2 + 5), qi)
        product = PRODUCTS[qi % 3]
        qty = 1 if qi % 5 else 2
        imp_days = 10 + qi % 12
        lines = [(product[0], product[1], qty, product[4], product[4] * (0.86 if qi % 3 == 0 else 0.92)),
                 ("P-IMP", "实施服务包", imp_days, 2400, 2400 * (0.9 if qi % 4 == 0 else 1.0))]
        calc = crm.quote_amount([{"qty": l[2], "listPrice": l[3], "price": l[4]} for l in lines])
        status = "已发送" if o[3] == "商务谈判" else ("待审批" if qno.endswith(("2", "4", "6", "8")) else "草稿")
        if status == "待审批" and not crm.need_discount_approval(calc["discountRate"], 0.15):
            status = "已发送"
        cn.execute(
            "INSERT INTO quotes(no,opp_no,customer_code,customer_name,title,amount,list_amount,"
            "discount_rate,status,valid_until,owner,approver,approved_at,reject_reason,remark,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (qno, no, ccode, cus[0], "%s报价单（%s）" % (o[0], product[1]), calc["amount"],
             calc["listAmount"], calc["discountRate"], status, d(30), o[5], "", "", "",
             "含 1 年运维", ts(-(abs(o[4]) // 2 + 5))))
        for si, l in enumerate(lines):
            cn.execute("INSERT INTO quote_lines(quote_no,seq,product_code,product_name,qty,list_price,price,amount)"
                       " VALUES(?,?,?,?,?,?,?,?)",
                       (qno, si + 1, l[0], l[1], l[2], l[3], crm.r2(l[4]), crm.r2(l[2] * l[4])))
        quote_no_by_opp[no] = qno

    # ---- 合同（赢单商机）
    ci = 0
    contracts = []
    for no, o, ccode, cus in opp_rows:
        if o[3] != "赢单":
            continue
        ci += 1
        cno = crm.doc_no("contract", TODAY - timedelta(days=abs(o[4])), ci)
        sign = TODAY - timedelta(days=abs(o[4]))
        status = "执行中" if abs(o[4]) > 10 else "已签署"
        cn.execute(
            "INSERT INTO contracts(no,customer_code,customer_name,quote_no,opp_no,title,amount,sign_date,"
            "start_date,end_date,payment_terms,status,owner,signed_at,terminated_at,remark,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cno, ccode, cus[0], quote_no_by_opp.get(no, ""), no, "%s 年度服务合同" % cus[0][:8],
             o[2], sign.isoformat(), sign.isoformat(), (sign + timedelta(days=365)).isoformat(),
             "3-4-3" if ci % 3 else "5-5", status, o[5], ts(-abs(o[4])), "", "", ts(-abs(o[4]) - 2)))
        plans = crm.build_plans(o[2], sign, "3-4-3" if ci % 3 else "5-5")
        paid_ratio = [1.0, 0.6, 0.0, 1.0, 0.3][ci % 5]
        for p in plans:
            paid = crm.r2(p["amount"] * paid_ratio) if p["seq"] == 1 else 0.0
            st = crm.plan_status(p["amount"], paid, p["dueDate"],
                                 TODAY)
            pid = cn.execute(
                "INSERT INTO contract_plans(contract_no,seq,due_date,amount,paid_amount,status,remark)"
                " VALUES(?,?,?,?,?,?,?)",
                (cno, p["seq"], p["dueDate"], p["amount"], paid, st, "")).lastrowid
            if paid > 0:
                cn.execute(
                    "INSERT INTO payments(no,contract_no,plan_id,customer_code,customer_name,amount,"
                    "pay_date,method,operator,remark,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (crm.doc_no("payment", sign + timedelta(days=5), ci * 10 + p["seq"]), cno, pid,
                     ccode, cus[0], paid, (sign + timedelta(days=5)).isoformat(),
                     "银行转账", "zhaomin", "首期款", ts(-abs(o[4]) + 5)))
        contracts.append((cno, o, ccode, cus))

    # 追加两笔逾期/部分收款，保证账龄报表有内容
    for extra in range(2):
        if not contracts:
            break
        cno, o, ccode, cus = contracts[extra]
        plans = db.rows(cn, "SELECT * FROM contract_plans WHERE contract_no=? ORDER BY seq", (cno,))
        if len(plans) >= 2:
            p = plans[1]
            cn.execute("UPDATE contract_plans SET paid_amount=?, status=? WHERE id=?",
                       (crm.r2(p["amount"] * 0.4), "部分逾期", p["id"]))
            cn.execute("INSERT INTO payments(no,contract_no,plan_id,customer_code,customer_name,amount,"
                       "pay_date,method,operator,remark,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (crm.doc_no("payment", TODAY - timedelta(days=20), 900 + extra), cno, p["id"],
                        ccode, cus[0], crm.r2(p["amount"] * 0.4),
                        (TODAY - timedelta(days=20)).isoformat(), "银行承兑", "zhaomin",
                        "客户分期支付 40%", ts(-20)))

    # ---- 工单
    for i, t in enumerate(TICKETS):
        title, cat, pri, status, owner, days_ago, resolved_days_ago, sat, desc = t
        created = ts(-days_ago, 9 + i % 8)
        resp_due, res_due = crm.sla_dues(created, pri)
        accepted = ts(-days_ago, 10 + i % 8) if status != "待受理" else ""
        resolved = ts(-resolved_days_ago, 16) if resolved_days_ago else ""
        closed = ts(-resolved_days_ago + 1, 10) if status == "已关闭" else ""
        st = crm.sla_state(res_due, None, resolved or None)
        if status in ("待受理", "处理中") and i % 3 == 1:
            st = "超时"
        ccode = cust_codes[(i * 5) % len(cust_codes)]
        cname = CUSTOMERS[(i * 5) % len(CUSTOMERS)][0]
        cno = contracts[i % len(contracts)][0] if contracts else ""
        no = crm.doc_no("ticket", TODAY - timedelta(days=days_ago), i + 1)
        cn.execute(
            "INSERT INTO tickets(no,customer_code,customer_name,contract_no,title,category,priority,"
            "status,owner,creator,description,created_at,accepted_at,resolved_at,closed_at,response_due,"
            "resolve_due,sla_state,satisfaction,resolution) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (no, ccode, cname, cno, title, cat, pri, status, owner, "chenlu", desc, created, accepted,
             resolved, closed, resp_due, res_due, st, sat,
             "已定位为数据索引缺失，重建索引后恢复" if resolved else ""))
        cn.execute("INSERT INTO ticket_logs(ticket_no,action,content,operator,created_at) VALUES(?,?,?,?,?)",
                   (no, "创建", desc, "chenlu", created))
        if accepted:
            cn.execute("INSERT INTO ticket_logs(ticket_no,action,content,operator,created_at) VALUES(?,?,?,?,?)",
                       (no, "受理", "已受理，预计 2 小时内给出方案", owner, accepted))
        if resolved:
            cn.execute("INSERT INTO ticket_logs(ticket_no,action,content,operator,created_at) VALUES(?,?,?,?,?)",
                       (no, "解决", "问题已解决，客户确认恢复正常", owner, resolved))
        if closed:
            cn.execute("INSERT INTO ticket_logs(ticket_no,action,content,operator,created_at) VALUES(?,?,?,?,?)",
                       (no, "关闭", "客户确认关闭，满意度 %d 分" % sat, owner, closed))

    # ---- 市场活动与归因
    for c in CAMPAIGNS:
        cn.execute("INSERT INTO campaigns(code,name,kind,channel,start_date,end_date,budget,cost,"
                   "target_leads,owner,status,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (c[0], c[1], c[2], c[3], d(c[4]), d(c[5]) if c[5] < 0 else d(60), c[6], c[7],
                    c[8], c[9], c[10], c[11]))
    for i, l in enumerate(LEADS):
        if not l[10]:
            continue
        lead_no = db.one(cn, "SELECT no FROM leads WHERE name=?", (l[0],))["no"]
        cn.execute("INSERT INTO campaign_members(campaign_code,lead_no,customer_code,cost,created_at)"
                   " VALUES(?,?,?,?,?)", (l[10], lead_no, "", 0, ts(-l[9])))
    for i, (cno, o, ccode, cus) in enumerate(contracts):
        if i % 2 == 0:
            cn.execute("INSERT INTO campaign_members(campaign_code,lead_no,customer_code,cost,created_at)"
                       " VALUES(?,?,?,?,?)",
                       ("CP-2026-EXPO" if i % 4 == 0 else "CP-2026-REF", "", ccode,
                        crm.r2(o[2] * 0.03), ts(-abs(o[4]))))

    # ---- 销售目标（近 4 个月，含本月）
    for owner in ("liuyang", "wangfang", "zhangwei"):
        for m, amount in zip(crm.month_list(TODAY - timedelta(days=60), 3),
                             (600000, 700000, 800000)):
            cn.execute("INSERT INTO targets(owner,period,amount,remark) VALUES(?,?,?,?)",
                       (owner, m, amount, "月度签约额目标"))

    # ---- 规则
    rules = [
        ("dup_check", "线索查重", 1, "", 1, "流程", "手机号/邮箱/公司名命中则提示重复，可强制创建但留痕"),
        ("pool_days", "公海回收天数", 30, "天", 1, "流程", "超过该天数未跟进的线索自动回收公海"),
        ("discount_approval", "报价折扣审批线", 0.15, "", 1, "流程", "折扣率超过该值必须销售总监审批"),
        ("sla_p1", "P1 工单解决时限", 4, "小时", 1, "服务", "P1（系统不可用）必须在时限内解决"),
        ("sla_p2", "P2 工单解决时限", 8, "小时", 1, "服务", "P2（功能异常）解决时限"),
        ("sla_p3", "P3 工单解决时限", 24, "小时", 1, "服务", "P3（咨询/需求）解决时限"),
        ("win_rate_alert", "商机赢率预警线", 0.35, "", 1, "分析", "阶段赢率低于该值时在漏斗页高亮提示"),
        ("forecast_months", "预测滚动月数", 3, "月", 1, "分析", "销售预测默认滚动月份数"),
    ]
    for r in rules:
        cn.execute("INSERT INTO rules(code,name,value,unit,enabled,category,remark) VALUES(?,?,?,?,?,?,?)", r)

    # ---- 集成：演示 API Key（只读）+ 停用的 Webhook
    demo_key = "fyk_demo_5f3a9c8b7d6e4f2a1b0c9d8e7f6a5b4c"
    cn.execute("INSERT INTO api_keys(name,key_prefix,key_hash,scope,owner,status,expires_at,"
               "last_used_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
               ("演示只读 Key（对接方示例）", demo_key[:12], db.sha256(demo_key), "read", "admin",
                "启用", d(365), "", ts(-10)))
    cn.execute("INSERT INTO webhooks(name,url,events,secret,status,last_status,last_at,fail_count,created_at)"
               " VALUES(?,?,?,?,?,?,?,?,?)",
               ("演示接收端（默认停用）", "http://127.0.0.1:8099/hook",
                "lead.created,customer.created,opportunity.stage_changed,contract.signed,payment.received",
                "demo-secret-2026", "停用", "", "", 0, ts(-10)))
    for i, (code, name) in enumerate([("C-0001", "crm-1001"), ("C-0003", "crm-1003"),
                                      ("C-0009", "crm-2001")]):
        cn.execute("INSERT INTO ext_mappings(obj_type,local_no,external_id,system,created_at)"
                   " VALUES(?,?,?,?,?)", ("customer", code, name, "ERP", ts(-30)))

    # ---- 变更日志（增量同步的初始水位）
    for row in db.rows(cn, "SELECT code,name,updated_at FROM customers"):
        cn.execute("INSERT INTO change_log(obj_type,obj_no,op,actor,payload,changed_at)"
                   " VALUES(?,?,?,?,?,?)",
                   ("customer", row["code"], "upsert", "seed",
                    '{"code": "%s", "name": "%s"}' % (row["code"], row["name"]),
                    row["updated_at"] or ts(-1)))
    for row in db.rows(cn, "SELECT no,name,created_at FROM leads"):
        cn.execute("INSERT INTO change_log(obj_type,obj_no,op,actor,payload,changed_at)"
                   " VALUES(?,?,?,?,?,?)",
                   ("lead", row["no"], "upsert", "seed",
                    '{"no": "%s", "name": "%s"}' % (row["no"], row["name"]),
                    row["created_at"] or ts(-1)))

    # ---- 客户评分回填
    for c in db.rows(cn, "SELECT * FROM customers"):
        days = crm.days_between(c["last_follow_at"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        paid = db.one(cn, "SELECT COALESCE(SUM(amount),0) s FROM payments WHERE customer_code=?",
                      (c["code"],))["s"]
        opps = db.one(cn, "SELECT COUNT(*) c FROM opportunities WHERE customer_code=? AND status='进行中'",
                      (c["code"],))["c"]
        sat = db.one(cn, "SELECT COALESCE(AVG(satisfaction),0) s FROM tickets "
                         "WHERE customer_code=? AND satisfaction>0", (c["code"],))["s"]
        od = db.one(cn, "SELECT COUNT(*) c FROM contract_plans p JOIN contracts t ON t.no=p.contract_no "
                        "WHERE t.customer_code=? AND p.status LIKE '%逾期%'", (c["code"],))["c"]
        cn.execute("UPDATE customers SET score=? WHERE code=?",
                   (crm.score_customer(days, paid, opps, sat, od), c["code"]))

    cn.execute("INSERT INTO op_logs(username,action,detail,created_at) VALUES(?,?,?,?)",
               ("system", "初始化", "装载演示数据（客户 36 / 线索 48 / 商机 52 / 合同 14 / 工单 18）", ts(0, 8)))

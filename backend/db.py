# -*- coding: utf-8 -*-
"""飞鹰 CRM · 数据层：SQLite 零依赖，连接管理 / 建表 / 种子装载。

并发纪律：
- journal_mode 是持久化设置，只在 init_db 设一次；每连接再设会写锁，
  Windows 下多连接并发偶发 "attempt to write a readonly database"；
- 服务层对所有 /api/ 请求整段串行化（RLock），这里只需 busy_timeout。
"""
import hashlib
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("FEIYING_DB", os.path.join(BASE_DIR, "data", "feiying.db"))

SCHEMA = """
-- ---------------------------------------------------------------- 账号与组织
CREATE TABLE IF NOT EXISTS users (
  username     TEXT PRIMARY KEY,
  password     TEXT NOT NULL,
  display_name TEXT NOT NULL,
  role         TEXT NOT NULL,
  team_code    TEXT DEFAULT '',
  phone        TEXT DEFAULT '',
  email        TEXT DEFAULT '',
  status       TEXT DEFAULT '在职',
  created_at   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sessions (
  token      TEXT PRIMARY KEY,
  username   TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS teams (
  code    TEXT PRIMARY KEY,
  name    TEXT NOT NULL,
  region  TEXT DEFAULT '',
  leader  TEXT DEFAULT '',
  remark  TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 客户主数据
CREATE TABLE IF NOT EXISTS customers (
  code          TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  short_name    TEXT DEFAULT '',
  industry      TEXT DEFAULT '制造业',
  scale         TEXT DEFAULT '中型',
  region        TEXT DEFAULT '华东',
  level         TEXT DEFAULT 'B',
  source        TEXT DEFAULT '老客推荐',
  owner         TEXT DEFAULT '',
  phone         TEXT DEFAULT '',
  website       TEXT DEFAULT '',
  address       TEXT DEFAULT '',
  credit_limit  REAL NOT NULL DEFAULT 0,
  status        TEXT DEFAULT '活跃',
  score         REAL NOT NULL DEFAULT 0,
  campaign_code TEXT DEFAULT '',
  created_at    TEXT DEFAULT '',
  updated_at    TEXT DEFAULT '',
  last_follow_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS contacts (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_code TEXT NOT NULL,
  name          TEXT NOT NULL,
  title         TEXT DEFAULT '',
  phone         TEXT DEFAULT '',
  email         TEXT DEFAULT '',
  wechat        TEXT DEFAULT '',
  is_primary    INTEGER NOT NULL DEFAULT 0,
  remark        TEXT DEFAULT '',
  created_at    TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 线索与商机
CREATE TABLE IF NOT EXISTS leads (
  no            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  contact       TEXT DEFAULT '',
  phone         TEXT DEFAULT '',
  email         TEXT DEFAULT '',
  source        TEXT DEFAULT '官网表单',
  industry      TEXT DEFAULT '',
  region        TEXT DEFAULT '',
  budget        REAL NOT NULL DEFAULT 0,
  demand        TEXT DEFAULT '',
  grade         TEXT DEFAULT 'B',
  status        TEXT DEFAULT '待分配',
  owner         TEXT DEFAULT '',
  creator       TEXT DEFAULT '',
  campaign_code TEXT DEFAULT '',
  converted_customer TEXT DEFAULT '',
  invalid_reason TEXT DEFAULT '',
  created_at    TEXT DEFAULT '',
  assigned_at   TEXT DEFAULT '',
  last_follow_at TEXT DEFAULT '',
  next_follow_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pool_logs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_no    TEXT NOT NULL,
  action     TEXT NOT NULL,
  from_owner TEXT DEFAULT '',
  to_owner   TEXT DEFAULT '',
  reason     TEXT DEFAULT '',
  operator   TEXT DEFAULT '',
  created_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS opportunities (
  no                TEXT PRIMARY KEY,
  name              TEXT NOT NULL,
  customer_code     TEXT NOT NULL,
  customer_name     TEXT DEFAULT '',
  amount            REAL NOT NULL DEFAULT 0,
  stage             TEXT NOT NULL DEFAULT '初步接触',
  probability       REAL NOT NULL DEFAULT 0.1,
  expect_close_date TEXT DEFAULT '',
  owner             TEXT DEFAULT '',
  source            TEXT DEFAULT '',
  campaign_code     TEXT DEFAULT '',
  competitor        TEXT DEFAULT '',
  decision_maker    TEXT DEFAULT '',
  status            TEXT DEFAULT '进行中',
  win_reason        TEXT DEFAULT '',
  lose_reason       TEXT DEFAULT '',
  next_action       TEXT DEFAULT '',
  created_at        TEXT DEFAULT '',
  updated_at        TEXT DEFAULT '',
  closed_at         TEXT DEFAULT '',
  last_activity_at  TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS stage_logs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  opp_no     TEXT NOT NULL,
  from_stage TEXT DEFAULT '',
  to_stage   TEXT DEFAULT '',
  amount     REAL NOT NULL DEFAULT 0,
  operator   TEXT DEFAULT '',
  remark     TEXT DEFAULT '',
  created_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS activities (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  obj_type     TEXT NOT NULL DEFAULT 'customer',
  obj_no       TEXT NOT NULL DEFAULT '',
  obj_name     TEXT DEFAULT '',
  kind         TEXT NOT NULL DEFAULT '电话',
  subject      TEXT NOT NULL DEFAULT '',
  content      TEXT DEFAULT '',
  happen_at    TEXT DEFAULT '',
  duration_min INTEGER NOT NULL DEFAULT 30,
  owner        TEXT DEFAULT '',
  result       TEXT DEFAULT '',
  next_plan    TEXT DEFAULT '',
  next_at      TEXT DEFAULT '',
  status       TEXT NOT NULL DEFAULT '完成',
  created_at   TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 报价 / 合同 / 回款
CREATE TABLE IF NOT EXISTS products (
  code     TEXT PRIMARY KEY,
  name     TEXT NOT NULL,
  category TEXT DEFAULT '软件',
  unit     TEXT DEFAULT '套',
  price    REAL NOT NULL DEFAULT 0,
  cost     REAL NOT NULL DEFAULT 0,
  status   TEXT DEFAULT '在售',
  remark   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS quotes (
  no            TEXT PRIMARY KEY,
  opp_no        TEXT DEFAULT '',
  customer_code TEXT NOT NULL,
  customer_name TEXT DEFAULT '',
  title         TEXT DEFAULT '',
  amount        REAL NOT NULL DEFAULT 0,
  list_amount   REAL NOT NULL DEFAULT 0,
  discount_rate REAL NOT NULL DEFAULT 0,
  status        TEXT NOT NULL DEFAULT '草稿',
  valid_until   TEXT DEFAULT '',
  owner         TEXT DEFAULT '',
  approver      TEXT DEFAULT '',
  approved_at   TEXT DEFAULT '',
  reject_reason TEXT DEFAULT '',
  remark        TEXT DEFAULT '',
  created_at    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS quote_lines (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  quote_no     TEXT NOT NULL,
  seq          INTEGER NOT NULL DEFAULT 1,
  product_code TEXT NOT NULL,
  product_name TEXT NOT NULL,
  qty          REAL NOT NULL DEFAULT 1,
  list_price   REAL NOT NULL DEFAULT 0,
  price        REAL NOT NULL DEFAULT 0,
  amount       REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS contracts (
  no             TEXT PRIMARY KEY,
  customer_code  TEXT NOT NULL,
  customer_name  TEXT DEFAULT '',
  quote_no       TEXT DEFAULT '',
  opp_no         TEXT DEFAULT '',
  title          TEXT DEFAULT '',
  amount         REAL NOT NULL DEFAULT 0,
  sign_date      TEXT DEFAULT '',
  start_date     TEXT DEFAULT '',
  end_date       TEXT DEFAULT '',
  payment_terms  TEXT DEFAULT '3-4-3',
  status         TEXT NOT NULL DEFAULT '草稿',
  owner          TEXT DEFAULT '',
  signed_at      TEXT DEFAULT '',
  terminated_at  TEXT DEFAULT '',
  remark         TEXT DEFAULT '',
  created_at     TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS contract_plans (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_no  TEXT NOT NULL,
  seq          INTEGER NOT NULL DEFAULT 1,
  due_date     TEXT NOT NULL,
  amount       REAL NOT NULL DEFAULT 0,
  paid_amount  REAL NOT NULL DEFAULT 0,
  status       TEXT NOT NULL DEFAULT '未收',
  remark       TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS payments (
  no            TEXT PRIMARY KEY,
  contract_no   TEXT DEFAULT '',
  plan_id       INTEGER NOT NULL DEFAULT 0,
  customer_code TEXT NOT NULL,
  customer_name TEXT DEFAULT '',
  amount        REAL NOT NULL DEFAULT 0,
  pay_date      TEXT DEFAULT '',
  method        TEXT DEFAULT '银行转账',
  operator      TEXT DEFAULT '',
  remark        TEXT DEFAULT '',
  created_at    TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 服务工单
CREATE TABLE IF NOT EXISTS tickets (
  no            TEXT PRIMARY KEY,
  customer_code TEXT NOT NULL,
  customer_name TEXT DEFAULT '',
  contract_no   TEXT DEFAULT '',
  title         TEXT NOT NULL,
  category      TEXT DEFAULT '咨询',
  priority      TEXT NOT NULL DEFAULT 'P2',
  status        TEXT NOT NULL DEFAULT '待受理',
  owner         TEXT DEFAULT '',
  creator       TEXT DEFAULT '',
  description   TEXT DEFAULT '',
  created_at    TEXT DEFAULT '',
  accepted_at   TEXT DEFAULT '',
  resolved_at   TEXT DEFAULT '',
  closed_at     TEXT DEFAULT '',
  response_due  TEXT DEFAULT '',
  resolve_due   TEXT DEFAULT '',
  sla_state     TEXT DEFAULT '正常',
  satisfaction  INTEGER NOT NULL DEFAULT 0,
  resolution    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ticket_logs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_no  TEXT NOT NULL,
  action     TEXT NOT NULL,
  content    TEXT DEFAULT '',
  operator   TEXT DEFAULT '',
  created_at TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 市场活动
CREATE TABLE IF NOT EXISTS campaigns (
  code         TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  kind         TEXT DEFAULT '线上投放',
  channel      TEXT DEFAULT '微信公众号',
  start_date   TEXT DEFAULT '',
  end_date     TEXT DEFAULT '',
  budget       REAL NOT NULL DEFAULT 0,
  cost         REAL NOT NULL DEFAULT 0,
  target_leads INTEGER NOT NULL DEFAULT 0,
  owner        TEXT DEFAULT '',
  status       TEXT DEFAULT '进行中',
  remark       TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS campaign_members (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_code TEXT NOT NULL,
  lead_no       TEXT DEFAULT '',
  customer_code TEXT DEFAULT '',
  cost          REAL NOT NULL DEFAULT 0,
  created_at    TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 目标与规则
CREATE TABLE IF NOT EXISTS targets (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  owner  TEXT NOT NULL,
  period TEXT NOT NULL,
  amount REAL NOT NULL DEFAULT 0,
  remark TEXT DEFAULT '',
  UNIQUE(owner, period)
);
CREATE TABLE IF NOT EXISTS rules (
  code     TEXT PRIMARY KEY,
  name     TEXT NOT NULL,
  value    REAL NOT NULL DEFAULT 0,
  unit     TEXT DEFAULT '',
  enabled  INTEGER NOT NULL DEFAULT 1,
  category TEXT DEFAULT '流程',
  remark   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS op_logs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  username   TEXT DEFAULT '',
  action     TEXT DEFAULT '',
  detail     TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- ---------------------------------------------------------------- 集成（对外对接）
CREATE TABLE IF NOT EXISTS api_keys (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  name         TEXT NOT NULL,
  key_prefix   TEXT NOT NULL,
  key_hash     TEXT NOT NULL,
  scope        TEXT NOT NULL DEFAULT 'read',
  owner        TEXT DEFAULT '',
  status       TEXT NOT NULL DEFAULT '启用',
  expires_at   TEXT DEFAULT '',
  last_used_at TEXT DEFAULT '',
  created_at   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS webhooks (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL,
  url         TEXT NOT NULL,
  events      TEXT NOT NULL DEFAULT '*',
  secret      TEXT NOT NULL DEFAULT '',
  status      TEXT NOT NULL DEFAULT '启用',
  last_status TEXT DEFAULT '',
  last_at     TEXT DEFAULT '',
  fail_count  INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS webhook_deliveries (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  webhook_id   INTEGER NOT NULL DEFAULT 0,
  event        TEXT NOT NULL,
  payload      TEXT NOT NULL DEFAULT '{}',
  signature    TEXT DEFAULT '',
  status       TEXT NOT NULL DEFAULT '待投递',
  attempts     INTEGER NOT NULL DEFAULT 0,
  http_code    INTEGER NOT NULL DEFAULT 0,
  error        TEXT DEFAULT '',
  next_at      TEXT DEFAULT '',
  created_at   TEXT DEFAULT '',
  delivered_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ext_mappings (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  obj_type    TEXT NOT NULL,
  local_no    TEXT NOT NULL,
  external_id TEXT NOT NULL,
  system      TEXT DEFAULT '',
  created_at  TEXT DEFAULT '',
  UNIQUE(obj_type, system, external_id)
);
CREATE TABLE IF NOT EXISTS change_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  obj_type   TEXT NOT NULL,
  obj_no     TEXT NOT NULL,
  op         TEXT NOT NULL DEFAULT 'upsert',
  actor      TEXT DEFAULT '',
  payload    TEXT DEFAULT '{}',
  changed_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS idem_keys (
  key        TEXT PRIMARY KEY,
  path       TEXT NOT NULL DEFAULT '',
  response   TEXT NOT NULL DEFAULT '{}',
  created_at TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status, owner);
CREATE INDEX IF NOT EXISTS idx_opp_stage ON opportunities(stage, status);
CREATE INDEX IF NOT EXISTS idx_act_obj ON activities(obj_type, obj_no);
CREATE INDEX IF NOT EXISTS idx_plan_contract ON contract_plans(contract_no);
CREATE INDEX IF NOT EXISTS idx_ticket_status ON tickets(status, priority);
CREATE INDEX IF NOT EXISTS idx_chg ON change_log(obj_type, id);
CREATE INDEX IF NOT EXISTS idx_deliv ON webhook_deliveries(status, id);
CREATE INDEX IF NOT EXISTS idx_map ON ext_mappings(external_id);
"""


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def conn():
    c = sqlite3.connect(DB_PATH, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=20000")
    return c


def rows(cn, sql, args=()):
    return [dict(r) for r in cn.execute(sql, args).fetchall()]


def one(cn, sql, args=()):
    r = cn.execute(sql, args).fetchone()
    return dict(r) if r else None


def log_action(cn, username, action, detail=""):
    cn.execute("INSERT INTO op_logs(username, action, detail) VALUES(?,?,?)",
               (username, action, detail))


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    cn = conn()
    try:
        cn.execute("PRAGMA journal_mode=WAL")
        cn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError:
        pass
    cn.executescript(SCHEMA)
    if cn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0:
        import seed
        seed.load(cn)
    cn.commit()
    cn.close()


if __name__ == "__main__":
    init_db()
    print("db ready:", DB_PATH)

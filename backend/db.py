# -*- coding: utf-8 -*-
"""飞泉 SCM · 数据层：SQLite 零依赖，建表 / 连接 / 种子装载。

并发纪律（与飞鹰 CRM 一致）
- journal_mode 是持久化设置，只在 init_db 设一次；
- 每连接只设 busy_timeout；
- 服务层对所有 /api/ 请求整段串行化（RLock），这里不再做额外锁。
"""
import hashlib
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("FEIQUAN_DB", os.path.join(BASE_DIR, "data", "feiquan.db"))

SCHEMA = """
-- ---------------------------------------------------------------- 账号与组织
CREATE TABLE IF NOT EXISTS users (
  username     TEXT PRIMARY KEY,
  password     TEXT NOT NULL,
  display_name TEXT NOT NULL,
  role         TEXT NOT NULL,
  dept_code    TEXT DEFAULT '',
  phone        TEXT DEFAULT '',
  email        TEXT DEFAULT '',
  status       TEXT DEFAULT '在职',
  created_at   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sessions (
  token      TEXT PRIMARY KEY,
  username   TEXT NOT NULL,
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS teams (
  code    TEXT PRIMARY KEY,
  name    TEXT NOT NULL,
  dept    TEXT DEFAULT '',
  leader  TEXT DEFAULT '',
  remark  TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS rules (
  code    TEXT PRIMARY KEY,
  name    TEXT NOT NULL,
  category TEXT DEFAULT '采购',
  value   REAL DEFAULT 0,
  unit    TEXT DEFAULT '',
  enabled INTEGER DEFAULT 1,
  remark  TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS op_logs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  username   TEXT DEFAULT '',
  action     TEXT DEFAULT '',
  detail     TEXT DEFAULT '',
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS budgets (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  period  TEXT NOT NULL,
  dept    TEXT NOT NULL,
  amount  REAL DEFAULT 0,
  used    REAL DEFAULT 0,
  remark  TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 供应商
CREATE TABLE IF NOT EXISTS suppliers (
  code           TEXT PRIMARY KEY,
  name           TEXT NOT NULL,
  short_name     TEXT DEFAULT '',
  category       TEXT DEFAULT '',
  level          TEXT DEFAULT 'B',
  status         TEXT DEFAULT '待准入',
  score          REAL DEFAULT 0,
  health         TEXT DEFAULT '正常',
  tax_no         TEXT DEFAULT '',
  contact        TEXT DEFAULT '',
  phone          TEXT DEFAULT '',
  email          TEXT DEFAULT '',
  address        TEXT DEFAULT '',
  region         TEXT DEFAULT '',
  payment_terms  INTEGER DEFAULT 30,
  lead_days      INTEGER DEFAULT 15,
  capacity       TEXT DEFAULT '',
  currency       TEXT DEFAULT 'CNY',
  remark         TEXT DEFAULT '',
  created_at     TEXT DEFAULT '',
  updated_at     TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS supplier_quals (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  supplier_code TEXT NOT NULL,
  name          TEXT NOT NULL,
  no            TEXT DEFAULT '',
  issued_at     TEXT DEFAULT '',
  expire_at     TEXT DEFAULT '',
  remark        TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS supplier_scores (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  supplier_code TEXT NOT NULL,
  period        TEXT NOT NULL,
  delivery_rate REAL DEFAULT 0,
  quality_rate  REAL DEFAULT 0,
  price_index   REAL DEFAULT 1,
  response_rate REAL DEFAULT 0,
  score         REAL DEFAULT 0,
  level         TEXT DEFAULT '',
  remark        TEXT DEFAULT '',
  created_at    TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 物料
CREATE TABLE IF NOT EXISTS materials (
  code           TEXT PRIMARY KEY,
  name           TEXT NOT NULL,
  spec           TEXT DEFAULT '',
  unit           TEXT DEFAULT '个',
  category       TEXT DEFAULT '',
  abc            TEXT DEFAULT 'C',
  standard_price REAL DEFAULT 0,
  last_price     REAL DEFAULT 0,
  lead_days      INTEGER DEFAULT 10,
  safety_stock   REAL DEFAULT 0,
  max_stock      REAL DEFAULT 0,
  min_order_qty  REAL DEFAULT 0,
  avg_daily_usage REAL DEFAULT 0,
  main_supplier  TEXT DEFAULT '',
  status         TEXT DEFAULT '启用',
  remark         TEXT DEFAULT '',
  created_at     TEXT DEFAULT '',
  updated_at     TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS material_prices (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  material_code TEXT NOT NULL,
  supplier_code TEXT DEFAULT '',
  price         REAL DEFAULT 0,
  effective_at  TEXT DEFAULT '',
  source        TEXT DEFAULT '',
  remark        TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS warehouses (
  code     TEXT PRIMARY KEY,
  name     TEXT NOT NULL,
  location TEXT DEFAULT '',
  keeper   TEXT DEFAULT '',
  status   TEXT DEFAULT '启用',
  remark   TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 请购
CREATE TABLE IF NOT EXISTS requisitions (
  no            TEXT PRIMARY KEY,
  dept          TEXT DEFAULT '',
  applicant     TEXT DEFAULT '',
  purpose       TEXT DEFAULT '',
  need_date     TEXT DEFAULT '',
  amount        REAL DEFAULT 0,
  status        TEXT DEFAULT '草稿',
  approver      TEXT DEFAULT '',
  approved_at   TEXT DEFAULT '',
  reject_reason TEXT DEFAULT '',
  converted_no  TEXT DEFAULT '',
  remark        TEXT DEFAULT '',
  created_at    TEXT DEFAULT '',
  updated_at    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS req_items (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  req_no        TEXT NOT NULL,
  material_code TEXT DEFAULT '',
  material_name TEXT DEFAULT '',
  spec          TEXT DEFAULT '',
  unit          TEXT DEFAULT '个',
  qty           REAL DEFAULT 0,
  est_price     REAL DEFAULT 0,
  amount        REAL DEFAULT 0,
  remark        TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 询价比价
CREATE TABLE IF NOT EXISTS rfqs (
  no               TEXT PRIMARY KEY,
  req_no           TEXT DEFAULT '',
  title            TEXT DEFAULT '',
  status           TEXT DEFAULT '询价中',
  deadline         TEXT DEFAULT '',
  owner            TEXT DEFAULT '',
  awarded_supplier TEXT DEFAULT '',
  awarded_amount   REAL DEFAULT 0,
  remark           TEXT DEFAULT '',
  created_at       TEXT DEFAULT '',
  updated_at       TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS rfq_items (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  rfq_no        TEXT NOT NULL,
  material_code TEXT DEFAULT '',
  material_name TEXT DEFAULT '',
  qty           REAL DEFAULT 0,
  unit          TEXT DEFAULT '个'
);
CREATE TABLE IF NOT EXISTS rfq_quotes (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  rfq_no        TEXT NOT NULL,
  supplier_code TEXT DEFAULT '',
  supplier_name TEXT DEFAULT '',
  amount        REAL DEFAULT 0,
  lead_days     INTEGER DEFAULT 0,
  valid_days    INTEGER DEFAULT 30,
  awarded       INTEGER DEFAULT 0,
  remark        TEXT DEFAULT '',
  created_at    TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 采购订单
CREATE TABLE IF NOT EXISTS purchase_orders (
  no              TEXT PRIMARY KEY,
  supplier_code   TEXT DEFAULT '',
  supplier_name   TEXT DEFAULT '',
  req_no          TEXT DEFAULT '',
  rfq_no          TEXT DEFAULT '',
  title           TEXT DEFAULT '',
  amount          REAL DEFAULT 0,
  currency        TEXT DEFAULT 'CNY',
  status          TEXT DEFAULT '草稿',
  promise_date    TEXT DEFAULT '',
  owner           TEXT DEFAULT '',
  approver        TEXT DEFAULT '',
  approved_at     TEXT DEFAULT '',
  ordered_at      TEXT DEFAULT '',
  ordered_qty     REAL DEFAULT 0,
  received_qty    REAL DEFAULT 0,
  received_amount REAL DEFAULT 0,
  invoiced_amount REAL DEFAULT 0,
  match_result    TEXT DEFAULT '',
  closed_at       TEXT DEFAULT '',
  cancel_reason   TEXT DEFAULT '',
  remark          TEXT DEFAULT '',
  created_at      TEXT DEFAULT '',
  updated_at      TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS po_items (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  po_no         TEXT NOT NULL,
  material_code TEXT DEFAULT '',
  material_name TEXT DEFAULT '',
  spec          TEXT DEFAULT '',
  unit          TEXT DEFAULT '个',
  qty           REAL DEFAULT 0,
  price         REAL DEFAULT 0,
  amount        REAL DEFAULT 0,
  received_qty  REAL DEFAULT 0,
  promise_date  TEXT DEFAULT '',
  remark        TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 收货质检
CREATE TABLE IF NOT EXISTS receipts (
  no            TEXT PRIMARY KEY,
  po_no         TEXT DEFAULT '',
  supplier_code TEXT DEFAULT '',
  supplier_name TEXT DEFAULT '',
  warehouse     TEXT DEFAULT '',
  status        TEXT DEFAULT '待质检',
  inspected_by  TEXT DEFAULT '',
  inspect_result TEXT DEFAULT '',
  received_at   TEXT DEFAULT '',
  posted_at     TEXT DEFAULT '',
  remark        TEXT DEFAULT '',
  created_at    TEXT DEFAULT '',
  updated_at    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS receipt_items (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  receipt_no    TEXT NOT NULL,
  material_code TEXT DEFAULT '',
  material_name TEXT DEFAULT '',
  unit          TEXT DEFAULT '个',
  qty           REAL DEFAULT 0,
  ok_qty        REAL DEFAULT 0,
  ng_qty        REAL DEFAULT 0,
  price         REAL DEFAULT 0,
  amount        REAL DEFAULT 0,
  batch         TEXT DEFAULT '',
  expire_at     TEXT DEFAULT '',
  remark        TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 发票与结算
CREATE TABLE IF NOT EXISTS invoices (
  no            TEXT PRIMARY KEY,
  po_no         TEXT DEFAULT '',
  supplier_code TEXT DEFAULT '',
  supplier_name TEXT DEFAULT '',
  invoice_no    TEXT DEFAULT '',
  amount        REAL DEFAULT 0,
  tax_rate      REAL DEFAULT 0.13,
  invoice_date  TEXT DEFAULT '',
  due_date      TEXT DEFAULT '',
  status        TEXT DEFAULT '待匹配',
  match_result  TEXT DEFAULT '',
  diff_amount   REAL DEFAULT 0,
  diff_rate     REAL DEFAULT 0,
  paid_amount   REAL DEFAULT 0,
  paid_at       TEXT DEFAULT '',
  remark        TEXT DEFAULT '',
  created_at    TEXT DEFAULT '',
  updated_at    TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 库存
CREATE TABLE IF NOT EXISTS stock (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  material_code TEXT NOT NULL,
  material_name TEXT DEFAULT '',
  spec          TEXT DEFAULT '',
  unit          TEXT DEFAULT '个',
  warehouse     TEXT NOT NULL,
  batch         TEXT DEFAULT '',
  qty           REAL DEFAULT 0,
  locked        REAL DEFAULT 0,
  unit_cost     REAL DEFAULT 0,
  in_date       TEXT DEFAULT '',
  expire_at     TEXT DEFAULT '',
  updated_at    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS stock_moves (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  no            TEXT DEFAULT '',
  type          TEXT DEFAULT '',
  material_code TEXT DEFAULT '',
  material_name TEXT DEFAULT '',
  warehouse     TEXT DEFAULT '',
  batch         TEXT DEFAULT '',
  qty           REAL DEFAULT 0,
  cost          REAL DEFAULT 0,
  ref_no        TEXT DEFAULT '',
  reason        TEXT DEFAULT '',
  operator      TEXT DEFAULT '',
  created_at    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS transfers (
  no         TEXT PRIMARY KEY,
  from_wh    TEXT DEFAULT '',
  to_wh      TEXT DEFAULT '',
  status     TEXT DEFAULT '草稿',
  applicant  TEXT DEFAULT '',
  approver   TEXT DEFAULT '',
  remark     TEXT DEFAULT '',
  created_at TEXT DEFAULT '',
  updated_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS transfer_items (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  transfer_no   TEXT NOT NULL,
  material_code TEXT DEFAULT '',
  material_name TEXT DEFAULT '',
  unit          TEXT DEFAULT '个',
  batch         TEXT DEFAULT '',
  qty           REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS stocktakes (
  no          TEXT PRIMARY KEY,
  warehouse   TEXT DEFAULT '',
  status      TEXT DEFAULT '草稿',
  applicant   TEXT DEFAULT '',
  approver    TEXT DEFAULT '',
  diff_amount REAL DEFAULT 0,
  remark      TEXT DEFAULT '',
  created_at  TEXT DEFAULT '',
  updated_at  TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS stocktake_items (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  stocktake_no  TEXT NOT NULL,
  material_code TEXT DEFAULT '',
  material_name TEXT DEFAULT '',
  unit          TEXT DEFAULT '个',
  batch         TEXT DEFAULT '',
  book_qty      REAL DEFAULT 0,
  real_qty      REAL DEFAULT 0,
  diff_qty      REAL DEFAULT 0,
  cost          REAL DEFAULT 0
);

-- ---------------------------------------------------------------- 集成
CREATE TABLE IF NOT EXISTS change_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  obj_type   TEXT DEFAULT '',
  obj_no     TEXT DEFAULT '',
  op         TEXT DEFAULT 'upsert',
  actor      TEXT DEFAULT '',
  payload    TEXT DEFAULT '',
  changed_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS api_keys (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  name         TEXT NOT NULL,
  key_prefix   TEXT DEFAULT '',
  key_hash     TEXT NOT NULL,
  scope        TEXT DEFAULT 'read',
  owner        TEXT DEFAULT '',
  status       TEXT DEFAULT '启用',
  expires_at   TEXT DEFAULT '',
  last_used_at TEXT DEFAULT '',
  created_at   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS webhooks (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT DEFAULT '',
  url         TEXT NOT NULL,
  events      TEXT DEFAULT '*',
  secret      TEXT DEFAULT '',
  status      TEXT DEFAULT '启用',
  last_status TEXT DEFAULT '',
  last_at     TEXT DEFAULT '',
  fail_count  INTEGER DEFAULT 0,
  created_at  TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS webhook_deliveries (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  webhook_id   INTEGER DEFAULT 0,
  event        TEXT DEFAULT '',
  payload      TEXT DEFAULT '',
  signature    TEXT DEFAULT '',
  status       TEXT DEFAULT '待投递',
  attempts     INTEGER DEFAULT 0,
  http_code    INTEGER DEFAULT 0,
  error        TEXT DEFAULT '',
  next_at      TEXT DEFAULT '',
  created_at   TEXT DEFAULT '',
  delivered_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS idem_keys (
  key        TEXT PRIMARY KEY,
  path       TEXT DEFAULT '',
  response   TEXT DEFAULT '',
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ext_mappings (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  obj_type    TEXT DEFAULT '',
  local_no    TEXT DEFAULT '',
  external_id TEXT DEFAULT '',
  system      TEXT DEFAULT '',
  created_at  TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_po_supplier   ON purchase_orders(supplier_code);
CREATE INDEX IF NOT EXISTS idx_po_status     ON purchase_orders(status);
CREATE INDEX IF NOT EXISTS idx_req_status    ON requisitions(status);
CREATE INDEX IF NOT EXISTS idx_receipt_po    ON receipts(po_no);
CREATE INDEX IF NOT EXISTS idx_stock_mat     ON stock(material_code);
CREATE INDEX IF NOT EXISTS idx_moves_mat     ON stock_moves(material_code);
CREATE INDEX IF NOT EXISTS idx_change_obj    ON change_log(obj_type);
CREATE INDEX IF NOT EXISTS idx_invoice_po    ON invoices(po_no);
"""


def sha256(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


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
    cn.execute("INSERT INTO op_logs(username, action, detail, created_at) VALUES(?,?,?,?)",
               (username, action, detail, __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")))


def init_db():
    d = os.path.dirname(DB_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
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

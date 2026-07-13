import os
import psycopg2
import psycopg2.extras
import urllib.parse
import uuid
import json
import time
import hmac
import hashlib
import base64
import urllib.request
from datetime import datetime, date
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.environ.get('UPLOAD_DIR', os.path.join(BASE_DIR, 'static', 'uploads'))
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ============================================================
# Supported Currencies
# ============================================================

CURRENCIES = {
    'IDR': {'name': '印尼盾', 'symbol': 'Rp'},
    'THB': {'name': '泰铢', 'symbol': '\u0e3f'},
    'VND': {'name': '越南盾', 'symbol': '\u20ab'},
    'MYR': {'name': '马来西亚令吉', 'symbol': 'RM'},
    'PHP': {'name': '菲律宾比索', 'symbol': '\u20b1'},
    'SGD': {'name': '新加坡元', 'symbol': 'S$'},
    'BRL': {'name': '巴西雷亚尔', 'symbol': 'R$'},
    'MXN': {'name': '墨西哥比索', 'symbol': '$'},
    'COP': {'name': '哥伦比亚比索', 'symbol': 'Col$'},
    'CLP': {'name': '智利比索', 'symbol': '$'},
    'USD': {'name': '美元', 'symbol': '$'},
    'CNY': {'name': '人民币', 'symbol': '\u00a5'},
    'EUR': {'name': '欧元', 'symbol': '\u20ac'},
    'JPY': {'name': '日元', 'symbol': '\u00a5'},
    'KRW': {'name': '韩元', 'symbol': '\u20a9'},
    'GBP': {'name': '英镑', 'symbol': '\u00a3'},
    'AUD': {'name': '澳元', 'symbol': 'A$'},
    'TRY': {'name': '土耳其里拉', 'symbol': '\u20ba'},
    'PLN': {'name': '波兰兹罗提', 'symbol': 'zl'},
    'INR': {'name': '印度卢比', 'symbol': '\u20b9'},
}


# ============================================================
# Database (PostgreSQL via Supabase)
# ============================================================

def _build_db_url():
    """Build DATABASE_URL from individual env vars if not set directly."""
    url = os.environ.get('DATABASE_URL')
    if url:
        return url
    host = os.environ.get('DB_HOST', '')
    port = os.environ.get('DB_PORT', '5432')
    dbname = os.environ.get('DB_NAME', 'postgres')
    user = os.environ.get('DB_USER', 'postgres')
    password = os.environ.get('DB_PASSWORD', '')
    if host and password:
        return f"postgresql://{user}:{urllib.parse.quote(password)}@{host}:{port}/{dbname}"
    return None

DATABASE_URL = _build_db_url()


class DB:
    """Wrapper around psycopg2 connection for sqlite3-compatible API."""
    def __init__(self, conn):
        self.conn = conn
        self.cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, sql, params=None):
        # Auto-convert sqlite3 ? placeholders to psycopg2 %s
        sql = sql.replace('?', '%s')
        self.cur.execute(sql, params)
        return self.cur

    def executescript(self, script):
        for stmt in script.split(';'):
            stmt = stmt.strip()
            if stmt:
                self.cur.execute(stmt)

    def commit(self):
        self.conn.commit()

    def close(self):
        self.cur.close()
        self.conn.close()


def get_db():
    if not DATABASE_URL:
        raise RuntimeError('DATABASE_URL or DB_HOST/DB_PASSWORD env var not set')
    conn = psycopg2.connect(DATABASE_URL)
    return DB(conn)


def init_db():
    db = get_db()
    statements = [
        """CREATE TABLE IF NOT EXISTS evaluation_expense_ledger (
            id SERIAL PRIMARY KEY,
            customer_name TEXT NOT NULL,
            payment_item TEXT NOT NULL DEFAULT 'FO-PLAN',
            order_fee DOUBLE PRECISION NOT NULL DEFAULT 0,
            commission DOUBLE PRECISION NOT NULL DEFAULT 0,
            total_cost DOUBLE PRECISION GENERATED ALWAYS AS (order_fee + commission) STORED,
            customer_paid DOUBLE PRECISION NOT NULL DEFAULT 0,
            customer_unpaid DOUBLE PRECISION GENERATED ALWAYS AS (order_fee + commission - customer_paid) STORED,
            collection_date TEXT,
            customer_proof_url TEXT,
            ar_status TEXT NOT NULL DEFAULT 'pending',
            product_paid DOUBLE PRECISION NOT NULL DEFAULT 0,
            product_payment_time TEXT,
            product_proof_url TEXT,
            product_ap_status TEXT NOT NULL DEFAULT 'pending',
            product_payment_currency TEXT,
            commission_paid DOUBLE PRECISION NOT NULL DEFAULT 0,
            commission_payment_time TEXT,
            commission_proof_url TEXT,
            commission_ap_status TEXT NOT NULL DEFAULT 'pending',
            commission_payment_currency TEXT,
            order_details TEXT,
            fo_paid DOUBLE PRECISION NOT NULL DEFAULT 0,
            fo_unpaid DOUBLE PRECISION GENERATED ALWAYS AS (order_fee + commission - fo_paid) STORED,
            fo_payment_time TEXT,
            fo_proof_url TEXT,
            ap_status TEXT NOT NULL DEFAULT 'pending',
            reconciliation_status TEXT NOT NULL DEFAULT 'open',
            currency TEXT NOT NULL DEFAULT 'IDR',
            exchange_rate DOUBLE PRECISION NOT NULL DEFAULT 0.000460,
            total_cost_cny DOUBLE PRECISION GENERATED ALWAYS AS ((order_fee + commission) * exchange_rate) STORED,
            remark TEXT,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            created_by TEXT NOT NULL DEFAULT 'admin',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS audit_log (
            id SERIAL PRIMARY KEY,
            table_name TEXT NOT NULL,
            record_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            operator_name TEXT NOT NULL DEFAULT 'admin',
            operated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS exchange_rate (
            id SERIAL PRIMARY KEY,
            from_currency TEXT NOT NULL,
            to_currency TEXT NOT NULL,
            rate DOUBLE PRECISION NOT NULL,
            rate_date TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(from_currency, to_currency, rate_date)
        )""",
        """CREATE TABLE IF NOT EXISTS sys_config (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS idx_ledger_customer ON evaluation_expense_ledger(customer_name)",
        "CREATE INDEX IF NOT EXISTS idx_ledger_ar_status ON evaluation_expense_ledger(ar_status)",
        "CREATE INDEX IF NOT EXISTS idx_ledger_ap_status ON evaluation_expense_ledger(ap_status)",
        "CREATE INDEX IF NOT EXISTS idx_ledger_currency ON evaluation_expense_ledger(currency)",
        "CREATE INDEX IF NOT EXISTS idx_ledger_created ON evaluation_expense_ledger(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_audit_record ON audit_log(table_name, record_id)",
    ]
    for stmt in statements:
        db.execute(stmt)

    # Insert default exchange rates (to CNY) if not exist
    default_rates = [
        ('IDR', 'CNY', 0.000460), ('CNY', 'IDR', 2173.9130),
        ('IDR', 'USD', 0.0000640), ('USD', 'IDR', 15625.000),
        ('THB', 'CNY', 0.1990), ('CNY', 'THB', 5.0251),
        ('VND', 'CNY', 0.000294), ('CNY', 'VND', 3401.361),
        ('MYR', 'CNY', 1.6230), ('CNY', 'MYR', 0.6162),
        ('PHP', 'CNY', 0.1265), ('CNY', 'PHP', 7.9051),
        ('SGD', 'CNY', 5.3500), ('CNY', 'SGD', 0.1869),
        ('BRL', 'CNY', 1.2800), ('CNY', 'BRL', 0.7813),
        ('MXN', 'CNY', 0.3680), ('CNY', 'MXN', 2.7174),
        ('COP', 'CNY', 0.00176), ('CNY', 'COP', 568.182),
        ('CLP', 'CNY', 0.00752), ('CNY', 'CLP', 132.979),
        ('USD', 'CNY', 7.2500), ('CNY', 'USD', 0.1379),
        ('EUR', 'CNY', 7.8500), ('CNY', 'EUR', 0.1274),
        ('JPY', 'CNY', 0.0450), ('CNY', 'JPY', 22.222),
        ('KRW', 'CNY', 0.00525), ('CNY', 'KRW', 190.476),
        ('GBP', 'CNY', 9.2000), ('CNY', 'GBP', 0.1087),
        ('AUD', 'CNY', 4.7800), ('CNY', 'AUD', 0.2092),
        ('TRY', 'CNY', 0.2120), ('CNY', 'TRY', 4.7170),
        ('PLN', 'CNY', 1.8300), ('CNY', 'PLN', 0.5464),
        ('INR', 'CNY', 0.0863), ('CNY', 'INR', 11.587),
    ]
    today = date.today().isoformat()
    for frm, to, rate in default_rates:
        db.execute(
            'INSERT INTO exchange_rate (from_currency, to_currency, rate, rate_date, source) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
            (frm, to, rate, today, 'manual')
        )
    # Default Feishu config
    db.execute("INSERT INTO sys_config (key, value) VALUES (%s, %s) ON CONFLICT DO NOTHING", ('feishu_webhook_url', ''))
    db.execute("INSERT INTO sys_config (key, value) VALUES (%s, %s) ON CONFLICT DO NOTHING", ('feishu_webhook_secret', ''))
    db.execute("INSERT INTO sys_config (key, value) VALUES (%s, %s) ON CONFLICT DO NOTHING", ('feishu_enabled', 'false'))
    db.commit()
    db.close()


def migrate_db():
    """Add new columns for split FO payment and multi-currency."""
    db = get_db()
    cols = db.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'evaluation_expense_ledger'"
    ).fetchall()
    col_names = [c['column_name'] for c in cols]

    new_cols = [
        ('product_paid', 'DOUBLE PRECISION NOT NULL DEFAULT 0'),
        ('product_payment_time', 'TEXT'),
        ('product_proof_url', 'TEXT'),
        ('product_ap_status', "TEXT NOT NULL DEFAULT 'pending'"),
        ('product_payment_currency', 'TEXT'),
        ('commission_paid', 'DOUBLE PRECISION NOT NULL DEFAULT 0'),
        ('commission_payment_time', 'TEXT'),
        ('commission_proof_url', 'TEXT'),
        ('commission_ap_status', "TEXT NOT NULL DEFAULT 'pending'"),
        ('commission_payment_currency', 'TEXT'),
        ('order_details', 'TEXT'),
    ]

    for col_name, col_def in new_cols:
        if col_name not in col_names:
            db.execute(f'ALTER TABLE evaluation_expense_ledger ADD COLUMN {col_name} {col_def}')
            print(f"  [migration] Added column: {col_name}")

    db.commit()
    db.close()


def row_to_dict(row):
    return dict(row) if row else None


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


def fmt_amount(val):
    if val is None:
        return '0'
    return f'{float(val):,.2f}'


def serialize_order_details(val):
    """order_details is stored in a TEXT column; keep it as valid JSON."""
    if val is None:
        return None
    if isinstance(val, (list, dict)):
        return json.dumps(val, ensure_ascii=False)
    return val


def parse_order_details(val):
    """Parse order_details TEXT back into a Python list (or [])."""
    if val is None:
        return []
    if isinstance(val, (list, dict)):
        return val
    try:
        parsed = json.loads(val)
        return parsed if isinstance(parsed, list) else [parsed]
    except Exception:
        return []


def enrich_ledger(row):
    """Add computed fields for split FO payment and currency info."""
    d = row_to_dict(row)
    if not d:
        return None
    d['order_details'] = parse_order_details(d.get('order_details'))
    d['product_unpaid'] = round(d['order_fee'] - d['product_paid'], 2)
    d['commission_unpaid'] = round(d['commission'] - d['commission_paid'], 2)
    d['fo_paid_total'] = round(d['product_paid'] + d['commission_paid'], 2)
    d['fo_unpaid_total'] = round(d['product_unpaid'] + d['commission_unpaid'], 2)
    cur = d.get('currency', 'IDR')
    d['currency_symbol'] = CURRENCIES.get(cur, {}).get('symbol', '')
    d['currency_name'] = CURRENCIES.get(cur, {}).get('name', cur)
    d['product_payment_currency'] = d.get('product_payment_currency') or cur
    d['commission_payment_currency'] = d.get('commission_payment_currency') or cur
    return d


def recalc_status(db, ledger_id):
    """Recalculate AR/AP/reconciliation status based on payment amounts."""
    ledger = db.execute(
        'SELECT * FROM evaluation_expense_ledger WHERE id = %s', (ledger_id,)
    ).fetchone()
    if not ledger:
        return
    ledger = dict(ledger)
    total = ledger['order_fee'] + ledger['commission']

    if ledger['customer_paid'] <= 0:
        ar = 'pending'
    elif ledger['customer_paid'] < total:
        ar = 'partial'
    else:
        ar = 'settled'

    if ledger['product_paid'] <= 0:
        product_ap = 'pending'
    elif ledger['product_paid'] < ledger['order_fee']:
        product_ap = 'partial'
    else:
        product_ap = 'settled'

    if ledger['commission_paid'] <= 0:
        commission_ap = 'pending'
    elif ledger['commission_paid'] < ledger['commission']:
        commission_ap = 'partial'
    else:
        commission_ap = 'settled'

    if product_ap == 'settled' and commission_ap == 'settled':
        ap = 'settled'
    elif product_ap == 'pending' and commission_ap == 'pending':
        ap = 'pending'
    else:
        ap = 'partial'

    if ar == 'settled' and ap == 'settled':
        recon = 'completed'
    elif ar != 'pending' or ap != 'pending':
        recon = 'in_progress'
    else:
        recon = 'open'

    db.execute(
        'UPDATE evaluation_expense_ledger SET ar_status=%s, ap_status=%s, product_ap_status=%s, commission_ap_status=%s, reconciliation_status=%s, updated_at=%s WHERE id=%s',
        (ar, ap, product_ap, commission_ap, recon, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ledger_id)
    )


def log_audit(db, table_name, record_id, field_name, old_val, new_val, operator='admin'):
    if str(old_val) == str(new_val):
        return
    db.execute(
        'INSERT INTO audit_log (table_name, record_id, field_name, old_value, new_value, operator_name) VALUES (%s,%s,%s,%s,%s,%s)',
        (table_name, record_id, field_name, str(old_val), str(new_val), operator)
    )


# ============================================================
# Feishu (Lark) Integration
# ============================================================

def get_sys_config(db, key):
    row = db.execute('SELECT value FROM sys_config WHERE key = %s', (key,)).fetchone()
    return row['value'] if row else None


def set_sys_config(db, key, value):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    db.execute(
        'INSERT INTO sys_config (key, value, updated_at) VALUES (%s, %s, %s) '
        'ON CONFLICT(key) DO UPDATE SET value = %s, updated_at = %s',
        (key, str(value), now, str(value), now)
    )


def _gen_feishu_sign(timestamp, secret):
    string_to_sign = f'{timestamp}\n{secret}'
    hmac_code = hmac.new(string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
    return base64.b64encode(hmac_code).decode('utf-8')


def send_feishu_message(webhook_url, secret, title, content, template='blue'):
    if not webhook_url:
        return False, 'Webhook URL is empty'
    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content}}
            ]
        }
    }
    if secret:
        timestamp = str(int(time.time()))
        payload['timestamp'] = timestamp
        payload['sign'] = _gen_feishu_sign(timestamp, secret)
    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode())
        if result.get('code', -1) == 0:
            return True, 'OK'
        else:
            return False, result.get('msg', 'Unknown error')
    except Exception as e:
        return False, str(e)


def notify_feishu(db, event_type, ledger, amount=None):
    webhook_url = get_sys_config(db, 'feishu_webhook_url')
    enabled = get_sys_config(db, 'feishu_enabled')
    secret = get_sys_config(db, 'feishu_webhook_secret') or ''
    if not webhook_url or not enabled or enabled == 'false':
        return
    cur = ledger.get('currency', 'IDR')
    sym = CURRENCIES.get(cur, {}).get('symbol', '')
    amt_str = f'{fmt_amount(amount)} {sym}' if amount is not None else ''
    events = {
        'create': {
            'title': 'New Ledger Created',
            'template': 'blue',
            'content': (
                f'**Customer**: {ledger["customer_name"]}\n'
                f'**Item**: {ledger.get("payment_item", "FO-PLAN")}\n'
                f'**Currency**: {cur} ({CURRENCIES.get(cur, {}).get("name", cur)})\n'
                f'**Order Fee**: {fmt_amount(ledger.get("order_fee", 0))} {sym}\n'
                f'**Commission**: {fmt_amount(ledger.get("commission", 0))} {sym}\n'
                f'**Total**: {fmt_amount(ledger.get("order_fee", 0) + ledger.get("commission", 0))} {sym}'
            )
        },
        'customer_payment': {
            'title': 'Customer Payment Received',
            'template': 'green',
            'content': (
                f'**Customer**: {ledger["customer_name"]}\n'
                f'**Amount**: {amt_str}\n'
                f'**AR Status**: {ledger.get("ar_status", "pending")}'
            )
        },
        'product_payment': {
            'title': 'Product Payment Sent',
            'template': 'orange',
            'content': (
                f'**Customer**: {ledger["customer_name"]}\n'
                f'**Amount**: {amt_str}\n'
                f'**Product AP Status**: {ledger.get("product_ap_status", "pending")}'
            )
        },
        'commission_payment': {
            'title': 'Commission Payment Sent',
            'template': 'purple',
            'content': (
                f'**Customer**: {ledger["customer_name"]}\n'
                f'**Amount**: {amt_str}\n'
                f'**Commission AP Status**: {ledger.get("commission_ap_status", "pending")}'
            )
        }
    }
    cfg = events.get(event_type)
    if cfg:
        send_feishu_message(webhook_url, secret, cfg['title'], cfg['content'], cfg['template'])


def push_summary_to_feishu(db):
    webhook_url = get_sys_config(db, 'feishu_webhook_url')
    secret = get_sys_config(db, 'feishu_webhook_secret') or ''
    if not webhook_url:
        return False, 'Webhook URL is empty'
    rows = db.execute('SELECT * FROM evaluation_expense_ledger WHERE is_deleted = 0').fetchall()
    rows = [dict(r) for r in rows]
    total_receivable = sum(r['customer_unpaid'] for r in rows)
    total_payable = sum((r['order_fee'] - r['product_paid']) + (r['commission'] - r['commission_paid']) for r in rows)
    total_receivable_cny = sum(r['customer_unpaid'] * r['exchange_rate'] for r in rows)
    total_payable_cny = sum(((r['order_fee'] - r['product_paid']) + (r['commission'] - r['commission_paid'])) * r['exchange_rate'] for r in rows)
    currency_map = {}
    for r in rows:
        cur = r['currency']
        if cur not in currency_map:
            currency_map[cur] = {'count': 0, 'receivable': 0, 'payable': 0}
        currency_map[cur]['count'] += 1
        currency_map[cur]['receivable'] += r['customer_unpaid']
        currency_map[cur]['payable'] += (r['order_fee'] - r['product_paid']) + (r['commission'] - r['commission_paid'])
    cur_lines = []
    for cur, info in sorted(currency_map.items()):
        sym = CURRENCIES.get(cur, {}).get('symbol', '')
        cur_lines.append(f'{cur}: {info["count"]} records | AR {fmt_amount(info["receivable"])} {sym} | AP {fmt_amount(info["payable"])} {sym}')
    content = (
        f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}\n'
        f'**Total Records**: {len(rows)}\n\n'
        f'**Total Receivable**: {fmt_amount(total_receivable)} (various currencies)\n'
        f'**Total Payable**: {fmt_amount(total_payable)} (various currencies)\n'
        f'**Receivable (CNY equiv)**: \u00a5{fmt_amount(total_receivable_cny)}\n'
        f'**Payable (CNY equiv)**: \u00a5{fmt_amount(total_payable_cny)}\n\n'
        f'**By Currency**:\n' + '\n'.join(cur_lines)
    )
    return send_feishu_message(webhook_url, secret, 'Financial Reconciliation Summary', content, 'blue')


# ============================================================
# API: Ledgers
# ============================================================

@app.route('/api/v1/ledgers', methods=['GET'])
def list_ledgers():
    db = get_db()
    customer = request.args.get('customer_name', '').strip()
    ar_status = request.args.get('ar_status', '')
    ap_status = request.args.get('ap_status', '')
    recon_status = request.args.get('reconciliation_status', '')
    currency = request.args.get('currency', '')
    sql = 'SELECT * FROM evaluation_expense_ledger WHERE is_deleted = 0'
    params = []
    if customer:
        sql += ' AND customer_name LIKE %s'
        params.append(f'%{customer}%')
    if ar_status:
        sql += ' AND ar_status = %s'
        params.append(ar_status)
    if ap_status:
        sql += ' AND ap_status = %s'
        params.append(ap_status)
    if recon_status:
        sql += ' AND reconciliation_status = %s'
        params.append(recon_status)
    if currency:
        sql += ' AND currency = %s'
        params.append(currency)
    sql += ' ORDER BY created_at DESC'
    rows = db.execute(sql, params).fetchall()
    db.close()
    return jsonify([enrich_ledger(r) for r in rows])


@app.route('/api/v1/ledgers', methods=['POST'])
def create_ledger():
    data = request.json
    db = get_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cur = db.execute(
        """INSERT INTO evaluation_expense_ledger
           (customer_name, payment_item, order_fee, commission, customer_paid,
            collection_date, customer_proof_url,
            product_paid, product_payment_time, product_proof_url, product_payment_currency,
            commission_paid, commission_payment_time, commission_proof_url,             commission_payment_currency,
            order_details,
            fo_paid, fo_payment_time, fo_proof_url,
            currency, exchange_rate, remark, created_by, updated_at, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id""",
        (
            data.get('customer_name', ''),
            data.get('payment_item', 'FO-PLAN'),
            float(data.get('order_fee', 0)),
            float(data.get('commission', 0)),
            float(data.get('customer_paid', 0)),
            data.get('collection_date'),
            data.get('customer_proof_url'),
            float(data.get('product_paid', 0)),
            data.get('product_payment_time'),
            data.get('product_proof_url'),
            data.get('product_payment_currency'),
            float(data.get('commission_paid', 0)),
            data.get('commission_payment_time'),
            data.get('commission_proof_url'),
            data.get('commission_payment_currency'),
            serialize_order_details(data.get('order_details')),
            float(data.get('fo_paid', 0)),
            data.get('fo_payment_time'),
            data.get('fo_proof_url'),
            data.get('currency', 'IDR'),
            float(data.get('exchange_rate', 0.000460)),
            data.get('remark', ''),
            'admin',
            now,
            now,
        )
    )
    ledger_id = cur.fetchone()['id']
    recalc_status(db, ledger_id)
    db.commit()
    row = db.execute('SELECT * FROM evaluation_expense_ledger WHERE id = %s', (ledger_id,)).fetchone()
    enriched = enrich_ledger(row)
    notify_feishu(db, 'create', enriched)
    db.commit()
    db.close()
    return jsonify(enriched), 201


@app.route('/api/v1/ledgers/<int:ledger_id>', methods=['GET'])
def get_ledger(ledger_id):
    db = get_db()
    row = db.execute('SELECT * FROM evaluation_expense_ledger WHERE id = %s AND is_deleted = 0', (ledger_id,)).fetchone()
    db.close()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(enrich_ledger(row))


@app.route('/api/v1/ledgers/<int:ledger_id>', methods=['PUT'])
def update_ledger(ledger_id):
    data = request.json
    db = get_db()
    old = db.execute('SELECT * FROM evaluation_expense_ledger WHERE id = %s AND is_deleted = 0', (ledger_id,)).fetchone()
    if not old:
        db.close()
        return jsonify({'error': 'Not found'}), 404
    old = dict(old)
    fields = [
        'customer_name', 'payment_item', 'order_fee', 'commission',
        'customer_paid', 'collection_date', 'customer_proof_url',
        'product_paid', 'product_payment_time', 'product_proof_url', 'product_payment_currency',
        'commission_paid', 'commission_payment_time', 'commission_proof_url', 'commission_payment_currency',
        'order_details',
        'fo_paid', 'fo_payment_time', 'fo_proof_url',
        'currency', 'exchange_rate', 'remark'
    ]
    updates = []
    params = []
    for f in fields:
        if f in data:
            old_val = old.get(f)
            new_val = serialize_order_details(data[f]) if f == 'order_details' else data[f]
            log_audit(db, 'evaluation_expense_ledger', ledger_id, f, old_val, new_val)
            updates.append(f'{f} = %s')
            params.append(new_val)
    if updates:
        updates.append("updated_at = %s")
        params.append(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        params.append(ledger_id)
        db.execute(f"UPDATE evaluation_expense_ledger SET {', '.join(updates)} WHERE id = %s", params)
    recalc_status(db, ledger_id)
    db.commit()
    row = db.execute('SELECT * FROM evaluation_expense_ledger WHERE id = %s', (ledger_id,)).fetchone()
    db.close()
    return jsonify(enrich_ledger(row))


@app.route('/api/v1/ledgers/<int:ledger_id>', methods=['DELETE'])
def delete_ledger(ledger_id):
    db = get_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    db.execute(
        'UPDATE evaluation_expense_ledger SET is_deleted = 1, deleted_at = %s, updated_at = %s WHERE id = %s',
        (now, now, ledger_id)
    )
    log_audit(db, 'evaluation_expense_ledger', ledger_id, 'is_deleted', 0, 1)
    db.commit()
    db.close()
    return jsonify({'message': 'deleted'})


# ============================================================
# API: Customer Payment
# ============================================================

@app.route('/api/v1/ledgers/<int:ledger_id>/customer-payment', methods=['POST', 'PUT'])
def customer_payment(ledger_id):
    data = request.json
    db = get_db()
    old = db.execute('SELECT * FROM evaluation_expense_ledger WHERE id = %s AND is_deleted = 0', (ledger_id,)).fetchone()
    if not old:
        db.close()
        return jsonify({'error': 'Not found'}), 404
    old = dict(old)
    is_edit = request.method == 'PUT'
    if is_edit:
        new_paid = float(data.get('amount', old['customer_paid']))
    else:
        new_paid = old['customer_paid'] + float(data.get('amount', 0))
    total = old['order_fee'] + old['commission']
    if new_paid > total:
        db.close()
        return jsonify({'error': 'Payment exceeds total cost', 'total': total, 'current_paid': old['customer_paid']}), 422
    log_audit(db, 'evaluation_expense_ledger', ledger_id, 'customer_paid', old['customer_paid'], new_paid)
    if data.get('collection_date'):
        log_audit(db, 'evaluation_expense_ledger', ledger_id, 'collection_date', old['collection_date'], data['collection_date'])
    if data.get('proof_url') is not None:
        log_audit(db, 'evaluation_expense_ledger', ledger_id, 'customer_proof_url', old['customer_proof_url'], data['proof_url'])
    db.execute(
        'UPDATE evaluation_expense_ledger SET customer_paid = %s, collection_date = %s, customer_proof_url = %s, updated_at = %s WHERE id = %s',
        (new_paid, data.get('collection_date', old['collection_date']), data.get('proof_url', old['customer_proof_url']),
         datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ledger_id)
    )
    recalc_status(db, ledger_id)
    db.commit()
    row = db.execute('SELECT * FROM evaluation_expense_ledger WHERE id = %s', (ledger_id,)).fetchone()
    enriched = enrich_ledger(row)
    if not is_edit:
        notify_feishu(db, 'customer_payment', enriched, float(data.get('amount', 0)))
    db.commit()
    db.close()
    return jsonify(enriched)


# ============================================================
# API: Product Value Payment
# ============================================================

@app.route('/api/v1/ledgers/<int:ledger_id>/product-payment', methods=['POST', 'PUT'])
def product_payment(ledger_id):
    data = request.json
    db = get_db()
    old = db.execute('SELECT * FROM evaluation_expense_ledger WHERE id = %s AND is_deleted = 0', (ledger_id,)).fetchone()
    if not old:
        db.close()
        return jsonify({'error': 'Not found'}), 404
    old = dict(old)
    is_edit = request.method == 'PUT'
    if not is_edit and old['ar_status'] == 'pending':
        db.close()
        return jsonify({'error': 'Cannot pay before customer pays. AR status is still pending.'}), 409
    if is_edit:
        new_paid = float(data.get('amount', old['product_paid']))
    else:
        new_paid = old['product_paid'] + float(data.get('amount', 0))
    if new_paid > old['order_fee']:
        db.close()
        return jsonify({'error': 'Product payment exceeds order fee', 'order_fee': old['order_fee'], 'current_paid': old['product_paid']}), 422
    log_audit(db, 'evaluation_expense_ledger', ledger_id, 'product_paid', old['product_paid'], new_paid)
    if data.get('payment_time'):
        log_audit(db, 'evaluation_expense_ledger', ledger_id, 'product_payment_time', old.get('product_payment_time'), data['payment_time'])
    if data.get('proof_url') is not None:
        log_audit(db, 'evaluation_expense_ledger', ledger_id, 'product_proof_url', old.get('product_proof_url'), data['proof_url'])
    if data.get('payment_currency'):
        log_audit(db, 'evaluation_expense_ledger', ledger_id, 'product_payment_currency', old.get('product_payment_currency'), data['payment_currency'])
    extra_set = ''
    extra_params = []
    if data.get('order_details') is not None:
        log_audit(db, 'evaluation_expense_ledger', ledger_id, 'order_details', old.get('order_details'), data['order_details'])
        extra_set = ', order_details = %s'
        extra_params = [serialize_order_details(data['order_details'])]
    db.execute(
        'UPDATE evaluation_expense_ledger SET product_paid = %s, product_payment_time = %s, product_proof_url = %s, product_payment_currency = %s' + extra_set + ', updated_at = %s WHERE id = %s',
        (new_paid, data.get('payment_time'), data.get('proof_url'), data.get('payment_currency'), *extra_params,
         datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ledger_id)
    )
    recalc_status(db, ledger_id)
    db.commit()
    row = db.execute('SELECT * FROM evaluation_expense_ledger WHERE id = %s', (ledger_id,)).fetchone()
    enriched = enrich_ledger(row)
    if not is_edit:
        notify_feishu(db, 'product_payment', enriched, float(data.get('amount', 0)))
    db.commit()
    db.close()
    return jsonify(enriched)


# ============================================================
# API: Commission Payment
# ============================================================

@app.route('/api/v1/ledgers/<int:ledger_id>/commission-payment', methods=['POST', 'PUT'])
def commission_payment(ledger_id):
    data = request.json
    db = get_db()
    old = db.execute('SELECT * FROM evaluation_expense_ledger WHERE id = %s AND is_deleted = 0', (ledger_id,)).fetchone()
    if not old:
        db.close()
        return jsonify({'error': 'Not found'}), 404
    old = dict(old)
    is_edit = request.method == 'PUT'
    if not is_edit and old['ar_status'] == 'pending':
        db.close()
        return jsonify({'error': 'Cannot pay before customer pays. AR status is still pending.'}), 409
    if is_edit:
        new_paid = float(data.get('amount', old['commission_paid']))
    else:
        new_paid = old['commission_paid'] + float(data.get('amount', 0))
    if new_paid > old['commission']:
        db.close()
        return jsonify({'error': 'Commission payment exceeds commission amount', 'commission': old['commission'], 'current_paid': old['commission_paid']}), 422
    log_audit(db, 'evaluation_expense_ledger', ledger_id, 'commission_paid', old['commission_paid'], new_paid)
    if data.get('payment_time'):
        log_audit(db, 'evaluation_expense_ledger', ledger_id, 'commission_payment_time', old.get('commission_payment_time'), data['payment_time'])
    if data.get('proof_url') is not None:
        log_audit(db, 'evaluation_expense_ledger', ledger_id, 'commission_proof_url', old.get('commission_proof_url'), data['proof_url'])
    if data.get('payment_currency'):
        log_audit(db, 'evaluation_expense_ledger', ledger_id, 'commission_payment_currency', old.get('commission_payment_currency'), data['payment_currency'])
    extra_set = ''
    extra_params = []
    if data.get('order_details') is not None:
        log_audit(db, 'evaluation_expense_ledger', ledger_id, 'order_details', old.get('order_details'), data['order_details'])
        extra_set = ', order_details = %s'
        extra_params = [serialize_order_details(data['order_details'])]
    db.execute(
        'UPDATE evaluation_expense_ledger SET commission_paid = %s, commission_payment_time = %s, commission_proof_url = %s, commission_payment_currency = %s' + extra_set + ', updated_at = %s WHERE id = %s',
        (new_paid, data.get('payment_time'), data.get('proof_url'), data.get('payment_currency'), *extra_params,
         datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ledger_id)
    )
    recalc_status(db, ledger_id)
    db.commit()
    row = db.execute('SELECT * FROM evaluation_expense_ledger WHERE id = %s', (ledger_id,)).fetchone()
    enriched = enrich_ledger(row)
    if not is_edit:
        notify_feishu(db, 'commission_payment', enriched, float(data.get('amount', 0)))
    db.commit()
    db.close()
    return jsonify(enriched)


# ============================================================
# API: FO Payment (legacy)
# ============================================================

@app.route('/api/v1/ledgers/<int:ledger_id>/fo-payment', methods=['POST'])
def fo_payment(ledger_id):
    data = request.json
    db = get_db()
    old = db.execute('SELECT * FROM evaluation_expense_ledger WHERE id = %s AND is_deleted = 0', (ledger_id,)).fetchone()
    if not old:
        db.close()
        return jsonify({'error': 'Not found'}), 404
    old = dict(old)
    if old['ar_status'] == 'pending':
        db.close()
        return jsonify({'error': 'Cannot pay FO before customer pays. AR status is still pending.'}), 409
    new_paid = old['fo_paid'] + float(data.get('amount', 0))
    total = old['order_fee'] + old['commission']
    if new_paid > total:
        db.close()
        return jsonify({'error': 'Payment exceeds total cost', 'total': total, 'current_paid': old['fo_paid']}), 422
    log_audit(db, 'evaluation_expense_ledger', ledger_id, 'fo_paid', old['fo_paid'], new_paid)
    if data.get('payment_time'):
        log_audit(db, 'evaluation_expense_ledger', ledger_id, 'fo_payment_time', old.get('fo_payment_time'), data['payment_time'])
    if data.get('proof_url'):
        log_audit(db, 'evaluation_expense_ledger', ledger_id, 'fo_proof_url', old.get('fo_proof_url'), data['proof_url'])
    db.execute(
        'UPDATE evaluation_expense_ledger SET fo_paid = %s, fo_payment_time = %s, fo_proof_url = %s, updated_at = %s WHERE id = %s',
        (new_paid, data.get('payment_time', old['fo_payment_time']), data.get('proof_url', old['fo_proof_url']),
         datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ledger_id)
    )
    recalc_status(db, ledger_id)
    db.commit()
    row = db.execute('SELECT * FROM evaluation_expense_ledger WHERE id = %s', (ledger_id,)).fetchone()
    db.close()
    return jsonify(enrich_ledger(row))


# ============================================================
# API: Attachments
# ============================================================

@app.route('/api/v1/attachments/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
        return jsonify({'error': 'Only image files are allowed'}), 400
    # Store as base64 data URI in database (persistent across restarts)
    file_data = file.read()
    mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.gif': 'image/gif'}
    mime = mime_map.get(ext, 'image/png')
    b64 = base64.b64encode(file_data).decode('utf-8')
    data_uri = f'data:{mime};base64,{b64}'
    return jsonify({
        'url': data_uri,
        'filename': f'{uuid.uuid4().hex[:8]}{ext}',
        'size': len(file_data)
    }), 201


# ============================================================
# API: Dashboard
# ============================================================

@app.route('/api/v1/dashboard/summary', methods=['GET'])
def dashboard_summary():
    db = get_db()
    rows = db.execute('SELECT * FROM evaluation_expense_ledger WHERE is_deleted = 0').fetchall()
    rows = [dict(r) for r in rows]
    total_receivable = sum(r['customer_unpaid'] for r in rows)
    total_payable = sum((r['order_fee'] - r['product_paid']) + (r['commission'] - r['commission_paid']) for r in rows)
    total_receivable_cny = sum(r['customer_unpaid'] * r['exchange_rate'] for r in rows)
    total_payable_cny = sum(((r['order_fee'] - r['product_paid']) + (r['commission'] - r['commission_paid'])) * r['exchange_rate'] for r in rows)
    today = date.today().isoformat()
    overdue_ar = sum(r['customer_unpaid'] for r in rows if r['collection_date'] and r['collection_date'] < today and r['ar_status'] != 'settled')
    ar_counts = {
        'pending': len([r for r in rows if r['ar_status'] == 'pending']),
        'partial': len([r for r in rows if r['ar_status'] == 'partial']),
        'settled': len([r for r in rows if r['ar_status'] == 'settled']),
    }
    ap_counts = {
        'pending': len([r for r in rows if r['ap_status'] == 'pending']),
        'partial': len([r for r in rows if r['ap_status'] == 'partial']),
        'settled': len([r for r in rows if r['ap_status'] == 'settled']),
    }
    product_ap_counts = {
        'pending': len([r for r in rows if r['product_ap_status'] == 'pending']),
        'partial': len([r for r in rows if r['product_ap_status'] == 'partial']),
        'settled': len([r for r in rows if r['product_ap_status'] == 'settled']),
    }
    commission_ap_counts = {
        'pending': len([r for r in rows if r['commission_ap_status'] == 'pending']),
        'partial': len([r for r in rows if r['commission_ap_status'] == 'partial']),
        'settled': len([r for r in rows if r['commission_ap_status'] == 'settled']),
    }
    currency_breakdown = {}
    for r in rows:
        cur = r['currency']
        if cur not in currency_breakdown:
            currency_breakdown[cur] = {
                'count': 0, 'receivable': 0, 'payable': 0,
                'receivable_cny': 0, 'payable_cny': 0,
                'symbol': CURRENCIES.get(cur, {}).get('symbol', ''),
                'name': CURRENCIES.get(cur, {}).get('name', cur),
            }
        currency_breakdown[cur]['count'] += 1
        currency_breakdown[cur]['receivable'] += r['customer_unpaid']
        currency_breakdown[cur]['payable'] += (r['order_fee'] - r['product_paid']) + (r['commission'] - r['commission_paid'])
        currency_breakdown[cur]['receivable_cny'] += r['customer_unpaid'] * r['exchange_rate']
        currency_breakdown[cur]['payable_cny'] += ((r['order_fee'] - r['product_paid']) + (r['commission'] - r['commission_paid'])) * r['exchange_rate']
    db.close()
    return jsonify({
        'total_receivable': round(total_receivable, 2),
        'total_payable': round(total_payable, 2),
        'total_receivable_cny': round(total_receivable_cny, 2),
        'total_payable_cny': round(total_payable_cny, 2),
        'overdue_ar': round(overdue_ar, 2),
        'ar_status_counts': ar_counts,
        'ap_status_counts': ap_counts,
        'product_ap_counts': product_ap_counts,
        'commission_ap_counts': commission_ap_counts,
        'currency_breakdown': currency_breakdown,
        'total_records': len(rows),
    })


# ============================================================
# API: Exchange Rates
# ============================================================

@app.route('/api/v1/rates', methods=['GET'])
def list_rates():
    db = get_db()
    rows = db.execute('SELECT * FROM exchange_rate ORDER BY rate_date DESC').fetchall()
    db.close()
    return jsonify(rows_to_dicts(rows))


@app.route('/api/v1/rates', methods=['POST'])
def add_rate():
    data = request.json
    db = get_db()
    try:
        cur = db.execute(
            'INSERT INTO exchange_rate (from_currency, to_currency, rate, rate_date, source) VALUES (%s,%s,%s,%s,%s) RETURNING id',
            (data['from_currency'], data['to_currency'], float(data['rate']), data['rate_date'], data.get('source', 'manual'))
        )
        rid = cur.fetchone()['id']
        db.commit()
        row = db.execute('SELECT * FROM exchange_rate WHERE id = %s', (rid,)).fetchone()
        db.close()
        return jsonify(row_to_dict(row)), 201
    except psycopg2.IntegrityError:
        db.conn.rollback()
        db.close()
        return jsonify({'error': 'Rate already exists for this currency pair and date'}), 409


@app.route('/api/v1/rates/latest', methods=['GET'])
def get_latest_rate():
    frm = request.args.get('from', '')
    to = request.args.get('to', 'CNY')
    if not frm:
        return jsonify({'error': 'Missing "from" parameter'}), 400
    db = get_db()
    row = db.execute(
        'SELECT * FROM exchange_rate WHERE from_currency = %s AND to_currency = %s ORDER BY rate_date DESC LIMIT 1',
        (frm, to)
    ).fetchone()
    db.close()
    if not row:
        return jsonify({'from': frm, 'to': to, 'rate': None, 'message': 'No rate found'})
    return jsonify(row_to_dict(row))


# ============================================================
# API: Currencies
# ============================================================

@app.route('/api/v1/currencies', methods=['GET'])
def list_currencies():
    return jsonify(CURRENCIES)


# ============================================================
# API: Audit Log
# ============================================================

@app.route('/api/v1/audit/logs', methods=['GET'])
def list_audit_logs():
    db = get_db()
    record_id = request.args.get('record_id', '')
    limit = min(int(request.args.get('limit', 100)), 500)
    sql = 'SELECT * FROM audit_log'
    params = []
    if record_id:
        sql += ' WHERE record_id = %s'
        params.append(record_id)
    sql += ' ORDER BY operated_at DESC LIMIT %s'
    params.append(limit)
    rows = db.execute(sql, params).fetchall()
    db.close()
    return jsonify(rows_to_dicts(rows))


# ============================================================
# API: System Settings (Feishu)
# ============================================================

@app.route('/api/v1/settings', methods=['GET'])
def get_settings():
    db = get_db()
    webhook_url = get_sys_config(db, 'feishu_webhook_url') or ''
    webhook_secret = get_sys_config(db, 'feishu_webhook_secret') or ''
    enabled = get_sys_config(db, 'feishu_enabled') or 'false'
    db.close()
    return jsonify({
        'feishu_webhook_url': webhook_url,
        'feishu_webhook_secret': webhook_secret,
        'feishu_enabled': enabled == 'true',
    })


@app.route('/api/v1/settings', methods=['PUT'])
def update_settings():
    data = request.json
    db = get_db()
    if 'feishu_webhook_url' in data:
        set_sys_config(db, 'feishu_webhook_url', data['feishu_webhook_url'])
    if 'feishu_webhook_secret' in data:
        set_sys_config(db, 'feishu_webhook_secret', data['feishu_webhook_secret'])
    if 'feishu_enabled' in data:
        set_sys_config(db, 'feishu_enabled', 'true' if data['feishu_enabled'] else 'false')
    db.commit()
    db.close()
    return jsonify({'message': 'Settings updated'})


@app.route('/api/v1/settings/feishu/test', methods=['POST'])
def test_feishu():
    db = get_db()
    webhook_url = get_sys_config(db, 'feishu_webhook_url')
    secret = get_sys_config(db, 'feishu_webhook_secret') or ''
    db.close()
    if not webhook_url:
        return jsonify({'error': 'Webhook URL is not configured'}), 400
    ok, msg = send_feishu_message(
        webhook_url, secret,
        'Test Notification',
        'This is a test message from the Financial Reconciliation System.\nIf you see this, the Feishu integration is working correctly!',
        'green'
    )
    if ok:
        return jsonify({'message': 'Test message sent successfully'})
    else:
        return jsonify({'error': f'Failed to send: {msg}'}), 500


@app.route('/api/v1/settings/feishu/push-summary', methods=['POST'])
def push_summary():
    db = get_db()
    ok, msg = push_summary_to_feishu(db)
    db.close()
    if ok:
        return jsonify({'message': 'Summary pushed to Feishu'})
    else:
        return jsonify({'error': f'Failed: {msg}'}), 500


# ============================================================
# Frontend
# ============================================================

@app.route('/')
def index():
    with open(os.path.join(BASE_DIR, 'templates', 'index.html'), 'r', encoding='utf-8') as f:
        return f.read()


@app.route('/static/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# ============================================================
# Initialize database
# ============================================================
init_db()
migrate_db()
print("=" * 50)
print("  Financial Reconciliation System v3.1 (PostgreSQL)")
print("  Database: Supabase PostgreSQL")
print("  Upload dir:", UPLOAD_DIR)
print("  Currencies:", len(CURRENCIES))
print("=" * 50)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"  Server: http://localhost:{port}")
    print("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=False)

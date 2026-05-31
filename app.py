"""
妖姬马来手机号 v3.0 — 马来西亚手机号续费提醒系统
PostgreSQL (Neon) 版
"""

import os
import psycopg2
import psycopg2.extras
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ── 数据库连接 ──
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_z0jm7fRUbYaQ@ep-round-cloud-ao2j0ka6-pooler.c-2.ap-southeast-1.aws.neon.tech/yaoji?sslmode=require"
)

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS numbers (
            id SERIAL PRIMARY KEY,
            phone_number TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT '',
            plan_name TEXT NOT NULL DEFAULT '',
            min_recharge REAL NOT NULL DEFAULT 0,
            deadline DATE NOT NULL,
            grace_days INTEGER NOT NULL DEFAULT 0,
            renewal_date DATE NOT NULL,
            remind_days INTEGER NOT NULL DEFAULT 7,
            is_alive INTEGER NOT NULL DEFAULT 1,
            notes TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS renewal_log (
            id SERIAL PRIMARY KEY,
            number_id INTEGER NOT NULL REFERENCES numbers(id),
            renewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            cost_paid REAL NOT NULL DEFAULT 0,
            new_deadline DATE NOT NULL,
            new_renewal_date DATE NOT NULL,
            notes TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS settlements (
            id SERIAL PRIMARY KEY,
            amount REAL NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

# ── 马来西亚电讯商 ──
PROVIDERS = [
    "CelcomDigi", "Maxis", "U Mobile", "Tune Talk",
    "YES", "unifi Mobile", "XOX", "Tron",
    "RedONE", "其他",
]

# ── 辅助函数 ──
def parse_malaysia_phone(num: str) -> str:
    cleaned = num.strip().replace(" ", "").replace("-", "").replace("+", "")
    if cleaned.startswith("60") and len(cleaned) >= 10:
        return "+" + cleaned
    if cleaned.startswith("0"):
        return "+60" + cleaned[1:]
    if cleaned.startswith("1") and len(cleaned) == 9:
        return "+60" + cleaned
    return num.strip()

def calc_renewal_date(deadline_str: str, grace_days: int) -> str:
    if not deadline_str:
        return ""
    d = datetime.strptime(deadline_str, "%Y-%m-%d").date()
    return (d + timedelta(days=grace_days)).isoformat()

def get_status_info(deadline_str: str, grace_days: int, remind_days: int, is_alive: bool = True):
    if not is_alive:
        return {"status": "📵 死卡", "color": "gray", "days_left": 999, "in_grace": False, "deadline": deadline_str, "renewal_date": "", "grace_end": ""}
    try:
        dl = datetime.strptime(deadline_str, "%Y-%m-%d").date()
        renew = dl + timedelta(days=grace_days)
        today = date.today()
    except:
        return {"status": "未知", "color": "gray", "days_left": 999, "in_grace": False, "deadline": deadline_str, "renewal_date": ""}

    days_to_deadline = (dl - today).days
    days_to_renew = (renew - today).days

    if days_to_renew < 0:
        return {"status": "☠️ 已失效", "color": "gray", "days_left": days_to_renew, "in_grace": False, "deadline": deadline_str, "renewal_date": renew.isoformat(), "grace_end": renew.isoformat()}

    if days_to_renew <= 7:
        c = "red"
    elif days_to_renew <= 14:
        c = "orange"
    else:
        c = "green"

    if days_to_deadline < 0:
        return {"status": f"还剩 {days_to_renew}天续费", "color": c, "days_left": days_to_deadline, "in_grace": True, "grace_days_left": days_to_renew, "deadline": deadline_str, "renewal_date": renew.isoformat(), "grace_end": renew.isoformat()}
    else:
        return {"status": f"续费日剩 {days_to_renew}天", "color": c, "days_left": days_to_renew, "in_grace": False, "deadline": deadline_str, "renewal_date": renew.isoformat(), "grace_end": renew.isoformat()}

# ── 数据库查询辅助 ──
def fetch_all(conn, query, params=None):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query, params or [])
    rows = cur.fetchall()
    cur.close()
    return rows

def fetch_one(conn, query, params=None):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query, params or [])
    row = cur.fetchone()
    cur.close()
    return row

# ── 路由 ──
@app.route("/")
def index():
    conn = get_db()
    show = request.args.get("show", "alive")
    if show == "all":
        rows = fetch_all(conn, "SELECT * FROM numbers WHERE active = 1 ORDER BY is_alive ASC, renewal_date ASC")
    elif show == "dead":
        rows = fetch_all(conn, "SELECT * FROM numbers WHERE active = 1 AND is_alive = 0 ORDER BY renewal_date ASC")
    else:
        rows = fetch_all(conn, "SELECT * FROM numbers WHERE active = 1 AND is_alive = 1 ORDER BY renewal_date ASC")
    conn.close()

    items = []
    for r in rows:
        info = get_status_info(r["deadline"].isoformat() if isinstance(r["deadline"], date) else r["deadline"],
                               r["grace_days"], r["remind_days"], bool(r["is_alive"]))
        items.append({
            "id": r["id"],
            "phone": r["phone_number"],
            "provider": r["provider"],
            "plan": r["plan_name"],
            "min_recharge": r["min_recharge"],
            "deadline": r["deadline"].isoformat() if isinstance(r["deadline"], date) else r["deadline"],
            "grace_days": r["grace_days"],
            "renewal_date": r["renewal_date"].isoformat() if isinstance(r["renewal_date"], date) else r["renewal_date"],
            "remind_days": r["remind_days"],
            "is_alive": bool(r["is_alive"]),
            "notes": r["notes"],
            "status": info["status"],
            "color": info["color"],
            "days_left": info["days_left"],
            "in_grace": info["in_grace"],
            "grace_end": info.get("grace_end", ""),
            "grace_days_left": info.get("grace_days_left", 0),
        })
    color_order = {"gray": 0, "red": 1, "orange": 2, "green": 3}
    items.sort(key=lambda x: (color_order.get(x["color"], 9), x["days_left"]))

    alive_count = sum(1 for i in items if i["is_alive"])
    dead_count = sum(1 for i in items if not i["is_alive"])
    urgent = sum(1 for i in items if i["color"] == "red")

    return render_template("index.html", items=items, providers=PROVIDERS, today=date.today().isoformat(),
                           show=show, alive_count=alive_count, dead_count=dead_count, urgent=urgent)

@app.route("/add", methods=["POST"])
def add():
    phone = request.form.get("phone", "").strip()
    provider = request.form.get("provider", "")
    plan_name = request.form.get("plan_name", "")
    min_recharge = request.form.get("min_recharge", 0)
    deadline = request.form.get("deadline", "")
    grace_days = int(request.form.get("grace_days", 0) or 0)
    remind_days = int(request.form.get("remind_days", 7) or 7)
    is_alive = int(request.form.get("is_alive", 1))
    notes = request.form.get("notes", "")

    if not phone:
        flash("请输入手机号码", "error")
        return redirect(url_for("index"))
    if not deadline:
        flash("请选择截止日期", "error")
        return redirect(url_for("index"))

    phone = parse_malaysia_phone(phone)
    renewal_date = calc_renewal_date(deadline, grace_days)
    tag = "活卡" if is_alive else "死卡"

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO numbers (phone_number, provider, plan_name, min_recharge, deadline, grace_days, renewal_date, remind_days, is_alive, notes) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (phone, provider, plan_name, float(min_recharge or 0), deadline, grace_days, renewal_date, remind_days, is_alive, notes),
    )
    conn.commit()
    cur.close()
    conn.close()

    flash(f"已添加 {phone} · {tag}（续费日：{renewal_date}）", "success")
    return redirect(url_for("index"))

@app.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    conn = get_db()
    if request.method == "POST":
        phone = parse_malaysia_phone(request.form.get("phone", ""))
        provider = request.form.get("provider", "")
        plan_name = request.form.get("plan_name", "")
        min_recharge = request.form.get("min_recharge", 0)
        deadline = request.form.get("deadline", "")
        grace_days = int(request.form.get("grace_days", 0) or 0)
        remind_days = int(request.form.get("remind_days", 7) or 7)
        is_alive = int(request.form.get("is_alive", 1))
        notes = request.form.get("notes", "")
        renewal_date = calc_renewal_date(deadline, grace_days)

        cur = conn.cursor()
        cur.execute(
            "UPDATE numbers SET phone_number=%s, provider=%s, plan_name=%s, min_recharge=%s, deadline=%s, grace_days=%s, renewal_date=%s, remind_days=%s, is_alive=%s, notes=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
            (phone, provider, plan_name, float(min_recharge or 0), deadline, grace_days, renewal_date, remind_days, is_alive, notes, id),
        )
        conn.commit()
        cur.close()
        conn.close()
        flash("已更新", "success")
        return redirect(url_for("index"))

    row = fetch_one(conn, "SELECT * FROM numbers WHERE id = %s", (id,))
    conn.close()
    if not row:
        flash("找不到该号码", "error")
        return redirect(url_for("index"))
    return render_template("edit.html", item=row, providers=PROVIDERS, today=date.today().isoformat())

@app.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE numbers SET active = 0 WHERE id = %s", (id,))
    conn.commit()
    cur.close()
    conn.close()
    flash("已删除", "success")
    return redirect(url_for("index"))

@app.route("/renew/<int:id>", methods=["POST"])
def renew(id):
    new_deadline = request.form.get("new_deadline", "")
    grace_days = int(request.form.get("grace_days", 0) or 0)
    cost_paid = request.form.get("cost_paid", 0)

    conn = get_db()
    row = fetch_one(conn, "SELECT * FROM numbers WHERE id = %s", (id,))
    if not row:
        conn.close()
        flash("找不到该号码", "error")
        return redirect(url_for("index"))

    if new_deadline:
        new_renewal = calc_renewal_date(new_deadline, grace_days)
        cur = conn.cursor()
        cur.execute(
            "UPDATE numbers SET deadline = %s, grace_days = %s, renewal_date = %s, is_alive = 1, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (new_deadline, grace_days, new_renewal, id),
        )
        cur.execute(
            "INSERT INTO renewal_log (number_id, cost_paid, new_deadline, new_renewal_date) VALUES (%s, %s, %s, %s)",
            (id, float(cost_paid or row["min_recharge"]), new_deadline, new_renewal),
        )
        conn.commit()
        cur.close()
        flash(f"{row['phone_number']} 已续费 ✅ 活卡（截止：{new_deadline}，续费日：{new_renewal}）", "success")

    conn.close()
    return redirect(url_for("index"))

@app.route("/history")
def history():
    from_date = request.args.get("from", "")
    to_date = request.args.get("to", "")

    conn = get_db()
    query = """
        SELECT rl.*, n.phone_number, n.provider
        FROM renewal_log rl
        JOIN numbers n ON rl.number_id = n.id
        WHERE 1=1
    """
    params = []
    if from_date:
        query += " AND rl.renewed_at >= %s"
        params.append(f"{from_date} 00:00:00")
    if to_date:
        query += " AND rl.renewed_at <= %s"
        params.append(f"{to_date} 23:59:59")
    query += " ORDER BY rl.renewed_at DESC"

    rows = fetch_all(conn, query, params)

    logs = []
    total_cost = 0
    for r in rows:
        total_cost += r["cost_paid"]
        logs.append({
            "id": r["id"],
            "phone": r["phone_number"],
            "provider": r["provider"],
            "cost_paid": r["cost_paid"],
            "new_deadline": r["new_deadline"].isoformat() if isinstance(r["new_deadline"], date) else r["new_deadline"],
            "new_renewal_date": r["new_renewal_date"].isoformat() if isinstance(r["new_renewal_date"], date) else r["new_renewal_date"],
            "renewed_at": r["renewed_at"].isoformat() if hasattr(r["renewed_at"], 'isoformat') else str(r["renewed_at"]),
        })

    if not from_date and not to_date:
        today = date.today()
        from_date = today.replace(day=1).isoformat()
        to_date = today.isoformat()

    # 结算数据：总已收金额
    total_received = 0
    settle_rows = fetch_all(conn, "SELECT COALESCE(SUM(amount), 0) as total FROM settlements")
    if settle_rows:
        total_received = settle_rows[0]['total'] or 0
    outstanding = total_cost - total_received
    conn.close()

    return render_template("history.html", logs=logs, total_cost=total_cost,
                           total_received=total_received, outstanding=outstanding,
                           from_date=from_date, to_date=to_date)

@app.route("/api/expiring")
def api_expiring():
    conn = get_db()
    today = date.today().isoformat()
    expired_rows = fetch_all(conn, "SELECT * FROM numbers WHERE active = 1 AND is_alive = 1 AND renewal_date < %s ORDER BY renewal_date ASC", (today,))
    grace_rows = fetch_all(conn, "SELECT * FROM numbers WHERE active = 1 AND is_alive = 1 AND deadline < %s AND renewal_date >= %s ORDER BY deadline ASC", (today, today))
    soon = (date.today() + timedelta(days=7)).isoformat()
    soon_rows = fetch_all(conn, "SELECT * FROM numbers WHERE active = 1 AND is_alive = 1 AND deadline >= %s AND deadline <= %s ORDER BY deadline ASC", (today, soon))
    conn.close()

    expired = [{"phone": r["phone_number"], "provider": r["provider"], "deadline": str(r["deadline"]),
                 "renewal_deadline": str(r["renewal_date"]),
                 "days_overdue": (date.today() - r["renewal_date"]).days}
               for r in expired_rows]
    in_grace = []
    for r in grace_rows:
        in_grace.append({"phone": r["phone_number"], "provider": r["provider"], "deadline": str(r["deadline"]),
                          "grace_days_left": (r["renewal_date"] - date.today()).days})
    coming = []
    for r in soon_rows:
        coming.append({"phone": r["phone_number"], "provider": r["provider"], "deadline": str(r["deadline"]),
                        "days_left": (r["deadline"] - date.today()).days})

    return jsonify({
        "expired": expired, "in_grace_period": in_grace, "expiring_soon": coming,
        "total_critical": len(expired) + len(in_grace) + len(coming),
        "check_date": today,
    })

@app.route("/settle", methods=["POST"])
def settle():
    """记录结算收款"""
    try:
        amount = float(request.form.get("amount", 0))
        notes = request.form.get("notes", "")
        if amount <= 0:
            flash("金额必须大于 0", "error")
            return redirect(url_for("history"))

        conn = get_db()
        query = "INSERT INTO settlements (amount, notes) VALUES (%s, %s)"
        cur = conn.cursor()
        cur.execute(query, (amount, notes))
        conn.commit()
        cur.close()
        conn.close()
        flash(f"✅ 收到收款 RM {'%.2f' % amount}", "success")
    except Exception as e:
        flash(f"❌ 结算失败: {e}", "error")
    return redirect(url_for("history"))

# ── 旧路由（保留兼容） ──
@app.route("/archived")
def archived():
    conn = get_db()
    rows = fetch_all(conn, "SELECT * FROM numbers WHERE active = 0 ORDER BY updated_at DESC")
    conn.close()
    return render_template("archived.html", items=rows)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    app.run(host="0.0.0.0", port=port, debug=True)

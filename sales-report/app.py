"""営業日報管理アプリ - メインサーバー"""
import json
import os
import re
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from http import HTTPStatus
from datetime import datetime

from jinja2 import Environment, FileSystemLoader
from database import get_db, init_db, seed_data, hash_password
from auth import create_token, get_current_user

# Jinja2テンプレートエンジン
template_env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=True,
)

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))
BASE_URL = os.environ.get("BASE_URL", f"http://localhost:{PORT}")


def calc_rate(numerator, denominator):
    """パーセント計算（分母0ならNone）"""
    if denominator and denominator > 0:
        return round(numerator / denominator * 100, 1)
    return None


def format_rate(value):
    """率をフォーマット"""
    if value is None:
        return "-"
    if value == int(value):
        return f"{int(value)}%"
    return f"{value}%"


def enrich_report(report):
    """日報データに率を追加"""
    r = dict(report)
    r["appointment_rate"] = calc_rate(r["appointment_count"], r["contact_count"])
    r["meeting_rate"] = calc_rate(r["meeting_count"], r["appointment_count"])
    r["application_rate"] = calc_rate(r["application_count"], r["meeting_count"])
    r["contract_rate"] = calc_rate(r["contract_count"], r["application_count"])
    r["overall_rate"] = calc_rate(r["contract_count"], r["contact_count"])
    return r


# テンプレートにフィルター登録
template_env.filters["format_rate"] = format_rate
template_env.globals["format_rate"] = format_rate


class RequestHandler(BaseHTTPRequestHandler):
    """HTTPリクエストハンドラ"""

    def log_message(self, format, *args):
        """ログ出力"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")

    def send_html(self, html, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def send_redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def render(self, template_name, **context):
        user = get_current_user(self)
        context["current_user"] = user
        # 未読通知数を取得
        if user:
            conn = get_db()
            count = conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
                (user["user_id"],)
            ).fetchone()[0]
            conn.close()
            context["unread_count"] = count
        else:
            context["unread_count"] = 0
        template = template_env.get_template(template_name)
        return template.render(**context)

    def get_post_data(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        return urllib.parse.parse_qs(body, keep_blank_values=True)

    def require_auth(self):
        """認証チェック。未認証ならリダイレクト"""
        user = get_current_user(self)
        if not user:
            self.send_redirect("/login")
            return None
        return user

    def require_admin(self):
        """管理者チェック"""
        user = self.require_auth()
        if user and user["role"] != "Admin":
            self.send_html(self.render("error.html", message="アクセス権限がありません"), 403)
            return None
        return user

    # ===================== GET ルーティング =====================
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 静的ファイル
        if path.startswith("/static/"):
            self.serve_static(path)
            return

        routes = {
            "/": self.handle_index,
            "/login": self.handle_login_page,
            "/logout": self.handle_logout,
            "/reports": self.handle_reports_list,
            "/reports/new": self.handle_report_new,
            "/notifications": self.handle_notifications,
            "/admin/reports": self.handle_admin_reports,
        }

        # 動的ルート
        report_detail = re.match(r"^/reports/(\d+)$", path)
        report_edit = re.match(r"^/reports/(\d+)/edit$", path)
        admin_comment = re.match(r"^/reports/(\d+)/comment$", path)
        notification_read = re.match(r"^/notifications/(\d+)/read$", path)

        if path in routes:
            routes[path](query)
        elif report_edit:
            self.handle_report_edit_page(int(report_edit.group(1)))
        elif admin_comment:
            self.handle_admin_comment_page(int(admin_comment.group(1)))
        elif report_detail:
            self.handle_report_detail(int(report_detail.group(1)))
        elif notification_read:
            self.handle_notification_read(int(notification_read.group(1)))
        else:
            self.send_html(self.render("error.html", message="ページが見つかりません"), 404)

    # ===================== POST ルーティング =====================
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/login":
            self.handle_login_submit()
            return
        if path == "/reports/new":
            self.handle_report_create()
            return

        report_edit = re.match(r"^/reports/(\d+)/edit$", path)
        if report_edit:
            self.handle_report_update(int(report_edit.group(1)))
            return

        admin_comment = re.match(r"^/reports/(\d+)/comment$", path)
        if admin_comment:
            self.handle_admin_comment_update(int(admin_comment.group(1)))
            return

        # API: リアルタイム計算
        if path == "/api/calculate":
            self.handle_api_calculate()
            return

        self.send_html(self.render("error.html", message="不正なリクエスト"), 400)

    # ===================== ハンドラ実装 =====================

    def handle_index(self, query=None):
        user = get_current_user(self)
        if user:
            if user["role"] == "Admin":
                self.send_redirect("/admin/reports")
            else:
                self.send_redirect("/reports")
        else:
            self.send_redirect("/login")

    def handle_login_page(self, query=None):
        error = query.get("error", [None])[0] if query else None
        html = self.render("login.html", error=error)
        self.send_html(html)

    def handle_login_submit(self):
        data = self.get_post_data()
        email = data.get("email", [""])[0].strip()
        password = data.get("password", [""])[0]

        if not email or not password:
            self.send_redirect("/login?error=メールアドレスとパスワードを入力してください")
            return

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE email=? AND password_hash=?",
            (email, hash_password(password))
        ).fetchone()
        conn.close()

        if not user:
            self.send_redirect("/login?error=メールアドレスまたはパスワードが正しくありません")
            return

        token = create_token(user["id"], user["email"], user["role"], user["name"])
        self.send_response(302)
        self.send_header("Set-Cookie", f"token={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400")
        self.send_header("Location", "/")
        self.end_headers()

    def handle_logout(self, query=None):
        self.send_response(302)
        self.send_header("Set-Cookie", "token=; Path=/; HttpOnly; Max-Age=0")
        self.send_header("Location", "/login")
        self.end_headers()

    def handle_reports_list(self, query=None):
        user = self.require_auth()
        if not user:
            return

        conn = get_db()
        reports = conn.execute("""
            SELECT dr.*, u.name as user_name
            FROM daily_reports dr
            JOIN users u ON dr.user_id = u.id
            WHERE dr.user_id = ?
            ORDER BY dr.report_date DESC
        """, (user["user_id"],)).fetchall()
        conn.close()

        reports = [enrich_report(r) for r in reports]
        html = self.render("reports_list.html", reports=reports)
        self.send_html(html)

    def handle_report_detail(self, report_id):
        user = self.require_auth()
        if not user:
            return

        conn = get_db()
        report = conn.execute("""
            SELECT dr.*, u.name as user_name, u.email as user_email
            FROM daily_reports dr
            JOIN users u ON dr.user_id = u.id
            WHERE dr.id = ?
        """, (report_id,)).fetchone()
        conn.close()

        if not report:
            self.send_html(self.render("error.html", message="日報が見つかりません"), 404)
            return

        # 権限チェック: 一般ユーザーは自分の日報のみ
        if user["role"] != "Admin" and report["user_id"] != user["user_id"]:
            self.send_html(self.render("error.html", message="アクセス権限がありません"), 403)
            return

        report = enrich_report(report)
        html = self.render("report_detail.html", report=report)
        self.send_html(html)

    def handle_report_new(self, query=None):
        user = self.require_auth()
        if not user:
            return
        if user["role"] == "Admin":
            self.send_html(self.render("error.html", message="管理者は日報を作成できません"), 403)
            return
        html = self.render("report_form.html", report=None, errors=None)
        self.send_html(html)

    def handle_report_create(self):
        user = self.require_auth()
        if not user:
            return
        if user["role"] == "Admin":
            self.send_html(self.render("error.html", message="管理者は日報を作成できません"), 403)
            return

        data = self.get_post_data()
        errors = self.validate_report_data(data)

        if errors:
            report_data = self.extract_report_data(data)
            html = self.render("report_form.html", report=report_data, errors=errors)
            self.send_html(html, 400)
            return

        report_date = data.get("report_date", [""])[0]

        conn = get_db()
        # 同一日付の重複チェック
        existing = conn.execute(
            "SELECT id FROM daily_reports WHERE user_id=? AND report_date=?",
            (user["user_id"], report_date)
        ).fetchone()

        if existing:
            conn.close()
            report_data = self.extract_report_data(data)
            html = self.render("report_form.html", report=report_data,
                             errors=["この日付の日報は既に存在します。編集画面から更新してください。"])
            self.send_html(html, 400)
            return

        conn.execute("""
            INSERT INTO daily_reports
            (user_id, report_date, contact_count, appointment_count, meeting_count,
             application_count, contract_count, success_today, failure_today,
             improvement_tomorrow, action_plan_tomorrow, bottleneck, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user["user_id"], report_date,
            int(data.get("contact_count", ["0"])[0] or 0),
            int(data.get("appointment_count", ["0"])[0] or 0),
            int(data.get("meeting_count", ["0"])[0] or 0),
            int(data.get("application_count", ["0"])[0] or 0),
            int(data.get("contract_count", ["0"])[0] or 0),
            data.get("success_today", [""])[0],
            data.get("failure_today", [""])[0],
            data.get("improvement_tomorrow", [""])[0],
            data.get("action_plan_tomorrow", [""])[0],
            data.get("bottleneck", [""])[0],
            data.get("reason", [""])[0],
        ))
        conn.commit()
        conn.close()

        self.send_redirect("/reports")

    def handle_report_edit_page(self, report_id):
        user = self.require_auth()
        if not user:
            return

        conn = get_db()
        report = conn.execute(
            "SELECT * FROM daily_reports WHERE id=?", (report_id,)
        ).fetchone()
        conn.close()

        if not report:
            self.send_html(self.render("error.html", message="日報が見つかりません"), 404)
            return

        # 一般ユーザーは自分の日報のみ編集可能
        if user["role"] != "Admin" and report["user_id"] != user["user_id"]:
            self.send_html(self.render("error.html", message="アクセス権限がありません"), 403)
            return

        html = self.render("report_form.html", report=dict(report), errors=None)
        self.send_html(html)

    def handle_report_update(self, report_id):
        user = self.require_auth()
        if not user:
            return

        conn = get_db()
        report = conn.execute(
            "SELECT * FROM daily_reports WHERE id=?", (report_id,)
        ).fetchone()

        if not report:
            conn.close()
            self.send_html(self.render("error.html", message="日報が見つかりません"), 404)
            return

        # 一般ユーザーは自分の日報のみ
        if user["role"] != "Admin" and report["user_id"] != user["user_id"]:
            conn.close()
            self.send_html(self.render("error.html", message="アクセス権限がありません"), 403)
            return

        data = self.get_post_data()
        errors = self.validate_report_data(data)

        if errors:
            report_data = self.extract_report_data(data)
            report_data["id"] = report_id
            html = self.render("report_form.html", report=report_data, errors=errors)
            self.send_html(html, 400)
            conn.close()
            return

        conn.execute("""
            UPDATE daily_reports SET
                report_date=?, contact_count=?, appointment_count=?,
                meeting_count=?, application_count=?, contract_count=?,
                success_today=?, failure_today=?, improvement_tomorrow=?,
                action_plan_tomorrow=?, bottleneck=?, reason=?,
                updated_at=datetime('now')
            WHERE id=? AND user_id=?
        """, (
            data.get("report_date", [""])[0],
            int(data.get("contact_count", ["0"])[0] or 0),
            int(data.get("appointment_count", ["0"])[0] or 0),
            int(data.get("meeting_count", ["0"])[0] or 0),
            int(data.get("application_count", ["0"])[0] or 0),
            int(data.get("contract_count", ["0"])[0] or 0),
            data.get("success_today", [""])[0],
            data.get("failure_today", [""])[0],
            data.get("improvement_tomorrow", [""])[0],
            data.get("action_plan_tomorrow", [""])[0],
            data.get("bottleneck", [""])[0],
            data.get("reason", [""])[0],
            report_id,
            user["user_id"] if user["role"] != "Admin" else report["user_id"],
        ))
        conn.commit()
        conn.close()

        self.send_redirect(f"/reports/{report_id}")

    # ---- 管理者機能 ----
    def handle_admin_reports(self, query=None):
        user = self.require_admin()
        if not user:
            return

        conn = get_db()

        # 絞り込みパラメータ
        where_clauses = []
        params = []

        if query:
            # 担当者絞り込み
            user_filter = query.get("user_id", [None])[0]
            if user_filter:
                where_clauses.append("dr.user_id = ?")
                params.append(int(user_filter))

            # 日付絞り込み
            date_from = query.get("date_from", [None])[0]
            if date_from:
                where_clauses.append("dr.report_date >= ?")
                params.append(date_from)

            date_to = query.get("date_to", [None])[0]
            if date_to:
                where_clauses.append("dr.report_date <= ?")
                params.append(date_to)

            # コメント有無
            comment_filter = query.get("has_comment", [None])[0]
            if comment_filter == "1":
                where_clauses.append("dr.manager_comment != ''")
            elif comment_filter == "0":
                where_clauses.append("(dr.manager_comment = '' OR dr.manager_comment IS NULL)")

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        # ソート
        sort_col = "dr.report_date"
        sort_dir = "DESC"
        if query:
            sort = query.get("sort", [None])[0]
            valid_sorts = {
                "date": "dr.report_date",
                "user": "u.name",
                "contact": "dr.contact_count",
                "contract": "dr.contract_count",
            }
            if sort and sort.lstrip("-") in valid_sorts:
                if sort.startswith("-"):
                    sort_col = valid_sorts[sort[1:]]
                    sort_dir = "ASC"
                else:
                    sort_col = valid_sorts[sort]
                    sort_dir = "DESC"

        reports = conn.execute(f"""
            SELECT dr.*, u.name as user_name
            FROM daily_reports dr
            JOIN users u ON dr.user_id = u.id
            WHERE {where_sql}
            ORDER BY {sort_col} {sort_dir}
        """, params).fetchall()

        users = conn.execute(
            "SELECT id, name FROM users WHERE role='User' ORDER BY name"
        ).fetchall()
        conn.close()

        reports = [enrich_report(r) for r in reports]
        html = self.render("admin_reports.html", reports=reports, users=users,
                         filters=query or {})
        self.send_html(html)

    def handle_admin_comment_page(self, report_id):
        user = self.require_admin()
        if not user:
            return

        conn = get_db()
        report = conn.execute("""
            SELECT dr.*, u.name as user_name
            FROM daily_reports dr
            JOIN users u ON dr.user_id = u.id
            WHERE dr.id = ?
        """, (report_id,)).fetchone()
        conn.close()

        if not report:
            self.send_html(self.render("error.html", message="日報が見つかりません"), 404)
            return

        report = enrich_report(report)
        html = self.render("admin_comment.html", report=report)
        self.send_html(html)

    def handle_admin_comment_update(self, report_id):
        user = self.require_admin()
        if not user:
            return

        conn = get_db()
        report = conn.execute(
            "SELECT * FROM daily_reports WHERE id=?", (report_id,)
        ).fetchone()

        if not report:
            conn.close()
            self.send_html(self.render("error.html", message="日報が見つかりません"), 404)
            return

        data = self.get_post_data()
        new_comment = data.get("manager_comment", [""])[0].strip()
        old_comment = report["manager_comment"] or ""

        # コメント更新
        conn.execute("""
            UPDATE daily_reports SET manager_comment=?, updated_at=datetime('now')
            WHERE id=?
        """, (new_comment, report_id))

        # 通知：コメントが変更され、空でない場合
        if new_comment and new_comment != old_comment:
            notification_msg = f"上長からコメントが届きました：{new_comment}"
            conn.execute("""
                INSERT INTO notifications (user_id, report_id, message)
                VALUES (?, ?, ?)
            """, (report["user_id"], report_id, notification_msg))

            # メール通知（ログ出力で代替、SMTP設定時はメール送信）
            target_user = conn.execute(
                "SELECT name, email FROM users WHERE id=?",
                (report["user_id"],)
            ).fetchone()
            if target_user:
                send_email_notification(
                    to_email=target_user["email"],
                    to_name=target_user["name"],
                    report_date=report["report_date"],
                    comment=new_comment,
                    report_id=report_id,
                )

        conn.commit()
        conn.close()

        self.send_redirect(f"/reports/{report_id}")

    # ---- 通知 ----
    def handle_notifications(self, query=None):
        user = self.require_auth()
        if not user:
            return

        conn = get_db()
        notifications = conn.execute("""
            SELECT n.*, dr.report_date
            FROM notifications n
            JOIN daily_reports dr ON n.report_id = dr.id
            WHERE n.user_id = ?
            ORDER BY n.created_at DESC
        """, (user["user_id"],)).fetchall()
        conn.close()

        html = self.render("notifications.html", notifications=notifications)
        self.send_html(html)

    def handle_notification_read(self, notification_id):
        user = self.require_auth()
        if not user:
            return

        conn = get_db()
        # ユーザー本人の通知のみ既読可能
        conn.execute("""
            UPDATE notifications SET is_read=1
            WHERE id=? AND user_id=?
        """, (notification_id, user["user_id"]))
        conn.commit()

        # 通知に紐づくreport_idを取得してリダイレクト
        notif = conn.execute(
            "SELECT report_id FROM notifications WHERE id=? AND user_id=?",
            (notification_id, user["user_id"])
        ).fetchone()
        conn.close()

        if notif:
            self.send_redirect(f"/reports/{notif['report_id']}")
        else:
            self.send_redirect("/notifications")

    # ---- API ----
    def handle_api_calculate(self):
        """リアルタイム率計算API"""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON"}, 400)
            return

        contact = int(data.get("contact_count", 0) or 0)
        appointment = int(data.get("appointment_count", 0) or 0)
        meeting = int(data.get("meeting_count", 0) or 0)
        application = int(data.get("application_count", 0) or 0)
        contract = int(data.get("contract_count", 0) or 0)

        result = {
            "appointment_rate": format_rate(calc_rate(appointment, contact)),
            "meeting_rate": format_rate(calc_rate(meeting, appointment)),
            "application_rate": format_rate(calc_rate(application, meeting)),
            "contract_rate": format_rate(calc_rate(contract, application)),
            "overall_rate": format_rate(calc_rate(contract, contact)),
        }
        self.send_json(result)

    # ---- 静的ファイル ----
    def serve_static(self, path):
        file_path = path.lstrip("/")
        if ".." in file_path:
            self.send_response(403)
            self.end_headers()
            return

        content_types = {
            ".css": "text/css",
            ".js": "application/javascript",
            ".png": "image/png",
            ".ico": "image/x-icon",
        }
        ext = os.path.splitext(file_path)[1]
        content_type = content_types.get(ext, "application/octet-stream")

        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()

    # ---- バリデーション ----
    def validate_report_data(self, data):
        errors = []
        report_date = data.get("report_date", [""])[0]
        if not report_date:
            errors.append("日付は必須です")

        numeric_fields = [
            ("contact_count", "当日接触数"),
            ("appointment_count", "アポ数"),
            ("meeting_count", "商談数"),
            ("application_count", "申込数"),
            ("contract_count", "成約数"),
        ]
        for field, label in numeric_fields:
            val = data.get(field, [""])[0]
            if val:
                try:
                    v = int(val)
                    if v < 0:
                        errors.append(f"{label}は0以上で入力してください")
                except ValueError:
                    errors.append(f"{label}は数値で入力してください")

        return errors

    def extract_report_data(self, data):
        """フォームデータを辞書に変換"""
        return {
            "report_date": data.get("report_date", [""])[0],
            "contact_count": data.get("contact_count", ["0"])[0],
            "appointment_count": data.get("appointment_count", ["0"])[0],
            "meeting_count": data.get("meeting_count", ["0"])[0],
            "application_count": data.get("application_count", ["0"])[0],
            "contract_count": data.get("contract_count", ["0"])[0],
            "success_today": data.get("success_today", [""])[0],
            "failure_today": data.get("failure_today", [""])[0],
            "improvement_tomorrow": data.get("improvement_tomorrow", [""])[0],
            "action_plan_tomorrow": data.get("action_plan_tomorrow", [""])[0],
            "bottleneck": data.get("bottleneck", [""])[0],
            "reason": data.get("reason", [""])[0],
        }


def send_email_notification(to_email, to_name, report_date, comment, report_id):
    """メール通知（SMTP未設定時はログ出力）"""
    smtp_host = os.environ.get("SMTP_HOST")

    if smtp_host:
        try:
            import smtplib
            from email.mime.text import MIMEText

            smtp_port = int(os.environ.get("SMTP_PORT", "587"))
            smtp_user = os.environ.get("SMTP_USER", "")
            smtp_pass = os.environ.get("SMTP_PASS", "")
            from_email = os.environ.get("FROM_EMAIL", "noreply@example.com")

            body = f"""{to_name} 様

上長からコメントが届きました。

■ 日報日付: {report_date}
■ コメント内容:
{comment}

■ 確認URL: {BASE_URL}/reports/{report_id}

---
営業日報管理システム
"""
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = "上長からコメントが届きました"
            msg["From"] = from_email
            msg["To"] = to_email

            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                if smtp_user:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            print(f"[通知] メール送信完了: {to_email}")
        except Exception as e:
            print(f"[通知] メール送信エラー: {e}")
    else:
        print(f"[通知] メール通知 (SMTP未設定/ログ出力):")
        print(f"  宛先: {to_name} <{to_email}>")
        print(f"  件名: 上長からコメントが届きました")
        print(f"  日報日付: {report_date}")
        print(f"  コメント: {comment}")
        print(f"  URL: {BASE_URL}/reports/{report_id}")


def main():
    print("データベースを初期化中...")
    init_db()
    seed_data()

    server = HTTPServer((HOST, PORT), RequestHandler)
    print(f"営業日報管理アプリを起動しました: http://localhost:{PORT}")
    print(f"テストアカウント:")
    print(f"  管理者: admin@example.com / admin123")
    print(f"  営業: hanako@example.com / user123")
    print(f"  営業: jiro@example.com / user123")
    print(f"  営業: misaki@example.com / user123")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nサーバーを停止しました。")
        server.server_close()


if __name__ == "__main__":
    main()

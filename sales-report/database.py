"""データベース初期化・接続管理"""
import sqlite3
import hashlib
import os
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "sales_report.db")


def get_db():
    """DB接続を取得"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def hash_password(password: str) -> str:
    """パスワードをSHA-256でハッシュ化（本番ではbcrypt推奨）"""
    salt = "sales_report_salt_v1"
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()


def init_db():
    """テーブル作成"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('Admin', 'User')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS daily_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            report_date TEXT NOT NULL,
            contact_count INTEGER NOT NULL DEFAULT 0,
            appointment_count INTEGER NOT NULL DEFAULT 0,
            meeting_count INTEGER NOT NULL DEFAULT 0,
            application_count INTEGER NOT NULL DEFAULT 0,
            contract_count INTEGER NOT NULL DEFAULT 0,
            success_today TEXT DEFAULT '',
            failure_today TEXT DEFAULT '',
            improvement_tomorrow TEXT DEFAULT '',
            action_plan_tomorrow TEXT DEFAULT '',
            bottleneck TEXT DEFAULT '',
            reason TEXT DEFAULT '',
            manager_comment TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, report_date)
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            report_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (report_id) REFERENCES daily_reports(id)
        );

        CREATE INDEX IF NOT EXISTS idx_reports_user_id ON daily_reports(user_id);
        CREATE INDEX IF NOT EXISTS idx_reports_date ON daily_reports(report_date);
        CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id);
        CREATE INDEX IF NOT EXISTS idx_notifications_is_read ON notifications(is_read);
    """)

    conn.commit()
    conn.close()


def seed_data():
    """テスト用初期データを投入"""
    conn = get_db()
    cursor = conn.cursor()

    # ユーザーが既に存在するか確認
    existing = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if existing > 0:
        conn.close()
        return

    # テストユーザー作成
    users = [
        ("管理者 太郎", "admin@example.com", hash_password("admin123"), "Admin"),
        ("営業 花子", "hanako@example.com", hash_password("user123"), "User"),
        ("営業 次郎", "jiro@example.com", hash_password("user123"), "User"),
        ("営業 美咲", "misaki@example.com", hash_password("user123"), "User"),
    ]
    cursor.executemany(
        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
        users,
    )

    # サンプル日報データ
    sample_reports = [
        (2, "2026-03-20", 30, 10, 5, 3, 1,
         "新規顧客との面談が好調", "プレゼン資料に不備があった",
         "資料の事前チェックを徹底", "A社訪問、B社電話フォロー",
         "クロージング力の向上", "成約率が目標に届いていない",
         "良い動きです。資料チェックは私も確認しましょう。"),
        (2, "2026-03-21", 25, 8, 4, 2, 1,
         "リピート顧客からの紹介を獲得", "アポ時間の調整ミス",
         "スケジュール管理の見直し", "C社提案、D社フォロー",
         "タイムマネジメント", "移動時間の見積もりが甘い", ""),
        (3, "2026-03-20", 40, 15, 8, 5, 2,
         "大口案件の商談が前進", "競合情報の収集が不足",
         "競合分析シートの作成", "E社プレゼン、F社初回訪問",
         "競合対策", "提案の差別化ポイントが弱い",
         "素晴らしい成果です。競合分析は週次MTGで共有しましょう。"),
        (3, "2026-03-21", 35, 12, 6, 3, 1,
         "既存顧客のアップセルに成功", "新規開拓の時間が少なかった",
         "午前中を新規開拓に充てる", "G社契約手続き、新規テレアポ20件",
         "新規/既存のバランス", "既存対応に時間を取られすぎ", ""),
        (4, "2026-03-20", 20, 5, 3, 1, 0,
         "テレアポのトークスクリプトを改善", "商談でのヒアリングが浅い",
         "ヒアリングシートの活用", "H社訪問、テレアポ30件",
         "ヒアリング力", "顧客のニーズを深掘りできていない",
         "ヒアリングシートを一緒に作りましょう。来週MTG設定します。"),
    ]
    cursor.executemany("""
        INSERT INTO daily_reports
        (user_id, report_date, contact_count, appointment_count, meeting_count,
         application_count, contract_count, success_today, failure_today,
         improvement_tomorrow, action_plan_tomorrow, bottleneck, reason, manager_comment)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, sample_reports)

    # サンプル通知
    cursor.execute("""
        INSERT INTO notifications (user_id, report_id, message, is_read)
        VALUES (2, 1, '上長からコメントが届きました：良い動きです。資料チェックは私も確認しましょう。', 0)
    """)
    cursor.execute("""
        INSERT INTO notifications (user_id, report_id, message, is_read)
        VALUES (3, 3, '上長からコメントが届きました：素晴らしい成果です。競合分析は週次MTGで共有しましょう。', 0)
    """)
    cursor.execute("""
        INSERT INTO notifications (user_id, report_id, message, is_read)
        VALUES (4, 5, '上長からコメントが届きました：ヒアリングシートを一緒に作りましょう。来週MTG設定します。', 0)
    """)

    conn.commit()
    conn.close()
    print("シードデータを投入しました。")

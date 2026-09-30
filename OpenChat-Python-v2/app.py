import os
import re
import sqlite3
import secrets
import uuid
from pathlib import Path

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    send_from_directory,
)
from flask_socketio import SocketIO, join_room, leave_room, emit
from werkzeug.utils import secure_filename


# =========================================================
# 基本設定
# =========================================================

BASE = Path(__file__).resolve().parent

DATA_DIR = Path(
    os.environ.get("DATA_DIR", BASE / "data")
)

UPLOAD_DIR = Path(
    os.environ.get("UPLOAD_DIR", DATA_DIR / "uploads")
)

# フォルダを自動作成
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# SQLiteデータベース
DB = DATA_DIR / "openchat.db"


# =========================================================
# Flask
# =========================================================

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    secrets.token_hex(32)
)

# アップロード最大8MB
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024


# =========================================================
# Socket.IO
# =========================================================

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="gevent",
)


# =========================================================
# ファイル・URL設定
# =========================================================

ALLOWED_IMAGES = {
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
}

URL_RE = re.compile(
    r"(?i)(https?://[^\s<]+|www\.[^\s<]+)"
)


# =========================================================
# データベース接続
# =========================================================

def db():
    con = sqlite3.connect(
        DB,
        timeout=10
    )

    con.row_factory = sqlite3.Row

    return con


# =========================================================
# データベース初期化
# =========================================================

def init_db():
    """
    データベースと必要なテーブルを作成する。
    Render + Gunicornでも必ず実行されるようにする。
    """

    con = db()

    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            avatar TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            invite_code TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS members (
            user_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            UNIQUE(user_id, group_id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            user_name TEXT NOT NULL,
            body TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    # -----------------------------------------------------
    # 旧バージョンのDBにも対応
    # -----------------------------------------------------

    cols = {
        r["name"]
        for r in con.execute(
            "PRAGMA table_info(users)"
        ).fetchall()
    }

    if "avatar" not in cols:
        con.execute(
            "ALTER TABLE users ADD COLUMN avatar TEXT DEFAULT ''"
        )

    cols = {
        r["name"]
        for r in con.execute(
            "PRAGMA table_info(messages)"
        ).fetchall()
    }

    if "image_url" not in cols:
        con.execute(
            "ALTER TABLE messages ADD COLUMN image_url TEXT DEFAULT ''"
        )

    con.commit()
    con.close()


# =========================================================
# 現在ログインしているユーザー
# =========================================================

def current_user():

    name = session.get("user")

    if not name:
        return None

    con = db()

    row = con.execute(
        "SELECT * FROM users WHERE name=?",
        (name,)
    ).fetchone()

    con.close()

    return row


# =========================================================
# 画像保存
# =========================================================

def save_image(file, folder="messages"):

    if not file or not file.filename:
        return None

    safe_name = secure_filename(file.filename)

    ext = (
        Path(safe_name)
        .suffix
        .lower()
        .lstrip(".")
    )

    if ext not in ALLOWED_IMAGES:
        return None

    sub = UPLOAD_DIR / folder

    sub.mkdir(
        parents=True,
        exist_ok=True
    )

    filename = (
        f"{uuid.uuid4().hex}.{ext}"
    )

    file.save(
        sub / filename
    )

    return (
        f"/uploads/{folder}/{filename}"
    )


# =========================================================
# トップページ
# =========================================================

@app.route("/")
def index():

    con = db()

    groups = con.execute(
        "SELECT * FROM groups ORDER BY id DESC"
    ).fetchall()

    con.close()

    return render_template(
        "index.html",
        groups=groups,
        user=current_user()
    )


# =========================================================
# ログイン
# =========================================================

@app.post("/login")
def login():

    name = (
        request.form
        .get("name", "")
        .strip()[:30]
    )

    if not name:
        return redirect(
            url_for("index")
        )

    con = db()

    con.execute(
        "INSERT OR IGNORE INTO users(name) VALUES (?)",
        (name,)
    )

    con.commit()
    con.close()

    session["user"] = name

    return redirect(
        url_for("index")
    )


# =========================================================
# プロフィール変更
# =========================================================

@app.post("/profile")
def profile():

    user = current_user()

    if not user:
        return redirect(
            url_for("index")
        )

    name = (
        request.form
        .get("name", "")
        .strip()[:30]
    )

    if not name:
        return redirect(
            url_for("index")
        )

    con = db()

    exists = con.execute(
        """
        SELECT id
        FROM users
        WHERE name=?
        AND name<>?
        """,
        (
            name,
            user["name"]
        )
    ).fetchone()

    if exists:

        con.close()

        return redirect(
            url_for("index")
        )

    # 現在のアイコン
    avatar = user["avatar"]

    # 新しいアイコン
    new_avatar = save_image(
        request.files.get("avatar"),
        "avatars"
    )

    if new_avatar:
        avatar = new_avatar

    con.execute(
        """
        UPDATE users
        SET name=?,
            avatar=?
        WHERE name=?
        """,
        (
            name,
            avatar,
            user["name"]
        )
    )

    con.commit()
    con.close()

    session["user"] = name

    return redirect(
        url_for("index")
    )


# =========================================================
# ログアウト
# =========================================================

@app.post("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("index")
    )


# =========================================================
# グループ作成
# =========================================================

@app.post("/groups/create")
def create_group():

    user = current_user()

    if not user:
        return redirect(
            url_for("index")
        )

    name = (
        request.form
        .get("name", "")
        .strip()[:50]
    )

    desc = (
        request.form
        .get("description", "")
        .strip()[:200]
    )

    if not name:
        return redirect(
            url_for("index")
        )

    # 招待コード生成
    code = secrets.token_urlsafe(7)

    con = db()

    cur = con.execute(
        """
        INSERT INTO groups(
            name,
            description,
            invite_code
        )
        VALUES (?, ?, ?)
        """,
        (
            name,
            desc,
            code
        )
    )

    gid = cur.lastrowid

    # 作成者をメンバーにする
    con.execute(
        """
        INSERT OR IGNORE INTO members(
            user_id,
            group_id
        )
        VALUES (?, ?)
        """,
        (
            user["id"],
            gid
        )
    )

    con.commit()
    con.close()

    return redirect(
        url_for(
            "chat",
            group_id=gid
        )
    )


# =========================================================
# グループ参加
# =========================================================

@app.post("/groups/join")
def join_group():

    user = current_user()

    if not user:
        return redirect(
            url_for("index")
        )

    code = (
        request.form
        .get("code", "")
        .strip()
    )

    con = db()

    group = con.execute(
        """
        SELECT *
        FROM groups
        WHERE invite_code=?
        """,
        (code,)
    ).fetchone()

    if not group:

        con.close()

        return redirect(
            url_for("index")
        )

    con.execute(
        """
        INSERT OR IGNORE INTO members(
            user_id,
            group_id
        )
        VALUES (?, ?)
        """,
        (
            user["id"],
            group["id"]
        )
    )

    con.commit()
    con.close()

    return redirect(
        url_for(
            "chat",
            group_id=group["id"]
        )
    )


# =========================================================
# チャットページ
# =========================================================

@app.route("/group/<int:group_id>")
def chat(group_id):

    user = current_user()

    if not user:
        return redirect(
            url_for("index")
        )

    con = db()

    group = con.execute(
        """
        SELECT *
        FROM groups
        WHERE id=?
        """,
        (group_id,)
    ).fetchone()

    if not group:

        con.close()

        return "Group not found", 404

    # メンバー確認
    member = con.execute(
        """
        SELECT 1
        FROM members
        WHERE user_id=?
        AND group_id=?
        """,
        (
            user["id"],
            group_id
        )
    ).fetchone()

    if not member:

        con.close()

        return redirect(
            url_for("index")
        )

    # 最新300件
    messages = con.execute(
        """
        SELECT
            m.*,
            COALESCE(
                u.avatar,
                ''
            ) AS avatar
        FROM messages m

        LEFT JOIN users u
        ON u.name=m.user_name

        WHERE m.group_id=?

        ORDER BY m.id ASC

        LIMIT 300
        """,
        (group_id,)
    ).fetchall()

    con.close()

    return render_template(
        "chat.html",
        group=group,
        messages=messages,
        user=user
    )


# =========================================================
# 画像アップロード
# =========================================================

@app.post("/upload")
def upload():

    user = current_user()

    if not user:
        return jsonify(
            {
                "error": "login required"
            }
        ), 401

    file = request.files.get(
        "image"
    )

    image_url = save_image(
        file
    )

    if not image_url:
        return jsonify(
            {
                "error": "PNG/JPG/GIF/WebP only"
            }
        ), 400

    return jsonify(
        {
            "url": image_url
        }
    )


# =========================================================
# アップロード画像表示
# =========================================================

@app.get(
    "/uploads/<folder>/<filename>"
)
def uploaded_file(
    folder,
    filename
):

    if folder not in {
        "avatars",
        "messages"
    }:
        return "Not found", 404

    return send_from_directory(
        UPLOAD_DIR / folder,
        filename
    )


# =========================================================
# メッセージAPI
# =========================================================

@app.get(
    "/api/groups/<int:group_id>/messages"
)
def get_messages(group_id):

    con = db()

    rows = con.execute(
        """
        SELECT
            m.*,
            COALESCE(
                u.avatar,
                ''
            ) AS avatar

        FROM messages m

        LEFT JOIN users u
        ON u.name=m.user_name

        WHERE m.group_id=?

        ORDER BY m.id ASC

        LIMIT 300
        """,
        (group_id,)
    ).fetchall()

    con.close()

    return jsonify(
        [
            dict(x)
            for x in rows
        ]
    )


# =========================================================
# Socket.IO
# =========================================================

@socketio.on("join")
def on_join(data):

    try:
        room = str(
            int(data["group_id"])
        )
    except (
        ValueError,
        TypeError,
        KeyError
    ):
        return

    join_room(room)


# =========================================================
# Socket.IO退出
# =========================================================

@socketio.on("leave")
def on_leave(data):

    try:
        room = str(
            int(data["group_id"])
        )
    except (
        ValueError,
        TypeError,
        KeyError
    ):
        return

    leave_room(room)


# =========================================================
# メッセージ送信
# =========================================================

@socketio.on("send_message")
def on_message(data):

    user = current_user()

    if not user:
        return

    try:

        group_id = int(
            data["group_id"]
        )

    except (
        ValueError,
        TypeError,
        KeyError
    ):
        return

    body = str(
        data.get(
            "body",
            ""
        )
    ).strip()[:2000]

    image_url = str(
        data.get(
            "image_url",
            ""
        )
    ).strip()[:500]

    # 何もない場合
    if not body and not image_url:
        return

    con = db()

    # メンバー確認
    member = con.execute(
        """
        SELECT 1
        FROM members
        WHERE user_id=?
        AND group_id=?
        """,
        (
            user["id"],
            group_id
        )
    ).fetchone()

    if not member:

        con.close()

        return

    # メッセージ保存
    cur = con.execute(
        """
        INSERT INTO messages(
            group_id,
            user_name,
            body,
            image_url
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            group_id,
            user["name"],
            body,
            image_url
        )
    )

    # 保存したメッセージ取得
    row = con.execute(
        """
        SELECT
            m.*,
            COALESCE(
                u.avatar,
                ''
            ) AS avatar

        FROM messages m

        LEFT JOIN users u
        ON u.name=m.user_name

        WHERE m.id=?
        """,
        (
            cur.lastrowid,
        )
    ).fetchone()

    con.commit()
    con.close()

    # 全員に送信
    emit(
        "message",
        dict(row),
        room=str(group_id)
    )


# =========================================================
# ★重要
# Gunicorn / RenderでもDBを初期化する
# =========================================================

init_db()


# =========================================================
# ローカル実行
# =========================================================

if __name__ == "__main__":

    socketio.run(
        app,
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=True
    )

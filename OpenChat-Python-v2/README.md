# OpenChat Python

オープンチャット風のグループSNSです。

## 現在の機能

- ニックネーム / 表示名
- プロフィールアイコン
- グループ作成
- 招待コード
- リアルタイムチャット
- 画像アップロード
- 画像表示
- URLを自動でクリック可能なリンクに変換
- SQLite保存
- スマホ対応
- Render対応
- GitHubから自動デプロイ可能

## ローカル起動

PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

ブラウザ:

```text
http://127.0.0.1:5000
```

## GitHub

```powershell
git init
git add .
git commit -m "Initial OpenChat"
git branch -M main
git remote add origin https://github.com/YOUR_NAME/openchat-python.git
git push -u origin main
```

## Render

Renderで `New -> Web Service` を選び、GitHubリポジトリを接続します。

Build Command:

```text
pip install -r requirements.txt
```

Start Command:

```text
gunicorn --worker-class gevent -w 1 app:app
```

`render.yaml`を使う場合は設定を自動化できます。

### 重要: 画像とSQLiteの永続化

Renderの通常のファイルシステムは永続ではありません。
このアプリは `DATA_DIR` 以下にSQLiteと画像を保存する設計です。

公開後も画像とデータを残す場合は、RenderのPersistent Diskを
`/opt/render/project/src/data` にマウントしてください。

無料プランで完全な永続保存をしたい場合は、次の段階で
PostgreSQL + 外部画像ストレージへ変更するのがおすすめです。

## セキュリティ

これはMVPです。本格運用では以下を追加してください。

- メール/パスワードまたはOAuthログイン
- CSRF対策
- レート制限
- 通報・BAN
- 管理者権限
- 画像のウイルス/コンテンツ検査
- DBをPostgreSQLへ移行
- 画像を外部ストレージへ移行
- HTTPS / セキュアCookie設定

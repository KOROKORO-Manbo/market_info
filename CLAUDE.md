# Market Data Dashboard Project

## 📝 概要
外部の金融・市場データ（国債利回り、ダウ平均、為替、金相場）をスクレイピング/APIで取得し、Djangoのダッシュボード画面に表示するシステム。

## ⚙️ 環境・技術スタック
- Backend: Django (Docker環境)
- Data Processing: pandas, requests, beautifulsoup4, yfinance
- 既存リソース: `/sample/info_retreive.py`（取得ロジック）, `/sample/index.html`（モックアップ）

## 🛠️ 開発・運用コマンド
- Dockerコンテナ起動: `docker-compose up -d`
- マイグレーション作成: `docker-compose exec web python manage.py makemigrations`
- マイグレーション実行: `docker-compose exec web python manage.py migrate`
- 依存パッケージ追加: `docker-compose exec web pip install [package]` (必要に応じて requirements.txt に追記)

## 🎨 実装ルール & ガイドライン
- **認証の必須化**: 新しく作成するダッシュボードビューには、必ずログイン必須（`@login_required` または `LoginRequiredMixin`）を適用すること。
- **データの永続化**: 取得したデータはCSV出力ではなく、Djangoのデータベース（Models）に保存する構成に変更する。
- **テンプレートの共通化**: `index.html` をDjangoのテンプレートシステム（`{% extends %}` 等）に適応させ、ログイン後の画面として組み込む。
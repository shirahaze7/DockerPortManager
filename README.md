# Docker Port Dashboard

ホスト上の `docker-compose.yml` を再帰的に検索し、
サービス名・ポート番号・使用状況・URLを一覧表示するWebダッシュボードです。
<img width="1890" height="990" alt="image" src="https://github.com/user-attachments/assets/cc07851d-745e-4d42-afca-339da2d2204a" />

## 起動

```bash
docker compose up -d
```

ブラウザで http://localhost:1010 を開く

## 停止

```bash
docker compose down
```

## 構成

```
docker-dashboard/
├── docker-compose.yml      # 本アプリの起動定義
├── backend/
│   ├── app.py              # Flask API（compose.yml解析 + ポート確認）
│   ├── requirements.txt
│   └── Dockerfile
└── frontend/
    ├── index.html          # ダッシュボードUI
    └── nginx.conf          # nginx設定（ポート1010）
```

## 仕組み

- **backend**: ホストの `/home/[user]/docker` を読み取り専用でマウントし、`docker-compose.yml` / `docker-compose.yaml` を再帰検索
  - サービス名・ホストポート・コンテナポートを抽出
  - `socket.connect` でポートの使用中チェック（127.0.0.1）
- **frontend**: nginx がポート1010で静的ファイルを配信、`/api/` はbackendへプロキシ
- 30秒ごとに自動リフレッシュ

## 注意

- ホストの `/` をマウントするため、読み取り専用（`:ro`）でマウントしています
- ポートの使用確認はDockerコンテナ内からホストの127.0.0.1へ接続します
  - `network_mode: host` を使うとより正確に確認できます（Linuxのみ）

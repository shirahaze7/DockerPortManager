# Docker Port Manager

ホスト上の複数の `docker-compose.yml` を自動検出し、各サービスの情報（名前・ポート・状態）を
リアルタイム表示するWebダッシュボード。ダッシュボードから直接サービスの開始・停止を制御できます。

<img width="1890" height="990" alt="image" src="https://github.com/user-attachments/assets/cc07851d-745e-4d42-afca-339da2d2204a" />

## 概要

Docker Port Manager は、複数のDockerプロジェクトを管理している環境で、
どのサービスがどのポートを使用しているかを一元管理するツールです。

### 主な機能

- **再帰的な検索**: ホスト上のすべての `docker-compose.yml/yaml` ファイルを自動検出
- **リアルタイム監視**: ポートの使用状況をリアルタイムで確認
- **サービス制御**: ダッシュボードから直接サービスの開始・停止を実行
- **ワンクリックアクセス**: サービスのURLをダッシュボードから直接開く
- **レスポンシブUI**: ブラウザで簡単にアクセス可能
- **自動更新**: 30秒ごとに最新の状態を表示

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
    ├── nginx.conf          # nginx設定（ポート1010）
    └── styles.css          # UIのCSS
```

## 仕組み

### Backend（Python Flask）

- ホストの `/home/[user]/docker` を読み取り専用でマウント
- `docker-compose.yml` / `docker-compose.yaml` ファイルを再帰的に検索
- YAMLを解析してサービス情報を抽出：
  - **サービス名**: サービスの識別名
  - **ホストポート**: ホスト側のポート番号
  - **コンテナポート**: コンテナ内のポート番号
- **ポート使用状況確認**: `socket.connect` を使用して `127.0.0.1` の指定ポートへの接続テストを実施
  - 接続成功 → ポート使用中（緑色表示）
  - 接続失敗 → ポート未使用（灰色表示）
- REST API でフロントエンドに最新情報を提供：
  - `GET /api/services`: サービス一覧取得
  - `POST /api/compose/up`: 指定サービスの起動（`docker-compose up -d`）
  - `POST /api/compose/down`: 指定サービスの停止（`docker-compose down`）

### Frontend（Nginx + JavaScript）

- **Nginx**: ポート1010でダッシュボード（index.html）を配信
- **プロキシ設定**: `/api/` リクエストをバックエンド（ポート5000）に自動転送
- **自動リフレッシュ**: JavaScript で30秒ごとに API を呼び出し、画面を更新
- **UI機能**:
  - サービスの色分け表示（使用中/未使用）
  - ポート番号をクリックしてブラウザで直接アクセス可能
  - 「開始」「終了」ボタンでサービスをワンクリック制御
  - レスポンシブデザイン対応

## インストール・使用方法

### 前提条件

- Docker と Docker Compose がインストールされていること
- ポート 1010 が使用可能であること

### セットアップ

1. このリポジトリをクローン：
   ```bash
   git clone https://github.com/shirahaze7/DockerPortManager.git
   cd DockerPortManager
   ```

2. Docker Compose で起動：
   ```bash
   docker compose up -d
   ```

3. ブラウザでアクセス：
   - http://localhost:1010

### 設定のカスタマイズ

`docker-compose.yml` で以下をカスタマイズ可能：
- ダッシュボードのポート（デフォルト: 1010）
- 検索対象ディレクトリ（デフォルト: `/home/[user]/docker`）
- 自動更新間隔（フロントエンドで変更可能）

## 注意事項と制限事項

### セキュリティ

- ホストのファイルシステムを読み取り専用（`:ro`）でマウントしています
- コンテナ内から外部ネットワークへのアクセスはありません

### ポート確認の精度

- ポートの使用確認は、Docker コンテナ内から `127.0.0.1` への接続テストで実施
- ホスト上の全てのインターフェースでの使用状況を完全に把握するには、
  Docker Compose で `network_mode: host` を設定してください（**Linux のみ対応**）
- `network_mode: host` 使用時はより正確にポート状況を確認できます

### 対応環境

- **Linux**: フル対応（`network_mode: host` で最高精度）
- **Docker Desktop (macOS/Windows)**: 基本機能は動作（ネットワーク制限により精度が低下）

## トラブルシューティング

### ダッシュボードが開かない

- ポート 1010 が他のアプリケーションで使用されていないか確認
- `docker compose logs` でログを確認

### ポート情報が表示されない

- `docker-compose.yml` ファイルの場所とファイル名（.yml / .yaml）を確認
- 検索対象ディレクトリがマウントされているか確認

### ポート使用状況が正確でない

- Docker Desktop 環境の場合、`network_mode: host` への対応状況を確認
- Linux 環境で `network_mode: host` の使用を検討

## ライセンス

GNU General Public License v3 (GPL v3)

このプロジェクトはGPL v3の下で公開されています。
本ソフトウェアを改変・拡張した場合、改変後のコードも同じGPL v3の下で公開する必要があります。

詳細は [LICENSE](./LICENSE) ファイルを参照してください。

## 貢献

プルリクエストやIssue報告を歓迎します。
改変版の公開やフォークも大歓迎です。GPL v3の条件に従ってください。

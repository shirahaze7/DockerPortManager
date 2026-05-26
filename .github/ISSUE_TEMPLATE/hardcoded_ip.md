---
name: Bug Report - Hardcoded IP
about: ホストIPがハードコードされている問題
title: "ホストIPアドレスがハードコードされている"
labels: 'bug'
assignees: ''

---

## 問題の説明
`backend/app.py` ファイルの 17-18 行目にホストIPアドレスがハードコードされており、環境変数で設定できません。

```python
IP_LOCAL = "192.168.0.206"
IP_VPN = "100.107.246.101"
```

## 再現手順
1. 異なるネットワーク構成の環境でDockerPortManagerを起動する
2. ホストIPアドレスを変更する必要がある
3. コードを直接編集する以外に設定方法がない

## 期待される動作
- 環境変数（例：`HOST_IP_LOCAL`, `HOST_IP_VPN`）でホストIPアドレスを指定できるようにする
- コンテナ起動時に環境変数を設定すれば、異なるネットワーク構成に対応できる

## 実際の動作
- ホストIPアドレスが固定値として使用されている
- 異なるネットワーク構成では正しくポート確認ができない可能性がある

## 環境
- OS: Linux / macOS / Windows
- Docker Version: Any
- Docker Compose Version: Any

## 追加情報
このハードコードは `docker-compose.yml` の環境変数設定でも対応可能にすべきです

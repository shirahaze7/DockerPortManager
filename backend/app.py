"""Docker Compose Manager API

このアプリケーションは、ホスト側の複数のdocker-compose.ymlを検索・管理し、
Web UIから各サービスの開始・停止を制御するFlask APIです。
"""

# 標準ライブラリ
import glob
import os
import socket
import subprocess

# サードパーティ
import yaml
from flask import Flask, jsonify, request
from flask_cors import CORS

# Flask アプリケーション初期化
app = Flask(__name__)
CORS(app)  # 外部フロントエンドからのAPIアクセスを許可

# ===== 設定値 =====
# 探索対象となるホスト側のルートディレクトリ（Dockerコンテナ内からマウントされたパス）
SEARCH_ROOT = os.environ.get("SEARCH_ROOT", "/host")

# ネットワークアクセス元に応じた接続先IP候補
# - ローカルネットワークからのアクセス
IP_LOCAL = "192.168.0.206"
# - VPN経由でのアクセス
IP_VPN = "100.107.246.101"


def find_compose_files():
    """SEARCH_ROOT 配下から docker-compose.yml / .yaml ファイルを再帰的に検索する
    
    Returns:
        list: 見つかったファイルパスのソート済みリスト（重複除外）
    """
    patterns = ["**/docker-compose.yml", "**/docker-compose.yaml"]
    files = []

    for pattern in patterns:
        files.extend(glob.glob(os.path.join(SEARCH_ROOT, pattern), recursive=True))

    return sorted(set(files))


def parse_compose_file(filepath):
    """指定された Compose ファイルを解析し、サービス名とポートの組み合わせを抽出する
    
    Args:
        filepath (str): docker-compose.yml の絶対パス
        
    Returns:
        tuple: (サービス情報リスト, エラーメッセージ)
               成功時: (list, None)
               失敗時: ([], "エラー内容")
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        return None, f"YAML読み込みエラー: {str(e)}"

    # 空ファイルや無効なYAML形式をスキップ
    if not data or not isinstance(data, dict):
        return [], None

    # Composeファイルが置いてあるディレクトリ名を取得（サービス識別用）
    # 例: /host/archiveBox/docker-compose.yml → "archiveBox"
    dir_name = os.path.basename(os.path.dirname(filepath))

    # YAML内の services セクションを取得
    services = data.get("services", {}) or {}
    results = []

    # 各サービスを処理
    for svc_name, svc_config in services.items():
        # 無効なサービス設定をスキップ
        if not svc_config or not isinstance(svc_config, dict):
            continue

        # ポート定義を取得（複数可）
        ports = svc_config.get("ports", []) or []
        for port_entry in ports:
            # ポート定義の形式が複数あるため、それぞれに対応
            if isinstance(port_entry, dict):
                # Long syntax: ports: - published: 8080, target: 80
                host_port = str(port_entry.get("published", ""))
                container_port = str(port_entry.get("target", ""))
            else:
                # Short syntax: ports: - "8080:80" または "127.0.0.1:8080:80"
                port_str = str(port_entry)

                # 前回のバグ修正：split().split() によるクラッシュを防止
                if ":" in port_str:
                    parts = port_str.split(":")
                    # IP:ホストポート:コンテナポート の場合、末尾2つを取得
                    host_part = parts[-2]
                    container_part = parts[-1]
                else:
                    # ホストポート のみ指定されている場合
                    host_part = port_str
                    container_part = port_str

                # プロトコル指定（/tcp, /udp）を削除
                host_port = host_part.split("/")[0]
                container_port = container_part.split("/")[0]

            # ポート範囲（8080-8085）が指定されている場合は、最初のポートのみを使用
            if "-" in host_port:
                host_port = host_port.split("-")[0]
            if "-" in container_port:
                container_port = container_port.split("-")[0]

            # ホストポートを整数に変換（失敗時は None）
            try:
                host_port_int = int(host_port)
            except ValueError:
                host_port_int = None

            # UI表示用のサービス名を作成：「ディレクトリ名(サービス名)」
            display_service_name = f"{dir_name}({svc_name})"

            results.append({
                "service": display_service_name,
                "host_port": host_port_int,
                "container_port": container_port,
                "compose_file": filepath.replace(SEARCH_ROOT, ""),
            })

    return results, None


def check_port_in_use(ip, port):
    """指定されたIPアドレスとポートが実際に使用中（リスン中）か確認する
    
    TCP ソケットを用いて接続を試みることで確認。
    
    Args:
        ip (str): チェック対象のIPアドレス
        port (int): チェック対象のポート番号
        
    Returns:
        bool: リスン中なら True、使用中でなければ False
    """
    # ポート番号が無効な場合はスキップ
    if port is None:
        return False
    try:
        # TCP ソケットで接続試行
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)  # 接続タイムアウト: 300ms
            result = s.connect_ex((ip, port))
            # connect_ex() が 0 を返す = 接続成功 = ポート使用中
            return result == 0
    except Exception:
        # ネットワークエラーなどの場合は未使用と判定
        return False


@app.route("/api/services")
def get_services():
    """全 Compose ファイルを走査し、アクセス元に応じたホストIPでサービス一覧を返す
    
    アクセス元のホストヘッダーを確認して、VPN経由か直接接続かを判定し、
    適切なIPアドレスを使ってポートの使用状況を確認する。
    
    Returns:
        JSON: {
            "services": サービス情報リスト,
            "compose_files_found": 見つかったCompose ファイル数,
            "errors": パース失敗したファイルのエラー情報
        }
    """
    # リクエスト元のホストを取得
    host_header = request.headers.get("Host", "")

    # VPN経由か直接接続かを判定して、アクセス先IPを決定
    # これにより UI上のURLが正しくユーザーから到達可能なIPになる
    if IP_VPN in host_header:
        target_ip = IP_VPN
    else:
        target_ip = IP_LOCAL

    # Compose ファイルを検索
    compose_files = find_compose_files()
    all_services = []
    errors = []

    # 各Compose ファイルを解析
    for filepath in compose_files:
        entries, error = parse_compose_file(filepath)
        if error:
            # 解析失敗時はエラーリストに記録
            errors.append({"file": filepath, "error": error})
            continue

        # 各サービスのポート使用状況を確認
        for entry in entries:
            # target_ip でのリスン状況を確認
            entry["in_use"] = check_port_in_use(target_ip, entry["host_port"])
            
            # サービスへのアクセスURL を生成（ポート指定されている場合のみ）
            if entry["host_port"]:
                entry["url"] = f"http://{target_ip}:{entry['host_port']}"
            else:
                entry["url"] = None
            all_services.append(entry)

    return jsonify({
        "services": all_services,
        "compose_files_found": len(compose_files),
        "errors": errors,
    })


@app.route("/api/compose/up", methods=["POST"])
def compose_up():
    """指定された docker-compose.yml を実行し、サービスを起動する
    
    リクエストボディ:
        {"compose_file": "/path/to/docker-compose.yml"}
        
    Returns:
        JSON: {"success": bool, "returncode": int, "stdout": str, "stderr": str}
    """
    print(f"[DEBUG] POST /api/compose/up received")
    data = request.get_json(silent=True) or {}
    print(f"[DEBUG] Request data: {data}")
    
    # リクエストボディからコンポーズファイルパスを取得
    compose_file = data.get("compose_file")
    if not compose_file:
        print(f"[DEBUG] compose_file missing")
        return jsonify({"success": False, "error": "compose_file required"}), 400

    # セキュリティ: ファイルパスの正規化と SEARCH_ROOT 外へのアクセス防止
    rel = compose_file.lstrip("/\\")
    search_root_norm = os.path.normcase(os.path.abspath(SEARCH_ROOT))
    full_path = os.path.normcase(os.path.abspath(os.path.join(SEARCH_ROOT, rel)))
    print(f"[DEBUG] search_root_norm: {search_root_norm}, full_path: {full_path}")
    
    # パストラバーサル攻撃対策
    if not full_path.startswith(search_root_norm):
        print(f"[DEBUG] Path validation failed")
        return jsonify({"success": False, "error": "invalid compose_file path"}), 400

    # ファイル存在確認
    if not os.path.exists(full_path):
        print(f"[DEBUG] File not found: {full_path}")
        return jsonify({"success": False, "error": "file not found", "path": full_path}), 404

    # docker-compose コマンドの実行ディレクトリを決定
    dirpath = os.path.dirname(full_path)
    print(f"[DEBUG] Running docker compose up in: {dirpath}")

    try:
        # docker-compose を使用（スタンドアロン版は安定性が高い）
        # -d フラグで バックグラウンド起動
        proc = subprocess.run(
            ["docker-compose", "up", "-d"],
            cwd=dirpath,
            capture_output=True,
            text=True,
            timeout=120  # 起動完了待機時間: 2分
        )
        
        ok = proc.returncode == 0
        print(f"[DEBUG] Process result - returncode: {proc.returncode}, stdout: {proc.stdout}, stderr: {proc.stderr}")
        return jsonify({"success": ok, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
    except Exception as e:
        # サブプロセス実行中の予期しないエラー
        print(f"[DEBUG] Exception: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/compose/down", methods=["POST"])
def compose_down():
    """指定された docker-compose.yml で起動しているサービスを停止する
    
    リクエストボディ:
        {"compose_file": "/path/to/docker-compose.yml"}
        
    Returns:
        JSON: {"success": bool, "returncode": int, "stdout": str, "stderr": str}
    """
    print(f"[DEBUG] POST /api/compose/down received")
    data = request.get_json(silent=True) or {}
    print(f"[DEBUG] Request data: {data}")
    
    # リクエストボディからコンポーズファイルパスを取得
    compose_file = data.get("compose_file")
    if not compose_file:
        print(f"[DEBUG] compose_file missing")
        return jsonify({"success": False, "error": "compose_file required"}), 400

    # セキュリティ: ファイルパスの正規化と SEARCH_ROOT 外へのアクセス防止
    rel = compose_file.lstrip("/\\")
    search_root_norm = os.path.normcase(os.path.abspath(SEARCH_ROOT))
    full_path = os.path.normcase(os.path.abspath(os.path.join(SEARCH_ROOT, rel)))
    print(f"[DEBUG] search_root_norm: {search_root_norm}, full_path: {full_path}")
    
    # パストラバーサル攻撃対策
    if not full_path.startswith(search_root_norm):
        print(f"[DEBUG] Path validation failed")
        return jsonify({"success": False, "error": "invalid compose_file path"}), 400

    # ファイル存在確認
    if not os.path.exists(full_path):
        print(f"[DEBUG] File not found: {full_path}")
        return jsonify({"success": False, "error": "file not found", "path": full_path}), 404

    # docker-compose コマンドの実行ディレクトリを決定
    dirpath = os.path.dirname(full_path)
    print(f"[DEBUG] Running docker compose down in: {dirpath}")

    try:
        # docker-compose を使用して コンテナを停止・削除
        proc = subprocess.run(
            ["docker-compose", "down"],
            cwd=dirpath,
            capture_output=True,
            text=True,
            timeout=120  # 停止完了待機時間: 2分
        )
        
        ok = proc.returncode == 0
        print(f"[DEBUG] Process result - returncode: {proc.returncode}, stdout: {proc.stdout}, stderr: {proc.stderr}")
        return jsonify({"success": ok, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
    except Exception as e:
        # サブプロセス実行中の予期しないエラー
        print(f"[DEBUG] Exception: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.errorhandler(Exception)
def handle_exception(e):
    """ハンドル済みでない例外をキャッチして JSON レスポンスで返す"""
    response = {"success": False, "error": str(e)}
    status_code = getattr(e, 'code', 500)
    return jsonify(response), status_code


@app.route("/api/health")
def health():
    """API の生存確認（ヘルスチェック）用エンドポイント
    
    Docker コンテナ起動時や負荷分散プロキシから周期的に呼び出される。
    
    Returns:
        JSON: {"status": "ok"}
    """
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    # Flask 開発サーバーを起動
    # - host="0.0.0.0" で全インターフェースでリッスン
    # - port=5000 はコンテナ内ポート（ホストからのマッピング先は docker-compose.yml で指定）
    # - debug=True で ホットリロード有効化
    app.run(host="0.0.0.0", port=5000, debug=True)

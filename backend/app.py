import glob
import os
import socket
import subprocess
import yaml
import docker
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # 外部フロントエンドからのAPIアクセスを許可

# 探索対象となるホスト側のルートディレクトリ
SEARCH_ROOT = os.environ.get("SEARCH_ROOT", "/host")

# 利用を想定しているホストIPの候補
IP_LOCAL = "192.168.0.206"
IP_VPN = "100.107.246.101"


def find_compose_files():
    """SEARCH_ROOT 配下から docker-compose.yml / .yaml ファイルを再帰的に検索する"""
    patterns = ["**/docker-compose.yml", "**/docker-compose.yaml"]
    files = []

    for pattern in patterns:
        files.extend(glob.glob(os.path.join(SEARCH_ROOT, pattern), recursive=True))

    return sorted(set(files))


def parse_compose_file(filepath):
    """指定された Compose ファイルを解析し、サービス名とポートの組み合わせを抽出する"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        return None, f"YAML読み込みエラー: {str(e)}"

    # data が空ファイルや辞書型でない場合のガード
    if not data or not isinstance(data, dict):
        return [], None

    # Composeファイルが置いてある直前のディレクトリ名（例: archiveBox）
    dir_name = os.path.basename(os.path.dirname(filepath))

    services = data.get("services", {}) or {}
    results = []

    for svc_name, svc_config in services.items():
        if not svc_config or not isinstance(svc_config, dict):
            continue

        ports = svc_config.get("ports", []) or []
        for port_entry in ports:
            # 数値型や辞書型（Long syntax）のポート定義も考慮して文字列化
            if isinstance(port_entry, dict):
                # ports: - published: 8080 のような記述形式の場合
                host_port = str(port_entry.get("published", ""))
                container_port = str(port_entry.get("target", ""))
            else:
                port_str = str(port_entry)

                # 前回のバグ修正：split().split() によるクラッシュを防止
                if ":" in port_str:
                    parts = port_str.split(":")
                    # 127.0.0.1:8080:80 のようにIPが含まれる場合は末尾の2つを対象にする
                    host_part = parts[-2]
                    container_part = parts[-1]
                else:
                    host_part = port_str
                    container_part = port_str

                # プロトコル指定（/tcp, /udp）を安全に除去
                host_port = host_part.split("/")[0]
                container_port = container_part.split("/")[0]

            # ポート範囲（例: "8080-8085"）が指定されている場合は、最初のポートのみを対象にする
            if "-" in host_port:
                host_port = host_port.split("-")[0]
            if "-" in container_port:
                container_port = container_port.split("-")[0]

            try:
                host_port_int = int(host_port)
            except ValueError:
                host_port_int = None

            # サービス名を「yml格納ディレクトリ(yml内のサービス名)」の形式に整形
            display_service_name = f"{dir_name}({svc_name})"

            results.append({
                "service": display_service_name,
                "host_port": host_port_int,
                "container_port": container_port,
                "compose_file": filepath.replace(SEARCH_ROOT, ""),
            })

    return results, None


def check_port_in_use(ip, port):
    """指定されたIPアドレスとポートが実際に使用中（リスン中）か確認する"""
    if port is None:
        return False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            result = s.connect_ex((ip, port))
            return result == 0
    except Exception:
        return False


@app.route("/api/services")
def get_services():
    """全 Compose ファイルを走査し、アクセス元に応じたホストIPでサービス一覧を返すAPI"""
    host_header = request.headers.get("Host", "")

    # VPNアドレスでアクセスされているか判定し、ターゲットIPを動的に決定
    if IP_VPN in host_header:
        target_ip = IP_VPN
    else:
        target_ip = IP_LOCAL

    compose_files = find_compose_files()
    all_services = []
    errors = []

    for filepath in compose_files:
        entries, error = parse_compose_file(filepath)
        if error:
            errors.append({"file": filepath, "error": error})
            continue

        for entry in entries:
            entry["in_use"] = check_port_in_use(target_ip, entry["host_port"])
            
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
    print(f"[DEBUG] POST /api/compose/up received")
    data = request.get_json(silent=True) or {}
    print(f"[DEBUG] Request data: {data}")
    compose_file = data.get("compose_file")
    if not compose_file:
        print(f"[DEBUG] compose_file missing")
        return jsonify({"success": False, "error": "compose_file required"}), 400

    rel = compose_file.lstrip("/\\")
    search_root_norm = os.path.normcase(os.path.abspath(SEARCH_ROOT))
    full_path = os.path.normcase(os.path.abspath(os.path.join(SEARCH_ROOT, rel)))
    print(f"[DEBUG] search_root_norm: {search_root_norm}, full_path: {full_path}")
    if not full_path.startswith(search_root_norm):
        print(f"[DEBUG] Path validation failed")
        return jsonify({"success": False, "error": "invalid compose_file path"}), 400

    if not os.path.exists(full_path):
        print(f"[DEBUG] File not found: {full_path}")
        return jsonify({"success": False, "error": "file not found", "path": full_path}), 404

    dirpath = os.path.dirname(full_path)
    print(f"[DEBUG] Running docker compose up in: {dirpath}")

    try:
        # Try "docker compose" first, fallback to "docker-compose"
        print(f"[DEBUG] Attempting: docker compose up -d")
        proc = subprocess.run(["docker", "compose", "up", "-d"], cwd=dirpath, capture_output=True, text=True, timeout=120)
        print(f"[DEBUG] First attempt returncode: {proc.returncode}, stderr: {proc.stderr[:200]}")
        
        if proc.returncode != 0 and "not a docker command" in proc.stderr.lower():
            print(f"[DEBUG] Retrying with: docker-compose up -d")
            proc = subprocess.run(["docker-compose", "up", "-d"], cwd=dirpath, capture_output=True, text=True, timeout=120)
            print(f"[DEBUG] Retry returncode: {proc.returncode}")
        
        ok = proc.returncode == 0
        print(f"[DEBUG] Final result - returncode: {proc.returncode}, stdout: {proc.stdout}, stderr: {proc.stderr}")
        return jsonify({"success": ok, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
    except Exception as e:
        print(f"[DEBUG] Exception: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/compose/down", methods=["POST"])
def compose_down():
    print(f"[DEBUG] POST /api/compose/down received")
    data = request.get_json(silent=True) or {}
    print(f"[DEBUG] Request data: {data}")
    compose_file = data.get("compose_file")
    if not compose_file:
        print(f"[DEBUG] compose_file missing")
        return jsonify({"success": False, "error": "compose_file required"}), 400

    rel = compose_file.lstrip("/\\")
    search_root_norm = os.path.normcase(os.path.abspath(SEARCH_ROOT))
    full_path = os.path.normcase(os.path.abspath(os.path.join(SEARCH_ROOT, rel)))
    print(f"[DEBUG] search_root_norm: {search_root_norm}, full_path: {full_path}")
    if not full_path.startswith(search_root_norm):
        print(f"[DEBUG] Path validation failed")
        return jsonify({"success": False, "error": "invalid compose_file path"}), 400

    if not os.path.exists(full_path):
        print(f"[DEBUG] File not found: {full_path}")
        return jsonify({"success": False, "error": "file not found", "path": full_path}), 404

    dirpath = os.path.dirname(full_path)
    print(f"[DEBUG] Running docker compose down in: {dirpath}")

    try:
        # Try "docker compose" first, fallback to "docker-compose"
        proc = subprocess.run(["docker", "compose", "down"], cwd=dirpath, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0 and "not a docker command" in proc.stderr.lower():
            print(f"[DEBUG] Retrying with docker-compose")
            proc = subprocess.run(["docker-compose", "down"], cwd=dirpath, capture_output=True, text=True, timeout=120)
        
        ok = proc.returncode == 0
        print(f"[DEBUG] Process result - returncode: {proc.returncode}, stdout: {proc.stdout}, stderr: {proc.stderr}")
        return jsonify({"success": ok, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
    except Exception as e:
        print(f"[DEBUG] Exception: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.errorhandler(Exception)
def handle_exception(e):
    response = {"success": False, "error": str(e)}
    status_code = getattr(e, 'code', 500)
    return jsonify(response), status_code


@app.route("/api/health")
def health():
    """コンテナやサービスの生存確認（ヘルスチェック）用API"""
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

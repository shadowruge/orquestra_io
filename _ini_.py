# webhook_orchestrator.py
# Requisitos: pip install flask pyyaml

import hmac, hashlib, json, os, subprocess, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, abort
import yaml

# CONFIGURACAO
REPO_PATH = '/home/usuario/repos/meu-repo'   # caminho local do repo (git clone já feito)
GIT_BIN = '/usr/bin/git'
WEBHOOK_SECRET = os.environ.get('GITHUB_WEBHOOK_SECRET', 'troque_isto')
MAX_WORKERS = 3
SCRIPT_DIR = 'scripts'   # relativo ao repo
CONFIG_FILE = 'orchestrator.yaml'  # no repo, define quais scripts rodar / ordem / timeout
LOG_DIR = '/home/usuario/logs_orchestrador'

os.makedirs(LOG_DIR, exist_ok=True)

app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
lock = threading.Lock()  # evitar pulls concorrentes

def verify_signature(req):
    header = req.headers.get('X-Hub-Signature-256')
    if header is None:
        return False
    sha_name, signature = header.split('=', 1)
    if sha_name != 'sha256':
        return False
    mac = hmac.new(WEBHOOK_SECRET.encode(), msg=req.data, digestmod=hashlib.sha256)
    return hmac.compare_digest(mac.hexdigest(), signature)

def git_pull(repo_path):
    with lock:
        # pega branch atual
        subprocess.run([GIT_BIN, 'fetch', '--all'], cwd=repo_path, check=True)
        subprocess.run([GIT_BIN, 'reset', '--hard', 'origin/HEAD'], cwd=repo_path, check=True)

def load_config(repo_path):
    cfg_path = os.path.join(repo_path, CONFIG_FILE)
    if not os.path.exists(cfg_path):
        return {}
    with open(cfg_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}

def run_script(repo_path, script_relpath, timeout=60):
    script_path = os.path.join(repo_path, script_relpath)
    log_file = os.path.join(LOG_DIR, f"{os.path.basename(script_relpath)}_{int(time.time())}.log")
    start = time.time()
    try:
        with open(log_file, 'wb') as out:
            proc = subprocess.run(
                [script_path],
                cwd=os.path.dirname(script_path),
                stdout=out,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        duration = time.time() - start
        return {'script': script_relpath, 'returncode': proc.returncode, 'duration': duration, 'log': log_file}
    except subprocess.TimeoutExpired:
        return {'script': script_relpath, 'error': 'timeout', 'log': log_file}
    except Exception as e:
        return {'script': script_relpath, 'error': str(e), 'log': log_file}

def orchestrate(repo_path, commit_sha=None):
    try:
        git_pull(repo_path)
    except Exception as e:
        print("git pull failed:", e)
        return

    cfg = load_config(repo_path)
    # Exemplo de orchestrator.yaml:
    # jobs:
    #  - path: scripts/task1.sh
    #    timeout: 120
    #  - path: scripts/task2.py
    jobs = cfg.get('jobs', [])
    futures = []
    results = []
    for job in jobs:
        path = job.get('path')
        timeout = job.get('timeout', 60)
        if not path:
            continue
        futures.append(executor.submit(run_script, repo_path, path, timeout))
    for fut in as_completed(futures):
        res = fut.result()
        results.append(res)
        print("Job finished:", res)
    # aqui você pode enviar resultados para um dashboard, slack, banco etc.
    return results

@app.route('/webhook', methods=['POST'])
def webhook():
    if not verify_signature(request):
        abort(400, 'Invalid signature')
    payload = request.get_json()
    # opcional: filtrar por branch, por exemplo refs/heads/main
    ref = payload.get('ref', '')
    if 'refs/heads/main' not in ref and 'refs/heads/master' not in ref:
        return 'ignored branch', 200

    # disparar orchestrate em background
    executor.submit(orchestrate, REPO_PATH, commit_sha=payload.get('after'))
    return 'ok', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

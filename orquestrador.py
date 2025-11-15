import os
import hmac
import hashlib
import subprocess
from flask import Flask, request, jsonify, redirect
from dotenv import load_dotenv
import shutil

# =========================================================
# CONFIGURAÇÕES
# =========================================================
load_dotenv()

GITHUB_SECRET = os.getenv("GITHUB_SECRET", "secret123")
GITHUB_USER = os.getenv("GITHUB_USER")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_NAME = os.getenv("REPO_NAME", "orquestra_io")
REPO_PATH = os.getenv("REPO_PATH", "./orquestra_io_repo")
LOG_PATH = os.getenv("LOG_PATH", "./logs")
GIT_BIN = os.getenv("GIT_BIN", "/usr/bin/git")

# =========================================================
# GARANTIR DIRETÓRIOS
# =========================================================
os.makedirs(LOG_PATH, exist_ok=True)
os.makedirs(REPO_PATH, exist_ok=True)

# =========================================================
# FLASK APP
# =========================================================
app = Flask(__name__)

# =========================================================
# FUNÇÕES ÚTEIS
# =========================================================
def write_log(message: str):
    """Salvar logs no arquivo padrão orquestrador.log"""
    os.makedirs(LOG_PATH, exist_ok=True)
    log_file = os.path.join(LOG_PATH, "orquestrador.log")
    with open(log_file, "a") as f:
        f.write(message + "\n")

def verify_signature(payload, header_signature):
    """Valida o hash HMAC SHA256 da requisição do GitHub"""
    if header_signature is None:
        return False
    try:
        sha_name, signature = header_signature.split("=")
    except ValueError:
        return False
    if sha_name != "sha256":
        return False
    mac = hmac.new(GITHUB_SECRET.encode(), msg=payload, digestmod=hashlib.sha256)
    return hmac.compare_digest(mac.hexdigest(), signature)

def is_git_repo(path):
    """Verifica se o diretório é um repositório Git válido"""
    return os.path.exists(os.path.join(path, ".git"))

def run_git_pull(repo_url=None):
    """Executa git pull ou clone do repositório"""
    global REPO_NAME
    if repo_url is None:
        repo_url = f"https://{GITHUB_USER}:{GITHUB_TOKEN}@github.com/{GITHUB_USER}/{REPO_NAME}.git"

    try:
        if not os.path.exists(REPO_PATH) or not is_git_repo(REPO_PATH):
            if os.path.exists(REPO_PATH):
                shutil.rmtree(REPO_PATH)
            subprocess.run(
                [GIT_BIN, "clone", repo_url, REPO_PATH],
                text=True,
                check=True,
                capture_output=True
            )
            write_log(f"✔ Repositório clonado com sucesso: {repo_url}")
        else:
            result = subprocess.run(
                [GIT_BIN, "pull"],
                cwd=REPO_PATH,
                text=True,
                capture_output=True,
                check=True
            )
            write_log("✔ Git pull executado com sucesso:")
            write_log(result.stdout)
        return True, "Operação concluída."
    except subprocess.CalledProcessError as e:
        write_log("❌ Erro no git pull/clone:")
        write_log(e.stderr)
        return False, e.stderr

# =========================================================
# ROTAS FLASK
# =========================================================
@app.route("/")
def home():
    return f"""
    <h1>Orquestrador GitHub</h1>
    
    
    <a href='/test-git-pull'>💻 Testar Git Pull</a>
    <div style="margin-bottom:20px;">
        <form action="/set-repo" method="POST">
            <label>Digite o repositório GitHub (HTTPS):</label><br>
            <input type="text" name="repo_url" value="https://github.com/{GITHUB_USER}/{REPO_NAME}.git" style="width:400px">
            <button type="submit" style="padding:10px 20px; margin-top:5px;">Atualizar Repositório</button>
        </form>
    </div>

    <div style="margin-bottom:10px;">
        <a href='/logs'><button style="padding:10px 20px;">📝 Ver Logs</button></a>
    </div>

    <div style="margin-bottom:10px;">
        <a href='/test-git-pull'><button style="padding:10px 20px;">💻 Testar Git Pull</button></a>
    </div>

    <div style="margin-bottom:10px;">
        <a href='/webhook'><button style="padding:10px 20px;">🚀 Simular Webhook</button></a>
        <p style="font-size:12px; color:gray;">* Para webhook real, use POST via GitHub</p>
    </div>
    """

@app.route("/set-repo", methods=["POST"])
def set_repo():
    """Atualiza o repositório via formulário web"""
    global REPO_NAME
    repo_url = request.form.get("repo_url")
    if not repo_url:
        return "URL do repositório não fornecida.", 400
    # Extrai o nome do repositório da URL
    REPO_NAME = repo_url.rstrip(".git").split("/")[-1]
    ok, output = run_git_pull(repo_url)
    return redirect("/")

@app.route("/logs")
def exibir_logs():
    files = [f for f in os.listdir(LOG_PATH) if f.endswith(".log")]
    if not files:
        return "<h3>Nenhum arquivo de log encontrado.</h3>"
    links = "".join([f"<li><a href='/logs/{f}'>{f}</a></li>" for f in files])
    return f"""
    <h1>Arquivos de Log</h1>
    <ul>{links}</ul>
    <br><a href='/'>🔙 Voltar</a>
    """

@app.route("/logs/<filename>")
def mostrar_log_individual(filename):
    file_path = os.path.join(LOG_PATH, filename)
    if not os.path.exists(file_path):
        return "<h3>Arquivo não encontrado.</h3>"
    with open(file_path, "r") as f:
        content = f.read().replace("\n", "<br>")
    return f"""
    <h1>Log: {filename}</h1>
    <div style='background:#111;color:#0f0;padding:20px;border-radius:10px;font-family: monospace;'>
        {content}
    </div>
    <br><a href='/logs'>🔙 Voltar</a>
    """

@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_signature(request.data, signature):
        write_log("⚠️ Assinatura inválida no webhook.")
        return jsonify({"error": "Invalid signature"}), 403
    write_log("🚀 Webhook recebido. Executando git pull...")
    ok, output = run_git_pull()
    return jsonify({"status": "ok" if ok else "error", "output": output})

@app.route("/test-git-pull")
def test_pull():
    ok, output = run_git_pull()
    return f"Status: {'ok' if ok else 'error'}<br>Output:<pre>{output}</pre>"

# =========================================================
# MAIN
# =========================================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    print(f"Servidor Flask rodando em http://localhost:{port}")
    app.run(host="0.0.0.0", port=port)

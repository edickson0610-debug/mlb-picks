import os, json, requests
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

USER = "edickson0610-debug"
REPO = "mlb-picks"
TOKEN = os.environ.get("GITHUB_TOKEN", "")

DASHBOARD_URL = f"https://{USER}.github.io/{REPO}/"
GITHUB_RAW = f"https://raw.githubusercontent.com/{USER}/{REPO}/main/dashboard_live.html"
ACTIONS_URL = f"https://github.com/{USER}/{REPO}/actions"
WORKFLOW_URL = f"https://api.github.com/repos/{USER}/{REPO}/actions/workflows/deploy.yml/dispatches"

INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MLB Picks</title>
  <style>
    body { font-family: -apple-system, sans-serif; margin: 0; padding: 16px; background: #0d1117; color: #c9d1d9; }
    .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
    h1 { font-size: 1.4em; margin: 0; }
    .btn { padding: 10px 20px; border: none; border-radius: 8px; font-size: 14px; cursor: pointer; text-decoration: none; }
    .btn-primary { background: #238636; color: white; }
    .btn-primary:hover { background: #2ea043; }
    .btn-secondary { background: #21262d; color: #c9d1d9; border: 1px solid #30363d; }
    .btn:disabled { opacity: 0.6; cursor: not-allowed; }
    .info { font-size: 12px; color: #8b949e; margin: 8px 0; }
    iframe { width: 100%; height: calc(100vh - 120px); border: none; border-radius: 8px; background: white; }
    .flash { padding: 12px; border-radius: 8px; margin-bottom: 12px; display: none; }
    .flash-success { background: #1a3a1a; color: #7ee787; display: block; }
    .flash-error { background: #3a1a1a; color: #ff7b72; display: block; }
    .flash-info { background: #1a2a3a; color: #79c0ff; display: block; }
  </style>
</head>
<body>
  <div class="header">
    <h1>MLB Picks</h1>
    <div>
      <a href="{{ refresh_url }}" class="btn btn-secondary" target="_blank">GitHub</a>
      <button class="btn btn-primary" onclick="refresh()" id="btn">Refresh</button>
    </div>
  </div>
  <div id="flash" class="flash flash-info" style="display:none;"></div>
  <div class="info">Ultima actualizacion: {{ last_update }}</div>
  <iframe id="dashboard" src="{{ dashboard_url }}"></iframe>
  
  <script>
    function refresh() {
      var btn = document.getElementById('btn');
      var flash = document.getElementById('flash');
      btn.disabled = true; btn.textContent = 'Corriendo...';
      flash.style.display = 'block'; flash.className = 'flash flash-info'; flash.textContent = 'Iniciando analisis...';
      
      fetch('/refresh', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
          flash.className = 'flash flash-' + (data.status === 'ok' ? 'success' : 'error');
          flash.textContent = data.message;
          if (data.status === 'ok') {
            setTimeout(function() {
              document.getElementById('dashboard').src = document.getElementById('dashboard').src;
              flash.textContent = 'Dashboard actualizado!';
              setTimeout(function() { flash.style.display = 'none'; }, 5000);
            }, 60000);
          }
        })
        .catch(function() {
          flash.className = 'flash flash-error';
          flash.textContent = 'Error al conectar. Abre GitHub Actions manualmente.';
        })
        .finally(function() {
          btn.disabled = false; btn.textContent = 'Refresh';
        });
    }
  </script>
</body>
</html>
"""


@app.route("/")
def index():
    last_update = "N/A"
    try:
        r = requests.get(f"https://api.github.com/repos/{USER}/{REPO}/actions/runs?per_page=1&status=completed",
                        headers={"Accept": "application/vnd.github.v3+json"}, timeout=5)
        rj = r.json()
        runs = rj.get("workflow_runs", [])
        if runs:
            last_update = runs[0]["updated_at"][:19].replace("T", " ")
    except:
        pass
    return render_template_string(INDEX_HTML, dashboard_url=DASHBOARD_URL,
                                  refresh_url=ACTIONS_URL, last_update=last_update)


@app.route("/refresh", methods=["POST"])
def refresh():
    if not TOKEN:
        return jsonify({"status": "error", "message": "GITHUB_TOKEN no configurado. Ve a Settings > Environment Variables."})
    try:
        r = requests.post(WORKFLOW_URL,
                         headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github.v3+json"},
                         json={"ref": "main"}, timeout=10)
        if r.status_code == 204:
            return jsonify({"status": "ok", "message": "Analisis iniciado! Espera ~1 min y recarga."})
        else:
            return jsonify({"status": "error", "message": f"Error: {r.status_code}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)

"""Serveur local pour l'interface graphique des reglages de la Viper V3 HyperSpeed.

N'ecoute que sur la boucle locale. Aucune requete sortante, aucune dependance web.
Le service Synapse (com.razer.gms) est arrete au demarrage et relance a la sortie.

  ./venv/bin/python server.py [port]
"""
import atexit
import json
import os
import signal
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import razer_hid as hid

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "stages-backup.hex")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
HOST = "127.0.0.1"
ALLOWED_ORIGINS = {f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"}
_restored = threading.Event()


def restore_synapse(*_):
    if _restored.is_set():
        return
    _restored.set()
    if hid.gms_start():
        print("\nservice Synapse relance.")
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, signal.SIG_DFL)


def save_backup():
    """Sauvegarde le bloc de paliers courant avant toute modification."""
    try:
        with open(BACKUP, "w") as handle:
            handle.write(hid.read_stage_block().hex())
    except Exception as error:
        print(f"  (sauvegarde impossible : {error})")


class Handler(BaseHTTPRequestHandler):
    server_version = "razer-dpi"

    def log_message(self, fmt, *args):
        if not self.path.startswith("/api/state"):
            print(f"  {self.command} {self.path}")

    # --- helpers ---------------------------------------------------------
    def send_json(self, payload, code=200):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def guard(self):
        """Refuse ce qui ne vient pas de notre propre page (CSRF depuis un site)."""
        origin = self.headers.get("Origin")
        if origin and origin not in ALLOWED_ORIGINS:
            self.send_json({"error": f"origine refusee : {origin}"}, 403)
            return False
        if self.headers.get("X-Razer-DPI") != "1":
            self.send_json({"error": "en-tete X-Razer-DPI manquant"}, 403)
            return False
        return True

    def body_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    # --- routes ----------------------------------------------------------
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            try:
                with open(os.path.join(HERE, "ui.html"), "rb") as handle:
                    body = handle.read()
            except OSError as error:
                self.send_json({"error": str(error)}, 500)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/state":
            state = hid.read_all()
            state["synapse_running"] = hid.gms_loaded()
            try:
                with open(BACKUP) as handle:
                    state["backup"] = handle.read().strip()
            except OSError:
                state["backup"] = None
            self.send_json(state)
        else:
            self.send_json({"error": "route inconnue"}, 404)

    def do_POST(self):
        if not self.guard():
            return
        try:
            data = self.body_json()
            if self.path == "/api/stages":
                save_backup()
                values = [int(v) for v in data["values"]]
                active = int(data["active"]) if data.get("active") else None
                result = hid.write_stages(values, active)
                message = ("paliers ecrits et relus octet par octet" if result["changed"]
                           else "aucune modification a ecrire")
            elif self.path == "/api/restore":
                hex_block = data.get("hex") or open(BACKUP).read().strip()
                save_backup_hex = hid.read_stage_block().hex()
                result = hid.restore_block(hex_block)
                result["replaced"] = save_backup_hex
                message = "configuration sauvegardee restauree et relue"
            elif self.path == "/api/poll":
                hid.write_poll(int(data["hz"]))
                result = {}
                message = f"taux de scrutation ecrit et relu : {int(data['hz'])} Hz"
            elif self.path == "/api/idle":
                seconds = hid.write_idle(int(data["seconds"]))
                result = {}
                message = f"mise en veille ecrite et relue : {seconds} s"
            elif self.path == "/api/threshold":
                actual = hid.write_threshold(int(data["percent"]))
                result = {}
                message = f"alerte batterie ecrite et relue : {actual['percent']} %"
            elif self.path == "/api/synapse":
                if data.get("running"):
                    hid.gms_start()
                    message = "service Synapse relance"
                else:
                    hid.gms_stop()
                    message = "service Synapse arrete"
                result = {}
            else:
                self.send_json({"error": "route inconnue"}, 404)
                return
        except hid.DeviceError as error:
            self.send_json({"error": str(error)}, 400)
            return
        except (KeyError, ValueError, TypeError) as error:
            self.send_json({"error": f"requete invalide : {error}"}, 400)
            return
        except Exception as error:                       # pragma: no cover
            self.send_json({"error": f"{type(error).__name__}: {error}"}, 500)
            return
        payload = {"message": message, "result": result}
        payload["state"] = hid.read_all()
        payload["state"]["synapse_running"] = hid.gms_loaded()
        self.send_json(payload)


def main():
    print(f"razer-dpi — interface sur http://{HOST}:{PORT}")
    if hid.gms_stop():
        print("service Synapse arrete le temps de la session (relance a la fermeture).")
    atexit.register(restore_synapse)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: (restore_synapse(), sys.exit(0)))
    save_backup()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    if os.environ.get("RAZER_DPI_OPEN", "1") == "1":
        threading.Timer(0.6, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    print("Ctrl-C pour quitter.\n")
    try:
        httpd.serve_forever()
    finally:
        restore_synapse()


if __name__ == "__main__":
    main()

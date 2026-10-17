"""Start Siron SQL Tracer.

    python run.py                 start (Waitress if installed, else Flask's server)
    python run.py --open          start and open the browser
    python run.py --save-password store the Oracle password in Windows Credential Manager
"""
from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
import threading
import webbrowser
from logging.handlers import RotatingFileHandler

from siron_tracer import __version__, create_app
from siron_tracer.config import load_settings, save_keyring_password


def setup_logging(log_dir: str) -> str:
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "siron_tracer.log")
    handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    root.addHandler(console)
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Siron SQL Tracer")
    parser.add_argument("--config", help="config.ini yolu (varsayılan: ./config.ini)")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--open", action="store_true", help="tarayıcıyı aç")
    parser.add_argument("--save-password", action="store_true",
                        help="Oracle şifresini Windows Credential Manager'a kaydet")
    parser.add_argument("--dev", action="store_true", help="Flask geliştirme sunucusu")
    args = parser.parse_args(argv)

    settings = load_settings(args.config)
    if args.save_password:
        if not settings.oracle_user:
            print("Önce config.ini [oracle] user ve dsn değerlerini girin.")
            return 1
        pw = getpass.getpass("%s@%s şifresi: " % (settings.oracle_user, settings.oracle_dsn))
        if save_keyring_password(settings.oracle_user, settings.oracle_dsn, pw):
            print("Şifre kaydedildi. config.ini içindeki password satırını boş bırakabilirsiniz.")
            return 0
        print("Kaydedilemedi: 'pip install keyring' kurulu mu?")
        return 1
    if settings.oracle_user and not settings.oracle_password and sys.stdin and sys.stdin.isatty():
        settings.oracle_password = getpass.getpass("%s@%s şifresi: " % (settings.oracle_user, settings.oracle_dsn))

    host = args.host or settings.host
    port = args.port or settings.port
    log_path = setup_logging(settings.log_dir)
    app = create_app(settings)
    url = "http://%s:%d" % ("127.0.0.1" if host in ("0.0.0.0", "") else host, port)
    print("Siron SQL Tracer %s  →  %s   (log: %s)" % (__version__, url, log_path))
    if host not in ("127.0.0.1", "localhost"):
        print("UYARI: uygulama %s adresinde dinliyor; kimlik doğrulaması yoktur." % host)
    if args.open:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    logging.getLogger(__name__).info("starting on %s:%s", host, port)

    if not args.dev:
        try:
            from waitress import serve
            serve(app, host=host, port=port, threads=8, channel_timeout=3600)
            return 0
        except ImportError:
            print("waitress kurulu değil; Flask sunucusu kullanılıyor (pip install waitress).")
    app.run(host=host, port=port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

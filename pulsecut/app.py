"""Programmstart: lokaler Server + Qt-Fenster (QtWebEngine). Ohne Qt: Bedienung im normalen Browser."""
import argparse
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

from . import APP_NAME, VERSION
from .i18n import L as _t
from .util import resource


def _qt_env():
    # Chromium-Sandbox scheitert in AppImages/als root an Benutzer-Namensräumen – die Seite ist rein lokal
    if getattr(sys, "frozen", False) or os.geteuid() == 0 or os.environ.get("APPIMAGE"):
        os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    for f in ("--autoplay-policy=no-user-gesture-required", "--enable-features=OverlayScrollbar"):
        if f.split("=")[0] not in flags:
            flags += " " + f
    if os.environ.get("PULSECUT_SOFTWARE_GL"):
        flags += " --disable-gpu"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = flags.strip()


def run_qt(url, state):
    _qt_env()
    from PySide6.QtCore import QFile, QIODevice, QObject, QUrl, Slot
    from PySide6.QtGui import QDesktopServices, QIcon
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("pulsecut")
    icon = resource("ui", "icon.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    f = QFile(":/qtwebchannel/qwebchannel.js")
    if f.open(QIODevice.ReadOnly):
        state.qwebchannel_js = bytes(f.readAll())
        f.close()

    class Bridge(QObject):
        def __init__(self, win):
            super().__init__()
            self.win = win

        @Slot(str, str, result=str)
        def ordnerWaehlen(self, titel, start):
            d = QFileDialog.getExistingDirectory(self.win, titel or _t("Ordner wählen"), start or str(Path.home()))
            return d or ""

        @Slot(str)
        def oeffnen(self, pfad):
            QDesktopServices.openUrl(QUrl.fromLocalFile(pfad))

        @Slot(str)
        def titel(self, t):
            self.win.setWindowTitle(t)

    class Page(QWebEnginePage):
        def javaScriptConsoleMessage(self, level, msg, line, src):
            if os.environ.get("PULSECUT_DEBUG"):
                print(f"[js] {msg} ({src}:{line})", flush=True)

    win = QMainWindow()
    win.setWindowTitle(f"{APP_NAME} {VERSION}")
    win.resize(1440, 920)
    view = QWebEngineView(win)
    page = Page(QWebEngineProfile.defaultProfile(), view)
    view.setPage(page)
    st = page.settings()
    st.setAttribute(QWebEngineSettings.PlaybackRequiresUserGesture, False)
    st.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)

    def grant(*args):   # Mikrofon für die Spracheingabe erlauben (nur unsere lokale Seite)
        try:
            if len(args) == 1:      # Qt ≥ 6.8: QWebEnginePermission
                perm = args[0]
                if perm.origin().host() in ("127.0.0.1", "localhost"):
                    perm.grant()
                else:
                    perm.deny()
            else:
                origin, feature = args
                ok = origin.host() in ("127.0.0.1", "localhost")
                page.setFeaturePermission(origin, feature, QWebEnginePage.PermissionGrantedByUser if ok
                                          else QWebEnginePage.PermissionDeniedByUser)
        except Exception as e:  # pragma: no cover
            print("Berechtigung:", e)

    if hasattr(page, "permissionRequested"):
        page.permissionRequested.connect(grant)
    else:
        page.featurePermissionRequested.connect(grant)
    channel = QWebChannel(page)
    bridge = Bridge(win)
    channel.registerObject("bridge", bridge)
    page.setWebChannel(channel)
    state.bridge = True
    view.setUrl(QUrl(url))
    win.setCentralWidget(view)
    win.show()
    if os.environ.get("PULSECUT_SCREENSHOT"):   # für automatische Tests
        from PySide6.QtCore import QTimer

        def shot():
            win.grab().save(os.environ["PULSECUT_SCREENSHOT"])
            if os.environ.get("PULSECUT_JS"):
                page.runJavaScript(os.environ["PULSECUT_JS"], 0, lambda r: print("JS:", r, flush=True))
                QTimer.singleShot(4000, lambda: (win.grab().save(os.environ["PULSECUT_SCREENSHOT"] + ".2.png"), app.quit()))
            else:
                app.quit()
        QTimer.singleShot(int(os.environ.get("PULSECUT_SCREENSHOT_MS", "6000")), shot)
    return app.exec()


def main():
    from .i18n import set_lang
    ap = argparse.ArgumentParser(prog="pulsecut", description=f"{APP_NAME} {VERSION} – {_t('Videos auf den Takt schneiden')}")
    ap.add_argument("projekt", nargs="?", help=_t("Projektordner öffnen"))
    ap.add_argument("--browser", action="store_true", help=_t("statt eigenem Fenster den normalen Browser verwenden"))
    ap.add_argument("--port", type=int, default=0, help=_t("Port des lokalen Servers (Standard: frei wählen)"))
    ap.add_argument("--lang", choices=["de", "en"], help=_t("Sprache der Oberfläche"))
    ap.add_argument("--nur-server", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    args = ap.parse_args()
    if args.lang:
        set_lang(args.lang)
    from .server import STATE, start_server
    from .projekt import Projekt
    srv, url = start_server(args.port)
    print(f"{APP_NAME} {VERSION} – {url}", flush=True)
    if args.projekt:
        try:
            STATE.open(Projekt(args.projekt))
        except Exception as e:
            print(_t("Projekt konnte nicht geöffnet werden:"), e)
    if args.nur_server:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return
    if not args.browser:
        try:
            import PySide6  # noqa
            sys.exit(run_qt(url, STATE))
        except ImportError:
            print(_t("Qt (PySide6) nicht gefunden – öffne den Browser."))
    webbrowser.open(url)
    print(_t("Zum Beenden Strg+C drücken."))
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass

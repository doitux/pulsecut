# PyInstaller-Bauplan für Pulsecut (onedir, wird danach als AppImage verpackt)
import os
from pathlib import Path
ROOT = Path(SPECPATH).parent
UV = os.environ.get("TS_UV")
datas = [(str(ROOT / "pulsecut" / "ui"), "pulsecut/ui"),
         (str(ROOT / "pulsecut" / "ki_worker.py"), "pulsecut")]
binaries = [(UV, "pulsecut/bin")] if UV else []
excl = ["tkinter", "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras", "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic", "PySide6.Qt3DRender", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtGraphs", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtQuick3D",
        "PySide6.QtSpatialAudio", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSensors",
        "PySide6.QtSerialPort", "PySide6.QtSerialBus", "PySide6.QtTextToSpeech", "PySide6.QtPdf",
        "PySide6.QtPdfWidgets", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtSql", "PySide6.QtTest",
        "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtLocation",
        "PySide6.QtPositioning", "PySide6.QtHttpServer", "PySide6.QtWebSockets", "PySide6.QtUiTools",
        "PySide6.QtAxContainer", "PySide6.QtConcurrent", "PySide6.QtNetworkAuth", "PySide6.QtSvgWidgets",
        "PySide6.QtCanvasPainter", "matplotlib", "scipy", "pandas", "IPython", "PIL", "cv2"]
a = Analysis([str(ROOT / "packaging" / "start.py")], pathex=[str(ROOT)], binaries=binaries, datas=datas,
             hiddenimports=["PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore", "PySide6.QtWebChannel",
                            "PySide6.QtPrintSupport", "numpy"],
             excludes=excl, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="pulsecut", console=False, strip=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="pulsecut")

"""Remove Qt components the app never loads, shrinking the onedir bundle."""
from __future__ import annotations

import os
import shutil
import sys

# files / folders relative to dist/PDFStudio/_internal/PySide6
TARGETS = [
    "opengl32sw.dll",
    "Qt6Quick.dll",
    "Qt6QuickWidgets.dll",
    "Qt6QuickControls2.dll",
    "Qt6QuickControls2Impl.dll",
    "Qt6QuickTemplates2.dll",
    "Qt6QuickLayouts.dll",
    "Qt6QuickDialogs2.dll",
    "Qt6QuickDialogs2QuickImpl.dll",
    "Qt6QuickDialogs2Utils.dll",
    "Qt6QuickShapes.dll",
    "Qt6QuickParticles.dll",
    "Qt6QuickTest.dll",
    "Qt6Qml.dll",
    "Qt6QmlModels.dll",
    "Qt6QmlWorkerScript.dll",
    "Qt6QmlCompiler.dll",
    "Qt6QmlLocalStorage.dll",
    "Qt6QmlXmlListModel.dll",
    "Qt6Pdf.dll",
    "Qt6PdfQuick.dll",
    "Qt6OpenGL.dll",
    "Qt6OpenGLWidgets.dll",
    "Qt6VirtualKeyboard.dll",
    "Qt6VirtualKeyboardQml.dll",
    "Qt6VirtualKeyboardSettings.dll",
    "Qt6WebEngineCore.dll",
    "Qt6WebEngineQuick.dll",
    "Qt6WebEngineWidgets.dll",
    "Qt6WebChannel.dll",
    "Qt6WebSockets.dll",
    "Qt6Multimedia.dll",
    "Qt6MultimediaWidgets.dll",
    "Qt6SpatialAudio.dll",
    "Qt6Charts.dll",
    "Qt6DataVisualization.dll",
    "Qt6Bluetooth.dll",
    "Qt6Nfc.dll",
    "Qt6Positioning.dll",
    "Qt6RemoteObjects.dll",
    "Qt6Sensors.dll",
    "Qt6SerialPort.dll",
    "Qt6Sql.dll",
    "Qt6StateMachine.dll",
    "Qt6Test.dll",
    "Qt6TextToSpeech.dll",
    "Qt6Designer.dll",
    "Qt6Help.dll",
    "Qt6UiTools.dll",
    "translations",
    "qml",
    "typesystems",
    "glue",
    "include",
    "Qt/qml",
    "Qt/bin",
    "Qt/plugins",
    "Qt/translations",
]

KEEP_PLUGINS = {
    "platforms", "imageformats", "iconengines", "styles", "printsupport",
    "platformthemes", "tls", "networkinformation", "generic",
}


def main(dist: str) -> None:
    internal = os.path.join(dist, "_internal")
    qt = os.path.join(internal, "PySide6")
    before = sum(os.path.getsize(os.path.join(r, f))
                 for r, _d, fs in os.walk(dist) for f in fs)

    for rel in TARGETS:
        path = os.path.join(qt, rel)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass

    plugins = os.path.join(qt, "plugins")
    if os.path.isdir(plugins):
        for name in os.listdir(plugins):
            if name not in KEEP_PLUGINS:
                p = os.path.join(plugins, name)
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)

    after = sum(os.path.getsize(os.path.join(r, f))
                for r, _d, fs in os.walk(dist) for f in fs)
    print(f"trim: {before/1024/1024:.1f} MB -> {after/1024/1024:.1f} MB "
          f"(hemat {before/1024/1024 - after/1024/1024:.1f} MB)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dist/PDFStudio")

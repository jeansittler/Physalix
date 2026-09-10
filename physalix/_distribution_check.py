"""Diagnostic explicite du bundle ; aucune exécution au lancement normal."""

import json
from pathlib import Path
import sys
import tempfile
import traceback


def run(report_path):
    report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False))}
    window = None
    try:
        import av
        import numpy as np
        import scipy
        import PySide6
        import pyqtgraph
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QApplication
        from physalix import __version__
        from physalix.fitting import fit_model
        from physalix.project import read_project, write_project
        from physalix.ui.branding import application_icon, set_windows_app_id
        from physalix.ui.main_window import MainWindow
        from physalix.ui.project_state import snapshot, restore
        from physalix.ui.resources import resource_path
        from physalix.ui.theme import apply_theme
        from physalix.video import prepare_video
        from physalix.updates import Manifest, MANIFEST_URL, manifest_url, is_newer

        set_windows_app_id()
        app = QApplication([])
        app.setApplicationName("Physalix")
        app.setApplicationVersion(__version__)
        app.setWindowIcon(application_icon())
        apply_theme(app)
        assert manifest_url() == MANIFEST_URL  # Frozen builds ignore development overrides.
        assert is_newer("1.10.0", "1.9.9")
        Manifest.parse(json.dumps(dict(version=__version__, installer_url="https://github.com/installer.exe",
                                       sha256="a" * 64, notes="Diagnostic", mandatory=False)))
        assert not application_icon().isNull()
        assert not QImage(str(resource_path("branding", "logo_physalix.png"))).isNull()
        assert resource_path("check.svg").is_file()
        assert np.allclose(np.linalg.solve([[2., 0.], [0., 4.]], [6., 8.]), [3., 2.])
        x = np.linspace(0, 4, 30)
        fit = fit_model(x, 2 * x + 3, "affine")
        assert np.allclose(list(fit.parameters.values()), [2, 3])
        nonlinear = fit_model(x, .3 + 5 * (1 - np.exp(-x / 1.2)), "charge")
        assert nonlinear.rmse < 1e-7
        window = MainWindow()
        window.data_tab.model.rows = [[str(i), str(2 * i + 3)] for i in range(8)]
        window.graph_tab.refresh_plot()
        window.modeling_tab.calculate()
        assert window.graph_tab.series[0].fits
        with tempfile.TemporaryDirectory(prefix="Physalix-check-") as temporary:
            path = Path(temporary) / "experience.physalix"
            state = snapshot(window)
            write_project(path, state)
            restore(window, read_project(path), path)
            assert window.data_tab.model.rows[0][:2] == ["0", "3"]
            video = Path(temporary) / "video.mkv"
            with av.open(str(video), "w") as output:
                stream = output.add_stream("ffv1", rate=25)
                stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
                for i in range(3):
                    frame = av.VideoFrame.from_ndarray(np.full((48, 64, 3), i * 60, dtype=np.uint8), format="rgb24")
                    for packet in stream.encode(frame):
                        output.mux(packet)
                for packet in stream.encode():
                    output.mux(packet)
            cache = prepare_video(video)
            try:
                assert len(cache.times) == 3
                assert not QImage(cache.path(0)).isNull()
            finally:
                cache.close()
        window._discard_on_close = True
        window.show()
        QTimer.singleShot(800, app.quit)
        app.exec()
        # QApplication.quit may close the window; the event loop ran above.
        report.update(ok=True, version=__version__, platform=app.platformName(),
                      executable=sys.executable, cwd=str(Path.cwd()),
                      dependencies={m.__name__: m.__version__ for m in (np, scipy, av, PySide6, pyqtgraph)},
                      checks=["resources", "numpy-linalg", "scipy-fit", "graph", "project-roundtrip", "video-codec", "qt-window-event-loop", "updater-imports-manifest-version"])
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if window is not None:
            window._discard_on_close = True
            window.close()
        Path(report_path).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if report["ok"] else 1

"""Vérifier les ressources officielles indépendamment du dossier de lancement."""

import os
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from physlab.ui.branding import BrandLogo, application_icon
from physlab.ui.resources import resource_path


class BrandingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_resources_outside_project_directory(self):
        previous = Path.cwd()
        with TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                for name in ("logo_physalix.png", "icon_physalix.png"):
                    image = QImage(str(resource_path("branding", name)))
                    self.assertFalse(image.isNull())
                    self.assertTrue(image.hasAlphaChannel())
                self.assertFalse(application_icon().isNull())
                logo = BrandLogo()
                self.assertFalse(logo.grab().isNull())
                self.assertEqual(logo.accessibleName(), "Physalix")
            finally:
                os.chdir(previous)

    def test_ico_contains_seven_transparent_resolutions(self):
        data = resource_path("branding", "icon_physalix.ico").read_bytes()
        self.assertEqual(struct.unpack_from("<HHH", data), (0, 1, 7))
        for index, size in enumerate((16, 24, 32, 48, 64, 128, 256)):
            width, height, _, _, planes, depth, length, offset = struct.unpack_from(
                "<BBBBHHII", data, 6 + 16 * index)
            self.assertEqual((width or 256, height or 256, planes, depth), (size, size, 1, 32))
            image = QImage.fromData(data[offset:offset + length], "PNG")
            self.assertEqual((image.width(), image.height()), (size, size))
            self.assertTrue(image.hasAlphaChannel())
            self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
            self.assertFalse(application_icon().pixmap(size, size).isNull())

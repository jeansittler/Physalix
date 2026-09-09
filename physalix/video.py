"""Décodage séquentiel sans perte, avec cache temporaire borné sur disque."""

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import av
from PySide6.QtGui import QImage


@dataclass
class VideoCache:
    directory: TemporaryDirectory
    times: list[float]
    width: int
    height: int
    estimated_times: bool

    def path(self, index):
        return str(Path(self.directory.name) / f"{index:09d}.png")

    def close(self):
        self.directory.cleanup()


def prepare_video(path, cancelled=lambda: False, progress=lambda count: None,
                  max_bytes=4 * 1024**3):
    """Lire toutes les images en ordre de présentation ; nettoyer en cas d'échec."""
    cache = VideoCache(TemporaryDirectory(prefix="Physalix-video-"), [], 0, 0, False)
    try:
        used = 0
        origin = None
        with av.open(str(path)) as container:
            if not container.streams.video:
                raise ValueError("Ce fichier ne contient aucune piste vidéo.")
            stream = container.streams.video[0]
            rate = float(stream.average_rate) if stream.average_rate else 0
            for frame in container.decode(stream):
                if cancelled():
                    cache.close()
                    return None
                index = len(cache.times)
                timestamp = float(frame.time) if frame.time is not None else None
                if timestamp is None:
                    if rate <= 0:
                        raise ValueError("Horodatages et cadence absents : chronologie indéterminable.")
                    cache.estimated_times = True
                    timestamp = (cache.times[-1] + 1 / rate) if index else 0.0
                else:
                    if origin is None:
                        origin = timestamp - (cache.times[-1] + 1 / rate if index and rate > 0 else 0)
                    timestamp -= origin
                if index and timestamp < cache.times[-1]:
                    raise ValueError("Les horodatages de cette vidéo ne sont pas dans l'ordre.")
                rgb = frame.to_ndarray(format="rgb24")
                height, width, _ = rgb.shape
                image = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format.Format_RGB888)
                destination = cache.path(index)
                if not image.save(destination, "PNG"):
                    raise OSError("Impossible d'écrire le cache vidéo. Vérifiez l'espace disque.")
                used += Path(destination).stat().st_size
                if used > max_bytes:
                    raise ValueError("Cette vidéo dépasse la limite de cache de 4 Go. Utilisez un extrait plus court.")
                cache.times.append(timestamp)
                cache.width, cache.height = width, height
                if index % 10 == 0:
                    progress(index + 1)
        if not cache.times:
            raise ValueError("Aucune image décodable dans ce fichier.")
        if cancelled():
            cache.close()
            return None
        return cache
    except Exception:
        cache.close()
        raise

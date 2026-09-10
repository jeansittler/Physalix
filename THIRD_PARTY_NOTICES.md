# Composants tiers de Physalix 1.1.3

Physalix est distribué sous **GPL-3.0-only**. Les composants tiers restent
soumis à leurs propres licences. L'inventaire machine lisible, les versions,
les URL des sources et les obligations détaillées se trouvent dans
`third_party/components.json`. Les textes de licence sont fournis dans
`third_party/licenses/` et dans les répertoires `.dist-info` embarqués.

## Pile vidéo réellement distribuée

La roue PyAV 17.1.0 contient FFmpeg 8.1.1 construit par le projet
`PyAV-Org/pyav-ffmpeg`, recette 8.1.1-2, commit
`b84838a003b1626152ef530750d5c3e0022c3db9`. Les API des DLL déclarent :

| Bibliothèque | Version API | Licence déclarée par la DLL |
| --- | --- | --- |
| libavutil | 60.26.101 | LGPL version 3 ou ultérieure |
| libavcodec | 62.28.101 | LGPL version 3 ou ultérieure |
| libavformat | 62.12.101 | LGPL version 3 ou ultérieure |
| libavdevice | 62.3.101 | LGPL version 3 ou ultérieure |
| libavfilter | 11.14.101 | LGPL version 3 ou ultérieure |
| libswscale | 9.5.101 | LGPL version 3 ou ultérieure |
| libswresample | 6.3.101 | LGPL version 3 ou ultérieure |

Le bundle contient aussi x264 (commit `b35605a`, ABI 165), x265
4.2+1-e444744, LAME 3.100, Opus 1.6.1, dav1d 1.5.3, SVT-AV1 4.1.0,
libvpx 1.16.0, libwebp 1.6.0, OpenCORE-AMR 0.1.6, oneVPL 2.16.0,
zlib 1.3.2, GNU libiconv 1.19 et les runtimes MinGW/GCC 15.2.0.

Bien que FFmpeg lui-même retourne « LGPL version 3 or later », la recette
active `libx264` et `libx265`. La distribution combinée est donc traitée comme
un ensemble GPL-2.0-or-later. Elle est compatible avec Physalix
GPL-3.0-only, à condition de fournir le code source correspondant, les scripts
et correctifs de construction, ainsi que les avis de licence. Aucun codec n'a
été supprimé.

Licences principales : x264 et x265 sous GPL-2.0-or-later ; LAME et libiconv
sous LGPL ; OpenCORE-AMR sous Apache-2.0 ; dav1d, Opus, SVT-AV1, libvpx et
libwebp sous licences BSD ; oneVPL sous MIT ; zlib sous licence zlib ; runtimes
GCC sous GPL-3.0-or-later avec GCC Runtime Library Exception 3.1. Les mentions
de copyright et les sources exactes sont conservées dans l'inventaire.

## Qt, PySide6 et shiboken6

Le bundle contient PySide6 6.11.2, shiboken6 6.11.2 et Qt 6.11.2 sous leurs
options libres. Les modules effectivement présents comprennent notamment Qt
Core, GUI, Widgets, Network, OpenGL, PDF, QML, Quick, SVG et Virtual Keyboard.

PySide6 et shiboken6 sont proposés sous LGPL-3.0-only, GPL-2.0-only ou
GPL-3.0-only (en plus d'une option commerciale non utilisée ici). Qt Virtual
Keyboard est GPL-3.0-only dans l'édition open source. Sa présence rend naturel
le traitement de l'application complète sous GPL-3.0-only. La distribution
doit conserver les avis Qt, les textes GPL/LGPL, permettre le remplacement des
bibliothèques partagées lorsque l'option LGPL s'applique, et fournir les
sources exactes de Qt for Python et Qt 6.11.2.

## Autres composants Python

La distribution embarque aussi Python 3.12 (PSF License), pyqtgraph 0.14.0
(MIT, avec données de palettes CET sous CC BY), NumPy 2.5.3 (BSD et avis
tiers) et SciPy 1.18.1 (BSD et avis tiers, notamment OpenBLAS et GCC Runtime
Library Exception). Leurs métadonnées et fichiers de licence sont copiés dans
le bundle par PyInstaller.

PyInstaller, altgraph, colorama, packaging, pefile, pyinstaller-hooks-contrib,
pywin32-ctypes et setuptools servent à la construction ; Inno Setup sert à
produire l'installateur. Leurs licences ne changent pas celle de Physalix.

## Sources correspondantes

Pour toute future publication binaire, les archives de source correspondant
exactement aux versions ci-dessus doivent être rendues accessibles depuis le
même emplacement que le binaire, sans frais supplémentaires. Il faut notamment
conserver la recette et les correctifs `pyav-ffmpeg` 8.1.1-2. Le fichier
`artifacts/third-party-inventory.json`, généré à chaque build, lie les versions
déclarées aux empreintes SHA-256 des DLL réellement distribuées.

Le dépôt Git ne stocke volontairement pas ces archives volumineuses. Cette
organisation évite des centaines de mégaoctets dans l'historique sans réduire
les obligations de mise à disposition lors d'une release.

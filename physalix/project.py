"""Format de projet versionné, sans exécution de code, et échanges CSV."""
import csv
import io
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile


FORMAT = 'Physalix'
# Read-only compatibility with projects saved before the product rename.
LEGACY_FORMAT = 'Physalyx'
PROJECT_SUFFIX = '.physalix'
LEGACY_SUFFIX = '.physalyx'
VERSION = 1


def atomic_write(path, writer):
    """Remplacer la destination uniquement après une écriture complète."""
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, suffix='.tmp', dir=path.parent)
    os.close(fd)
    try:
        writer(temporary)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_project(path, state, cache=None):
    def write(temporary):
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('project.json', json.dumps(
                {'format': FORMAT, 'version': VERSION, 'state': state}, ensure_ascii=False, allow_nan=False))
            if cache:
                for index in range(len(cache.times)):
                    archive.write(cache.path(index), f'video/{index:09d}.png', compress_type=zipfile.ZIP_STORED)
    atomic_write(path, write)


def read_project(path):
    with zipfile.ZipFile(path) as archive:
        if archive.getinfo('project.json').file_size > 64 * 1024**2:
            raise ValueError('Le projet dépasse la taille maximale des données (64 Mo).')
        document = json.loads(archive.read('project.json'))
    if document.get('format') not in (FORMAT, LEGACY_FORMAT) or document.get('version') != VERSION:
        raise ValueError('Format de projet inconnu ou version non prise en charge.')
    return document['state']


def read_csv(path, delimiter=None, header=True):
    raw = Path(path).read_bytes()
    if len(raw) > 64 * 1024**2:
        raise ValueError('Le CSV dépasse 64 Mo.')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('cp1252')
    lines = text.splitlines()
    if lines and lines[0].lower().startswith('sep=') and len(lines[0]) == 5:
        delimiter = delimiter or lines[0][-1]
        text = '\n'.join(lines[1:])
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:16384], delimiters=';,\t').delimiter
        except csv.Error:
            delimiter = ';' if ';' in text else '\t' if '\t' in text else ','
    rows = list(csv.reader(io.StringIO(text, newline=''), delimiter=delimiter, strict=True))
    rows = [row for row in rows if row]
    if not rows:
        raise ValueError('Le fichier CSV est vide.')
    width = max(map(len, rows))
    if width > 10000 or len(rows) * width > 2000000:
        raise ValueError('Le CSV contient trop de cellules (maximum : 2 millions).')
    rows = [[cell.strip() for cell in row] + [''] * (width-len(row)) for row in rows]
    headings = rows.pop(0) if header else [f'C{i+1}' for i in range(width)]
    names, units = [], []
    for i, heading in enumerate(headings):
        match = re.fullmatch(r'(.*?)\s*\[([^\[\]]*)\]', heading)
        names.append((match[1].strip() if match else heading) or f'C{i+1}')
        units.append(match[2] if match else '')
    return {'names': names, 'units': units, 'rows': rows or [[''] * width]}


def write_csv(path, model, order=None):
    order = list(range(len(model.names))) if order is None else order
    rows = list(model.rows)
    while rows and not any(rows[-1]):
        rows.pop()
    def safe(value):
        # Les textes importés restent des textes dans Excel, jamais des commandes.
        try:
            float(value.replace(',', '.'))
            return value.replace('.', ',')
        except ValueError:
            return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
    def write(temporary):
        with open(temporary, 'w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream, delimiter=';')
            writer.writerow([safe(model.names[c] + (f' [{model.units[c]}]' if model.units[c] else '')) for c in order])
            writer.writerows([[safe(row[c]) for c in order] for row in rows])
    atomic_write(path, write)

"""Conversion explicite de l'espace de travail en données portables."""
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QComboBox, QLineEdit, QAbstractButton, QSpinBox, QDoubleSpinBox, QSlider
from physlab.calculations import Calculation, Formula
from physlab.fitting import FitResult
from physlab.video import VideoCache


def controls(owner):
    result = {}
    for name, widget in vars(owner).items():
        if isinstance(widget, QComboBox):
            result[name] = widget.currentIndex()
        elif isinstance(widget, QLineEdit):
            result[name] = widget.text()
        elif isinstance(widget, QAbstractButton) and widget.isCheckable():
            result[name] = widget.isChecked()
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox, QSlider)):
            result[name] = widget.value()
    return result


def restore_controls(owner, values):
    # Les clés du fichier ne peuvent viser que les contrôles connus de cette page.
    for name in controls(owner):
        if name not in values:
            continue
        widget, value = vars(owner)[name], values[name]
        if isinstance(widget, QComboBox):
            widget.setCurrentIndex(value)
        elif isinstance(widget, QLineEdit):
            widget.setText(value)
        elif isinstance(widget, QAbstractButton):
            widget.setChecked(value)
        else:
            widget.setValue(value)


def point(value):
    return [value.x(), value.y()] if value is not None else None


def snapshot(window):
    model = window.data_tab.model
    engine = window.calculations_tab.engine
    model.recalculate_cells()
    engine.recalculate()
    model.recalculate_cells()
    graphs = []
    for subwindow in window.graph_tab.windows:
        graph = subwindow.graph
        if graph._refresh_timer.isActive():
            graph._refresh_timer.stop()
            graph.sync_columns()
        entries = []
        for series in graph.series:
            fits = []
            for fit in series.fits:
                result = asdict(fit.result)
                result['x'], result['y'] = result['x'].tolist(), result['y'].tolist()
                fits.append(dict(number=fit.number, result=result, kind=fit.kind, settings=fit.settings))
            entries.append(dict(number=series.number, controls=controls(series), color=series.color.name(),
                                styles=[[list(k), list(v)] for k, v in series._styles.items()],
                                next_fit_number=series.next_fit_number, fits=fits))
        tools = {}
        for name in ('tangent_tool', 'conductimetry_tool', 'curve_guides_tool'):
            tool = getattr(graph, name)
            regions = [tool.region] if hasattr(tool, 'region') else getattr(tool, 'regions', [])
            tools[name] = dict(active=tool.active, controls=controls(tool),
                               regions=[list(r.getRegion()) for r in regions],
                               plateau_linked=getattr(tool, 'plateau_linked', False))
        graphs.append(dict(title=subwindow.windowTitle(), series=entries, controls=controls(graph),
                           modeling=controls(window.modeling_tab.pages[graph]), tools=tools,
                           view=graph.plot.viewRange(), right_view=graph.right_view.viewRange(),
                           mouse_mode=graph.plot.getViewBox().state['mouseMode'],
                           reticle=graph.reticle_action.isChecked(),
                           legend=point(graph.legend.pos()) if graph.legend.manual else None,
                           interval=list(graph.fit_region.getRegion()),
                           geometry=[subwindow.x(), subwindow.y(), subwindow.width(), subwindow.height()]))
    tracking = window.video_tab.tracking
    video = dict(tracking={name: getattr(tracking, name) for name in
                           ('x_direction', 'y_direction', 'scale', 'unit', 'length', 'columns', 'written_rows')},
                 origin=point(tracking.origin), ruler=[point(p) for p in tracking.ruler] if tracking.ruler else None,
                 points=[[i, point(p), t] for i, (p, t) in sorted(tracking.points.items())],
                 index=window.video_tab.index, controls=controls(window.video_tab))
    cache = window.video_tab.cache
    if cache:
        video['cache'] = dict(times=cache.times, width=cache.width, height=cache.height, estimated_times=cache.estimated_times)
    header = window.data_tab.table.horizontalHeader()
    return dict(table=dict(names=list(model.names), units=list(model.units), rows=[list(r) for r in model.rows],
                           formulas=[[r, c, text] for (r, c), text in sorted(model.formulas.items())],
                           order=[header.logicalIndex(i) for i in range(model.columnCount())]),
                calculations=[dict(column=c.column, kind=c.kind, source=c.source, axis=c.axis,
                                   expression=c.formula.editable_expression() if c.formula else None,
                                   automatic_unit=c.automatic_unit, previous_unit=c.previous_unit) for c in engine.items],
                graphs=graphs, arrangement=window.graph_tab.arrangement.currentIndex(),
                active_graph=next(i for i, w in enumerate(window.graph_tab.windows) if w.graph is window.graph_tab.active_graph),
                calculations_controls=controls(window.calculations_tab), statistics=controls(window.statistics_tab),
                video=video, tab=window.tabs.currentIndex())


def restore(window, state, path=None):
    """Restaurer dans une fenêtre de préparation ; l'original reste intact en cas d'erreur."""
    table = state['table']
    names, units, rows = table['names'], table['units'], table['rows']
    if (len(names) > 10000 or len(names) != len(units) or not rows
            or len(rows)*len(names) > 2000000
            or any(len(row) != len(names) for row in rows)
            or any(not isinstance(s, str) for s in names + units + [s for row in rows for s in row])):
        raise ValueError('Structure du tableur incorrecte.')
    model = window.data_tab.model
    model.beginResetModel()
    model.names, model.units, model.rows = list(names), list(units), [list(r) for r in rows]
    model.formulas = {}
    for r, c, expression in table.get('formulas', []):
        if not (0 <= r < len(rows) and 0 <= c < len(names)) or not isinstance(expression, str):
            raise ValueError('Référence de cellule incorrecte.')
        model.formulas[r, c] = expression
    model.endResetModel()
    engine = window.calculations_tab.engine
    for entry in state.get('calculations', []):
        entry = dict(entry)
        expression = entry.pop('expression')
        item = Calculation(**entry, formula=Formula(expression, names) if expression is not None else None)
        refs = set(item.formula.references.values()) if item.formula else {item.source, item.axis}
        if (item.kind not in ('formula', 'derivative') or item.column in model.calculated_columns
                or any(type(c) is not int or not 0 <= c < len(names) for c in refs | {item.column})):
            raise ValueError('Référence de calcul incorrecte.')
        engine.items.append(item)
        model.calculated_columns.add(item.column)
        model.column_dependencies[item.column] = refs
    engine.recalculate()
    model.recalculate_cells()
    window.calculations_tab.refresh()
    header = window.data_tab.table.horizontalHeader()
    order = table.get('order', list(range(len(names))))
    if sorted(order) != list(range(len(names))):
        raise ValueError('Ordre des colonnes incorrect.')
    for visual, logical in enumerate(order):
        header.moveSection(header.visualIndex(logical), visual)
    graphs = state.get('graphs', [])
    if not 1 <= len(graphs) <= 100:
        raise ValueError('Nombre de graphiques incorrect.')
    for index, saved in enumerate(graphs):
        graph = window.graph_tab.windows[0].graph if index == 0 else window.graph_tab.add_graph()
        graph.sync_columns()
        window.graph_tab.windows[index].setWindowTitle(saved['title'])
        if not 1 <= len(saved['series']) <= 100:
            raise ValueError('Nombre de séries incorrect.')
        for j, entry in enumerate(saved['series']):
            series = graph.series[0] if j == 0 else graph.add_series()
            series.number = entry['number']
            series.visible.setText(f'Série {series.number}')
            for axis in ('x_choice', 'y_choice'):
                if not -1 <= entry['controls'][axis] < len(names):
                    raise ValueError('Colonne du graphique introuvable.')
            restore_controls(series, entry['controls'])
            series._styles = {tuple(k): tuple(v) for k, v in entry.get('styles', [])}
            series.set_curve_color(entry['color'])
            for fit in entry['fits']:
                result = dict(fit['result'])
                result['x'], result['y'] = np.asarray(result['x'], float), np.asarray(result['y'], float)
                if (not result['x'].size or result['x'].ndim != 1 or result['x'].shape != result['y'].shape
                        or not np.isfinite(result['x']).all() or not np.isfinite(result['y']).all()):
                    raise ValueError('Résultat de modélisation incorrect.')
                series.next_fit_number = fit['number']
                graph.set_model(series, FitResult(**result), fit['kind'], fit['settings'])
            series.next_fit_number = entry['next_fit_number']
        graph._next_number = max(s.number for s in graph.series) + 1
        graph.refresh_plot()
        page = window.modeling_tab.pages[graph]
        page.sync_series()
        restore_controls(page, saved['modeling'])
        page.show_result()
        graph.fit_region.setRegion(saved['interval'])
        for name, entry in saved['tools'].items():
            if name not in ('tangent_tool', 'conductimetry_tool', 'curve_guides_tool'):
                continue
            tool = getattr(graph, name)
            if entry['active']:
                tool.open_tool('tangent') if name == 'curve_guides_tool' else tool.open_tool()
                restore_controls(tool, entry['controls'])
                regions = [tool.region] if hasattr(tool, 'region') else getattr(tool, 'regions', [])
                for region, bounds in zip(regions, entry['regions']):
                    region.setRegion(bounds)
                if entry.get('plateau_linked'):
                    tool.use_plateau()
                tool.calculate()
        restore_controls(graph, saved['controls'])
        graph.reticle_action.setChecked(saved['reticle'])
        graph.plot.getViewBox().setMouseMode(saved['mouse_mode'])
        graph._refresh_timer.stop()
    window.graph_tab.arrangement.setCurrentIndex(state['arrangement'])
    window.graph_tab.area.setActiveSubWindow(window.graph_tab.windows[state['active_graph']])
    restore_controls(window.calculations_tab, state.get('calculations_controls', {}))
    window.statistics_tab.sync()
    restore_controls(window.statistics_tab, state.get('statistics', {}))
    window.statistics_tab.calculate()
    video = state.get('video', {})
    tracking = window.video_tab.tracking
    for name in ('x_direction', 'y_direction', 'scale', 'unit', 'length', 'columns', 'written_rows'):
        if name in video.get('tracking', {}):
            setattr(tracking, name, video['tracking'][name])
    tracking.origin = QPointF(*video['origin']) if video.get('origin') else None
    tracking.ruler = tuple(QPointF(*p) for p in video['ruler']) if video.get('ruler') else None
    tracking.points = {i: (QPointF(*p), t) for i, p, t in video.get('points', [])}
    if video.get('cache'):
        metadata = video['cache']
        if not path or not metadata['times']:
            raise ValueError('Vidéo du projet manquante.')
        cache = VideoCache(TemporaryDirectory(prefix='Physalyx-project-'), **metadata)
        window.video_tab.cache = cache
        with zipfile.ZipFile(path) as archive:
            size = sum(archive.getinfo(f'video/{i:09d}.png').file_size for i in range(len(cache.times)))
            if size > 4 * 1024**3:
                raise ValueError('La vidéo du projet dépasse 4 Go.')
            for i in range(len(cache.times)):
                Path(cache.path(i)).write_bytes(archive.read(f'video/{i:09d}.png'))
        window.video_tab.slider.setRange(0, len(cache.times)-1)
        window.video_tab._show_frame(min(video['index'], len(cache.times)-1))
        window.video_tab.status.setText('Vidéo intégrée au projet · Lecture sans son.')
    window.tabs.setCurrentIndex(state.get('tab', 0))
    restore_views(window, graphs)
    model.undo_stack.clear()


def restore_views(window, graphs):
    for subwindow, saved in zip(window.graph_tab.windows, graphs):
        graph = subwindow.graph
        graph._refresh_timer.stop()
        graph.plot.setRange(xRange=saved['view'][0], yRange=saved['view'][1], padding=0)
        graph.right_view.setYRange(*saved['right_view'][1], padding=0)
        if saved['legend']:
            graph.legend.manual = True
            graph.legend.setPos(*saved['legend'])
        if window.graph_tab.arrangement.currentIndex() == 3:
            subwindow.setGeometry(*saved['geometry'])

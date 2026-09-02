import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFormLayout, QLabel, QLineEdit, QPushButton,
    QWidget)

from vantage.helpers.interaction import ButtonPolishFilter
from vantage.helpers.responsive import ResponsiveActionBar, polish_form, scrollable
from vantage.helpers.splash import StartupSplash


def _app():
    return QApplication.instance() or QApplication([])


def test_scrollable_marks_dark_responsive_surfaces():
    _app()
    page = QWidget()
    area = scrollable(page, "TestScroll")

    assert area.widgetResizable()
    assert area.viewport().property("ResponsiveViewport") is True
    assert page.property("ResponsivePage") is True


def test_forms_wrap_and_action_bar_reflows_without_clipping():
    app = _app()
    form = polish_form(QFormLayout())
    assert form.rowWrapPolicy() == QFormLayout.RowWrapPolicy.WrapLongRows

    bar = ResponsiveActionBar(min_cell_width=80)
    buttons = [QPushButton(str(index)) for index in range(4)]
    for button in buttons:
        bar.addWidget(button)
    bar.resize(170, 120)
    bar.show()
    app.processEvents()
    assert bar._columns == 2

    bar.resize(90, 180)
    app.processEvents()
    assert bar._columns == 1


def test_button_polish_adds_pointer_focus_and_accessible_name():
    _app()
    button = QPushButton("Guardar")
    filter_ = ButtonPolishFilter(button)
    filter_.eventFilter(button, QEvent(QEvent.Type.Polish))

    assert button.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert button.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert button.accessibleName() == "Guardar"

    button.setEnabled(False)
    filter_.eventFilter(button, QEvent(QEvent.Type.EnabledChange))
    assert button.cursor().shape() == Qt.CursorShape.ArrowCursor


def test_polish_adds_tooltips_to_labeled_interactive_controls():
    _app()
    host = QWidget()
    form = QFormLayout(host)
    field = QLineEdit()
    choice = QComboBox()
    choice.addItem("Normal")
    form.addRow(QLabel("Nombre"), field)
    form.addRow(QLabel("Modo"), choice)
    filter_ = ButtonPolishFilter(host)

    filter_.eventFilter(field, QEvent(QEvent.Type.Polish))
    filter_.eventFilter(choice, QEvent(QEvent.Type.Polish))

    assert "Nombre" in field.toolTip()
    assert "Modo" in choice.toolTip()
    assert "list" in choice.toolTip()


def test_splash_reports_real_loading_progress_and_closes():
    _app()
    splash = StartupSplash()
    splash.step("Loading maps and game documents…", 24)

    assert splash.status.text() == "Loading maps and game documents…"
    assert splash.progress.value() == 24
    assert splash.accessibleDescription() == splash.status.text()
    assert splash.findChild(
        QLabel, "StartupSplashCreator").text() == (
            "Created by Mindflux / Harmflux · P99 Green Server")

    splash.complete()
    assert splash.progress.value() == 100
    assert splash.isHidden()

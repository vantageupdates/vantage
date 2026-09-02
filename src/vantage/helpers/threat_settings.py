"""Compact editor for the local threat estimator."""

from copy import deepcopy

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialogButtonBox, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from vantage.helpers.threat import WEAPON_TYPES, Weapon
from vantage.helpers.threat_presets import WEAPON_PRESETS, find_weapon_preset
from vantage.helpers.scaled_dialog import UniformScaleDialog
from vantage.helpers.responsive import ensure_tab_tooltips


class WeaponEditor(QWidget):
    def __init__(self, value, hand, parent=None):
        super().__init__(parent)
        weapon = Weapon.from_mapping(value)
        layout = QFormLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(5)

        self.name = QLineEdit(weapon.name)
        self.name.setPlaceholderText(f"{hand} weapon name")
        self.name.setClearButtonEnabled(True)
        self.name.setToolTip(
            "Your label for this weapon; it is stored locally in Vantage")
        layout.addRow("Name", self.name)

        self.weapon_type = QComboBox()
        for code, label in WEAPON_TYPES:
            self.weapon_type.addItem(label, code)
        index = self.weapon_type.findData(weapon.weapon_type)
        self.weapon_type.setCurrentIndex(max(0, index))
        self.weapon_type.setToolTip(
            "Attack animation type used to distinguish main-hand and off-hand attempts")
        layout.addRow("Type", self.weapon_type)

        self.damage = QSpinBox()
        self.damage.setRange(0, 1000)
        self.damage.setValue(weapon.damage)
        self.damage.setToolTip(
            "Base item damage; threat is based on weapon stats, not the damage dealt")
        layout.addRow("Damage", self.damage)

        self.delay = QSpinBox()
        self.delay.setRange(0, 1000)
        self.delay.setValue(weapon.delay)
        self.delay.setToolTip(
            "Weapon delay, retained for your configuration and future rate calculations")
        layout.addRow("Delay", self.delay)

        self.damage_bonus = QSpinBox()
        self.damage_bonus.setRange(0, 1000)
        self.damage_bonus.setValue(weapon.damage_bonus)
        self.damage_bonus.setToolTip(
            "Two-hand damage bonus; ignored for one-hand and hand-to-hand weapons")
        layout.addRow("2H bonus", self.damage_bonus)

        proc = QGroupBox("Optional proc")
        proc.setToolTip(
            "A configured landed or resisted message adds proc threat once")
        proc_layout = QFormLayout(proc)
        proc_layout.setContentsMargins(7, 7, 7, 7)
        proc_layout.setSpacing(5)
        self.proc_threat = QSpinBox()
        self.proc_threat.setRange(-100000, 100000)
        self.proc_threat.setValue(weapon.proc_threat)
        self.proc_threat.setToolTip(
            "Estimated threat added when either proc message appears")
        proc_layout.addRow("Threat", self.proc_threat)
        self.proc_landed = QLineEdit(weapon.proc_landed)
        self.proc_landed.setPlaceholderText("e.g. {target} is engulfed in flames.")
        self.proc_landed.setClearButtonEnabled(True)
        self.proc_landed.setToolTip(
            "Plain log-text fragment for a landed proc; {target} resolves to the active target")
        proc_layout.addRow("Landed text", self.proc_landed)
        self.proc_resisted = QLineEdit(weapon.proc_resisted)
        self.proc_resisted.setPlaceholderText("e.g. Your target resisted the … spell.")
        self.proc_resisted.setClearButtonEnabled(True)
        self.proc_resisted.setToolTip(
            "Plain log-text fragment for a resisted proc; leave blank if unavailable")
        proc_layout.addRow("Resisted text", self.proc_resisted)
        layout.addRow(proc)

        self.preset = QComboBox()
        self.preset.setEditable(True)
        self.preset.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.preset.setAccessibleName(f'{hand} verified weapon preset')
        self.preset.setToolTip(
            'Choose a classic preset or type an alias such as jbow, willsapper, or earth')
        self.preset.addItem('Custom / manual', None)
        selected = 0
        for index, preset in enumerate(WEAPON_PRESETS, 1):
            self.preset.addItem(preset['name'], preset)
            aliases = ', '.join(preset['aliases'])
            self.preset.setItemData(
                index,
                f"Aliases: {aliases} · {preset['damage']}/{preset['delay']} · "
                f"{preset['type'].upper()}",
                Qt.ItemDataRole.ToolTipRole)
            if find_weapon_preset(weapon.name) is preset:
                selected = index
        self.preset.setCurrentIndex(selected)
        self.preset.activated.connect(self._apply_preset_index)
        self.preset.lineEdit().returnPressed.connect(self._apply_typed_preset)
        layout.insertRow(0, 'Preset', self.preset)

    def _apply_typed_preset(self):
        preset = find_weapon_preset(self.preset.currentText())
        if preset:
            index = self.preset.findText(preset['name'])
            self.preset.setCurrentIndex(index)
            self._apply_preset(preset)

    def _apply_preset_index(self, index):
        preset = self.preset.itemData(index)
        if isinstance(preset, dict):
            self._apply_preset(preset)

    def _apply_preset(self, preset):
        self.name.setText(preset['name'])
        index = self.weapon_type.findData(preset['type'])
        self.weapon_type.setCurrentIndex(max(0, index))
        self.damage.setValue(preset['damage'])
        self.delay.setValue(preset['delay'])
        self.damage_bonus.setValue(preset['damage_bonus'])
        self.proc_threat.setValue(preset['proc_threat'])
        self.proc_landed.setText(preset['proc_landed'])
        self.proc_resisted.setText(preset['proc_resisted'])

    def value(self):
        return {
            "name": self.name.text().strip() or "Unconfigured",
            "type": self.weapon_type.currentData(),
            "damage": self.damage.value(),
            "delay": self.delay.value(),
            "damage_bonus": self.damage_bonus.value(),
            "proc_threat": self.proc_threat.value(),
            "proc_landed": self.proc_landed.text().strip(),
            "proc_resisted": self.proc_resisted.text().strip(),
        }


class ThreatSettingsDialog(UniformScaleDialog):
    def __init__(self, settings, parent=None):
        super().__init__(
            QSize(560, 590), parent, minimum_size=QSize(196, 207),
            initial_size=QSize(448, 472))
        self._original = deepcopy(settings if isinstance(settings, dict) else {})
        self.setWindowTitle("Threat Estimate Setup")
        self.setObjectName("ThreatSettingsDialog")
        layout = QVBoxLayout(self.scaled_surface)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)

        intro = QLabel(
            "LOCAL ESTIMATE · P99 logs do not expose the server hate list. "
            "Vantage counts observable swings, skills, configured procs, and supported spells.")
        intro.setObjectName("CombatDataNotice")
        intro.setWordWrap(True)
        intro.setToolTip(
            "No process memory, injection, game control, or remote threat service is used")
        layout.addWidget(intro)

        options = QGroupBox("Estimator")
        form = QFormLayout(options)
        form.setContentsMargins(8, 7, 8, 7)
        form.setSpacing(6)
        self.enabled = QCheckBox("Parse local threat")
        self.enabled.setChecked(bool(self._original.get("enabled", True)))
        self.enabled.setToolTip(
            "Turn local threat parsing on or off without deleting weapon settings")
        form.addRow(self.enabled)
        self.main_rate = QSpinBox()
        self.main_rate.setRange(5, 95)
        self.main_rate.setSuffix("%")
        self.main_rate.setValue(int(self._original.get("same_type_main_rate", 55)))
        self.main_rate.setToolTip(
            "Estimated main-hand share when both weapons use the same attack animation")
        form.addRow("Same-type main share", self.main_rate)
        layout.addWidget(options)

        tabs = QTabWidget()
        tabs.setObjectName("ThreatSettingsTabs")
        tabs.setDocumentMode(True)
        tabs.tabBar().setDrawBase(False)
        tabs.setToolTip("Configure each hand independently")
        self.main = WeaponEditor(
            self._original.get("main_hand", {}), "Main-hand", tabs)
        self.off = WeaponEditor(
            self._original.get("off_hand", {}), "Off-hand", tabs)
        tabs.addTab(self.main, "Main hand")
        tabs.addTab(self.off, "Off hand")
        ensure_tab_tooltips(tabs, {
            "Main hand": "Configure main-hand swings, damage, and proc threat",
            "Off hand": "Configure off-hand swings, damage, and proc threat",
        })
        layout.addWidget(tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel)
        save = buttons.button(QDialogButtonBox.StandardButton.Save)
        save.setText("Save")
        save.setObjectName("PrimaryAction")
        save.setToolTip("Save weapon and proc settings to Vantage")
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setToolTip("Close without changing threat settings")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self):
        return {
            "enabled": self.enabled.isChecked(),
            "same_type_main_rate": self.main_rate.value(),
            "main_hand": self.main.value(),
            "off_hand": self.off.value(),
        }

"""Standalone, live-log /random scoreboard for Project 1999."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QAccessible, QAccessibleAnnouncementEvent, QColor)
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout)

from vantage.helpers.combat import RANDOM_ROLLER, RANDOM_VALUE
from vantage.helpers.icons import game_icon
from vantage.helpers.parser import ParserWindow
from vantage.helpers.responsive import ensure_table_header_tooltips


@dataclass(frozen=True)
class RandomRoll:
    player: str
    value: int
    high: int


class RandomParser(ParserWindow):
    """Display valid zero-based rolls from exact EQ result-line pairs."""

    name = "random_parser"
    _allow_clickthrough = False

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Random Parser")
        self._title.setText("Random Parser")
        self._pending_roll = None
        # Hidden parsers continue receiving the live log; bound the scoreboard
        # so an unattended session cannot grow memory without limit.
        self._rolls = deque(maxlen=500)
        self._accepted_players = set()
        self._locked_high = None
        self._round = 1
        self._build_ui()
        self._render()

    def _build_ui(self):
        panel = QFrame()
        panel.setObjectName("RandomParserPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(7, 5, 7, 7)
        layout.setSpacing(5)

        self.summary = QLabel()
        self.summary.setObjectName("CombatDataNotice")
        self.summary.setWordWrap(True)
        self.summary.setAccessibleName("Random round status")
        self.summary.setToolTip(
            "Winner status calculated only from exact zero-based EQ /random results")
        layout.addWidget(self.summary)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(4)
        self.new_round_button = QPushButton("New Round")
        self.new_round_button.setIcon(game_icon("roll"))
        self.new_round_button.setAccessibleName("Start a new random round")
        self.new_round_button.setToolTip(
            "Clear the current scoreboard and advance to the next round")
        self.new_round_button.clicked.connect(self.new_round)
        controls.addWidget(self.new_round_button)

        self.clear_button = QPushButton("Clear")
        self.clear_button.setIcon(game_icon("delete"))
        self.clear_button.setAccessibleName("Clear current random rolls")
        self.clear_button.setToolTip(
            "Clear this round without changing its round number")
        self.clear_button.clicked.connect(self.clear_rolls)
        controls.addWidget(self.clear_button)

        self.reset_button = QPushButton("Reset")
        self.reset_button.setIcon(game_icon("refresh"))
        self.reset_button.setAccessibleName("Reset the random parser")
        self.reset_button.setToolTip(
            "Clear all current rolls and return to round one")
        self.reset_button.clicked.connect(self.reset)
        controls.addWidget(self.reset_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(("Player", "Roll", "Result"))
        ensure_table_header_tooltips(self.table, "the Random Parser")
        for column in range(self.table.columnCount()):
            heading = self.table.horizontalHeaderItem(column)
            heading.setData(
                Qt.ItemDataRole.AccessibleTextRole,
                f"Random Parser {heading.text()} column")
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setAccessibleName("Current random round participants")
        self.table.setAccessibleDescription(
            "Players and valid zero-based rolls, sorted highest first; winner and ties are written in the Result column")
        self.table.setToolTip(
            "Only EQ result pairs whose reported lower bound is exactly zero appear")
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)
        self.content.addWidget(panel, 1)

    @staticmethod
    def _elapsed_seconds(earlier, later):
        try:
            return abs((later - earlier).total_seconds())
        except (AttributeError, TypeError):
            return 0.0

    def parse(self, timestamp, text):
        text = str(text or "")
        roller = RANDOM_ROLLER.fullmatch(text)
        if roller:
            player = " ".join(roller.group("player").split())
            self._pending_roll = (
                timestamp, player) if 0 < len(player) <= 80 else None
            return
        result = RANDOM_VALUE.fullmatch(text)
        if not result:
            return
        pending = self._pending_roll
        self._pending_roll = None
        if not pending or self._elapsed_seconds(pending[0], timestamp) > 5.0:
            return
        low = int(result.group("low"))
        high = int(result.group("high"))
        value = int(result.group("value"))
        if low != 0 or high < 0 or not 0 <= value <= high:
            return
        player_key = pending[1].casefold()
        if (self._locked_high is not None and high != self._locked_high) or \
                player_key in self._accepted_players:
            return
        if self._locked_high is None:
            self._locked_high = high
        self._accepted_players.add(player_key)
        self._rolls.append(RandomRoll(pending[1], value, high))
        self._render(announce=True)

    def _render(self, announce=False):
        ordered = sorted(
            enumerate(self._rolls), key=lambda entry: (-entry[1].value, entry[0]))
        highest = max((roll.value for roll in self._rolls), default=None)
        winners = [roll.player for roll in self._rolls if roll.value == highest]
        tied = len(winners) > 1
        self.table.setRowCount(len(ordered))
        for row, (_index, roll) in enumerate(ordered):
            is_winner = highest is not None and roll.value == highest
            status = "Tied winner" if is_winner and tied else (
                "Winner" if is_winner else "Participant")
            values = (roll.player, str(roll.value), status)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(
                    Qt.ItemDataRole.AccessibleTextRole,
                    f"{roll.player}, roll {roll.value}, {status}")
                if is_winner:
                    item.setForeground(QColor("#E8C56A"))
                    item.setFont(self._winner_font(item.font()))
                self.table.setItem(row, column, item)
        if highest is None:
            status_text = f"ROUND {self._round} · Waiting for valid /random 0 N results"
        elif tied:
            status_text = (
                f"ROUND {self._round} · RANGE 0–{self._locked_high} · "
                f"TIE at {highest}: " +
                ", ".join(winners))
        else:
            status_text = (
                f"ROUND {self._round} · RANGE 0–{self._locked_high} · "
                f"WINNER: {winners[0]} · {highest}")
        self.summary.setText(status_text)
        self.summary.setAccessibleDescription(status_text)
        active_range = (
            f"0–{self._locked_high}" if self._locked_high is not None else
            "not locked")
        self.table.setToolTip(
            f"Active round range: {active_range}. One accepted roll per player; only exact zero-based EQ results appear.")
        if announce:
            QAccessible.updateAccessibility(
                QAccessibleAnnouncementEvent(self.summary, status_text))

    @staticmethod
    def _winner_font(font):
        font.setBold(True)
        return font

    def clear_rolls(self):
        self._pending_roll = None
        self._rolls.clear()
        self._accepted_players.clear()
        self._locked_high = None
        self._render()
        self.new_round_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def new_round(self):
        self._round += 1
        self._pending_roll = None
        self._rolls.clear()
        self._accepted_players.clear()
        self._locked_high = None
        self._render()
        self.new_round_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def reset(self):
        self._round = 1
        self._pending_roll = None
        self._rolls.clear()
        self._accepted_players.clear()
        self._locked_high = None
        self._render()
        self.reset_button.setFocus(Qt.FocusReason.OtherFocusReason)

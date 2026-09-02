"""Small, opt-out visual emphasis for isolated call-to-action controls."""

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QPauseAnimation, QPropertyAnimation,
    QSequentialAnimationGroup)
from PySide6.QtWidgets import QGraphicsOpacityEffect


def attach_subtle_pulse(widget, enabled=True, minimum_opacity=0.86,
                        pause_ms=1100):
    """Attach one low-frequency opacity pulse and retain it on the widget."""
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(1.0)
    widget.setGraphicsEffect(effect)
    animation = QSequentialAnimationGroup(widget)
    fade_down = QPropertyAnimation(effect, b"opacity", animation)
    fade_down.setDuration(150)
    fade_down.setStartValue(1.0)
    fade_down.setEndValue(float(minimum_opacity))
    fade_down.setEasingCurve(QEasingCurve.Type.InOutSine)
    fade_up = QPropertyAnimation(effect, b"opacity", animation)
    fade_up.setDuration(150)
    fade_up.setStartValue(float(minimum_opacity))
    fade_up.setEndValue(1.0)
    fade_up.setEasingCurve(QEasingCurve.Type.InOutSine)
    animation.addAnimation(fade_down)
    animation.addAnimation(fade_up)
    animation.addAnimation(QPauseAnimation(max(0, int(pause_ms)), animation))
    animation.setLoopCount(-1)
    widget._vantage_pulse_effect = effect
    widget._vantage_pulse_animation = animation
    set_subtle_pulse_enabled(widget, enabled)
    return animation


def set_subtle_pulse_enabled(widget, enabled):
    """Start the pulse or leave the emphasized control fully opaque."""
    animation = getattr(widget, "_vantage_pulse_animation", None)
    effect = getattr(widget, "_vantage_pulse_effect", None)
    if animation is None or effect is None:
        return
    if enabled:
        if animation.state() != QAbstractAnimation.State.Running:
            animation.start()
    else:
        animation.stop()
        effect.setOpacity(1.0)

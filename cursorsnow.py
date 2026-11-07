"""
A little snow hat on the mouse pointer.

Leave the mouse still for a couple of seconds and nearby flakes start
drifting towards it and settle on the arrow's tip, building up a hat of
snow. Move the mouse and the hat falls off, tumbling down to the taskbar.

Positions are in overlay pixels; the anchor is the pointer's tip.
"""

import math
import random

from PyQt6.QtGui import QPainter, QPainterPath

STILL_DELAY = 2.0       # s the mouse must rest before snow starts settling on it
STILL_TOLERANCE = 3     # px of wobble that still counts as resting
MAGNET_RAMP = 2.0       # s for the pull on nearby flakes to reach full strength
MAX_SNOW = 420          # px² of snow in a full hat
HAT_CLUMP_AREA = 22     # px² per clump when the hat falls off
HAT_ENABLED = True


class CursorSnow:
    """The snow sitting on the mouse pointer."""

    def __init__(self):
        self.visible = False
        self.anchor = None    # where the pointer came to rest
        self.previous = None  # where it was last frame
        self.vx = self.vy = 0.0
        self.still_for = 0.0
        self.amount = 0.0     # px² of snow on the pointer

    def follow(self, cursor, dt):
        """Track the pointer. Returns the clumps that fell off as (x, y, area), if it moved."""
        self.visible = cursor is not None
        if cursor is None:
            self.previous = None  # hidden: keep the hat, but don't guess a speed later
            return []
        if self.previous is not None:
            self.vx = (cursor[0] - self.previous[0]) / dt
            self.vy = (cursor[1] - self.previous[1]) / dt
        self.previous = cursor
        if self.anchor is not None and math.dist(cursor, self.anchor) <= STILL_TOLERANCE:
            self.still_for += dt
            return []
        loose = self._break_up()
        self.anchor = cursor
        self.still_for = 0.0
        self.amount = 0.0
        return loose

    def forget_motion(self):
        self.previous = None

    def knock_off(self):
        """Knock the whole hat off (e.g. a snowball burst nearby). Returns its clumps."""
        loose = self._break_up()
        self.amount = 0.0
        return loose

    # ----- gathering snow -----

    def gathering(self):
        return (HAT_ENABLED and self.visible and self.still_for >= STILL_DELAY
                and self.amount < MAX_SNOW)

    def magnet(self):
        """(x, y, strength) for steering nearby flakes onto the pointer, or None."""
        if not self.gathering():
            return None
        width, height = self._size()
        strength = min(1.0, (self.still_for - STILL_DELAY) / MAGNET_RAMP)
        return self.anchor[0] + width * 0.05, self.anchor[1] - height, strength

    def catch(self, x, y_before, y_after, area):
        """True if a falling flake landed on the hat."""
        if not self.gathering():
            return False
        width, height = self._size()
        tip_x, tip_y = self.anchor
        top = tip_y - height
        if tip_x - width * 0.4 - 3 <= x <= tip_x + width * 0.5 + 3 and y_before < top <= y_after:
            self.amount = min(MAX_SNOW, self.amount + area)
            return True
        return False

    # ----- shape -----

    def _size(self):
        """(width, height) of the hat; it gets wider and taller as snow builds up."""
        fullness = self.amount / MAX_SNOW
        return 10 + 22 * math.sqrt(fullness), 1.5 + 14 * fullness ** 0.75

    def _break_up(self):
        if self.anchor is None or self.amount < 1:
            return []
        width, height = self._size()
        tip_x, tip_y = self.anchor
        count = max(1, round(self.amount / HAT_CLUMP_AREA))
        each = self.amount / count
        return [(tip_x + random.uniform(-0.4, 0.5) * width, tip_y - random.uniform(0, height), each)
                for _ in range(count)]

    def draw(self, painter, brush, pen):
        """Draw the hat: a puffy mound on the tip, draping down the arrow's slanted edge."""
        if not self.visible or self.anchor is None or self.amount < 3:
            return
        width, height = self._size()
        left, drape = -width * 0.3, width * 0.5
        path = QPainterPath()
        path.moveTo(left, 1.5)
        path.cubicTo(left * 0.9, -height * 0.45, left * 0.6, -height * 0.9, -width * 0.05, -height * 0.95)
        path.quadTo(width * 0.1, -height * 1.08, width * 0.22, -height * 0.9)  # a little lump on top
        path.cubicTo(width * 0.45, -height * 0.8, drape + 1, drape - height * 0.5, drape, drape)
        path.lineTo(0, 0)
        path.closeSubpath()

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(*self.anchor)
        painter.fillPath(path, brush)
        painter.strokePath(path, pen)
        painter.restore()

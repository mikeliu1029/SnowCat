"""
Snowball slingshot.

Left-drag on an empty part of the desktop, or right-drag anywhere (even over
apps): a snowball is pulled back on a rubber band, with a dotted line showing
where it will fly. Let go and it launches, arcs through the air and bursts
when it hits a window, the taskbar, an icon or a pile of snow - knocking
nearby snow flying, scattering the falling flakes and leaving a splat that
slowly fades. A snowball launched over an app flies in front of that app.

The overlay itself can't receive clicks; overlay.py works out the drags
(left button on the desktop, right button via mousehook.py).
"""

import math
import random

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen

from snowcover import make_clump_frames

SLINGSHOT_ENABLED = True
MIN_PULL = 25           # px; shorter drags are ordinary clicks and do nothing
MAX_PULL = 320          # px; pulling further doesn't add power
LAUNCH_POWER = 5.5      # launch speed (px/s) per px of pull
GRAVITY = 1000          # px/s²; lighter than falling clumps, for nice long arcs
BALL_RADIUS = 7
BALL_LIFETIME = 8       # s before a lost snowball (e.g. thrown off screen) is forgotten
BLAST_RADIUS = 130      # px of snow knocked loose around a burst
FLAKE_BLAST_POWER = 700 # px/s given to falling flakes right next to a burst
SPLAT_LIFE = 2.5        # s for a splat mark to fade
RING_LIFE = 0.35        # s for the burst's shock ring
PREVIEW_STEPS = 16      # dots in the aiming line
PREVIEW_STEP_TIME = 0.055

BAND_SLACK = QColor(175, 135, 100, 220)   # rubber band, gently pulled
BAND_TAUT = QColor(235, 95, 70, 235)      # rubber band, pulled all the way


class Snowball:
    __slots__ = ("x", "y", "vx", "vy", "angle", "spin", "age", "armed", "ignore")


class Splat:
    __slots__ = ("x", "y", "life", "blobs")


class Ring:
    __slots__ = ("x", "y", "age")


class SnowballLauncher:
    """Aiming, flying snowballs, and what's left after they burst."""

    def __init__(self, cover, snowfall, pixel_ratio):
        self.cover, self.snowfall = cover, snowfall
        self.anchor = None  # where the drag started, while aiming
        self.aim = None     # where the snowball is pulled back to
        self.source = None  # "left" or "right": which mouse button is pulling
        self.balls, self.splats, self.rings = [], [], []

        rng = random.Random(11)
        self._ball_frames, self._ball_half = make_clump_frames(BALL_RADIUS, pixel_ratio, rng)
        self._splat_sprites = []
        for radius in (3.0, 4.2, 5.5, 7.0):
            frames, half = make_clump_frames(radius, pixel_ratio, rng)
            self._splat_sprites.append((frames[0], half))

    # ----- aiming -----

    @property
    def aiming(self):
        return self.anchor is not None

    def begin_aim(self, point, source):
        """Start pulling the slingshot back from `point`. source says which button is doing it."""
        if SLINGSHOT_ENABLED:
            self.anchor = self.aim = point
            self.source = source

    def release(self):
        """Let go: fire if it was pulled back far enough."""
        if self.anchor is not None:
            self._release()

    def cancel(self):
        """Stop aiming without firing (e.g. when Snowcat is paused)."""
        self.anchor = self.aim = self.source = None

    # ----- each frame -----

    def update(self, dt, cursor):
        """Follow the mouse while aiming, and move the snowballs in the air."""
        if not SLINGSHOT_ENABLED:
            self.cancel()
        elif self.anchor is not None and cursor:
            self.aim = cursor

        self._fly(dt)
        for splat in self.splats:
            splat.life -= dt
            splat.y += 6 * dt  # slides down the window a little
        self.splats = [s for s in self.splats if s.life > 0]
        for ring in self.rings:
            ring.age += dt
        self.rings = [r for r in self.rings if r.age < RING_LIFE]

    def _launch_velocity(self):
        """Slingshot: the snowball flies away from where you pulled it."""
        dx, dy = self.anchor[0] - self.aim[0], self.anchor[1] - self.aim[1]
        pull = math.hypot(dx, dy)
        if pull < MIN_PULL:
            return None
        power = min(pull, MAX_PULL) * LAUNCH_POWER / pull
        return dx * power, dy * power

    def _release(self):
        velocity = self._launch_velocity()
        if velocity:
            ball = Snowball()
            ball.x, ball.y = self.aim
            ball.vx, ball.vy = velocity
            ball.angle = 0.0
            ball.spin = random.uniform(-10, 10)
            ball.age = 0.0
            ball.armed = False  # it can't hit anything until it has cleared whatever it started over
            ball.ignore = self.cover.obstacle_at(ball.x, ball.y)  # launched over an app: fly in front of it
            self.balls.append(ball)
        self.anchor = self.aim = self.source = None

    def _fly(self, dt):
        flying = []
        for ball in self.balls:
            ball.age += dt
            ball.angle += ball.spin * dt
            if self._move_ball(ball, dt):
                continue  # burst
            off_screen = not -40 < ball.x < self.cover.width + 40 or ball.y > self.cover.height + 40
            if not off_screen and ball.age < BALL_LIFETIME:
                flying.append(ball)
                if random.random() < 30 * dt:
                    self.cover.powder(ball.x, ball.y, ball.vx * 0.05, ball.vy * 0.05)
        self.balls = flying

    def _move_ball(self, ball, dt):
        """Move in small steps so a fast snowball can't skip over a thin pile. True if it burst."""
        steps = max(1, math.ceil(math.hypot(ball.vx, ball.vy) * dt / 6))
        step = dt / steps
        for _ in range(steps):
            ball.vy += GRAVITY * step
            ball.x += ball.vx * step
            ball.y += ball.vy * step
            solid = self.cover.is_solid(ball.x, ball.y, ball.ignore)
            if not ball.armed:
                ball.armed = not solid
            elif solid:
                self._burst(ball.x, ball.y)
                return True
        return False

    def _burst(self, x, y):
        self.cover.blast(x, y, BLAST_RADIUS)
        self.snowfall.blast(x, y, BLAST_RADIUS * 1.6, FLAKE_BLAST_POWER)
        self.cover.burst(x, y, 40, 420)

        splat = Splat()
        splat.x, splat.y, splat.life = x, y, SPLAT_LIFE
        splat.blobs = [(random.uniform(-14, 14), random.uniform(-10, 10), random.randrange(len(self._splat_sprites)))
                       for _ in range(random.randint(7, 11))]
        splat.blobs.append((0.0, 0.0, len(self._splat_sprites) - 1))  # a big lump in the middle
        self.splats.append(splat)

        ring = Ring()
        ring.x, ring.y, ring.age = x, y, 0.0
        self.rings.append(ring)

    # ----- drawing -----

    def draw(self, painter):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_splats(painter)
        self._draw_rings(painter)
        for ball in self.balls:
            self._draw_ball(painter, ball.x, ball.y, ball.angle)
        if self.anchor is not None:
            self._draw_aim(painter)
        painter.restore()

    def _draw_ball(self, painter, x, y, angle):
        count = len(self._ball_frames)
        frame = self._ball_frames[int(angle / math.tau * count) % count]
        painter.drawPixmap(QPointF(x - self._ball_half, y - self._ball_half), frame)

    def _draw_splats(self, painter):
        for splat in self.splats:
            painter.setOpacity(min(1.0, splat.life / (SPLAT_LIFE * 0.6)))
            for dx, dy, size in splat.blobs:
                pixmap, half = self._splat_sprites[size]
                painter.drawPixmap(QPointF(splat.x + dx - half, splat.y + dy - half), pixmap)
        painter.setOpacity(1.0)

    def _draw_rings(self, painter):
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for ring in self.rings:
            t = ring.age / RING_LIFE
            radius = 10 + BLAST_RADIUS * 0.7 * (1 - (1 - t) ** 3)  # fast, then easing out
            painter.setPen(QPen(QColor(255, 255, 255, int(200 * (1 - t))), 1 + 4 * (1 - t)))
            painter.drawEllipse(QPointF(ring.x, ring.y), radius, radius)

    def _draw_aim(self, painter):
        ax, ay = self.anchor
        bx, by = self.aim
        pull = math.hypot(ax - bx, ay - by)
        velocity = self._launch_velocity()

        if velocity:
            self._draw_preview(painter, bx, by, *velocity)

        # Rubber band: two strands from the slingshot's prongs to the snowball
        tension = min(1.0, pull / MAX_PULL)
        colour = QColor(*(round(a + (b - a) * tension) for a, b in zip(BAND_SLACK.getRgb(), BAND_TAUT.getRgb())))
        painter.setPen(QPen(colour, 3.0 - tension, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if pull > 1:
            side_x, side_y = -(by - ay) / pull * 9, (bx - ax) / pull * 9
        else:
            side_x, side_y = 9, 0
        for sign in (1, -1):
            painter.drawLine(QPointF(ax + side_x * sign, ay + side_y * sign), QPointF(bx, by))
        painter.setPen(QPen(QColor(255, 255, 255, 170), 1.5))
        painter.drawEllipse(QPointF(ax, ay), 4, 4)
        self._draw_ball(painter, bx, by, 0.0)

    def _draw_preview(self, painter, x, y, vx, vy):
        """Dotted line showing where the snowball will fly."""
        painter.setPen(Qt.PenStyle.NoPen)
        ignore = self.cover.obstacle_at(x, y)
        cleared = not self.cover.is_solid(x, y, ignore)
        for i in range(1, PREVIEW_STEPS + 1):
            t = i * PREVIEW_STEP_TIME
            px, py = x + vx * t, y + vy * t + GRAVITY * t * t / 2
            solid = self.cover.is_solid(px, py, ignore)
            if cleared and solid:
                break  # this is where it will hit
            cleared = cleared or not solid
            painter.setBrush(QColor(255, 255, 255, int(220 * (1 - i / (PREVIEW_STEPS + 1)))))
            painter.drawEllipse(QPointF(px, py), 2.3, 2.3)

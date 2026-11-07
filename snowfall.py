"""
Falling snowflakes: how many there are, how they drift, and how they're drawn.

Each flake has a "depth" from 0 (far away) to 1 (close). Close flakes are
bigger, brighter, fall faster and get pushed more by the wind, which gives
the snow a soft sense of depth.

Swipe the mouse quickly through the snow and the flakes near it get blown
along in its wake, then calm down and drift on. Rest the mouse and nearby
flakes drift onto it instead.
"""

import math
import random

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap, QRadialGradient

FLAKES_PER_MEGAPIXEL = 110               # density (1920x1080 -> ~230 flakes)
SIZE_LEVELS = 8                          # number of pre-drawn flake sizes
MIN_RADIUS, MAX_RADIUS = 1.6, 4.6        # px, far -> near
MIN_FALL_SPEED, MAX_FALL_SPEED = 16, 52  # px per second, far -> near
MIN_ALPHA, MAX_ALPHA = 0.45, 0.95        # opacity, far -> near
SWAY_SPEED_RANGE = (4, 18)               # px per second of side-to-side sway
SWAY_FREQ_RANGE = (0.4, 1.2)             # sway wobbles per second (radians)
EDGE_MARGIN = 12                         # px off-screen before a flake wraps/respawns
FALL_SPEED_SCALE = 1.0                   # multiplies every flake's fall speed (settings)
WIND_SCALE = 1.0                         # multiplies the breeze (settings)

# Mouse gusts
GUSTS_ENABLED = True
GUST_MIN_SPEED = 600                     # px/s; slower mouse movement doesn't stir the snow
GUST_MAX_STEP = 400                      # px; bigger jumps are the cursor teleporting, not a swipe
GUST_RADIUS = 190                        # px around the mouse's path that gets blown
GUST_FOLLOW = 0.6                        # share of the mouse's speed a blown flake picks up
GUST_SPREAD = 0.3                        # how hard flakes get pushed out to the sides
GUST_GRIP = 0.5                          # how quickly a flake right by the mouse catches the gust
GUST_CALM = 1.8                          # how quickly blown flakes settle back down (per second)
MAX_GUST_SPEED = 1400                    # px/s

# Snow magnet: flakes drifting onto a resting mouse pointer
MAGNET_WIDTH = 150                       # px either side, at the top of the funnel
MAGNET_HEIGHT = 340                      # px above the pointer that flakes get steered from
MAGNET_GRIP = 2.5                        # how quickly flakes turn towards it (per second)
MAGNET_MAX_STEER = 90                    # px/s


def lerp(a, b, t):
    """Blend from a (t=0) to b (t=1)."""
    return a + (b - a) * t


# ----- flake images ---------------------------------------------------------

def make_flake_sprite(radius, alpha, pixel_ratio):
    """Pre-draw one soft round flake, so each frame is just a fast image copy.

    The rim is a faint blue-grey so flakes stay visible over white windows.
    Returns (pixmap, half_size) where half_size centres the image on a point.
    """
    size = math.ceil(radius * 2 + 2)
    pixmap = QPixmap(round(size * pixel_ratio), round(size * pixel_ratio))
    pixmap.setDevicePixelRatio(pixel_ratio)
    pixmap.fill(Qt.GlobalColor.transparent)

    centre = QPointF(size / 2, size / 2)
    gradient = QRadialGradient(centre, radius)
    gradient.setColorAt(0.0, QColor(255, 255, 255, int(255 * alpha)))
    gradient.setColorAt(0.55, QColor(255, 255, 255, int(235 * alpha)))
    gradient.setColorAt(0.8, QColor(170, 190, 215, int(140 * alpha)))
    gradient.setColorAt(1.0, QColor(170, 190, 215, 0))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawEllipse(centre, radius, radius)
    painter.end()
    return pixmap, size / 2


def make_flake_sprites(pixel_ratio):
    """One sprite per depth level, from small & faint to big & bright."""
    sprites = []
    for level in range(SIZE_LEVELS):
        t = level / (SIZE_LEVELS - 1)
        radius = lerp(MIN_RADIUS, MAX_RADIUS, t)
        alpha = lerp(MIN_ALPHA, MAX_ALPHA, t)
        sprites.append(make_flake_sprite(radius, alpha, pixel_ratio))
    return sprites


# ----- flakes ---------------------------------------------------------------

class Flake:
    """One snowflake. Plain slots keep the per-frame loop fast."""

    __slots__ = ("x", "y", "vx", "vy", "depth", "level", "fall_speed",
                 "sway_speed", "sway_freq", "sway_phase")


class Snowfall:
    """All the falling flakes on one screen."""

    def __init__(self, width, height, pixel_ratio):
        self.width = width
        self.height = height
        self.clock = 0.0  # seconds of snowfall so far (drives wind and sway)
        self.sprites = make_flake_sprites(pixel_ratio)
        self.flakes = [self._new_flake() for _ in range(self._target_count())]

    def _target_count(self):
        """How many flakes this screen size should have."""
        megapixels = self.width * self.height / 1_000_000
        return max(40, int(megapixels * FLAKES_PER_MEGAPIXEL))

    def _new_flake(self):
        """A flake somewhere on screen, so snow is already falling at startup."""
        flake = Flake()
        self._reset_flake(flake, y=random.uniform(-EDGE_MARGIN, self.height))
        return flake

    def _reset_flake(self, flake, y):
        """Give a flake a fresh random look and motion, at height y."""
        depth = random.random() ** 1.6  # more far-away (small) flakes than close ones
        flake.depth = depth
        flake.level = round(depth * (SIZE_LEVELS - 1))
        flake.x = random.uniform(-EDGE_MARGIN, self.width + EDGE_MARGIN)
        flake.y = y
        flake.vx = flake.vy = 0.0  # extra speed from mouse gusts
        flake.fall_speed = lerp(MIN_FALL_SPEED, MAX_FALL_SPEED, depth) * random.uniform(0.85, 1.15)
        flake.sway_speed = random.uniform(*SWAY_SPEED_RANGE)
        flake.sway_freq = random.uniform(*SWAY_FREQ_RANGE)
        flake.sway_phase = random.uniform(0, math.tau)

    def refresh(self):
        """Re-apply settings: add or remove flakes to match the chosen amount of snow."""
        self.resize(self.width, self.height)

    def resize(self, width, height):
        """Adapt to a new screen size, adding or removing flakes to keep the density."""
        self.width, self.height = width, height
        wanted = self._target_count()
        while len(self.flakes) < wanted:
            self.flakes.append(self._new_flake())
        del self.flakes[wanted:]

    # ----- motion -----

    def wind_speed(self):
        """A gentle breeze that slowly changes strength and direction (px/s)."""
        t = self.clock
        return (9 * math.sin(t * 0.07) + 5 * math.sin(t * 0.19 + 1.3)) * WIND_SCALE

    def update(self, dt, catch=None):
        """Advance every flake by dt seconds.

        catch(x, y_before, y_after, depth) is asked whether a flake settled on
        something on its way down; settled flakes start over at the top.
        """
        self.clock += dt
        wind = self.wind_speed()
        calm = math.exp(-GUST_CALM * dt)
        for flake in self.flakes:
            y_before = flake.y
            self._move_flake(flake, wind, calm, dt)
            if catch is not None and catch(flake.x, y_before, flake.y, flake.depth):
                self._reset_flake(flake, y=-EDGE_MARGIN)
            else:
                self._wrap_or_respawn(flake)

    def _move_flake(self, flake, wind, calm, dt):
        """Fall straight down, sway side to side, drift with the wind, and ride any gust."""
        sway = math.sin(self.clock * flake.sway_freq + flake.sway_phase) * flake.sway_speed
        flake.vx *= calm
        flake.vy *= calm
        flake.x += (wind * (0.4 + 0.6 * flake.depth) + sway + flake.vx) * dt
        flake.y += (flake.fall_speed * FALL_SPEED_SCALE + flake.vy) * dt

    def _wrap_or_respawn(self, flake):
        """Flakes leaving the bottom start over at the top; side exits wrap around."""
        if flake.y > self.height + EDGE_MARGIN:
            self._reset_flake(flake, y=-EDGE_MARGIN)
        elif flake.y < -GUST_RADIUS:
            flake.y = -GUST_RADIUS  # blown up off the screen: let it fall back in
            flake.vy = max(flake.vy, 0.0)
        elif flake.x < -EDGE_MARGIN:
            flake.x += self.width + 2 * EDGE_MARGIN
        elif flake.x > self.width + EDGE_MARGIN:
            flake.x -= self.width + 2 * EDGE_MARGIN

    def blow(self, x0, y0, x1, y1, dt):
        """The mouse moved from (x0, y0) to (x1, y1): if that was a fast swipe, blow flakes along."""
        if not GUSTS_ENABLED:
            return
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if dt <= 0 or length > GUST_MAX_STEP or length < GUST_MIN_SPEED * dt:
            return
        speed = length / dt
        vx, vy = dx / dt, dy / dt
        side_x, side_y = -dy / length, dx / length  # points to the left of the swipe
        min_x, max_x = min(x0, x1) - GUST_RADIUS, max(x0, x1) + GUST_RADIUS
        min_y, max_y = min(y0, y1) - GUST_RADIUS, max(y0, y1) + GUST_RADIUS

        for flake in self.flakes:
            if not (min_x < flake.x < max_x and min_y < flake.y < max_y):
                continue
            # Nearest point on the mouse's path this frame
            t = ((flake.x - x0) * dx + (flake.y - y0) * dy) / (length * length)
            t = 0.0 if t < 0 else 1.0 if t > 1 else t
            off_x, off_y = flake.x - (x0 + dx * t), flake.y - (y0 + dy * t)
            distance = math.hypot(off_x, off_y)
            if distance >= GUST_RADIUS:
                continue
            closeness = 1 - distance / GUST_RADIUS
            side = 1 if off_x * side_x + off_y * side_y >= 0 else -1
            spread = speed * GUST_SPREAD * side
            grip = closeness * GUST_GRIP
            flake.vx += (vx * GUST_FOLLOW + side_x * spread - flake.vx) * grip
            flake.vy += (vy * GUST_FOLLOW + side_y * spread - flake.vy) * grip
            blown = math.hypot(flake.vx, flake.vy)
            if blown > MAX_GUST_SPEED:
                flake.vx *= MAX_GUST_SPEED / blown
                flake.vy *= MAX_GUST_SPEED / blown

    def blast(self, x, y, radius, power):
        """Throw flakes outward from a snowball burst at (x, y)."""
        for flake in self.flakes:
            dx, dy = flake.x - x, flake.y - y
            distance = math.hypot(dx, dy)
            if 0 < distance < radius:
                push = power * (1 - distance / radius) / distance
                flake.vx += dx * push
                flake.vy += dy * push
                blown = math.hypot(flake.vx, flake.vy)
                if blown > MAX_GUST_SPEED:
                    flake.vx *= MAX_GUST_SPEED / blown
                    flake.vy *= MAX_GUST_SPEED / blown

    def attract(self, x, y, strength, dt):
        """Steer flakes falling above (x, y) so they land there (snow settling on a resting pointer)."""
        grip = min(1.0, MAGNET_GRIP * strength * dt)
        wind = self.wind_speed()
        for flake in self.flakes:
            above = y - flake.y
            if not 0 < above < MAGNET_HEIGHT:
                continue
            dx = x - flake.x
            if abs(dx) > 20 + MAGNET_WIDTH * above / MAGNET_HEIGHT:  # a funnel, wide at the top
                continue
            fall = flake.fall_speed * FALL_SPEED_SCALE + flake.vy
            if fall <= 5:
                continue
            sway = math.sin(self.clock * flake.sway_freq + flake.sway_phase) * flake.sway_speed
            drift = wind * (0.4 + 0.6 * flake.depth) + sway
            needed = dx * fall / max(above, 15) - drift  # sideways speed that arrives right on target
            needed = max(-MAGNET_MAX_STEER, min(MAGNET_MAX_STEER, needed))
            flake.vx += (needed - flake.vx) * grip

    # ----- drawing -----

    def draw(self, painter):
        """Stamp every flake's pre-drawn image at its position."""
        sprites = self.sprites
        for flake in self.flakes:
            pixmap, half = sprites[flake.level]
            painter.drawPixmap(QPointF(flake.x - half, flake.y - half), pixmap)

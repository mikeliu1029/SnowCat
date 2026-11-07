"""
Snow that settles: on top of your open windows, on the taskbar, and on the
mouse pointer.

- Flakes that touch a window's top edge can settle there and pile up; the
  taskbar and the desktop's shortcut icons collect snow too.
- Shake a window (or fling it hard) and its snow breaks loose in lumpy,
  tumbling clumps that trail powder and burst when they hit the taskbar.
  Closing or maximizing a snowy window drops its snow too.
- Rest the mouse on a pile and the snow under it melts away in a sparkle.
- Leave the mouse still and a little snow hat builds up on it (see
  cursorsnow.py); move it and the hat falls off.
- Snow piled right up to a window's end trickles off as little clumps.

Everything here is in the overlay's own pixels.
"""

import math
import random

from PyQt6.QtCore import QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import (QBrush, QColor, QLinearGradient, QPainter, QPen, QPixmap,
                         QRadialGradient, QRegion)

import win32_helpers
from cursorsnow import CursorSnow
from snowfall import make_flake_sprite
from snowpile import BASE_OVERLAP, SnowPile

# Settling
WINDOW_SNOW_DEPTH = 20      # px; the deepest snow a window can hold
TASKBAR_SNOW_DEPTH = 40     # px; the deepest snow the taskbar can hold
WINDOW_STICK_CHANCE = 0.5   # chance a flake touching a window settles (the rest fall past in front)
TASKBAR_STICK_CHANCE = 1.0  # chance a flake reaching the taskbar settles there
SNOW_PER_FLAKE = 150         # px² of snow one settled flake adds. Raise it for faster piles.
ICONS_ENABLED = True        # snow settles on the desktop's shortcut icons
ICON_SNOW_DEPTH = 12        # px; the deepest snow an icon can hold
ICON_STICK_CHANCE = 0.6     # chance a flake touching an icon settles there
HAT_SNOW_PER_FLAKE = 45    # px² one flake adds to the snow hat on a resting mouse
TOP_EDGE_GAP = 6            # px; windows this close to the top of the screen (maximized) collect none

# Shaking
SHAKE_SWING = 28            # px a window must travel before turning back counts as a shake
SHAKE_FADE = 1.2            # how quickly the shaking "cools down" (per second)
SHAKE_THRESHOLD = 1.5       # shake level where snow starts coming off (about 2 quick back-and-forths)
SHAKE_LOOSEN = 0.5          # share of the snow each further shake knocks loose
FLING_SPEED = 4500          # px/s; moving a window faster than this throws snow off
SNAP_JUMP = 220             # px; a window jumping this far in one frame (snapped) drops all its snow
THROW = 0.7                 # share of the window's speed that loose snow flies off with

# Melting under the mouse
MELT_ENABLED = True
MELT_RADIUS = 34            # px either side of the cursor
MELT_REACH = 10             # px above the snow where the cursor still melts it
RING_OPEN_SPEED = 14        # how quickly the cleared circle springs open (per second)
RIM_SHARE = 0.3             # share of the cleared snow shoved aside into a rim around the hole
RING_PEN = QColor(255, 255, 255)

# Falling clumps
GRAVITY = 1600              # px/s²
CLUMP_AREA_RANGE = (14, 60) # px² of snow per clump (randomly picked, so sizes vary)
CLUMP_RADII = (2.2, 3.0, 3.9, 4.9, 6.0)
CLUMP_SHAPES = 3            # different lumpy shapes per size
CLUMP_ROTATIONS = 12        # pre-drawn angles per shape, so clumps can tumble
MAX_CLUMPS = 600
BOUNCE_SHARE = 0.4          # share of a clump that bounces back up as pieces when it lands
TRAIL_RATE = 9              # powder puffs per second shed by a mid-sized falling clump

# Puffs: melt sparkles, powder trails and landing bursts
MAX_PUFFS = 700
PUFF_AREA = 5               # px² of melted snow per sparkle

LANDING_BUCKET = 64         # px; falling flakes only check surfaces in their own strip of the screen

PILE_EDGE = QPen(QColor(135, 160, 195, 160), 1.0)  # faint outline so snow shows on white windows


def pile_brush(depth):
    """Bright white on top, shading to icy blue where the snow meets the edge."""
    gradient = QLinearGradient(0, -depth, 0, BASE_OVERLAP)
    gradient.setColorAt(0.0, QColor(255, 255, 255, 252))
    gradient.setColorAt(0.6, QColor(245, 249, 255, 252))
    gradient.setColorAt(1.0, QColor(212, 226, 244, 252))
    return QBrush(gradient)


def make_clump_frames(radius, pixel_ratio, rng):
    """A lumpy clump of snow (a few overlapping blobs) drawn at several angles."""
    blobs = [(0.0, 0.0, radius * 0.75)]
    for _ in range(rng.randint(3, 5)):
        angle = rng.uniform(0, math.tau)
        distance = radius * rng.uniform(0.3, 0.55)
        blobs.append((math.cos(angle) * distance, math.sin(angle) * distance,
                      radius * rng.uniform(0.4, 0.62)))
    size = math.ceil(radius * 2.4 + 3)
    frames = []
    for k in range(CLUMP_ROTATIONS):
        pixmap = QPixmap(round(size * pixel_ratio), round(size * pixel_ratio))
        pixmap.setDevicePixelRatio(pixel_ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.translate(size / 2, size / 2)
        painter.rotate(360 * k / CLUMP_ROTATIONS)
        for x, y, r in blobs:
            shade = QRadialGradient(QPointF(x - r * 0.25, y - r * 0.25), r * 1.1)
            shade.setColorAt(0.0, QColor(255, 255, 255, 255))
            shade.setColorAt(0.65, QColor(240, 246, 255, 250))
            shade.setColorAt(1.0, QColor(185, 205, 230, 0))
            painter.setBrush(shade)
            painter.drawEllipse(QPointF(x, y), r, r)
        painter.end()
        frames.append(pixmap)
    return frames, size / 2


# ----- small moving things --------------------------------------------------

class Clump:
    """A lump of snow knocked loose, tumbling down towards the taskbar."""
    __slots__ = ("x", "y", "vx", "vy", "area", "frames", "half", "angle", "spin", "bounced")


class Puff:
    """A wisp of powder: a melt sparkle, a bit of trail, or spray from a landing."""
    __slots__ = ("x", "y", "vx", "vy", "gravity", "life", "max_life", "sprite")


class Swing:
    """Notices a window turning back after a decent swing along one axis."""
    __slots__ = ("direction", "distance")

    def __init__(self):
        self.direction, self.distance = 0, 0.0

    def turned_back(self, step):
        if abs(step) < 0.5:
            return False
        direction = 1 if step > 0 else -1
        if direction == self.direction:
            self.distance += abs(step)
            return False
        was_swinging = self.direction != 0 and self.distance >= SHAKE_SWING
        self.direction, self.distance = direction, abs(step)
        return was_swinging


# ----- surfaces -------------------------------------------------------------

class Surface:
    """Something snow can settle on: the top edge of a window, or the taskbar."""

    def __init__(self, width, depth, kind="window"):
        self.pile = SnowPile(width, depth)
        self.kind = kind         # "window", "taskbar" or "icon"
        self.left = self.top = self.right = 0.0
        self.on_screen = False
        self.spans = []          # stretches of the edge you can actually see: [(x0, x1), ...]
        self.clip = QRegion()    # where its snow may be drawn (not over windows stacked above)
        self.spill_left = self.spill_right = 0.0  # snow slid off the ends, waiting to fall
        self.reset_motion()

    def reset_motion(self):
        self.vx = self.vy = 0.0  # px/s, smoothed
        self.shake = 0.0
        self.swing_x, self.swing_y = Swing(), Swing()

    def edge_visible_at(self, x):
        for start, end in self.spans:
            if start <= x < end:
                return True
        return False


class SnowCover:
    """All the settled snow on one screen, plus whatever is falling off or melting."""

    def __init__(self, width, height, pixel_ratio):
        self.width, self.height = width, height
        self.windows = {}  # hwnd -> Surface, kept while a window is minimized so its snow survives
        self.taskbar = Surface(width, TASKBAR_SNOW_DEPTH, "taskbar")
        self.icons = {}    # desktop icon number -> Surface
        self.cursor_snow = CursorSnow()
        self.clumps = []
        self.puffs = []
        self._ring_radius = 0.0  # the cleared circle around the mouse, while it's on snow
        self._ring_glow = 0.0
        self._ring_at = None
        self._showing = []    # surfaces on screen this frame
        self._obstacles = []  # (key, left, top, right, bottom) of everything solid, top-most first
        self._buckets = []    # surfaces that can catch flakes, per strip of the screen

        rng = random.Random(7)  # same lumpy shapes every run
        self._clump_shapes = [[make_clump_frames(r, pixel_ratio, rng) for _ in range(CLUMP_SHAPES)]
                              for r in CLUMP_RADII]
        self._sparkle_sprite = make_flake_sprite(2.0, 0.9, pixel_ratio)
        self._powder_sprite = make_flake_sprite(1.5, 0.8, pixel_ratio)
        self._hat_brush = pile_brush(16)
        self._make_brushes()

    def _make_brushes(self):
        self._brushes = {"window": pile_brush(WINDOW_SNOW_DEPTH),
                         "taskbar": pile_brush(TASKBAR_SNOW_DEPTH),
                         "icon": pile_brush(ICON_SNOW_DEPTH)}

    def refresh(self):
        """Re-apply settings that are baked into existing piles (how deep snow can get)."""
        self._make_brushes()
        for surface in self.windows.values():
            surface.pile.set_max_height(WINDOW_SNOW_DEPTH)
        self.taskbar.pile.set_max_height(TASKBAR_SNOW_DEPTH)
        for surface in self.icons.values():
            surface.pile.set_max_height(ICON_SNOW_DEPTH)

    def clear_all(self):
        """Make every bit of settled snow vanish in a sparkle."""
        for surface in [*self.windows.values(), *self.icons.values(), self.taskbar]:
            loose = surface.pile.shake_off(1.0)
            if surface.on_screen:
                for x, height, _ in loose[::3]:
                    self._puff(surface.left + x, surface.top - height * random.random(),
                               random.uniform(-35, 35), random.uniform(-75, -15),
                               gravity=0, life=random.uniform(0.35, 0.8), sprite=self._sparkle_sprite)
        self.cursor_snow.knock_off()
        self.clumps = []

    def resize(self, width, height):
        self.width, self.height = width, height
        self.taskbar.pile.resize(width, keep_right=False)

    def forget_motion(self):
        """After a pause, don't mistake windows (or the mouse) that moved meanwhile for a shake."""
        for surface in self.windows.values():
            surface.on_screen = False
        self.cursor_snow.forget_motion()

    # ----- following the windows -----

    def follow_windows(self, boxes, to_local, dt, icons=()):
        """Line the snow up with where every window (and desktop icon) is now.

        boxes: win32_helpers.WindowBox list, top-most first.
        to_local: converts a physical screen position to overlay pixels.
        icons: desktop icon picture boxes in physical pixels (they sit below every window).
        """
        obstacles = []  # everything a snowball can hit, top-most first
        above = []      # boxes of everything stacked above the window being looked at
        placed = set()  # windows holding snow this frame
        in_view = set() # windows on screen that can't hold snow right now (e.g. maximized)
        showing = []
        taskbar_found = False

        for box in boxes:
            left, top = to_local(box.left, box.top)
            right, bottom = to_local(box.right, box.bottom)
            if box.role == win32_helpers.ROLE_TASKBAR:
                if not taskbar_found and self._along_bottom(left, top, right):
                    self._place_taskbar(top, above, showing)
                    taskbar_found = True
            elif box.role == win32_helpers.ROLE_WINDOW:
                if TOP_EDGE_GAP < top < self.height - 4 and right > 0 and left < self.width:
                    self._place_window(box.hwnd, left, top, right, dt, above, showing)
                    placed.add(box.hwnd)
                else:
                    in_view.add(box.hwnd)
            above.append((left, top, right, bottom))
            obstacles.append((box.hwnd, left, top, right, bottom))

        if not taskbar_found:
            # Taskbar hidden or on a side: snow gathers on the bottom of the screen instead.
            self._place_taskbar(self.height, above, showing)
        self._place_icons(icons, to_local, above, showing, obstacles)
        self._handle_missing_windows(placed, in_view)
        self._showing = showing
        self._obstacles = obstacles
        self._sort_into_buckets(showing)

    def _place_icons(self, icons, to_local, above, showing, obstacles):
        if len(icons) != len(self.icons):
            # Icons added, removed or switched off: start them all fresh (their snow falls off).
            for surface in self.icons.values():
                if surface.on_screen:
                    self._knock_loose(surface, 1.0)
            self.icons = {}
        for i, (box_left, box_top, box_right, box_bottom) in enumerate(icons):
            left, top = to_local(box_left, box_top)
            right, bottom = to_local(box_right, box_bottom)
            surface = self.icons.get(i)
            if surface is None:
                surface = self.icons[i] = Surface(right - left, ICON_SNOW_DEPTH, "icon")
            elif abs(left - surface.left) > 1 or abs(top - surface.top) > 1:
                self._knock_loose(surface, 1.0)  # the icon was dragged somewhere else: its snow falls off
                surface.pile.resize(right - left, keep_right=False)
            surface.left, surface.top, surface.right = left, top, right
            surface.on_screen = True
            self._find_visible_part(surface, above)
            showing.append(surface)
            obstacles.append((("icon", i), left, top, right, bottom))

    def _sort_into_buckets(self, showing):
        """Group the surfaces you can see by strip of screen, so flakes only check nearby ones."""
        buckets = [[] for _ in range(int(self.width // LANDING_BUCKET) + 1)]
        last = len(buckets) - 1
        for surface in showing:
            if surface.spans:
                first = max(0, min(last, int(surface.left // LANDING_BUCKET)))
                end = max(0, min(last, int(surface.right // LANDING_BUCKET)))
                for b in range(first, end + 1):
                    buckets[b].append(surface)
        self._buckets = buckets

    def _along_bottom(self, left, top, right):
        return top > self.height / 2 and right - left >= self.width / 2

    def _place_taskbar(self, top, above, showing):
        bar = self.taskbar
        bar.left, bar.top, bar.right = 0.0, top, float(self.width)
        bar.on_screen = True
        self._find_visible_part(bar, above)
        showing.append(bar)

    def _place_window(self, hwnd, left, top, right, dt, above, showing):
        surface = self.windows.get(hwnd)
        if surface is None:
            surface = self.windows[hwnd] = Surface(right - left, WINDOW_SNOW_DEPTH)
            surface.left, surface.top, surface.right = left, top, right

        keep_right = abs(right - surface.right) < 0.5 and abs(left - surface.left) >= 0.5
        dx, dy = left - surface.left, top - surface.top
        surface.left, surface.top, surface.right = left, top, right
        self._drop(surface, surface.pile.resize(right - left, keep_right))

        if surface.on_screen:
            self._feel_motion(surface, dx, dy, dt)
        else:
            surface.reset_motion()  # just reappeared: its jump isn't a shake
        surface.on_screen = True
        self._find_visible_part(surface, above)
        showing.append(surface)

    def _find_visible_part(self, surface, above):
        """Work out which parts of the snow aren't hidden behind windows stacked above."""
        top = surface.top
        band_top = top - surface.pile.max_height - 2
        band_bottom = top + BASE_OVERLAP + 1
        for left, other_top, right, bottom in above:
            if left <= surface.left and right >= surface.right and other_top <= band_top and bottom >= band_bottom:
                surface.clip, surface.spans = QRegion(), []  # completely behind one window
                return
        clip = QRegion(_rect(surface.left, band_top, surface.right, band_bottom))
        spans = [(surface.left, surface.right)]
        for left, other_top, right, bottom in above:
            if right <= surface.left or left >= surface.right or bottom <= band_top or other_top >= band_bottom:
                continue
            clip = clip.subtracted(QRegion(_rect(left, other_top, right, bottom)))
            if other_top <= top and bottom >= top - 1:  # it covers the edge itself
                spans = _cut_span(spans, left, right)
        surface.clip, surface.spans = clip, spans

    def _handle_missing_windows(self, placed, in_view):
        for hwnd, surface in list(self.windows.items()):
            if hwnd in placed:
                continue
            if hwnd in in_view or not win32_helpers.window_exists(hwnd):
                # Maximized, pushed off the top, or closed: the snow falls off.
                if surface.on_screen:
                    self._knock_loose(surface, 1.0)
                del self.windows[hwnd]
            else:
                surface.on_screen = False  # minimized or on another desktop: keep its snow for later

    # ----- shaking -----

    def _feel_motion(self, surface, dx, dy, dt):
        """Notice a window being shaken or flung, and knock its snow loose."""
        surface.vx += (dx / dt - surface.vx) * 0.5
        surface.vy += (dy / dt - surface.vy) * 0.5
        if math.hypot(dx, dy) >= SNAP_JUMP:
            self._knock_loose(surface, 1.0)
            return

        surface.shake = max(0.0, surface.shake - SHAKE_FADE * dt)
        turns = surface.swing_x.turned_back(dx) + surface.swing_y.turned_back(dy)
        if turns:
            surface.shake += turns
            if surface.shake >= SHAKE_THRESHOLD:
                self._knock_loose(surface, SHAKE_LOOSEN)

        speed = math.hypot(surface.vx, surface.vy)
        if speed > FLING_SPEED:
            self._knock_loose(surface, min(1.0, (speed / FLING_SPEED - 1) * 4 * dt))

    def _knock_loose(self, surface, fraction):
        self._drop(surface, surface.pile.shake_off(fraction), surface.vx, surface.vy)

    def _drop(self, surface, loose, vx=0.0, vy=0.0):
        """Turn loose snow (x, height, area) into clumps that tumble down to the taskbar."""
        gathered = 0.0
        target = random.uniform(*CLUMP_AREA_RANGE)
        for x, height, area in loose:
            gathered += area
            if gathered >= target:
                self._spawn_clump(surface.left + x, surface.top - random.uniform(0, height), gathered,
                                  vx * THROW + random.uniform(-70, 70),
                                  vy * THROW + random.uniform(-200, 10))
                gathered = 0.0
                target = random.uniform(*CLUMP_AREA_RANGE)
        if gathered > 1:
            x, height, _ = loose[-1]
            self._spawn_clump(surface.left + x, surface.top - height / 2, gathered,
                              vx * THROW, vy * THROW - 60)

    def _spawn_clump(self, x, y, area, vx, vy, bounced=False):
        if len(self.clumps) >= MAX_CLUMPS:
            self._land_on_taskbar(x, area)  # plenty already in the air: skip the fall
            return
        clump = Clump()
        clump.x, clump.y, clump.area = x, y, area
        clump.vx = max(-1500.0, min(1500.0, vx))
        clump.vy = max(-1500.0, min(1500.0, vy))
        radius = math.sqrt(area / math.pi) * 1.15
        size = min(range(len(CLUMP_RADII)), key=lambda i: abs(CLUMP_RADII[i] - radius))
        clump.frames, clump.half = random.choice(self._clump_shapes[size])
        clump.angle = random.uniform(0, math.tau)
        clump.spin = random.uniform(-9, 9) + clump.vx / 60  # thrown sideways -> rolls that way
        clump.bounced = bounced
        self.clumps.append(clump)

    def _land_on_taskbar(self, x, area):
        if 0 <= x < self.width:
            self.taskbar.pile.add(x - self.taskbar.left, area)

    # ----- snowballs -----

    def obstacle_at(self, x, y):
        """Which window (or icon) is top-most at (x, y), or None."""
        for key, left, top, right, bottom in self._obstacles:
            if left <= x < right and top <= y < bottom:
                return key
        return None

    def is_solid(self, x, y, ignore=None):
        """True if (x, y) is inside a window, the taskbar, an icon, or a pile of snow.

        ignore: a window the snowball flies in front of (the one it was launched over).
        """
        for key, left, top, right, bottom in self._obstacles:
            if left <= x < right and top <= y < bottom:
                return key != ignore  # only the top-most thing at this spot matters
        for surface in self._showing:
            if (surface.left <= x < surface.right and y <= surface.top
                    and y >= surface.top - surface.pile.height_at(x - surface.left)
                    and surface.edge_visible_at(x)):
                return True
        return False

    def blast(self, x, y, radius):
        """A snowball burst at (x, y): knock nearby snow flying outward from it."""
        for surface in self._showing:
            dy = y - surface.top
            if abs(dy) >= radius or x + radius < surface.left or x - radius > surface.right:
                continue
            reach = math.sqrt(radius * radius - dy * dy)
            loose = surface.pile.blast(x - surface.left, reach, 1 - abs(dy) / radius * 0.5)
            self._scatter(surface.left, surface.top, loose, x, y, radius)
        hat = self.cursor_snow
        if hat.anchor and math.dist(hat.anchor, (x, y)) < radius:
            for cx, cy, area in hat.knock_off():
                self._fling_from(cx, cy, area, x, y, radius)

    def _scatter(self, left, top, loose, x, y, radius):
        gathered = 0.0
        target = random.uniform(*CLUMP_AREA_RANGE)
        for cx, height, area in loose:
            gathered += area
            if gathered >= target:
                self._fling_from(left + cx, top - random.uniform(0, height), gathered, x, y, radius)
                gathered = 0.0
                target = random.uniform(*CLUMP_AREA_RANGE)
        if gathered > 1:
            cx, height, _ = loose[-1]
            self._fling_from(left + cx, top - height / 2, gathered, x, y, radius)

    def _fling_from(self, cx, cy, area, x, y, radius):
        """Launch a clump at (cx, cy) away from a burst at (x, y)."""
        dx, dy = cx - x, cy - y - 12  # bias upwards so snow sprays up and out
        distance = math.hypot(dx, dy) or 1.0
        speed = random.uniform(300, 700) * (1.2 - min(1.0, distance / radius) * 0.6)
        self._spawn_clump(cx, cy, area, dx / distance * speed,
                          dy / distance * speed - random.uniform(80, 220))

    def burst(self, x, y, count, speed):
        """A spray of powder flying out in every direction."""
        for _ in range(count):
            angle = random.uniform(0, math.tau)
            v = speed * random.uniform(0.3, 1.0)
            self._puff(x, y, math.cos(angle) * v, math.sin(angle) * v - 60,
                       gravity=320, life=random.uniform(0.4, 0.9), sprite=self._sparkle_sprite)

    def powder(self, x, y, vx, vy):
        """One wisp of powder trail."""
        self._puff(x, y, vx, vy, gravity=30, life=random.uniform(0.25, 0.5), sprite=self._powder_sprite)

    # ----- the mouse -----

    def follow_cursor(self, cursor, dt):
        """Track the mouse for the snow hat; if the mouse moved, the hat tumbles off."""
        hat = self.cursor_snow
        for x, y, area in hat.follow(cursor, dt):
            self._spawn_clump(x, y, area, hat.vx * 0.4 + random.uniform(-50, 50),
                              hat.vy * 0.4 + random.uniform(-140, 0))

    # ----- falling flakes landing -----

    def catch_flake(self, x, y_before, y_after, depth):
        """Called for every falling flake each frame. Returns True if it settled somewhere."""
        if self.cursor_snow.catch(x, y_before, y_after, HAT_SNOW_PER_FLAKE * (0.4 + 1.2 * depth)):
            return True
        bucket = int(x // LANDING_BUCKET)
        if not 0 <= bucket < len(self._buckets):
            return False
        for surface in self._buckets[bucket]:
            if not surface.left <= x < surface.right:
                continue
            top = surface.top
            if y_after < top - surface.pile.max_height - 1 or y_before > top + 1:
                continue
            snow_line = top - surface.pile.height_at(x - surface.left)
            if y_before < snow_line <= y_after and surface.edge_visible_at(x):
                chance = (TASKBAR_STICK_CHANCE if surface.kind == "taskbar"
                          else ICON_STICK_CHANCE if surface.kind == "icon" else WINDOW_STICK_CHANCE)
                if random.random() < chance:
                    self._settle(surface, x, SNOW_PER_FLAKE * (0.4 + 1.2 * depth))
                    return True
        return False

    def _settle(self, surface, x, area):
        spilled_left, spilled_right = surface.pile.add(x - surface.left, area)
        if surface is self.taskbar:
            return  # snow sliding off the screen's ends just disappears
        surface.spill_left += spilled_left
        surface.spill_right += spilled_right
        low = CLUMP_AREA_RANGE[0]
        if surface.spill_left >= low:
            self._spawn_clump(surface.left - 1, surface.top - 1, surface.spill_left, -35, 0)
            surface.spill_left = 0.0
        if surface.spill_right >= low:
            self._spawn_clump(surface.right + 1, surface.top - 1, surface.spill_right, 35, 0)
            surface.spill_right = 0.0

    # ----- each frame -----

    def update(self, dt, cursor):
        """Melt snow under the mouse and move falling clumps and puffs."""
        touching = cursor is not None and MELT_ENABLED and self._melt_under(cursor, dt)
        # The circle springs open while the mouse is on snow, and closes again once it leaves.
        target = MELT_RADIUS if touching else 0.0
        self._ring_radius += (target - self._ring_radius) * min(1.0, dt * (RING_OPEN_SPEED if touching else 12))
        self._ring_glow = min(1.0, self._ring_glow + dt * 8) if touching else max(0.0, self._ring_glow - dt * 3)
        if cursor is not None:
            self._ring_at = cursor
        self._move_clumps(dt)
        self._move_puffs(dt)

    def _melt_under(self, cursor, dt):
        """Cut a round hole in any snow around the mouse. True if the mouse is touching snow."""
        cx, cy = cursor
        reach = MELT_RADIUS + MELT_REACH
        radius = max(4.0, self._ring_radius)
        touching = False
        for surface in self._showing:
            if cy > surface.top + reach or not surface.left - reach < cx < surface.right + reach:
                continue
            local = cx - surface.left
            peak = surface.pile.peak(local - reach, local + reach)
            if peak <= 0 or cy < surface.top - peak - reach or cy > surface.top + 1:
                continue  # no snow near, or the mouse is below the edge (e.g. on the title bar)
            if not surface.clip.contains(QPoint(int(cx), int(min(cy, surface.top)))):
                continue  # the mouse is over a window stacked in front
            touching = True
            removed = surface.pile.carve(local, surface.top - cy, radius)
            if removed:
                self._burst_from_circle(surface, removed, cx, cy)
                self._push_aside(surface, local, radius, sum(area for _, _, area in removed))
        return touching

    def _burst_from_circle(self, surface, removed, cx, cy):
        """Sparkles fly outward from the edge of the circle."""
        for x, height, area in removed:
            count = area / PUFF_AREA
            for _ in range(int(count) + (random.random() < count % 1)):
                px = surface.left + x + random.uniform(-1.5, 1.5)
                py = surface.top - height * random.random()
                dx, dy = px - cx, py - cy
                if dy > 0:
                    dy *= -0.5  # bits from the bottom of the circle spray up and out, not into the edge
                distance = math.hypot(dx, dy) or 1.0
                speed = random.uniform(70, 190)
                self._puff(px, py, dx / distance * speed, dy / distance * speed - 30,
                           gravity=140, life=random.uniform(0.3, 0.7), sprite=self._sparkle_sprite)

    def _push_aside(self, surface, local, radius, area):
        """Some of the snow gets shoved out to the sides, heaping up a little rim around the hole."""
        rim = area * RIM_SHARE / 2
        for side in (-1, 1):
            x = local + side * (radius + random.uniform(2, 7))
            if 0 <= x < surface.pile.width:
                surface.pile.add(x, rim)

    def _puff(self, x, y, vx, vy, gravity, life, sprite):
        if len(self.puffs) >= MAX_PUFFS:
            return
        puff = Puff()
        puff.x, puff.y, puff.vx, puff.vy = x, y, vx, vy
        puff.gravity = gravity
        puff.life = puff.max_life = life
        puff.sprite = sprite
        self.puffs.append(puff)

    def _move_clumps(self, dt):
        bar = self.taskbar
        drag = math.exp(-0.8 * dt)
        falling, self.clumps = self.clumps, []  # landings can add bounced pieces to the new list
        for clump in falling:
            clump.vx *= drag
            clump.vy += GRAVITY * dt
            clump.x += clump.vx * dt
            clump.y += clump.vy * dt
            clump.angle += clump.spin * dt
            ground = bar.top - bar.pile.height_at(clump.x - bar.left)
            if clump.y >= ground:
                self._impact(clump, ground)
            elif -60 < clump.x < self.width + 60 and clump.y < self.height + 40:
                self.clumps.append(clump)
                self._shed_powder(clump, dt)

    def _shed_powder(self, clump, dt):
        """Falling clumps leave a faint trail of powder behind them."""
        if clump.vy > 150 and random.random() < TRAIL_RATE * dt * min(2.0, clump.area / 30):
            self._puff(clump.x + random.uniform(-clump.half, clump.half) * 0.6, clump.y - clump.half * 0.5,
                       clump.vx * 0.15 + random.uniform(-15, 15), random.uniform(-30, 0),
                       gravity=30, life=random.uniform(0.3, 0.6), sprite=self._powder_sprite)

    def _impact(self, clump, ground):
        """A clump hits the taskbar: most of it settles, a few pieces bounce, and powder sprays up."""
        x, area = clump.x, clump.area
        if not clump.bounced and area >= 12:
            pieces = 2 if area < 35 else 3
            hop = min(1.0, clump.vy / 900)
            for _ in range(pieces):
                self._spawn_clump(x + random.uniform(-2, 2), ground - 2, area * BOUNCE_SHARE / pieces,
                                  clump.vx * 0.25 + random.uniform(-120, 120),
                                  -random.uniform(110, 260) * hop, bounced=True)
            area *= 1 - BOUNCE_SHARE
        self._land_on_taskbar(x, area)

        sprays = max(2, min(10, int(clump.area / 5)))
        for _ in range(sprays):
            self._puff(x + random.uniform(-3, 3), ground - 1,
                       random.uniform(-95, 95), -random.uniform(40, 160),
                       gravity=280, life=random.uniform(0.35, 0.7), sprite=self._powder_sprite)

    def _move_puffs(self, dt):
        drag = math.exp(-2.5 * dt)
        alive = []
        for puff in self.puffs:
            puff.life -= dt
            if puff.life > 0:
                puff.vy += puff.gravity * dt
                puff.vx *= drag
                puff.vy *= drag
                puff.x += puff.vx * dt
                puff.y += puff.vy * dt
                alive.append(puff)
        self.puffs = alive

    # ----- drawing -----

    def draw_piles(self, painter):
        """Draw the settled snow (before the falling flakes, so flakes pass in front)."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for surface in self._showing:
            fill, ridge = surface.pile.outline()
            if fill.isEmpty() or surface.clip.isEmpty():
                continue
            painter.setClipRegion(surface.clip)
            painter.translate(surface.left, surface.top)
            painter.fillPath(fill, self._brushes[surface.kind])
            painter.strokePath(ridge, PILE_EDGE)
            painter.resetTransform()
        painter.restore()

    def draw_loose_snow(self, painter):
        """Draw tumbling clumps, powder and sparkles, and the snow hat on the mouse."""
        for clump in self.clumps:
            frame = int(clump.angle / math.tau * CLUMP_ROTATIONS) % CLUMP_ROTATIONS
            painter.drawPixmap(QPointF(clump.x - clump.half, clump.y - clump.half), clump.frames[frame])
        for puff in self.puffs:
            pixmap, half = puff.sprite
            painter.setOpacity(puff.life / puff.max_life)
            painter.drawPixmap(QPointF(puff.x - half, puff.y - half), pixmap)
        painter.setOpacity(1.0)
        self.cursor_snow.draw(painter, self._hat_brush, PILE_EDGE)
        self._draw_ring(painter)

    def _draw_ring(self, painter):
        """A soft glowing ring around the mouse while it clears snow."""
        if self._ring_glow <= 0.02 or self._ring_at is None or self._ring_radius < 2:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        centre = QPointF(*self._ring_at)
        for width, alpha in ((5.0, 40), (1.6, 170)):  # faint wide glow, then a crisp line
            colour = QColor(RING_PEN)
            colour.setAlpha(int(alpha * self._ring_glow))
            painter.setPen(QPen(colour, width))
            painter.drawEllipse(centre, self._ring_radius, self._ring_radius)
        painter.restore()


def _rect(left, top, right, bottom):
    """A whole-pixel QRect covering the given box."""
    x, y = math.floor(left), math.floor(top)
    return QRect(x, y, math.ceil(right) - x, math.ceil(bottom) - y)


def _cut_span(spans, start, end):
    """Remove start..end from a list of (x0, x1) stretches."""
    result = []
    for x0, x1 in spans:
        if end <= x0 or start >= x1:
            result.append((x0, x1))
            continue
        if x0 < start:
            result.append((x0, start))
        if end < x1:
            result.append((end, x1))
    return result

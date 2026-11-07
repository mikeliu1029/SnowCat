"""
A strip of snow resting on one edge: the top of a window, or the taskbar.

The snow is stored as a row of heights, one every few pixels. New snow
spreads over a few neighbouring columns and then slides downhill until no
step is too steep, so piles come out soft and rounded and snow near the
ends trickles over the edge.

Each pile also has its own wavy "ceiling", so a full pile has drifts and
dips instead of a flat top.

Positions are local: x runs from the left end of the edge, and heights are
measured in px upwards from the edge.
"""

import math
import random

from PyQt6.QtGui import QPainterPath

COLUMN_WIDTH = 3        # px of edge per height sample
MAX_STEP = 0.9          # px; the steepest height difference allowed between neighbours
SETTLE_PASSES = 8       # how far snow from one landing is allowed to slide
LANDING_SPREAD = (0.05, 0.1, 0.2, 0.3, 0.2, 0.1, 0.05)  # how one flake's snow spreads sideways
CLUMP_COLUMNS = 4       # shaken snow breaks off in clumps this many columns wide
MIN_VISIBLE = 0.3       # px; thinner snow than this is cleared away
BASE_OVERLAP = 1.0      # px the snow tucks down over the window's top border
LOWEST_CEILING = 0.5    # where the wavy ceiling dips lowest, as a share of the max depth


def column_count(width):
    return max(1, int(width // COLUMN_WIDTH))


class SnowPile:
    """The snow heights along one edge."""

    def __init__(self, width, max_height):
        self.width = width
        self.max_height = max_height
        self.heights = [0.0] * column_count(width)
        self._outline = None  # cached (fill, ridge) paths; rebuilt after the snow changes
        # A few overlapping waves, different for every pile, shape the ceiling.
        self._waves = [(random.uniform(0.04, 0.09), random.uniform(0, math.tau)),   # broad drifts
                       (random.uniform(0.12, 0.25), random.uniform(0, math.tau)),   # bumps
                       (random.uniform(0.3, 0.5), random.uniform(0, math.tau))]     # small lumps
        self._wave_offset = 0  # keeps the ceiling lined up when columns are added on the left
        self._make_ceiling()

    def _make_ceiling(self):
        """Work out the deepest the snow may get in each column."""
        low = LOWEST_CEILING
        ceiling = []
        for i in range(len(self.heights)):
            c = i + self._wave_offset
            wave = (0.55 * math.sin(c * self._waves[0][0] + self._waves[0][1])
                    + 0.3 * math.sin(c * self._waves[1][0] + self._waves[1][1])
                    + 0.15 * math.sin(c * self._waves[2][0] + self._waves[2][1]))  # -1..1
            ceiling.append(self.max_height * (low + (1 - low) * (wave + 1) / 2))
        self._ceiling = ceiling

    def set_max_height(self, max_height):
        """Change how deep the snow can get, trimming any that's now too deep."""
        self.max_height = max_height
        self._make_ceiling()
        self.heights = [min(h, cap) for h, cap in zip(self.heights, self._ceiling)]
        self._outline = None

    # ----- reading -----

    def height_at(self, x):
        """How deep the snow is at x."""
        i = int(x // COLUMN_WIDTH)
        return self.heights[i] if 0 <= i < len(self.heights) else 0.0

    def peak(self, x0, x1):
        """The deepest snow between x0 and x1."""
        lo, hi = self._column_range(x0, x1)
        return max(self.heights[lo:hi], default=0.0)

    def _column_range(self, x0, x1):
        return max(0, int(x0 // COLUMN_WIDTH)), min(len(self.heights), int(x1 // COLUMN_WIDTH) + 1)

    # ----- adding snow -----

    def add(self, x, area):
        """Drop `area` px² of snow at x.

        Returns (spilled_left, spilled_right): px² that slid off each end.
        """
        heights, ceiling = self.heights, self._ceiling
        centre = int(x // COLUMN_WIDTH)
        reach = len(LANDING_SPREAD) // 2
        for offset, share in enumerate(LANDING_SPREAD, start=-reach):
            i = centre + offset
            if 0 <= i < len(heights):
                heights[i] = min(ceiling[i], heights[i] + area * share / COLUMN_WIDTH)
        self._outline = None
        return self._settle(centre - reach, centre + reach + 1)

    def _settle(self, lo, hi):
        """Let snow around columns lo..hi slide downhill until no step is too steep."""
        heights = self.heights
        n = len(heights)
        spilled_left = spilled_right = 0.0
        for _ in range(SETTLE_PASSES):
            lo, hi = max(0, lo), min(n, hi)
            moved = False
            for i in range(lo, hi):
                for j in (i - 1, i + 1):
                    neighbour = heights[j] if 0 <= j < n else 0.0  # past the ends is a drop
                    excess = heights[i] - neighbour - MAX_STEP
                    if excess <= 0.01:
                        continue
                    flow = excess / 2
                    heights[i] -= flow
                    moved = True
                    if j < 0:
                        spilled_left += flow * COLUMN_WIDTH
                    elif j >= n:
                        spilled_right += flow * COLUMN_WIDTH
                    else:
                        heights[j] = min(self._ceiling[j], heights[j] + flow)
            if not moved:
                break
            lo, hi = lo - 1, hi + 1  # the slide can carry on into the next columns
        return spilled_left, spilled_right

    # ----- removing snow -----
    # Each of these returns the snow it took away as a list of (x, height, area),
    # so the caller can turn it into falling clumps or melting sparkles.

    def melt(self, x, radius, depth):
        """Melt up to `depth` px of snow around x, a little less towards the sides."""
        removed = []
        lo, hi = self._column_range(x - radius, x + radius)
        for i in range(lo, hi):
            if self.heights[i] <= 0:
                continue
            closeness = 1 - abs((i + 0.5) * COLUMN_WIDTH - x) / radius
            if closeness > 0:
                removed.append(self._cut(i, depth * (0.4 + 0.6 * closeness)))
        if removed:
            self._outline = None
        return removed

    def blast(self, x, reach, strength):
        """Blow away snow around x: nearly all of it at the centre, less towards the sides."""
        removed = []
        lo, hi = self._column_range(x - reach, x + reach)
        for i in range(lo, hi):
            height = self.heights[i]
            closeness = 1 - abs((i + 0.5) * COLUMN_WIDTH - x) / reach
            if height > 0 and closeness > 0:
                removed.append(self._cut(i, height * min(1.0, strength * closeness * 1.5)))
        if removed:
            self._outline = None
        return removed

    def carve(self, x, y, radius):
        """Cut a round hole centred at (x, y), where y is the height above the edge.

        Snow inside the circle goes; any snow resting on top of it slumps down.
        """
        removed = []
        lo, hi = self._column_range(x - radius, x + radius)
        for i in range(lo, hi):
            height = self.heights[i]
            dx = (i + 0.5) * COLUMN_WIDTH - x
            if height <= 0 or abs(dx) >= radius:
                continue
            half = math.sqrt(radius * radius - dx * dx)
            overlap = min(height, y + half) - max(0.0, y - half)
            if overlap > 0:
                removed.append(self._cut(i, overlap))
        if removed:
            self._outline = None
        return removed

    def shake_off(self, fraction):
        """Knock loose about `fraction` (0..1) of the snow, in uneven clumps."""
        removed = []
        share = fraction
        for i, height in enumerate(self.heights):
            if i % CLUMP_COLUMNS == 0 and fraction < 1:
                share = min(1.0, fraction * random.uniform(0.4, 1.6))
            if height > 0:
                removed.append(self._cut(i, height * share))
        if removed:
            self._outline = None
        return removed

    def resize(self, width, keep_right):
        """Follow the edge's new width. Snow that no longer fits is returned.

        keep_right means the left end moved (the window was resized from its
        left side), so the snow stays lined up with the right end.
        """
        self.width = width
        old = self.heights
        n = column_count(width)
        change = n - len(old)
        if change == 0:
            return []
        self._outline = None
        if keep_right:
            self._wave_offset -= change  # the right end stays put, so the ceiling does too
        if change > 0:
            self.heights = [0.0] * change + old if keep_right else old + [0.0] * change
            self._make_ceiling()
            return []
        if keep_right:
            dropped, self.heights = old[:-change], old[-change:]
            first = change  # dropped columns now sit left of the new left end
        else:
            dropped, self.heights = old[n:], old[:n]
            first = n
        self._make_ceiling()
        return [((first + k + 0.5) * COLUMN_WIDTH, height, height * COLUMN_WIDTH)
                for k, height in enumerate(dropped) if height > 0]

    def _cut(self, i, amount):
        """Take up to `amount` px off column i (all of it if only a dusting would be left)."""
        before = self.heights[i]
        after = before - amount
        if after < MIN_VISIBLE:
            after = 0.0
        self.heights[i] = after
        return (i + 0.5) * COLUMN_WIDTH, before, (before - after) * COLUMN_WIDTH

    # ----- shape -----

    def outline(self):
        """The snow's shape as (fill, ridge) paths: x from the left end, y negative going up.

        fill is the whole shape; ridge is just its top line, for a soft outline.
        """
        if self._outline is None:
            self._outline = self._build_outline()
        return self._outline

    def _build_outline(self):
        fill, ridge = QPainterPath(), QPainterPath()
        heights = self.heights
        n = len(heights)
        i = 0
        while i < n:
            if heights[i] < MIN_VISIBLE:
                i += 1
                continue
            start = i
            while i < n and heights[i] >= MIN_VISIBLE:
                i += 1
            self._trace_mound(fill, ridge, start, i)
        return fill, ridge

    def _trace_mound(self, fill, ridge, start, end):
        """Add one unbroken stretch of snow, as a smooth curve through the heights."""
        heights = self.heights
        half = COLUMN_WIDTH / 2
        x, y = start * COLUMN_WIDTH + half, -heights[start]
        fill.moveTo(start * COLUMN_WIDTH, BASE_OVERLAP)
        fill.lineTo(x, y)
        ridge.moveTo(start * COLUMN_WIDTH, 0)
        ridge.lineTo(x, y)
        for i in range(start + 1, end):
            next_x, next_y = i * COLUMN_WIDTH + half, -heights[i]
            mid_x, mid_y = (x + next_x) / 2, (y + next_y) / 2
            fill.quadTo(x, y, mid_x, mid_y)
            ridge.quadTo(x, y, mid_x, mid_y)
            x, y = next_x, next_y
        fill.lineTo(x, y)
        fill.lineTo(end * COLUMN_WIDTH, BASE_OVERLAP)
        fill.closeSubpath()
        ridge.lineTo(x, y)
        ridge.lineTo(end * COLUMN_WIDTH, 0)

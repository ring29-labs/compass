#!/usr/bin/env python3
"""Render actual asciicast terminal output to a GIF with pyte and Pillow."""
import argparse
import copy
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import pyte

ROOT = Path(__file__).resolve().parents[1]
COLORS = {'default': '#d9e2f2', 'black': '#0d1117', 'red': '#ff7b72',
          'green': '#7ee787', 'brown': '#d29922', 'blue': '#79c0ff',
          'magenta': '#d2a8ff', 'cyan': '#a5d6ff', 'white': '#f0f6fc',
          'brightblack': '#6e7681', 'brightred': '#ffa198', 'brightgreen': '#aff5b4',
          'brightbrown': '#e3b341', 'brightblue': '#a5d6ff', 'brightmagenta': '#d2a8ff',
          'brightcyan': '#a5d6ff', 'brightwhite': '#ffffff'}


class TerminalScreen(pyte.Screen):
    """Preserve the normal screen while curses uses xterm's alternate buffer."""
    normal = None

    def set_mode(self, *modes, **kwargs):
        if kwargs.get('private') and 1049 in modes and self.normal is None:
            self.normal = (copy.deepcopy(self.buffer), copy.deepcopy(self.cursor), self.margins)
            self.erase_in_display(2)
            self.cursor_position()
        super().set_mode(*modes, **kwargs)

    def reset_mode(self, *modes, **kwargs):
        super().reset_mode(*modes, **kwargs)
        if kwargs.get('private') and 1049 in modes and self.normal is not None:
            self.buffer, self.cursor, self.margins = self.normal
            self.normal = None
            self.dirty.update(range(self.lines))


def color(value, background=False):
    if value == 'default':
        return '#0d1117' if background else '#d9e2f2'
    if value in COLORS:
        return COLORS[value]
    if len(value) == 6:
        return '#' + value
    return '#0d1117' if background else '#d9e2f2'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('cast', nargs='?', type=Path, default=ROOT / 'docs/demo.cast')
    p.add_argument('--output', type=Path, default=ROOT / 'docs/demo.gif')
    p.add_argument('--poster', type=Path, default=ROOT / 'docs/demo.png')
    p.add_argument('--font', type=Path)
    args = p.parse_args()
    lines = args.cast.read_text().splitlines()
    header, events = json.loads(lines[0]), [json.loads(line) for line in lines[1:]]
    fonts = [args.font, Path('/System/Library/Fonts/Menlo.ttc'),
             Path('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf')]
    font_path = next((font for font in fonts if font and font.exists()), None)
    font = ImageFont.truetype(str(font_path), 15) if font_path else ImageFont.load_default()
    cell_w, cell_h, pad, top = round(font.getlength('M')), 21, 24, 60
    width, height = header['width'] * cell_w + pad * 2, header['height'] * cell_h + top + pad
    screen = TerminalScreen(header['width'], header['height'])
    stream = pyte.Stream(screen)
    frames, durations, index, poster = [], [], 0, None
    end = events[-1][0] + 1
    stamp = 0.0
    while stamp <= end:
        while index < len(events) and events[index][0] <= stamp:
            if events[index][1] == 'o':
                stream.feed(events[index][2])
            index += 1
        image = Image.new('RGB', (width, height), '#0d1117')
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, width, 42), fill='#161b22')
        for x, fill in ((22, '#ff5f57'), (42, '#febc2e'), (62, '#28c840')):
            draw.ellipse((x - 5, 15, x + 5, 25), fill=fill)
        draw.text((90, 10), 'Compass  /  Tab Tab + Jev  /  ~ >>', font=font, fill='#8b949e')
        for row in range(screen.lines):
            column = 0
            while column < screen.columns:
                cell = screen.buffer[row][column]
                start, text = column, cell.data
                column += 1
                while column < screen.columns:
                    following = screen.buffer[row][column]
                    if (following.fg, following.bg, following.reverse, following.bold) != (cell.fg, cell.bg, cell.reverse, cell.bold):
                        break
                    text += following.data
                    column += 1
                fg, bg = color(cell.fg), color(cell.bg, True)
                if cell.reverse:
                    fg, bg = bg, fg
                x, y = pad + start * cell_w, top + row * cell_h
                if bg != '#0d1117':
                    draw.rectangle((x, y, pad + column * cell_w, y + cell_h), fill=bg)
                if text.strip():
                    draw.text((x, y), text, font=font, fill=fg)
        if not screen.cursor.hidden:
            x, y = pad + screen.cursor.x * cell_w, top + screen.cursor.y * cell_h
            draw.rectangle((x, y + cell_h - 3, x + cell_w, y + cell_h - 1), fill='#7ee787')
        flat = '\n'.join(screen.display)
        if poster is None and 'Shell completion choices' in flat and 'describe-instances' in flat and '> describe-instances' in flat:
            poster = image.copy()
        # Collapse identical frames rather than storing idle repetition.
        if frames and image.tobytes() == frames[-1].tobytes():
            durations[-1] += 150
        else:
            frames.append(image)
            durations.append(150)
        stamp += 0.15
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(args.output, save_all=True, append_images=frames[1:], duration=durations,
                   loop=0, optimize=False, disposal=1)
    (poster or frames[len(frames)//2]).save(args.poster)
    print(f'Rendered {len(frames)} frames to {args.output} ({args.output.stat().st_size:,} bytes)')


if __name__ == '__main__':
    main()

"""
Turns raw transparent Blender frames into finished 1080x1920 frames:
gradient background, optional blur-to-sharp reveal, hook text, stat cards,
call-to-action and an optional handle watermark.

Text is kept inside the safe zone that TikTok, Reels and Shorts leave free
of their own buttons and captions (roughly: not the top 13%, not the bottom
22%, not the right-hand 13%).
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_CANDIDATES = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
    '/Library/Fonts/Arial Bold.ttf',
    '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
    'C:/Windows/Fonts/arialbd.ttf',
]


def find_font(preferred: str = '') -> str:
    for candidate in ([preferred] if preferred else []) + FONT_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    raise FileNotFoundError('No bold TTF font found; set FONT_PATH (e.g. install fonts-dejavu-core).')


def _rgb255(rgb: Sequence[float]) -> Tuple[int, int, int]:
    return tuple(max(0, min(255, round(c * 255))) for c in rgb)


def ease_out_back(t: float) -> float:
    t = max(0.0, min(1.0, t))
    c1 = 1.70158
    return 1 + (c1 + 1) * (t - 1) ** 3 + c1 * (t - 1) ** 2


@dataclass
class OverlayPlan:
    background_top: Sequence[float]
    background_bottom: Sequence[float]
    hook: str = ''
    hook_seconds: float = 2.8
    cta: str = ''
    cta_seconds: float = 2.2
    answer: str = ''
    stat_lines: List[str] = field(default_factory=list)
    blur_reveal: bool = False
    reveal_seconds: float = 2.4
    text_style: str = 'stroke'          # 'stroke' or 'pill'
    series_label: str = ''
    handle: str = ''


class FrameCompositor:
    def __init__(self, width: int = 1080, height: int = 1920, fps: int = 30, font_path: str = ''):
        self.width = width
        self.height = height
        self.fps = fps
        self.font_path = find_font(font_path)
        s = width / 1080
        self.safe_left = int(70 * s)
        self.safe_right = width - int(150 * s)
        self.safe_top = int(0.13 * height)
        self.safe_bottom = int(0.78 * height)
        self.scale = s

    # ------------------------------------------------------------ building blocks
    def background(self, top: Sequence[float], bottom: Sequence[float]) -> Image.Image:
        """Vertical gradient with a soft vignette."""
        h, w = self.height, self.width
        t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
        grad = (1 - t) * np.array(_rgb255(top), np.float32) + t * np.array(_rgb255(bottom), np.float32)
        grad = np.repeat(grad, w, axis=1)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        d = np.sqrt(((xx - w / 2) / (w * 0.75)) ** 2 + ((yy - h * 0.45) / (h * 0.75)) ** 2)
        vignette = np.clip(1.0 - 0.35 * d ** 2, 0.55, 1.0)[..., None]
        return Image.fromarray(np.clip(grad * vignette, 0, 255).astype(np.uint8), 'RGB')

    def _font(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(self.font_path, size)

    def _wrap(self, text: str, font, max_width: int) -> List[str]:
        lines, current = [], ''
        for word in text.split():
            trial = f'{current} {word}'.strip()
            if font.getlength(trial) <= max_width or not current:
                current = trial
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def text_block(self, text: str, size: int, style: str, max_lines: int = 3,
                   accent: Sequence[float] = (1.0, 0.85, 0.2)) -> Image.Image:
        """Render wrapped text to a tight RGBA image, shrinking the font until it fits."""
        max_width = self.safe_right - self.safe_left
        size = int(size * self.scale)
        while True:
            font = self._font(size)
            lines = self._wrap(text, font, max_width - int(60 * self.scale))
            if len(lines) <= max_lines or size < 30:
                break
            size = int(size * 0.9)

        stroke = max(3, size // 9) if style == 'stroke' else 0
        line_h = int(size * 1.18)
        pad_x, pad_y = (int(size * 0.55), int(size * 0.35)) if style == 'pill' else (stroke, stroke)
        text_w = max(int(font.getlength(line)) for line in lines)
        img_w = text_w + 2 * pad_x
        img_h = line_h * len(lines) + 2 * pad_y
        img = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        if style == 'pill':
            draw.rounded_rectangle([0, 0, img_w - 1, img_h - 1], radius=int(size * 0.45),
                                   fill=(*_rgb255(accent), 245))
            fill, stroke_fill = (15, 15, 20, 255), None
        else:
            fill, stroke_fill = (255, 255, 255, 255), (0, 0, 0, 255)

        for i, line in enumerate(lines):
            x = (img_w - font.getlength(line)) / 2
            y = pad_y + i * line_h
            draw.text((x, y), line, font=font, fill=fill,
                      stroke_width=stroke, stroke_fill=stroke_fill)
        return img

    def _paste_centered(self, canvas: Image.Image, layer: Image.Image, center_y: int,
                        scale: float = 1.0, alpha: float = 1.0):
        if alpha <= 0 or scale <= 0:
            return
        if scale != 1.0:
            layer = layer.resize((max(1, int(layer.width * scale)), max(1, int(layer.height * scale))),
                                 Image.LANCZOS)
        if alpha < 1.0:
            layer = layer.copy()
            layer.putalpha(layer.getchannel('A').point(lambda a: int(a * alpha)))
        center_x = (self.safe_left + self.safe_right) // 2
        canvas.alpha_composite(layer, (center_x - layer.width // 2, center_y - layer.height // 2))

    # ------------------------------------------------------------ per-frame logic
    @staticmethod
    def _pop(t: float, start: float, end: float, fade: float = 0.25) -> Tuple[float, float]:
        """(scale, alpha) for a layer shown between start and end seconds."""
        if t < start or t > end:
            return 0.0, 0.0
        appear = (t - start) / 0.22
        scale = 0.75 + 0.25 * ease_out_back(appear) if appear < 1 else 1.0
        alpha = min(1.0, appear * 1.5, (end - t) / fade if fade else 1.0)
        return scale, max(0.0, alpha)

    def compose(self, raw_dir: Path, out_dir: Path, plan: OverlayPlan) -> List[Path]:
        raw_frames = sorted(Path(raw_dir).glob('frame_*.png'))
        if not raw_frames:
            raise FileNotFoundError(f'no frames in {raw_dir}')
        out_dir.mkdir(parents=True, exist_ok=True)
        for stale in out_dir.glob('frame_*.png'):
            stale.unlink()

        total = len(raw_frames)
        duration = total / self.fps
        bg = self.background(plan.background_top, plan.background_bottom).convert('RGBA')

        hook_img = self.text_block(plan.hook, 92, plan.text_style) if plan.hook else None
        cta_img = self.text_block(plan.cta, 78, plan.text_style, accent=(0.3, 0.9, 0.6)) if plan.cta else None
        answer_img = self.text_block(plan.answer, 70, 'pill', accent=(1.0, 1.0, 1.0)) if plan.answer else None
        stat_imgs = [self.text_block(line, 56, 'pill', max_lines=1, accent=(1, 1, 1)) for line in plan.stat_lines]
        label_img = self.text_block(plan.series_label, 40, 'stroke', max_lines=1) if plan.series_label else None
        handle_img = self.text_block(plan.handle, 38, 'stroke', max_lines=1) if plan.handle else None

        hook_y = self.safe_top + int(150 * self.scale)
        cta_y = self.safe_bottom - int(120 * self.scale)
        cta_start = max(plan.hook_seconds, duration - plan.cta_seconds)
        answer_start = max(plan.hook_seconds, duration - 1.8) if plan.answer else None
        if answer_img is not None:  # answer takes the end slot; CTA moves before it
            cta_start = max(plan.hook_seconds, answer_start - plan.cta_seconds)

        written = []
        for index, raw_path in enumerate(raw_frames):
            t = index / self.fps
            frame = bg.copy()
            obj = Image.open(raw_path).convert('RGBA')
            if obj.size != (self.width, self.height):
                obj = obj.resize((self.width, self.height), Image.LANCZOS)
            frame.alpha_composite(obj)

            if plan.blur_reveal and t < plan.reveal_seconds:
                progress = t / plan.reveal_seconds
                radius = 45 * self.scale * (1 - progress) ** 2
                if radius > 0.5:
                    frame = frame.filter(ImageFilter.GaussianBlur(radius))

            if label_img is not None:
                self._paste_centered(frame, label_img, self.safe_top + int(20 * self.scale), alpha=0.85)
            if hook_img is not None:
                self._paste_centered(frame, hook_img, hook_y, *self._pop(t, 0.0, plan.hook_seconds))
            for i, stat in enumerate(stat_imgs):
                start = plan.hook_seconds + 0.1 + 0.7 * i
                y = hook_y + int((20 + 95 * i) * self.scale)
                self._paste_centered(frame, stat, y, *self._pop(t, start, cta_start, fade=0.2))
            if cta_img is not None:
                end = answer_start if answer_start else duration + 1
                self._paste_centered(frame, cta_img, cta_y, *self._pop(t, cta_start, end, fade=0.15))
            if answer_img is not None:
                self._paste_centered(frame, answer_img, cta_y, *self._pop(t, answer_start, duration + 1))
            if handle_img is not None:
                frame.alpha_composite(self._faded(handle_img, 0.6),
                                      (self.safe_left, self.safe_bottom - handle_img.height))

            path = out_dir / f'frame_{index + 1:04d}.png'
            frame.convert('RGB').save(path, compress_level=1)
            written.append(path)
        return written

    @staticmethod
    def _faded(layer: Image.Image, alpha: float) -> Image.Image:
        layer = layer.copy()
        layer.putalpha(layer.getchannel('A').point(lambda a: int(a * alpha)))
        return layer

    # ------------------------------------------------------------ cover
    def cover(self, raw_frame: Path, out_path: Path, plan: OverlayPlan) -> Path:
        """Grid/thumbnail image: sharp model, big hook text."""
        frame = self.background(plan.background_top, plan.background_bottom).convert('RGBA')
        obj = Image.open(raw_frame).convert('RGBA').resize((self.width, self.height), Image.LANCZOS)
        frame.alpha_composite(obj)
        if plan.hook:
            self._paste_centered(frame, self.text_block(plan.hook, 104, plan.text_style),
                                 self.safe_top + int(170 * self.scale))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        frame.convert('RGB').save(out_path, quality=92)
        return out_path

    def preview_still(self, raw_frame: Path, out_path: Path, plan: OverlayPlan) -> Path:
        """Sharp model on its background, no text (what the LLM looks at)."""
        frame = self.background(plan.background_top, plan.background_bottom).convert('RGBA')
        obj = Image.open(raw_frame).convert('RGBA').resize((self.width, self.height), Image.LANCZOS)
        frame.alpha_composite(obj)
        small = frame.convert('RGB').resize((self.width // 2, self.height // 2), Image.LANCZOS)
        small.save(out_path, quality=85)
        return out_path

"""
透明磁带音乐播放器
- 磁带轮旋转动画
- 上一首 / 播放暂停 / 下一首
- 支持 MP3/FLAC/WAV
"""
import sys
import os
import math
import random
from pathlib import Path

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget,
                              QVBoxLayout, QHBoxLayout, QPushButton,
                              QFileDialog, QListWidget, QLabel, QSlider)
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QUrl, QSettings
from PyQt6.QtGui import (QPainter, QColor, QBrush, QPen, QFont,
                          QLinearGradient, QRadialGradient, QPainterPath,
                          QFontDatabase, QAction)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

from mutagen import File as MutagenFile
from mutagen.mp3 import MP3


# ============================================================
# 音频引擎
# ============================================================

class AudioEngine:
    def __init__(self, parent=None):
        self._player = QMediaPlayer(parent)
        self._audio = QAudioOutput(parent)
        self._player.setAudioOutput(self._audio)
        self._audio.setVolume(0.8)

        self._playlist = []
        self._index = -1
        self._playing = False

        self._player.playbackStateChanged.connect(self._on_state_change)

    def _on_state_change(self, state):
        self._playing = (state == QMediaPlayer.PlaybackState.PlayingState)

    @property
    def playing(self):
        return self._playing

    @property
    def current_index(self):
        return self._index

    @property
    def playlist(self):
        return self._playlist

    def load_folder(self, folder_path):
        """扫描文件夹中的音乐文件"""
        extensions = {'.mp3', '.flac', '.wav', '.ogg', '.m4a', '.aac'}
        self._playlist = []
        for ext in extensions:
            for f in Path(folder_path).rglob(f'*{ext}'):
                self._playlist.append(str(f))
        self._playlist.sort()
        return len(self._playlist)

    def play_index(self, index):
        if 0 <= index < len(self._playlist):
            path = self._playlist[index]
            self._player.setSource(QUrl.fromLocalFile(path))
            self._player.play()
            self._playing = True
            self._index = index
            return True
        return False

    def toggle(self):
        if self._playing:
            self._player.pause()
        else:
            self._player.play()

    def stop(self):
        self._player.stop()
        self._playing = False

    def next(self):
        if self._playlist:
            nxt = (self._index + 1) % len(self._playlist)
            return self.play_index(nxt)
        return False

    def prev(self):
        if self._playlist:
            prv = (self._index - 1) % len(self._playlist)
            return self.play_index(prv)
        return False

    @staticmethod
    def get_metadata(filepath):
        """读取歌曲元数据"""
        try:
            if filepath.endswith('.mp3'):
                audio = MP3(filepath)
                tags = audio.tags
                if tags:
                    title = str(tags.get('TIT2', Path(filepath).stem))
                    artist = str(tags.get('TPE1', 'Unknown'))
                    return {'title': title, 'artist': artist, 'path': filepath}
            return {'title': Path(filepath).stem, 'artist': 'Unknown', 'path': filepath}
        except Exception:
            return {'title': Path(filepath).stem, 'artist': 'Unknown', 'path': filepath}


# ============================================================
# 磁带播放器主控件
# ============================================================

class CassettePlayer(QWidget):
    def __init__(self):
        super().__init__()
        self.audio = AudioEngine(self)
        self.rotation_angle = 0.0
        self._settings = QSettings("CassettePlayer", "CassettePlayer")

        # 频谱柱数据（预分配足够容量，实际使用数量由布局决定）
        self._bar_count = 60
        self._bars = [0.05] * self._bar_count
        self._bar_targets = [0.05] * self._bar_count
        self._bar_frame = 0
        self._hue_offset = 0.0
        self._drag_start = None

        # 动画定时器
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start(30)  # ~33fps

        # 加载字体
        self._setup_ui()
        # 恢复上次状态
        self._restore_state()

    def _setup_ui(self):
        self.setMinimumSize(500, 400)
        self.setMouseTracking(True)
        self.setStyleSheet("background: transparent;")

        _base_w, _base_h = 680, 520  # 设计基准尺寸

        # 歌曲信息标签
        self.lbl_title = QLabel("未播放", self)
        self.lbl_title.setStyleSheet(
            "color: #fff; font-size: 18px; font-weight: bold; background: transparent;")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.lbl_artist = QLabel("请打开音乐文件夹", self)
        self.lbl_artist.setStyleSheet(
            "color: #aaa; font-size: 14px; background: transparent;")
        self.lbl_artist.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_artist.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # 按钮
        btn_style = """
            QPushButton {
                background: rgba(255,255,255,0.1);
                color: #ddd;
                border: 2px solid rgba(255,255,255,0.25);
                border-radius: 24px;
                font-size: 22px;
                min-width: 40px;
                min-height: 40px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.25);
                color: #fff;
                border-color: rgba(255,255,255,0.5);
            }
            QPushButton:pressed {
                background: rgba(255,255,255,0.35);
            }
        """
        self.btn_prev = QPushButton("⏮", self)
        self.btn_prev.setStyleSheet(btn_style)
        self.btn_prev.clicked.connect(self._prev)

        self.btn_play = QPushButton("▶", self)
        self.btn_play.setStyleSheet(btn_style)
        self.btn_play.clicked.connect(self._play_pause)

        self.btn_next = QPushButton("⏭", self)
        self.btn_next.setStyleSheet(btn_style)
        self.btn_next.clicked.connect(self._next)

        # 文件列表（隐藏的）
        self._file_list = []

    def resizeEvent(self, event):
        """窗口缩放时重排子控件位置"""
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        base_w = 680
        s = w / base_w  # 缩放比
        btn_s = int(48 * s)  # 按钮尺寸
        reel_s = int(170 * s)

        # 按钮 Y 对齐 reel 中心
        ry = self._reel_center_y()
        bw = btn_s
        spacing = int(reel_s * 0.50)  # 按钮更靠近中心，远离 reel
        center_x = w // 2
        self.btn_prev.setGeometry(center_x - spacing - bw // 2, ry - bw // 2, bw, bw)
        self.btn_play.setGeometry(center_x - bw // 2, ry - bw // 2, bw, bw)
        self.btn_next.setGeometry(center_x + spacing - bw // 2, ry - bw // 2, bw, bw)
        # 标签位置
        lw = int(520 * s)
        self.lbl_title.setGeometry(int(80 * s), int(96 * s), lw, int(28 * s))
        self.lbl_title.setStyleSheet(
            f"color: #fff; font-size: {max(10, int(16*s))}px; font-weight: bold; background: transparent;")
        self.lbl_artist.setGeometry(int(80 * s), int(122 * s), lw, int(22 * s))
        self.lbl_artist.setStyleSheet(
            f"color: #aaa; font-size: {max(9, int(13*s))}px; background: transparent;")

    def _reel_center_y(self):
        """计算磁带轮中心 Y 坐标（动态适配）"""
        w = self.width()
        s = w / 680
        margin = int(18 * s)
        label_y = margin + int(8 * s)
        label_h = int(68 * s)
        waveform_max_h = int(68 * s)
        waveform_base_offset = int(24 * s)
        cassette_bottom = self.height() - margin
        waveform_top = cassette_bottom - waveform_base_offset - waveform_max_h
        return label_y + label_h + (waveform_top - label_y - label_h) // 2

    # ================================================================
    # 动画
    # ================================================================

    def _tick(self):
        if self.audio.playing:
            self.rotation_angle += 3.0  # 每帧转3度
            self._bar_frame += 1
            # 每4帧更新一批柱子的目标高度
            if self._bar_frame % 4 == 0:
                n = self._bar_count
                for i in range(0, n, 3):
                    self._bar_targets[i] = random.uniform(0.2, 1.0)
                    self._bar_targets[min(i + 1, n - 1)] = random.uniform(0.12, 0.65)
                    self._bar_targets[min(i + 2, n - 1)] = random.uniform(0.05, 0.35)
        else:
            # 暂停时缓慢衰减到低平
            for i in range(self._bar_count):
                self._bar_targets[i] = 0.05
        # 平滑插值到目标
        for i in range(self._bar_count):
            self._bars[i] += (self._bar_targets[i] - self._bars[i]) * 0.18
        # 色相持续流动
        self._hue_offset = (self._hue_offset + 0.003) % 1.0
        self.update()  # 重绘

    # ================================================================
    # 绘制
    # ================================================================

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        # 布局常量（基于宽度比例缩放）
        base_w = 680
        s = w / base_w
        margin = int(18 * s)
        cassette_bottom = h - margin
        bw = w - margin * 2
        bh = h - margin * 2

        # --- 玻璃磁带主体（填满窗口） ---
        path = QPainterPath()
        path.addRoundedRect(QRectF(margin, margin, bw, bh), 22, 22)
        p.fillPath(path, QColor(55, 60, 72, 110))
        p.setPen(QPen(QColor(170, 180, 200, 150), 2))
        p.drawPath(path)

        # 内部发光
        path2 = QPainterPath()
        path2.addRoundedRect(QRectF(margin + 3, margin + 3, bw - 6, bh - 6), 20, 20)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawPath(path2)

        # --- 标签区（梯形 + 凸起效果） ---
        label_y = margin + int(10 * s)
        label_h = int(64 * s)
        slant = int(10 * s)
        tl_x = margin + int(26 * s)
        tr_x = w - margin - int(26 * s)
        bl_x = tl_x + slant
        br_x = tr_x - slant
        top_y = label_y
        bottom_y = label_y + label_h
        cr = int(8 * s)  # 圆角半径

        def _rounded_trapezoid(tlx, trx, blx, brx, ty, by, radius):
            """创建圆角梯形路径"""
            path = QPainterPath()
            path.moveTo(tlx + radius, ty)
            path.lineTo(trx - radius, ty)
            path.arcTo(trx - 2 * radius, ty, 2 * radius, 2 * radius, 90, -90)
            path.lineTo(brx, by - radius)
            path.arcTo(brx - 2 * radius, by - 2 * radius, 2 * radius, 2 * radius, 0, -90)
            path.lineTo(blx + radius, by)
            path.arcTo(blx, by - 2 * radius, 2 * radius, 2 * radius, 270, -90)
            path.lineTo(tlx, ty + radius)
            path.arcTo(tlx, ty, 2 * radius, 2 * radius, 180, -90)
            path.closeSubpath()
            return path

        # 底部阴影
        shadow_path = _rounded_trapezoid(tl_x + int(2*s), tr_x - int(2*s), bl_x, br_x,
                                         top_y + int(3*s), bottom_y + int(4*s), cr)
        p.fillPath(shadow_path, QColor(0, 0, 0, 40))

        # 标签主体
        label_path = _rounded_trapezoid(tl_x, tr_x, bl_x, br_x, top_y, bottom_y, cr)
        p.fillPath(label_path, QColor(72, 64, 50, 160))
        p.setPen(QPen(QColor(180, 170, 140, 90), 1))
        p.drawPath(label_path)

        # 顶部高光边
        hl_path = _rounded_trapezoid(tl_x + int(2*s), tr_x - int(2*s),
                                     bl_x + int(4*s), br_x - int(4*s),
                                     top_y + int(1*s), top_y + int(8*s), int(5*s))
        p.fillPath(hl_path, QColor(255, 255, 255, 35))

        # 全局玻璃反光（与梯形贴纸精确重合）
        grad = QLinearGradient(0, top_y, 0, bottom_y)
        grad.setColorAt(0, QColor(255, 255, 255, 100))
        grad.setColorAt(0.3, QColor(255, 255, 255, 30))
        grad.setColorAt(1, QColor(255, 255, 255, 0))
        hl_global = _rounded_trapezoid(tl_x, tr_x, bl_x, br_x, top_y, bottom_y, cr)
        p.fillPath(hl_global, grad)

        # 标签横线
        p.setPen(QPen(QColor(200, 190, 160, 50), 1))
        for i in range(2):
            ly = top_y + 22 + i * 20
            p.drawLine(int(bl_x + 16), ly, int(br_x - 16), ly)

        # --- 磁带轮 ---
        reel_r = int(44 * s)
        reel_y = self._reel_center_y()
        reel_spacing = int(170 * s)
        r1_x = w // 2 - reel_spacing
        r2_x = w // 2 + reel_spacing

        for cx in [r1_x, r2_x]:
            self._draw_reel(p, cx, reel_y, reel_r)

        # --- 四角螺丝 ---
        screw_r = int(7 * s)
        screw_off = int(14 * s)
        screw_positions = [
            (margin + screw_off, margin + screw_off),
            (w - margin - screw_off, margin + screw_off),
            (margin + screw_off, cassette_bottom - screw_off),
            (w - margin - screw_off, cassette_bottom - screw_off),
        ]
        self._screw_positions = screw_positions  # 供点击检测

        for idx, (sx, sy) in enumerate(screw_positions):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(165, 170, 180, 170))
            p.drawEllipse(QPointF(sx, sy), screw_r, screw_r)
            p.setBrush(QColor(135, 140, 150, 190))
            p.drawEllipse(QPointF(sx, sy), screw_r - int(3 * s), screw_r - int(3 * s))

            lw = int(2 * s)
            if idx == 0:
                p.setPen(QPen(QColor(220, 225, 235, 200), max(1, lw)))
                d = int(3 * s)
                p.drawLine(int(sx - d), int(sy), int(sx + d), int(sy))
                p.drawLine(int(sx), int(sy - d), int(sx), int(sy + d))
            elif idx == 1:
                p.setPen(QPen(QColor(220, 225, 235, 200), max(1, lw)))
                d = int(2 * s)
                p.drawLine(int(sx - d), int(sy - d), int(sx + d), int(sy + d))
                p.drawLine(int(sx + d), int(sy - d), int(sx - d), int(sy + d))
            else:
                p.setPen(QPen(QColor(100, 105, 115, 150), 1))
                p.drawLine(int(sx - d), int(sy), int(sx + d), int(sy))
                p.drawLine(int(sx), int(sy - d), int(sx), int(sy + d))

        # === 频谱音浪 ===
        wave_start_x = (w // 2 - reel_spacing) - reel_r
        wave_end_x = (w // 2 + reel_spacing) + reel_r
        wave_total_w = wave_end_x - wave_start_x

        bar_count = min(60, len(self._bars))
        self._bar_count = bar_count
        cell_w = wave_total_w / bar_count  # 每格宽度（浮点）
        bar_w = max(2.0, cell_w * 0.7)     # 柱宽占格宽 70%
        bar_gap = cell_w - bar_w

        waveform_max_h = int(68 * s)
        waveform_base_offset = int(24 * s)
        base_y = cassette_bottom - waveform_base_offset
        max_bar_h = waveform_max_h

        # 先绘制整体炫光背景
        glow_grad = QLinearGradient(0, base_y - max_bar_h, 0, base_y)
        glow_grad.setColorAt(0, QColor(255, 255, 255, 0))
        glow_grad.setColorAt(1, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)

        for i in range(self._bar_count):
            t = self._bars[i]
            bar_h = max(2, int(t * max_bar_h))
            bx = wave_start_x + i * cell_w
            by = base_y - bar_h

            # 流动色相：位置基色 + 时间偏移
            hue = (i / self._bar_count + self._hue_offset) % 1.0
            sat = 1.0
            val = 0.75 + t * 0.25
            # HSV → RGB
            chroma = val * sat
            h6 = hue * 6
            hx = chroma * (1 - abs(h6 % 2 - 1))
            cm = val - chroma
            if h6 < 1:
                rf, gf, bf = chroma, hx, 0
            elif h6 < 2:
                rf, gf, bf = hx, chroma, 0
            elif h6 < 3:
                rf, gf, bf = 0, chroma, hx
            elif h6 < 4:
                rf, gf, bf = 0, hx, chroma
            elif h6 < 5:
                rf, gf, bf = hx, 0, chroma
            else:
                rf, gf, bf = chroma, 0, hx
            r = int((rf + cm) * 255)
            g = int((gf + cm) * 255)
            b = int((bf + cm) * 255)

            # 外层炫光（宽而极其透明）
            p.setBrush(QColor(r, g, b, 30))
            p.drawRoundedRect(QRectF(bx - 3, by - 6, bar_w + 6, bar_h + 10), 6, 6)
            # 中层光晕
            p.setBrush(QColor(r, g, b, 80))
            p.drawRoundedRect(QRectF(bx - 1, by - 3, bar_w + 2, bar_h + 5), 4, 4)
            # 主体色柱
            p.setBrush(QColor(r, g, b, 240))
            p.drawRoundedRect(QRectF(bx, by, bar_w, bar_h), 2, 2)
            # 顶部高亮
            p.setBrush(QColor(min(r + 80, 255), min(g + 80, 255), min(b + 80, 255), 200))
            p.drawRoundedRect(QRectF(bx, by, bar_w, max(3, int(bar_h * 0.25))), 2, 2)

    def _draw_reel(self, p, cx, cy, r):
        """画一个磁带轮（带旋转）"""
        p.save()
        p.translate(cx, cy)

        # 外圈光环
        p.setPen(QPen(QColor(140, 150, 170, 60), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), r, r)

        # 轮体
        p.setPen(QPen(QColor(120, 130, 150, 140), 2))
        p.setBrush(QColor(25, 28, 35, 140))
        p.drawEllipse(QPointF(0, 0), r-2, r-2)

        # 旋转齿轮（计算角度时考虑旋转）
        angle_rad = math.radians(self.rotation_angle)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(55, 58, 68, 100))

        for i in range(5):
            a = math.radians(i * 72) + angle_rad
            gx = math.cos(a) * (r - 16)
            gy = math.sin(a) * (r - 16)
            p.drawEllipse(QPointF(gx, gy), 5, 5)

        # 内环
        p.setPen(QPen(QColor(90, 100, 120, 100), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), r-24, r-24)

        # 中心轴
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(75, 80, 95, 160))
        p.drawEllipse(QPointF(0, 0), 10, 10)
        p.setBrush(QColor(140, 145, 160, 200))
        p.drawEllipse(QPointF(0, 0), 4, 4)

        p.restore()

    # ================================================================
    # 操作
    # ================================================================

    def _open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择音乐文件夹")
        if folder:
            count = self.audio.load_folder(folder)
            if count > 0:
                self._file_list = self.audio.playlist
                self.audio.play_index(0)
                self._update_track_info()
                self.btn_play.setText("⏸")
            else:
                self.lbl_title.setText("未找到音乐文件")
                self.lbl_artist.setText(folder)

    def _play_pause(self):
        if not self.audio.playlist:
            self._open_folder()
            return
        if not self.audio.playing and self.audio.current_index < 0:
            self.audio.play_index(0)
            self._update_track_info()
        else:
            self.audio.toggle()
        self.btn_play.setText("⏸" if self.audio.playing else "▶")

    def _next(self):
        if self.audio.playlist:
            self.audio.next()
            self._update_track_info()
            self.btn_play.setText("⏸")

    def _prev(self):
        if self.audio.playlist:
            self.audio.prev()
            self._update_track_info()
            self.btn_play.setText("⏸")

    def _update_track_info(self):
        if 0 <= self.audio.current_index < len(self.audio.playlist):
            path = self.audio.playlist[self.audio.current_index]
            meta = AudioEngine.get_metadata(path)
            self.lbl_title.setText(meta['title'])
            self.lbl_artist.setText(meta['artist'])
            self._save_state()

    def _save_state(self):
        """持久化保存当前文件夹和歌曲索引"""
        if self.audio.playlist and self.audio.current_index >= 0:
            folder = str(Path(self.audio.playlist[0]).parent)
            self._settings.setValue("last_folder", folder)
            self._settings.setValue("last_index", self.audio.current_index)

    def _restore_state(self):
        """启动时恢复上次的文件夹和歌曲"""
        folder = self._settings.value("last_folder")
        if folder and os.path.isdir(folder):
            count = self.audio.load_folder(folder)
            if count > 0:
                self._file_list = self.audio.playlist
                last_index = self._settings.value("last_index", 0, type=int)
                if last_index >= count:
                    last_index = 0
                self.audio.play_index(last_index)
                self._update_track_info()
                self.btn_play.setText("⏸")
                return
        # 没有保存的状态或文件夹已不存在
        self.lbl_title.setText("未播放")
        self.lbl_artist.setText("请打开音乐文件夹")

    def _corner_at(self, pos):
        """检测鼠标在哪个角：TL=0, TR=1, BL=2, BR=3，无=None"""
        z = 30  # 角落检测范围
        w, h = self.width(), self.height()
        if pos.x() < z and pos.y() < z:
            return 0  # TL
        if pos.x() > w - z and pos.y() < z:
            return 1  # TR
        if pos.x() < z and pos.y() > h - z:
            return 2  # BL
        if pos.x() > w - z and pos.y() > h - z:
            return 3  # BR
        return None

    def mousePressEvent(self, event):
        """处理 角缩放 / 螺丝点击 / 拖拽"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            # 1. 功能螺丝优先（左上 + 和右上 ✕）
            if hasattr(self, '_screw_positions'):
                r = 14  # 固定像素，不随缩放变小
                for idx in (0, 1):
                    sx, sy = self._screw_positions[idx]
                    dist = ((pos.x() - sx) ** 2 + (pos.y() - sy) ** 2) ** 0.5
                    if dist <= r:
                        if idx == 0:
                            self._open_folder()
                        else:
                            self.window().close()
                        return
            # 2. 角缩放（角落 30px）
            corner = self._corner_at(pos)
            if corner is not None:
                self._resize_corner = corner
                self._resize_start = event.globalPosition().toPoint()
                self._resize_geom = self.window().geometry()
                self._resize_min = self.window().minimumSize()
                self.grabMouse()
                return
            # 3. 拖拽移动
            self._drag_start = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        """角缩放 / 窗口拖拽"""
        if hasattr(self, '_resize_corner') and self._resize_corner is not None:
            delta = event.globalPosition().toPoint() - self._resize_start
            g = self._resize_geom
            mw, mh = self._resize_min.width(), self._resize_min.height()
            x, y, w, h = g.x(), g.y(), g.width(), g.height()
            c = self._resize_corner
            if c in (0, 2):  # left
                nx = g.x() + delta.x()
                nw = g.width() - delta.x()
                if nw >= mw:
                    x = nx
                    w = nw
            if c in (1, 3):  # right
                w = max(mw, g.width() + delta.x())
            if c in (0, 1):  # top
                ny = g.y() + delta.y()
                nh = g.height() - delta.y()
                if nh >= mh:
                    y = ny
                    h = nh
            if c in (2, 3):  # bottom
                h = max(mh, g.height() + delta.y())
            self.window().setGeometry(x, y, w, h)
        elif self._drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_start
            self.window().move(self.window().pos() + delta)
            self._drag_start = event.globalPosition().toPoint()
        else:
            c = self._corner_at(event.position())
            if c in (0, 3):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif c in (1, 2):
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if hasattr(self, '_resize_corner') and self._resize_corner is not None:
            self.releaseMouse()
        self._resize_corner = None
        self._drag_start = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._play_pause()
        elif event.key() == Qt.Key.Key_Right:
            self._next()
        elif event.key() == Qt.Key.Key_Left:
            self._prev()

    def closeEvent(self, event):
        self._save_state()
        self.audio.stop()
        self._anim_timer.stop()
        event.accept()


# ============================================================
# 主窗口
# ============================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(680, 520)
        self.setMinimumSize(500, 400)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")

        self.player = CassettePlayer()
        self.setCentralWidget(self.player)


# ============================================================
# 入口
# ============================================================

def main():
    app = QApplication(sys.argv)

    # 全局暗色样式
    app.setStyle("Fusion")
    palette = app.palette()
    palette.setColor(palette.ColorRole.Window, QColor(10, 12, 20))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

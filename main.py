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

        # 动画定时器
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start(30)  # ~33fps

        # 加载字体
        self._setup_ui()
        # 恢复上次状态
        self._restore_state()

    def _setup_ui(self):
        self.setMinimumSize(680, 520)
        self.setWindowTitle("Cassette Player")
        self.setStyleSheet("background: transparent;")

        # 打开文件夹按钮（顶部）
        self.btn_open = QPushButton("+ 打开音乐文件夹", self)
        self.btn_open.setGeometry(250, 12, 180, 28)
        self.btn_open.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.12);
                color: #ccc;
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 14px;
                font-size: 13px;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.25);
                color: #fff;
            }
        """)
        self.btn_open.clicked.connect(self._open_folder)

        # 歌曲信息标签
        self.lbl_title = QLabel("未播放", self)
        self.lbl_title.setGeometry(80, 96, 520, 28)
        self.lbl_title.setStyleSheet("color: #fff; font-size: 18px; font-weight: bold; background: transparent;")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_artist = QLabel("请打开音乐文件夹", self)
        self.lbl_artist.setGeometry(80, 122, 520, 22)
        self.lbl_artist.setStyleSheet("color: #aaa; font-size: 14px; background: transparent;")
        self.lbl_artist.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 按钮
        btn_style = """
            QPushButton {
                background: rgba(255,255,255,0.1);
                color: #ddd;
                border: 2px solid rgba(255,255,255,0.25);
                border-radius: 24px;
                font-size: 22px;
                min-width: 48px;
                min-height: 48px;
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

        # 按钮Y：与磁带轮中心对齐
        btn_h = 48
        btn_y = self._reel_center_y() - btn_h // 2

        self.btn_prev = QPushButton("⏮", self)
        self.btn_prev.setGeometry(220, btn_y, 48, 48)
        self.btn_prev.setStyleSheet(btn_style)
        self.btn_prev.clicked.connect(self._prev)

        self.btn_play = QPushButton("▶", self)
        self.btn_play.setGeometry(316, btn_y, 48, 48)
        self.btn_play.setStyleSheet(btn_style)
        self.btn_play.clicked.connect(self._play_pause)

        self.btn_next = QPushButton("⏭", self)
        self.btn_next.setGeometry(412, btn_y, 48, 48)
        self.btn_next.setStyleSheet(btn_style)
        self.btn_next.clicked.connect(self._next)

        # 文件列表（隐藏的）
        self._file_list = []

    def _reel_center_y(self):
        """计算磁带轮中心 Y 坐标（动态适配，音浪上方）"""
        margin = 18
        label_y = margin + 8
        label_h = 68
        waveform_max_h = 68
        waveform_base_offset = 24
        cassette_bottom = self.height() - margin
        waveform_top = cassette_bottom - waveform_base_offset - waveform_max_h
        label_bottom = label_y + label_h
        return label_bottom + (waveform_top - label_bottom) // 2

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
        self.update()  # 重绘

    # ================================================================
    # 绘制
    # ================================================================

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        # 布局常量
        margin = 18
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

        # 顶部高光
        grad = QLinearGradient(0, margin, 0, margin + 80)
        grad.setColorAt(0, QColor(255, 255, 255, 100))
        grad.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(margin + 30, margin + 3, bw - 60, 75), grad)

        # --- 标签区 ---
        label_y = margin + 8
        label_h = 68
        label_path = QPainterPath()
        label_path.addRoundedRect(QRectF(margin + 26, label_y, bw - 52, label_h), 8, 8)
        p.fillPath(label_path, QColor(70, 62, 48, 130))
        p.setPen(QPen(QColor(190, 180, 150, 80), 1))
        p.drawPath(label_path)

        # 标签横线
        p.setPen(QPen(QColor(210, 200, 170, 60), 1))
        for i in range(2):
            ly = label_y + 24 + i * 20
            p.drawLine(int(margin + 42), ly, int(w - margin - 42), ly)

        # --- 磁带轮 ---
        reel_r = 44
        reel_y = self._reel_center_y()
        reel_spacing = 170
        r1_x = w // 2 - reel_spacing
        r2_x = w // 2 + reel_spacing

        for cx in [r1_x, r2_x]:
            self._draw_reel(p, cx, reel_y, reel_r)

        # --- 四角螺丝 ---
        screw_r = 7
        for sx, sy in [(margin + 14, margin + 14),
                       (w - margin - 14, margin + 14),
                       (margin + 14, cassette_bottom - 14),
                       (w - margin - 14, cassette_bottom - 14)]:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(165, 170, 180, 170))
            p.drawEllipse(QPointF(sx, sy), screw_r, screw_r)
            p.setBrush(QColor(135, 140, 150, 190))
            p.drawEllipse(QPointF(sx, sy), screw_r - 3, screw_r - 3)
            p.setPen(QPen(QColor(100, 105, 115, 150), 1))
            p.drawLine(int(sx - 2), int(sy), int(sx + 2), int(sy))
            p.drawLine(int(sx), int(sy - 2), int(sx), int(sy + 2))

        # === 频谱音浪（磁带机身内部底部，宽度对齐两磁带轮外边缘） ===
        # 复用磁带轮的水平位置
        reel_r = 44
        reel_spacing = 170
        wave_start_x = (w // 2 - reel_spacing) - reel_r   # 左轮左边缘
        wave_end_x = (w // 2 + reel_spacing) + reel_r     # 右轮右边缘
        wave_total_w = wave_end_x - wave_start_x

        bar_w = 5
        bar_gap = 2
        bar_count = (wave_total_w + bar_gap) // (bar_w + bar_gap)
        self._bar_count = min(bar_count, len(self._bars))  # 不超过预分配容量
        actual_total_w = self._bar_count * (bar_w + bar_gap) - bar_gap
        start_x = wave_start_x + (wave_total_w - actual_total_w) // 2

        waveform_max_h = 68
        waveform_base_offset = 24
        base_y = cassette_bottom - waveform_base_offset
        max_bar_h = waveform_max_h

        p.setPen(Qt.PenStyle.NoPen)
        for i in range(self._bar_count):
            t = self._bars[i]  # 0.0 ~ 1.0
            bar_h = max(2, int(t * max_bar_h))
            bx = start_x + i * (bar_w + bar_gap)
            by = base_y - bar_h

            # 彩虹频谱：色相从左到右渐变，亮度随高度变化
            hue = i / self._bar_count          # 0.0 → 1.0 全色相
            sat = 0.90
            val = 0.5 + t * 0.5               # 基准更亮，确保低柱可见
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
            a = int(160 + t * 95)

            p.setBrush(QColor(r, g, b, a))
            p.drawRoundedRect(QRectF(bx, by, bar_w, bar_h), 2, 2)

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
        self.setWindowTitle("Cassette Player")
        self.setFixedSize(680, 520)
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

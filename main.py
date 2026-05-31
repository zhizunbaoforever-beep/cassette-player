"""
透明磁带音乐播放器 — Cassette Player
─────────────────────────────────────────
• 磁带轮旋转动画 + 频谱音浪可视化
• 上一首 / 播放暂停 / 下一首
• 支持 MP3 / FLAC / WAV / OGG / M4A / AAC
• 无边框透明窗口 + 四角拖拽缩放
• 状态记忆（上次文件夹 & 歌曲）
"""
import sys        # 系统相关，获取平台信息
import os          # 文件路径操作
import math        # 数学函数（sin/cos 用于旋转角度）
import random      # 随机数（频谱动画用）
from pathlib import Path  # 面向对象的文件路径处理

# ── PyQt6 GUI 组件 ────────────────────────────
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget,
                              QVBoxLayout, QHBoxLayout, QPushButton,
                              QFileDialog, QListWidget, QLabel, QSlider)
# ── PyQt6 核心（事件、定时器、几何、URL、设置）──
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QUrl, QSettings
# ── PyQt6 绘图（画笔、颜色、画刷、渐变、路径）──
from PyQt6.QtGui import (QPainter, QColor, QBrush, QPen, QFont,
                          QLinearGradient, QRadialGradient, QPainterPath,
                          QFontDatabase, QAction)
# ── PyQt6 多媒体（音频播放器 + 输出设备）───────
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

# ── mutagen：读取音频文件元数据（ID3 tags）─────
from mutagen import File as MutagenFile
from mutagen.mp3 import MP3


# ============================================================
#  音频引擎 — 负责所有音频播放逻辑（独立于 UI）
# ============================================================

class AudioEngine:
    """管理播放列表、播放控制、元数据读取"""

    def __init__(self, parent=None):
        # ── Qt 多媒体核心：播放器 + 音频输出 ──
        self._player = QMediaPlayer(parent)      # 媒体播放器实例
        self._audio = QAudioOutput(parent)       # 音频输出设备
        self._player.setAudioOutput(self._audio) # 绑定输出
        self._audio.setVolume(0.8)               # 默认音量 80%

        # ── 播放列表状态 ──
        self._playlist = []   # 歌曲路径列表
        self._index = -1      # 当前播放索引（-1 = 无）
        self._playing = False # 是否正在播放

        # ── 监听播放状态变化（Qt 信号 → 本地回调）──
        self._player.playbackStateChanged.connect(self._on_state_change)

    def _on_state_change(self, state):
        """Qt 播放状态变化时更新内部标志"""
        self._playing = (state == QMediaPlayer.PlaybackState.PlayingState)

    # ── 属性（只读）────────────────────────────
    @property
    def playing(self):
        return self._playing

    @property
    def current_index(self):
        return self._index

    @property
    def playlist(self):
        return self._playlist

    def position(self):
        """当前播放位置（毫秒）"""
        return self._player.position()

    def duration(self):
        """当前歌曲总时长（毫秒）"""
        return self._player.duration()

    def seek(self, ms):
        """跳转到指定毫秒位置"""
        self._player.setPosition(ms)

    # ── 播放列表管理 ───────────────────────────
    def load_folder(self, folder_path):
        """递归扫描文件夹，收集支持的音频文件"""
        extensions = {'.mp3', '.flac', '.wav', '.ogg', '.m4a', '.aac'}
        self._playlist = []
        for ext in extensions:
            for f in Path(folder_path).rglob(f'*{ext}'):  # 递归匹配
                self._playlist.append(str(f))
        self._playlist.sort()  # 按路径排序
        return len(self._playlist)

    def play_index(self, index):
        """播放指定索引的歌曲"""
        if 0 <= index < len(self._playlist):
            path = self._playlist[index]
            # QUrl.fromLocalFile 将本地路径转为 Qt 可识别的 URL
            self._player.setSource(QUrl.fromLocalFile(path))
            self._player.play()
            self._playing = True
            self._index = index
            return True
        return False

    # ── 播放控制 ───────────────────────────────
    def toggle(self):
        """播放 / 暂停切换"""
        if self._playing:
            self._player.pause()
        else:
            self._player.play()

    def stop(self):
        """停止播放"""
        self._player.stop()
        self._playing = False

    def next(self):
        """下一首（循环到列表头）"""
        if self._playlist:
            nxt = (self._index + 1) % len(self._playlist)
            return self.play_index(nxt)
        return False

    def prev(self):
        """上一首（循环到列表尾）"""
        if self._playlist:
            prv = (self._index - 1) % len(self._playlist)
            return self.play_index(prv)
        return False

    # ── 元数据 ─────────────────────────────────
    @staticmethod
    def get_metadata(filepath):
        """读取歌曲的标题（TIT2）和艺术家（TPE1）标签"""
        try:
            if filepath.endswith('.mp3'):
                audio = MP3(filepath)     # mutagen 解析 MP3
                tags = audio.tags          # ID3 标签字典
                if tags:
                    title = str(tags.get('TIT2', Path(filepath).stem))
                    artist = str(tags.get('TPE1', 'Unknown'))
                    return {'title': title, 'artist': artist, 'path': filepath}
            # 非 MP3 或无标签时用文件名作为标题
            return {'title': Path(filepath).stem, 'artist': 'Unknown', 'path': filepath}
        except Exception:
            return {'title': Path(filepath).stem, 'artist': 'Unknown', 'path': filepath}


# ============================================================
#  磁带播放器主控件 — 所有 UI 绘制 & 交互逻辑
# ============================================================

class CassettePlayer(QWidget):
    """磁带风格音乐播放器控件（继承 QWidget）"""

    # ── 构造 & 初始化 ──────────────────────────
    def __init__(self):
        super().__init__()
        self.audio = AudioEngine(self)          # 音频引擎实例
        self.rotation_angle = 0.0               # 磁带轮旋转角度（度）
        self._settings = QSettings("CassettePlayer", "CassettePlayer")  # 持久化存储

        # ── 频谱柱数据（预分配容量，实际数量由布局决定）──
        self._bar_count = 60                    # 柱子上限
        self._bars = [0.05] * self._bar_count   # 当前高度（0~1）
        self._bar_targets = [0.05] * self._bar_count  # 目标高度
        self._bar_frame = 0                     # 动画帧计数
        self._hue_offset = 0.0                  # 色相偏移（流动彩虹）
        self._drag_start = None                 # 拖拽起始坐标
        self._seeking = False                  # 是否正在拖拽进度条

        # ── 动画定时器：每 30ms 触发 _tick，约 33fps ──
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start(30)

        # ── 歌曲信息（由 paintEvent 绘制到标签区）──
        self._track_title = "未播放"
        self._track_artist = "请打开音乐文件夹"

        # ── 初始化 UI 并恢复上次播放状态 ──
        self._setup_ui()
        self._restore_state()

    # ── UI 初始化（只调用一次）──────────────────
    def _setup_ui(self):
        self.setMinimumSize(500, 320)           # 窗口最小尺寸（磁带比例）
        self.setMouseTracking(True)             # 启用鼠标追踪（悬停光标变化）
        self.setStyleSheet("background: transparent;")  # 透明背景

        # ── 三个控制按钮（QPushButton）──────────
        # 按钮由 paintEvent 手绘（避免原生样式干扰）
        self._btn_play_text = "▶"         # 播放按钮文字（▶ / ⏸）
        self._btn_regions = []            # [(rect, action), ...] → 点击检测
        self._btn_hover = -1              # 当前悬停按钮索引（-1 = 无）
        self._file_list = []

    # ── 窗口缩放时重新布局 ─────────────────────
    def resizeEvent(self, event):
        """窗口缩放时触发重绘"""
        super().resizeEvent(event)

    # ── 磁带轮中心 Y 坐标计算 ──────────────────
    def _reel_center_y(self):
        """动态计算：在标签区和进度条+音浪区之间居中"""
        w = self.width()
        s = w / 680
        margin = int(18 * s)
        label_y = margin + int(8 * s)
        label_h = int(68 * s)
        waveform_max_h = int(78 * s)
        waveform_base_offset = int(6 * s)
        progress_space = int(14 * s)     # 进度条高度 + 间距
        cassette_bottom = self.height() - margin
        # reel 下方的可用空间顶部
        content_bottom = cassette_bottom - waveform_base_offset - waveform_max_h - progress_space
        return label_y + label_h + (content_bottom - label_y - label_h) // 2

    # ================================================================
    #  动画循环 — 每 30ms 执行一次
    # ================================================================

    def _tick(self):
        """更新磁带轮角度 + 频谱柱高度 + 色相偏移"""
        if self.audio.playing:
            # ── 播放中：磁带轮旋转 + 频谱跳动 ──
            self.rotation_angle += 3.0         # 每帧旋转 3°（约 100°/秒）
            self._bar_frame += 1               # 帧计数器递增
            if self._bar_frame % 4 == 0:       # 每 4 帧（~120ms）更新一批
                n = self._bar_count
                for i in range(0, n, 3):       # 步长 3，分批更新
                    # random.uniform(a, b)：生成 a~b 间随机浮点数
                    self._bar_targets[i] = random.uniform(0.2, 1.0)        # 主柱：较高
                    self._bar_targets[min(i + 1, n - 1)] = random.uniform(0.12, 0.65)  # 邻柱：中等
                    self._bar_targets[min(i + 2, n - 1)] = random.uniform(0.05, 0.35)  # 次邻：矮
        else:
            # ── 暂停中：所有柱子缓慢衰减到接近 0 ──
            for i in range(self._bar_count):
                self._bar_targets[i] = 0.05

        # ── 平滑插值（lerp）：当前值 → 目标值，每帧移动 18% ──
        for i in range(self._bar_count):
            self._bars[i] += (self._bar_targets[i] - self._bars[i]) * 0.18

        # ── 色相偏移：每帧 +0.003，循环 0~1，实现彩虹流动 ──
        self._hue_offset = (self._hue_offset + 0.003) % 1.0

        self.update()  # 触发 paintEvent 重绘

    # ================================================================
    #  绘制 — paintEvent 在 update() 或窗口变化时自动调用
    # ================================================================

    def paintEvent(self, event):
        """绘制整个磁带 UI：机身 → 标签 → 磁带轮 → 螺丝 → 频谱"""
        p = QPainter(self)                            # 创建画笔
        p.setRenderHint(QPainter.RenderHint.Antialiasing)  # 抗锯齿

        w, h = self.width(), self.height()            # 当前控件尺寸

        # ── 缩放参数（以 680px 宽为基准）─────────
        base_w = 680
        s = w / base_w                               # 缩放比例
        margin = int(18 * s)                         # 机身外边距
        cassette_bottom = h - margin                 # 机身底部 Y
        bw = w - margin * 2                          # 机身宽度（扣除边距）
        bh = h - margin * 2                          # 机身高度（扣除边距）

        # ── 玻璃磁带主体（圆角矩形 + 半透明填充）──
        path = QPainterPath()                        # 创建矢量路径
        path.addRoundedRect(QRectF(margin, margin, bw, bh), 22, 22)  # 圆角半径 22
        p.fillPath(path, QColor(55, 60, 72, 110))    # 深灰蓝半透明填充
        p.setPen(QPen(QColor(170, 180, 200, 150), 2)) # 浅灰边框 2px
        p.drawPath(path)                             # 绘制路径

        # ── 内部发光（比机身小 3px 的亮框）───────
        path2 = QPainterPath()
        path2.addRoundedRect(QRectF(margin + 3, margin + 3, bw - 6, bh - 6), 20, 20)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1)) # 极淡白色
        p.drawPath(path2)

        # ── 标签区（梯形 + 凸起效果）─────────────
        label_y = margin + int(10 * s)               # 标签顶部 Y
        label_h = int(64 * s)                        # 标签高度
        slant = int(10 * s)                          # 梯形内收量（上宽下窄）
        tl_x = margin + int(26 * s)                  # 标签左上 X
        tr_x = w - margin - int(26 * s)              # 标签右上 X
        bl_x = tl_x + slant                          # 标签左下 X（内收）
        br_x = tr_x - slant                          # 标签右下 X（内收）
        top_y = label_y
        bottom_y = label_y + label_h
        cr = int(8 * s)                              # 圆角半径

        # 局部函数：构建圆角梯形矢量路径
        def _rounded_trapezoid(tlx, trx, blx, brx, ty, by, radius):
            """返回 QPainterPath：上宽下窄的圆角梯形。
               四角用 arcTo 画 90° 圆弧，边用 lineTo 连直线。"""
            path = QPainterPath()
            # 起点：左上角弧线结束处
            path.moveTo(tlx + radius, ty)
            # 顶边 →
            path.lineTo(trx - radius, ty)
            # 右上角弧（从 90° 逆时针转 90° → 0°）
            path.arcTo(trx - 2 * radius, ty, 2 * radius, 2 * radius, 90, -90)
            # 右边 ↙（斜向内收）
            path.lineTo(brx, by - radius)
            # 右下角弧（0° → 270°）
            path.arcTo(brx - 2 * radius, by - 2 * radius, 2 * radius, 2 * radius, 0, -90)
            # 底边 ←
            path.lineTo(blx + radius, by)
            # 左下角弧（270° → 180°）
            path.arcTo(blx, by - 2 * radius, 2 * radius, 2 * radius, 270, -90)
            # 左边 ↗（斜向外扩）
            path.lineTo(tlx, ty + radius)
            # 左上角弧（180° → 90°）
            path.arcTo(tlx, ty, 2 * radius, 2 * radius, 180, -90)
            path.closeSubpath()  # 闭合路径
            return path

        # ① 标签底部阴影（向下偏移 3~4px）
        shadow_path = _rounded_trapezoid(tl_x + int(2*s), tr_x - int(2*s), bl_x, br_x,
                                         top_y + int(3*s), bottom_y + int(4*s), cr)
        p.fillPath(shadow_path, QColor(0, 0, 0, 40))  # 40/255 透明黑

        # ② 标签主体（暖棕色半透明）
        label_path = _rounded_trapezoid(tl_x, tr_x, bl_x, br_x, top_y, bottom_y, cr)
        p.fillPath(label_path, QColor(72, 64, 50, 160))
        p.setPen(QPen(QColor(180, 170, 140, 90), 1))
        p.drawPath(label_path)

        # ③ 顶部高光边（窄梯形，模拟光打在凸起边缘）
        hl_path = _rounded_trapezoid(tl_x + int(2*s), tr_x - int(2*s),
                                     bl_x + int(4*s), br_x - int(4*s),
                                     top_y + int(1*s), top_y + int(8*s), int(5*s))
        p.fillPath(hl_path, QColor(255, 255, 255, 35))

        # ④ 全局玻璃反光（与梯形精确重合的渐变）
        # QLinearGradient(x1, y1, x2, y2)：从 (x1,y1) 到 (x2,y2) 的线性渐变
        grad = QLinearGradient(0, top_y, 0, bottom_y)  # 垂直渐变
        grad.setColorAt(0, QColor(255, 255, 255, 100))   # 顶部亮白
        grad.setColorAt(0.3, QColor(255, 255, 255, 30))  # 30% 处骤减
        grad.setColorAt(1, QColor(255, 255, 255, 0))     # 底部全透
        hl_global = _rounded_trapezoid(tl_x, tr_x, bl_x, br_x, top_y, bottom_y, cr)
        p.fillPath(hl_global, grad)

        # ⑤ 标签装饰横线（两条淡色线）
        p.setPen(QPen(QColor(200, 190, 160, 50), 1))
        for i in range(2):
            ly = top_y + 22 + i * 20
            p.drawLine(int(bl_x + 16), ly, int(br_x - 16), ly)

        # ⑥ 绘制歌曲信息文字（融入标签区）
        font_s = max(10, int(14 * s))              # 歌名字体大小
        artist_font_s = max(8, int(11 * s))        # 艺术家字体大小
        label_cx = (tl_x + tr_x) / 2               # 标签水平中心

        # ── 歌名 ──
        title_font = QFont("Microsoft YaHei", font_s)
        title_font.setBold(True)
        p.setFont(title_font)
        p.setPen(QColor(240, 235, 220, 220))       # 暖白色
        title_rect = QRectF(tl_x + 10, top_y + 4, tr_x - tl_x - 20, 24 * s)
        p.drawText(title_rect, Qt.AlignmentFlag.AlignCenter, self._track_title)

        # ── 艺术家 ──
        artist_font = QFont("Microsoft YaHei", artist_font_s)
        p.setFont(artist_font)
        p.setPen(QColor(200, 190, 170, 180))       # 淡暖色
        artist_rect = QRectF(tl_x + 10, top_y + 28 * s, tr_x - tl_x - 20, 20 * s)
        p.drawText(artist_rect, Qt.AlignmentFlag.AlignCenter, self._track_artist)

        # ── 磁带轮（左右两个旋转轮盘）───────────
        reel_r = int(44 * s)                       # 轮盘半径
        reel_y = self._reel_center_y()              # 轮盘中心 Y
        reel_spacing = int(170 * s)                 # 两轮中心间距
        r1_x = w // 2 - reel_spacing               # 左轮 X
        r2_x = w // 2 + reel_spacing               # 右轮 X
        for cx in [r1_x, r2_x]:
            self._draw_reel(p, cx, reel_y, reel_r)

        # ── 手绘控制按钮（⏮ ▶/⏸ ⏭）──────────────
        btn_s = int(44 * s)
        btn_spacing = int(reel_spacing * 0.50)
        center_x = w // 2
        btn_y = reel_y - btn_s // 2
        btn_font = QFont("Segoe UI Symbol", max(10, int(20 * s)))
        p.setFont(btn_font)

        # 三组按钮位置 (x, y, w, symbol)
        btns = [
            (center_x - btn_spacing - btn_s // 2, btn_y, btn_s, "⏮"),   # 上一首
            (center_x - btn_s // 2, btn_y, btn_s, self._btn_play_text),  # 播放/暂停
            (center_x + btn_spacing - btn_s // 2, btn_y, btn_s, "⏭"),   # 下一首
        ]
        self._btn_regions = []  # 重建点击区域
        for i, (bx, by_, bs, sym) in enumerate(btns):
            rect = QRectF(bx, by_, bs, bs)
            self._btn_regions.append(rect)
            # 悬停高亮
            hovered = (self._btn_hover == i)
            if hovered:
                p.setPen(QColor(255, 255, 255, 255))
            else:
                p.setPen(QColor(180, 180, 180, 180))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, sym)

        # ── 四角螺丝 ────────────────────────────
        screw_r = int(7 * s)                       # 螺丝外圈半径
        screw_off = int(14 * s)                    # 螺丝距边缘偏移
        screw_positions = [
            (margin + screw_off, margin + screw_off),                     # 左上：+
            (w - margin - screw_off, margin + screw_off),                 # 右上：✕
            (margin + screw_off, cassette_bottom - screw_off),            # 左下：一字槽
            (w - margin - screw_off, cassette_bottom - screw_off),        # 右下：一字槽
        ]
        self._screw_positions = screw_positions     # 存储 → 供点击检测

        for idx, (sx, sy) in enumerate(screw_positions):
            # 外圈（浅银灰）
            p.setPen(Qt.PenStyle.NoPen)            # 无边框
            p.setBrush(QColor(165, 170, 180, 170))  # 画刷填充
            p.drawEllipse(QPointF(sx, sy), screw_r, screw_r)
            # 内圈（稍暗）
            p.setBrush(QColor(135, 140, 150, 190))
            p.drawEllipse(QPointF(sx, sy), screw_r - int(3 * s), screw_r - int(3 * s))

            lw = int(2 * s)                        # 线条宽度
            if idx == 0:                           # 左上：十字 +
                p.setPen(QPen(QColor(220, 225, 235, 200), max(1, lw)))
                d = int(3 * s)
                p.drawLine(int(sx - d), int(sy), int(sx + d), int(sy))   # 横线
                p.drawLine(int(sx), int(sy - d), int(sx), int(sy + d))   # 竖线
            elif idx == 1:                         # 右上：叉号 ✕
                p.setPen(QPen(QColor(220, 225, 235, 200), max(1, lw)))
                d = int(2 * s)
                p.drawLine(int(sx - d), int(sy - d), int(sx + d), int(sy + d))  # 对角线
                p.drawLine(int(sx + d), int(sy - d), int(sx - d), int(sy + d))  # 反对角线
            else:                                  # 左下/右下：一字槽
                p.setPen(QPen(QColor(100, 105, 115, 150), 1))
                p.drawLine(int(sx - d), int(sy), int(sx + d), int(sy))
                p.drawLine(int(sx), int(sy - d), int(sx), int(sy + d))

        # ── 播放进度条（音浪上方）─────────────────
        # 先算音浪水平跨度 & 垂直参数（进度条 & 音浪共用）
        wave_start_x = (w // 2 - reel_spacing) - reel_r
        wave_end_x = (w // 2 + reel_spacing) + reel_r
        wave_total_w = wave_end_x - wave_start_x

        waveform_max_h = int(78 * s)
        waveform_base_offset = int(6 * s)

        dur = self.audio.duration()
        pos_ms = self.audio.position()

        # ── 进度条 Y 坐标 ────────────────────────
        progress_y = cassette_bottom - waveform_base_offset - waveform_max_h - int(10 * s)

        # ── 时间标签 ────────────────────────────
        def _fmt(ms):
            """毫秒 → MM:SS"""
            if ms <= 0:
                return "00:00"
            sec = ms // 1000
            return f"{sec // 60:02d}:{sec % 60:02d}"

        time_font = QFont("Consolas", max(9, int(12 * s)))
        p.setFont(time_font)
        p.setPen(QColor(200, 200, 200, 160))
        elapsed_text = _fmt(pos_ms)
        remain_text = "-" + _fmt(max(0, dur - pos_ms))
        # 左侧已播放时间
        p.drawText(QRectF(wave_start_x - int(70 * s), progress_y - int(12 * s),
                          int(65 * s), int(20 * s)),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   elapsed_text)
        # 右侧剩余时间
        p.drawText(QRectF(wave_end_x + int(5 * s), progress_y - int(12 * s),
                          int(65 * s), int(20 * s)),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   remain_text)

        # ── 进度条轨道 ──────────────────────────
        progress_h = int(4 * s)
        progress_rect = QRectF(wave_start_x, progress_y, wave_total_w, progress_h)
        self._progress_rect = progress_rect

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawRoundedRect(progress_rect, 2, 2)

        # 已播放部分
        if dur > 0:
            frac = min(pos_ms / dur, 1.0)
            filled_w = int(progress_rect.width() * frac)
            if filled_w > 0:
                filled_rect = QRectF(progress_rect.x(), progress_rect.y(),
                                     filled_w, progress_rect.height())
                p.setBrush(QColor(220, 200, 150, 180))
                p.drawRoundedRect(filled_rect, 2, 2)

        # 进度滑块（爱心符号 ❤）
        if dur > 0 and pos_ms >= 0:
            dot_x = progress_rect.x() + progress_rect.width() * frac
            dot_y = progress_rect.center().y()
            heart_font = QFont("Segoe UI Emoji", max(8, int(11 * s)))
            p.setFont(heart_font)
            p.setPen(QColor(255, 100, 130, 240))
            p.drawText(QRectF(dot_x - int(10 * s), dot_y - int(10 * s),
                              int(20 * s), int(20 * s)),
                       Qt.AlignmentFlag.AlignCenter, "❤")

        # ── 频谱音浪（磁带机身内部底部）───────────
        bar_count = min(60, len(self._bars))
        self._bar_count = bar_count
        cell_w = wave_total_w / bar_count
        bar_w = max(2.0, cell_w * 0.7)
        bar_gap = cell_w - bar_w

        base_y = cassette_bottom - waveform_base_offset
        max_bar_h = waveform_max_h

        p.setPen(Qt.PenStyle.NoPen)                # 以下全部无边框
        for i in range(self._bar_count):
            t = self._bars[i]                      # 当前高度比例（0~1）
            bar_h = max(2, int(t * max_bar_h))     # 实际像素高度
            bx = wave_start_x + i * cell_w         # 柱子左边缘 X
            by = base_y - bar_h                    # 柱子顶部 Y（从基线向上）

            # ── HSV → RGB 颜色计算 ────────────
            # 色相 = 位置 + 时间偏移 → 流动彩虹
            hue = (i / self._bar_count + self._hue_offset) % 1.0
            sat = 1.0                              # 全饱和
            val = 0.75 + t * 0.25                  # 亮度随高度增强

            chroma = val * sat                     # 色度
            h6 = hue * 6                           # 色相 × 6（映射到 6 段）
            hx = chroma * (1 - abs(h6 % 2 - 1))   # 中间量
            cm = val - chroma                      # 亮度补偿

            # 根据 h6 的整数部分确定 RGB 分量
            if h6 < 1:       rf, gf, bf = chroma, hx, 0
            elif h6 < 2:     rf, gf, bf = hx, chroma, 0
            elif h6 < 3:     rf, gf, bf = 0, chroma, hx
            elif h6 < 4:     rf, gf, bf = 0, hx, chroma
            elif h6 < 5:     rf, gf, bf = hx, 0, chroma
            else:            rf, gf, bf = chroma, 0, hx

            r = int((rf + cm) * 255)               # 红色通道
            g = int((gf + cm) * 255)               # 绿色通道
            b = int((bf + cm) * 255)               # 蓝色通道

            # ── 三层绘制（炫光效果）───────────
            # ① 外层炫光：宽 6px，极其透明（alpha=30）
            p.setBrush(QColor(r, g, b, 30))
            p.drawRoundedRect(QRectF(bx - 3, by - 6, bar_w + 6, bar_h + 10), 6, 6)
            # ② 中层光晕：宽 2px，半透明（alpha=80）
            p.setBrush(QColor(r, g, b, 80))
            p.drawRoundedRect(QRectF(bx - 1, by - 3, bar_w + 2, bar_h + 5), 4, 4)
            # ③ 主体色柱：原宽度，高不透明（alpha=240）
            p.setBrush(QColor(r, g, b, 240))
            p.drawRoundedRect(QRectF(bx, by, bar_w, bar_h), 2, 2)
            # ④ 顶部高亮：柱顶 25% 部分额外增亮
            p.setBrush(QColor(min(r + 80, 255), min(g + 80, 255), min(b + 80, 255), 200))
            p.drawRoundedRect(QRectF(bx, by, bar_w, max(3, int(bar_h * 0.25))), 2, 2)

    def _draw_reel(self, p, cx, cy, r):
        """绘制一个磁带轮（含旋转齿轮和中心轴）
           p.save/translate/restore：临时移动坐标系到 (cx, cy)，画完后恢复"""
        p.save()                                   # 保存当前画笔状态
        p.translate(cx, cy)                        # 移动坐标系原点到此轮中心

        # ① 外圈光环（浅色细环）
        p.setPen(QPen(QColor(140, 150, 170, 60), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)          # 不填充
        p.drawEllipse(QPointF(0, 0), r, r)

        # ② 轮体（深色圆盘）
        p.setPen(QPen(QColor(120, 130, 150, 140), 2))
        p.setBrush(QColor(25, 28, 35, 140))
        p.drawEllipse(QPointF(0, 0), r - 2, r - 2)

        # ③ 5 个旋转齿轮（随 rotation_angle 旋转）
        angle_rad = math.radians(self.rotation_angle)  # 角度 → 弧度
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(55, 58, 68, 100))
        for i in range(5):
            a = math.radians(i * 72) + angle_rad      # 每个齿轮间隔 72°，加上旋转偏移
            gx = math.cos(a) * (r - 16)               # 齿轮 X = cos(角度) × 半径
            gy = math.sin(a) * (r - 16)               # 齿轮 Y = sin(角度) × 半径
            p.drawEllipse(QPointF(gx, gy), 5, 5)      # 小圆齿轮

        # ④ 内环（装饰圈）
        p.setPen(QPen(QColor(90, 100, 120, 100), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), r - 24, r - 24)

        # ⑤ 中心轴（大圆 + 小亮点）
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(75, 80, 95, 160))
        p.drawEllipse(QPointF(0, 0), 10, 10)
        p.setBrush(QColor(140, 145, 160, 200))
        p.drawEllipse(QPointF(0, 0), 4, 4)

        p.restore()                                # 恢复坐标系

    # ================================================================
    #  操作 — 播放控制 & 状态管理
    # ================================================================

    def _open_folder(self):
        """打开文件夹对话框，加载音乐并播放第一首"""
        # QFileDialog.getExistingDirectory：系统原生文件夹选择对话框
        folder = QFileDialog.getExistingDirectory(self, "选择音乐文件夹")
        if folder:
            count = self.audio.load_folder(folder)
            if count > 0:
                self._file_list = self.audio.playlist  # 缓存播放列表引用
                self.audio.play_index(0)                # 播放第一首
                self._update_track_info()               # 更新标签文字
                self._btn_play_text = "⏸"
                self.update()
            else:
                self._track_title = "未找到音乐文件"
                self._track_artist = folder

    def _play_pause(self):
        """播放/暂停切换。若无播放列表则先打开文件夹"""
        if not self.audio.playlist:
            self._open_folder()                      # 空列表 → 提示选文件夹
            return
        if not self.audio.playing and self.audio.current_index < 0:
            self.audio.play_index(0)                 # 从未播放过 → 播放第一首
            self._update_track_info()
        else:
            self.audio.toggle()                      # 播放 ↔ 暂停
        self._btn_play_text = "⏸" if self.audio.playing else "▶"
        self.update()

    def _next(self):
        """下一首"""
        if self.audio.playlist:
            self.audio.next()
            self._update_track_info()
            self._btn_play_text = "⏸"
            self.update()

    def _prev(self):
        """上一首"""
        if self.audio.playlist:
            self.audio.prev()
            self._update_track_info()
            self._btn_play_text = "⏸"
            self.update()

    def _update_track_info(self):
        """根据当前索引更新歌名和艺术家标签"""
        if 0 <= self.audio.current_index < len(self.audio.playlist):
            path = self.audio.playlist[self.audio.current_index]
            meta = AudioEngine.get_metadata(path)    # 读取 ID3 标签
            self._track_title = meta['title']
            self._track_artist = meta['artist']
            self._save_state()                       # 自动保存状态

    def _save_state(self):
        """用 QSettings 持久化：当前文件夹路径 + 歌曲索引"""
        if self.audio.playlist and self.audio.current_index >= 0:
            folder = str(Path(self.audio.playlist[0]).parent)  # 取第一首所在文件夹
            self._settings.setValue("last_folder", folder)
            self._settings.setValue("last_index", self.audio.current_index)

    def _restore_state(self):
        """启动时恢复上次的播放状态"""
        folder = self._settings.value("last_folder")  # 读取设置
        if folder and os.path.isdir(folder):           # 文件夹仍存在
            count = self.audio.load_folder(folder)
            if count > 0:
                self._file_list = self.audio.playlist
                last_index = self._settings.value("last_index", 0, type=int)
                if last_index >= count:                # 防止索引越界
                    last_index = 0
                self.audio.play_index(last_index)
                self._update_track_info()
                self._btn_play_text = "⏸"
                self.update()
                return
        # 恢复失败：显示默认提示
        self._track_title = "未播放"
        self._track_artist = "请打开音乐文件夹"

    # ================================================================
    #  鼠标 & 键盘事件
    # ================================================================

    def _corner_at(self, pos):
        """判断鼠标坐标在哪个窗口角。
           z=30：四角 30×30px 为缩放热区。
           返回 0(TL), 1(TR), 2(BL), 3(BR), None(非角落)"""
        z = 30
        w, h = self.width(), self.height()
        if pos.x() < z and pos.y() < z:      return 0   # 左上 ↖
        if pos.x() > w - z and pos.y() < z:  return 1   # 右上 ↗
        if pos.x() < z and pos.y() > h - z:  return 2   # 左下 ↙
        if pos.x() > w - z and pos.y() > h - z: return 3  # 右下 ↘
        return None

    def mousePressEvent(self, event):
        """鼠标按下 → 螺丝 / 角缩放 / 拖拽 三选一"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()                   # 相对于本控件的坐标

            # ① 手绘按钮点击
            if hasattr(self, '_btn_regions'):
                for i, r in enumerate(self._btn_regions):
                    if r.contains(pos):
                        if i == 0:
                            self._prev()
                        elif i == 1:
                            self._play_pause()
                        elif i == 2:
                            self._next()
                        return

            # ② 进度条点击 / 拖动跳转
            if hasattr(self, '_progress_rect') and self.audio.duration() > 0:
                pr = self._progress_rect
                if pr.contains(pos):
                    self._seeking = True         # 进入拖拽模式
                    frac = (pos.x() - pr.x()) / pr.width()
                    frac = max(0.0, min(1.0, frac))
                    self.audio.seek(int(self.audio.duration() * frac))
                    return

            # ② 功能螺丝（半径 14px 固定值）
            if hasattr(self, '_screw_positions'):
                r = 14
                for idx in (0, 1):                   # 只检查左上(+)和右上(✕)
                    sx, sy = self._screw_positions[idx]
                    # 勾股定理算距离
                    dist = ((pos.x() - sx) ** 2 + (pos.y() - sy) ** 2) ** 0.5
                    if dist <= r:
                        if idx == 0:
                            self._open_folder()      # 左上：打开文件夹
                        else:
                            self.window().close()    # 右上：关闭窗口
                        return                       # 已处理，不继续

            # ② 角落缩放
            corner = self._corner_at(pos)
            if corner is not None:
                self._resize_corner = corner          # 记录哪个角
                self._resize_start = event.globalPosition().toPoint()  # 起始屏幕坐标
                self._resize_geom = self.window().geometry()   # 起始窗口几何
                self._resize_min = self.window().minimumSize() # 最小尺寸限制
                return

            # ③ 否则：开始拖拽
            self._drag_start = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        """鼠标移动 → 进度条拖拽 / 缩放 / 窗口拖拽 / 光标切换"""
        # ── 进度条拖拽中 ──
        if (hasattr(self, '_seeking') and self._seeking
                and event.buttons() & Qt.MouseButton.LeftButton):
            if hasattr(self, '_progress_rect') and self.audio.duration() > 0:
                pr = self._progress_rect
                pos = event.position()
                frac = (pos.x() - pr.x()) / pr.width()
                frac = max(0.0, min(1.0, frac))
                self.audio.seek(int(self.audio.duration() * frac))
                return

        # ── 缩放中 ──
        if (hasattr(self, '_resize_corner') and self._resize_corner is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            delta = event.globalPosition().toPoint() - self._resize_start
            g = self._resize_geom
            mw, mh = self._resize_min.width(), self._resize_min.height()
            x, y, w, h = g.x(), g.y(), g.width(), g.height()  # 初始几何
            c = self._resize_corner

            # 根据角落位置调整对应边
            if c in (0, 2):                          # 左边角 → 修改左边界 & 宽度
                nx = g.x() + delta.x()
                nw = g.width() - delta.x()
                if nw >= mw:                         # 不低于最小宽度
                    x = nx; w = nw
            if c in (1, 3):                          # 右边角 → 修改宽度
                w = max(mw, g.width() + delta.x())
            if c in (0, 1):                          # 上边角 → 修改上边界 & 高度
                ny = g.y() + delta.y()
                nh = g.height() - delta.y()
                if nh >= mh:
                    y = ny; h = nh
            if c in (2, 3):                          # 下边角 → 修改高度
                h = max(mh, g.height() + delta.y())

            self.window().setGeometry(x, y, w, h)    # 应用新尺寸

        # ── 拖拽中 ──
        elif self._drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_start
            self.window().move(self.window().pos() + delta)  # 移动窗口
            self._drag_start = event.globalPosition().toPoint()

        # ── 悬停中（仅切换光标形状）──
        else:
            pos = event.position()
            # 按钮 hover 检测
            hover_changed = False
            if hasattr(self, '_btn_regions'):
                new_hover = -1
                for i, r in enumerate(self._btn_regions):
                    if r.contains(pos):
                        new_hover = i
                        break
                if new_hover != self._btn_hover:
                    self._btn_hover = new_hover
                    hover_changed = True
            # 进度条上显示手型光标
            if (hasattr(self, '_progress_rect')
                    and self._progress_rect.contains(pos)
                    and self.audio.duration() > 0):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            elif hasattr(self, '_btn_regions') and self._btn_hover >= 0:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                c = self._corner_at(pos)
                if c in (0, 3):
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                elif c in (1, 2):
                    self.setCursor(Qt.CursorShape.SizeBDiagCursor)
                else:
                    self.setCursor(Qt.CursorShape.ArrowCursor)
            if hover_changed:
                self.update()  # 重绘以显示/隐藏 hover 效果

    def mouseReleaseEvent(self, event):
        """鼠标释放 → 清除所有拖拽状态"""
        self._seeking = False
        self._resize_corner = None
        self._drag_start = None

    def keyPressEvent(self, event):
        """键盘快捷键：空格 = 播放/暂停，←→ = 切歌"""
        if event.key() == Qt.Key.Key_Space:
            self._play_pause()
        elif event.key() == Qt.Key.Key_Right:
            self._next()
        elif event.key() == Qt.Key.Key_Left:
            self._prev()

    def closeEvent(self, event):
        """窗口关闭前保存状态，停止音频和动画"""
        self._save_state()
        self.audio.stop()
        self._anim_timer.stop()
        event.accept()                             # 允许关闭


# ============================================================
#  主窗口 — 承载 CassettePlayer 的顶层容器
# ============================================================

class MainWindow(QMainWindow):
    """无边框透明主窗口"""

    def __init__(self):
        super().__init__()
        self.resize(680, 420)              # 初始窗口尺寸（磁带比例）
        self.setMinimumSize(500, 320)      # 最小尺寸

        # FramelessWindowHint：去掉系统标题栏和边框 → 磁带形状即窗口
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

        # WA_TranslucentBackground：允许窗口背景透明 → 桌面可见
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")

        # 将 CassettePlayer 设为中心控件（填满窗口）
        self.player = CassettePlayer()
        self.setCentralWidget(self.player)


# ============================================================
#  程序入口
# ============================================================

def main():
    """创建 Qt 应用 → 显示窗口 → 进入事件循环"""
    app = QApplication(sys.argv)           # Qt 应用实例（必须最先创建）

    # ── 全局暗色主题 ──
    app.setStyle("Fusion")                 # Fusion：跨平台一致的现代风格
    palette = app.palette()
    palette.setColor(palette.ColorRole.Window, QColor(10, 12, 20))  # 默认窗口暗色
    app.setPalette(palette)

    window = MainWindow()                  # 创建主窗口
    window.show()                          # 显示窗口
    sys.exit(app.exec())                   # 进入 Qt 事件循环（阻塞直到关闭）


if __name__ == "__main__":
    main()                                 # 直接运行时调用入口

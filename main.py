import json
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, messagebox
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor
import re

# ----------- Utils -----------

COMMON_COLORS = {
    "White": "#FFFFFF",
    "Black": "#000000",
    "Yellow": "#FFD700",
    "Light Yellow": "#FFFACD",
    "Blue": "#1E90FF",
    "Light Blue": "#87CEFA",
    "Red": "#FF4500",
    "Green": "#32CD32",
    "Gray": "#A9A9A9"
}

def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return RGBColor(int(hex_color[0:2],16), int(hex_color[2:4],16), int(hex_color[4:6],16))

def parse_lyrics(text):
    """
    解析歌詞成 [(SEG, lyrics), ...] 格式
    依照 [Verse], [Chorus], [Bridge], [Pre-Chorus] 等標籤拆段
    """
    blocks = []
    current_seg = "Intro"
    current_lines = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r'\[(.+?)\]', line)
        if match:
            # 新段落
            if current_lines:
                blocks.append((current_seg, "\n".join(current_lines)))
            current_seg = match.group(1)
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        blocks.append((current_seg, "\n".join(current_lines)))
    return blocks

# ----------- Page Tab -----------

class SongTab(ttk.Frame):
    def __init__(self, master, clone_from=None):
        super().__init__(master)
        self.bg_image = tk.StringVar()
        self.lyrics_left = tk.DoubleVar(value=0.05)
        self.lyrics_top = tk.DoubleVar(value=1.8)

        self._build_ui()
        if clone_from:
            self.clone_settings(clone_from)

    def _build_ui(self):
        # ----- 歌詞輸入 -----
        lyrics_frame = ttk.LabelFrame(self, text="歌曲資訊")
        lyrics_frame.pack(fill="both", expand=True, padx=10, pady=5)

        ttk.Label(lyrics_frame, text="歌曲名稱: ").pack(anchor="w")
        self.title_text = tk.Text(lyrics_frame, height=1)
        self.title_text.pack(fill="x", pady=2)

        # ttk.Label(lyrics_frame, text="貼上歌詞:\n[分段]\n歌詞\n...\n[分段]\n歌詞\n...\n)").pack(anchor="w", pady=(5,0))
        ttk.Label(lyrics_frame, text="所有歌詞:\n\t[分段]歌詞 -> 製成一頁PPT").pack(anchor="w", pady=(5,0))
        self.lyrics_text = tk.Text(lyrics_frame, height=15)
        self.lyrics_text.pack(fill="both", expand=True, pady=2)

        # ----- Style Controls -----
        style_frame = ttk.LabelFrame(self, text="PPT字幕顏色")
        style_frame.pack(fill="x", padx=10, pady=5)

        self.styles = {}
        for key, name in zip(["Title", "Segment", "Lyrics"], ["標題文字設定:  ", "段落文字設定:  ", "歌詞文字設定:  "]):
            self._style_row(style_frame, key, name)

        # ----- Lyric Position Controls -----
        pos_frame = ttk.LabelFrame(self, text="歌詞位置調整 (吋)")
        pos_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(pos_frame, text="距離左邊:  ").pack(side="left")
        ttk.Entry(pos_frame, textvariable=self.lyrics_left, width=6).pack(side="left", padx=5)
        ttk.Label(pos_frame, text="距離上邊:  ").pack(side="left", padx=(10, 0))
        ttk.Entry(pos_frame, textvariable=self.lyrics_top, width=6).pack(side="left", padx=5)

        # ----- Background -----
        bg_frame = ttk.LabelFrame(self, text="背景設定")
        bg_frame.pack(fill="x", padx=10, pady=5)
        ttk.Button(bg_frame, text="選擇背景圖片", command=self.select_bg).pack(side="left")
        ttk.Label(bg_frame, textvariable=self.bg_image).pack(side="left", padx=10)

    def _style_row(self, parent, key, name):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=2)
        ttk.Label(frame, text=name, width=15).pack(side="left")

        font_var = tk.StringVar(value="Arial")
        size_var = tk.IntVar(value=64 if key=="Lyrics" else 60 if key=="Title" else 30)
        color_var = tk.StringVar(value="#FFFFFF")

        ttk.Entry(frame, textvariable=font_var, width=10).pack(side="left", padx=3)
        ttk.Entry(frame, textvariable=size_var, width=5).pack(side="left", padx=3)

        btn = tk.Button(frame, width=3, bg=color_var.get())
        btn.pack(side="left", padx=3)
        btn.bind("<Button-1>", lambda e, v=color_var, b=btn: self.pick_common_color(v,b))
        btn.bind("<Button-3>", lambda e, v=color_var, b=btn: self.pick_color_picker(v,b))

        self.styles[key] = {"font": font_var, "size": size_var, "color": color_var}

    def pick_common_color(self, var, btn):
        menu = tk.Menu(self, tearoff=0)
        for name, hexcode in COMMON_COLORS.items():
            menu.add_command(label=name, background=hexcode,
                             command=lambda h=hexcode: self._set_color(var, btn, h))
        menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    def pick_color_picker(self, var, btn):
        c = colorchooser.askcolor()[1]
        if c:
            self._set_color(var, btn, c)

    def _set_color(self, var, btn, color):
        var.set(color)
        btn.config(bg=color)

    def select_bg(self):
        path = filedialog.askopenfilename(filetypes=[("Image", "*.jpg *.png *.jpeg")])
        if path:
            self.bg_image.set(path)

    def clone_settings(self, other):
        self.title_text.insert("1.0", other.title_text.get("1.0", "end"))
        self.lyrics_text.insert("1.0", other.lyrics_text.get("1.0", "end"))
        self.bg_image.set(other.bg_image.get())
        for k in self.styles:
            self.styles[k]["font"].set(other.styles[k]["font"].get())
            self.styles[k]["size"].set(other.styles[k]["size"].get())
            self.styles[k]["color"].set(other.styles[k]["color"].get())

# ----------- Main App -----------

class WorshipPPTApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("教會 敬拜歌曲PPT 快速生成器")
        self.geometry("950x700")

        # Notebook
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        self._menu()
        self.add_tab()

    def _menu(self):
        menu_frame = ttk.Frame(self)
        menu_frame.pack(fill="x")
        ttk.Button(menu_frame, text="+ 新增歌曲", command=self.add_tab).pack(side="left", padx=5)
        ttk.Button(menu_frame, text="生成 PPT", command=self.generate_ppt).pack(side="left", padx=5)
        ttk.Button(menu_frame, text="預覽 (尚未開發)", state="disabled").pack(side="left", padx=5)

        ttk.Button(menu_frame, text="儲存專案", command=self.save_json).pack(side="left", padx=20)
        ttk.Button(menu_frame, text="讀取專案 (將覆蓋掉現在沒有存檔的一切)", command=self.load_json).pack(side="left", padx=5)

    def save_json(self):
        data = {"songs": []}

        for tab_id in self.notebook.tabs():
            tab = self.notebook.nametowidget(tab_id)

            song = {
                "title": tab.title_text.get("1.0", "end").strip(),
                "lyrics": tab.lyrics_text.get("1.0", "end").strip(),
                "background": tab.bg_image.get(),
                "lyrics_left": tab.lyrics_left.get(),
                "lyrics_top": tab.lyrics_top.get(),
                "styles": {}
            }

            for key, style in tab.styles.items():
                song["styles"][key] = {
                    "font": style["font"].get(),
                    "size": style["size"].get(),
                    "color": style["color"].get(),
                }

            data["songs"].append(song)

        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON File", "*.json")]
        )

        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            messagebox.showinfo("Saved", "Project saved successfully.")

    def load_json(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON File", "*.json")]
        )

        if not path:
            return

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # ---------- 清空現有 tabs ----------
        for tab_id in self.notebook.tabs():
            self.notebook.forget(tab_id)

        # ---------- 重建 tabs ----------
        for idx, song in enumerate(data.get("songs", []), start=1):
            tab = SongTab(self.notebook)
            self.notebook.add(tab, text=f"Song {idx}  ✖")

            # Title / Lyrics
            tab.title_text.insert("1.0", song.get("title", ""))
            tab.lyrics_text.insert("1.0", song.get("lyrics", ""))

            # Background
            tab.bg_image.set(song.get("background", ""))
            tab.lyrics_left.set(song.get("lyrics_left", 0.05))
            tab.lyrics_top.set(song.get("lyrics_top", 1.8))

            # Styles
            for key, style in song.get("styles", {}).items():
                if key in tab.styles:
                    tab.styles[key]["font"].set(style.get("font", "Arial"))
                    tab.styles[key]["size"].set(style.get("size", 40))
                    tab.styles[key]["color"].set(style.get("color", "#FFFFFF"))

        if self.notebook.tabs():
            self.notebook.select(self.notebook.tabs()[0])

        messagebox.showinfo("Loaded", "Project loaded successfully.")

    def add_tab(self):
        clone = None
        if self.notebook.tabs():
            clone = self.notebook.nametowidget(self.notebook.select())

        tab = SongTab(self.notebook, clone_from=clone)
        idx = len(self.notebook.tabs()) + 1
        self.notebook.add(tab, text=f"Song {idx}  ✖")
        self.notebook.select(tab)

        # X close button
        self.notebook.bind("<Button-2>", self.close_tab)

    def close_tab(self, event):
        try:
            index = self.notebook.index(f"@{event.x},{event.y}")
            self.notebook.forget(index)
        except:
            pass

    def generate_ppt(self):
        prs = Presentation()
        blank = prs.slide_layouts[6]  # Blank slide
        warned_bg_missing = set()

        for tab_id in self.notebook.tabs():
            tab = self.notebook.nametowidget(tab_id)
            title = tab.title_text.get("1.0", "end").strip()
            full_lyrics = tab.lyrics_text.get("1.0", "end")
            blocks = parse_lyrics(full_lyrics)

            for seg, lyrics in blocks:
                slide = prs.slides.add_slide(blank)

                # ---------- Background ----------
                bg_path = tab.bg_image.get()
                song_name = title or f"Song {self.notebook.index(tab_id) + 1}"

                if bg_path:
                    try:
                        slide.shapes.add_picture(
                            bg_path,
                            0, 0,
                            width=prs.slide_width,
                            height=prs.slide_height
                        )

                    except FileNotFoundError:
                        # ---- 同一首歌只警告一次 ----
                        if song_name not in warned_bg_missing:
                            warned_bg_missing.add(song_name)

                            messagebox.showwarning(
                                "背景圖片不存在",
                                f"找不到背景圖片，該歌曲將不使用背景圖。\n\n"
                                f"歌曲：{song_name}\n"
                                f"檔案：\n{bg_path}"
                            )

                # ---------- HEADER : Title + Segment (同一行) ----------
                header_text = f"{title}    [{seg}]"

                self.add_header(
                    slide,
                    title=title,
                    segment=seg,
                    title_style=tab.styles["Title"],
                    segment_style=tab.styles["Segment"],
                    left=Inches(0.5),
                    top=Inches(0.4),
                    width=prs.slide_width - Inches(1),
                    height=Inches(1.0)
                )

                # ---------- LYRICS : 滿版 ----------
                self.add_textbox(
                    slide,
                    lyrics,
                    tab.styles["Lyrics"],
                    left=Inches(tab.lyrics_left.get()),
                    top=Inches(tab.lyrics_top.get()),
                    width=prs.slide_width - Inches(tab.lyrics_left.get()*2),
                    height=prs.slide_height - Inches(2.1)
                )

        out_path = filedialog.asksaveasfilename(
            defaultextension=".pptx",
            filetypes=[("PowerPoint", "*.pptx")]
        )
        if out_path:
            prs.save(out_path)
            messagebox.showinfo("Done", f"PPT generated:\n{out_path}")

    def add_header(self, slide, title, segment, title_style, segment_style, left, top, width, height):
        box = slide.shapes.add_textbox(left, top, width, height)
        tf = box.text_frame
        tf.word_wrap = False
        tf.clear()

        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER

        # ----- TITLE -----
        run_title = p.add_run()
        run_title.text = title + "  "
        run_title.font.name = title_style["font"].get()
        run_title.font.size = Pt(title_style["size"].get())
        run_title.font.color.rgb = hex_to_rgb(title_style["color"].get())

        # ----- SEGMENT -----
        run_seg = p.add_run()
        run_seg.text = f"[{segment}]"
        run_seg.font.name = segment_style["font"].get()
        run_seg.font.size = Pt(segment_style["size"].get())
        run_seg.font.color.rgb = hex_to_rgb(segment_style["color"].get())


    def add_textbox(self, slide, content, style, left, top, width, height):
        box = slide.shapes.add_textbox(left, top, width, height)
        tf = box.text_frame
        tf.word_wrap = True
        tf.clear()

        # 新增：整個文字都是同一樣式
        p = tf.paragraphs[0]
        p.text = content.strip()
        p.alignment = PP_ALIGN.CENTER

        for run in p.runs:
            run.font.name = style["font"].get()
            run.font.size = Pt(style["size"].get())
            run.font.color.rgb = hex_to_rgb(style["color"].get())

        # 如果只有一個段落，就確保整個段落套用顏色
        if len(tf.paragraphs) == 1:
            for paragraph in tf.paragraphs:
                for r in paragraph.runs:
                    r.font.color.rgb = hex_to_rgb(style["color"].get())


# ----------- Run App -----------

if __name__ == "__main__":
    WorshipPPTApp().mainloop()

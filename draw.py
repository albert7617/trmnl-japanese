import cairo
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, TypedDict
from typing import List, Dict
import os
import random
from enum import IntEnum
import sqlite3
from bs4 import BeautifulSoup, Tag

import qrcode


DB_PATH = os.path.join("data", "jisho_words.db")

def get_pat_path(idx):
    pattern_base_path = os.path.join("www", "img")
    return os.path.join(pattern_base_path, f"gray-{idx}.png")

def get_all_words() -> List[Dict]:
    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        query = """
        SELECT
            mw.wrapper_html as meaning_wrapper,
            w.representation_html as representation,
            mw.word_id,
            mw.id as meaning_wrapper_id
        FROM meaning_wrappers mw
        JOIN words w ON mw.word_id = w.id
        ORDER BY mw.word_id, mw.id
        """

        cursor = conn.cursor()
        cursor.execute(query, )
        rows = cursor.fetchall()

        return [dict(row) for row in rows]

    finally:
        conn.close()

def extract_meaning(html: str) -> tuple[str, List[tuple], str]:
    soup = BeautifulSoup(html, "html.parser")
    # Extract meaning-meaning
    meaning_span = soup.find("span", class_="meaning-meaning")
    meaning = meaning_span.get_text(strip=True) if meaning_span else ""

    # Extract all <li> elements inside the first <ul>
    li_elements = []
    ul = soup.find("ul")
    if ul and isinstance(ul, Tag):
        for li in ul.find_all("li"):
            if not isinstance(li, Tag):
                continue
            # Extract furigana and unlinked text if present
            furigana = None
            unlinked = None
            furigana_span = li.find("span", class_="furigana")
            if furigana_span:
                furigana = furigana_span.get_text(strip=True)
            unlinked_span = li.find("span", class_="unlinked")
            if unlinked_span:
                unlinked = unlinked_span.get_text(strip=True)
            li_elements.append((furigana, unlinked))

    # Extract english sentence
    english_span = soup.find("span", class_="english")
    english = english_span.get_text(strip=True) if english_span else ""

    return meaning, li_elements, english

class RepresentationBlock:
    def __init__(self, kanji: str, furigana: str, furigana_span: str|None = None):
        self.kanji = kanji
        self.furigana = furigana
        self.furigana_span = furigana_span

    def __repr__(self):
        return f"RepresentationBlock(kanji={self.kanji!r}, furigana={self.furigana!r}, furigana_span={self.furigana_span!r})"

class TextBlock:
    def __init__(self, char: str, is_span: bool):
        if char is None:
            self.char = ""
        else:
            self.char = char
        self.is_span = is_span

    def __len__(self):
        if self.is_span:
            return 1
        else:
            return len(self.char)

    def __repr__(self):
        return self.char

class FullMeaning:
    def __init__(self, word: List[RepresentationBlock], meaning: str, japanese: List[tuple], english: str):
        self.word = word
        self.meaning = meaning
        self.japanese = japanese
        self.english = english

    def __repr__(self):
        return f"FullMeaning(word={self.word!r}, meaning={self.meaning!r}, japanese={self.japanese!r}, english={self.english!r})"

def extract_representation(html: str):
    soup = BeautifulSoup(html, 'html.parser')
    concept_div = soup.find('div', class_='concept_light-representation')

    if not concept_div:
        return []

    furigana = []
    furigana_span = []
    text = []

    # Extract furigana elements with precise structure analysis
    assert isinstance(concept_div, Tag)
    furigana_span_div = concept_div.find('span', class_='furigana')
    if furigana_span_div and isinstance(furigana_span_div, Tag):
        for child in furigana_span_div.children:
            if getattr(child, 'name', None) == 'span':
                furigana.append(child.text.strip())
                furigana_span.append(None)
            elif getattr(child, 'name', None) == 'ruby':
                assert isinstance(child, Tag)
                rt = child.find('rt')
                rb = child.find('rb')
                if rt is None:
                    raise ValueError("Malformed ruby element: missing <rt>")
                furigana.append(rt.text.strip())
                furigana_span.append(rb.text.strip() if rb else None)
            else:
                raise ValueError(f"Unexpected element in furigana span: {child}")

    # Extract text elements with precise structure analysis
    text_span = concept_div.find('span', class_='text')
    assert isinstance(text_span, Tag)
    if text_span:
        for content in text_span.contents:
            if isinstance(content, str) and content.strip():
                text.append(TextBlock(content.strip(), is_span=False))
            elif getattr(content, 'name', None) == 'span':
                text.append(TextBlock(content.text.strip(), is_span=True))

    if len(furigana) == len(text):
        return [RepresentationBlock(kanji=str(k), furigana=f, furigana_span=fs) for k, f, fs in zip(text, furigana, furigana_span)]
    elif len(furigana) == sum(len(tb) for tb in text):
        combined_text = []
        for tb in text:
            if tb.is_span:
                combined_text.append(str(tb))
            else:
                combined_text.extend(list(tb.char))
        return [RepresentationBlock(kanji=k, furigana=f, furigana_span=fs) for k, f, fs in zip(combined_text, furigana, furigana_span)]

    raise ValueError("Mismatch between furigana and text lengths")

def get_font_size_constraint_width(ctx: cairo.Context, text: str, max_width: float, initial_size: int = 96, min_size: int = 8) -> int:
    font_size = initial_size
    while True:
        ctx.set_font_size(font_size)
        extents = ctx.text_extents(text)
        if extents.x_advance < max_width:
            return font_size
        else:
            font_size -= 1
            if font_size < min_size:
                return font_size

def get_font_size_constraint_height(ctx: cairo.Context, text: str, furigana: str, max_height: float, initial_size: int = 96, min_size: int = 8) -> int:
    font_size = initial_size
    while True:
        ctx.set_font_size(font_size)
        extents = ctx.text_extents(text)
        ctx.set_font_size(font_size/3)
        extents_furigana = ctx.text_extents(furigana)
        if (extents.height + extents_furigana.height) < max_height:
            return font_size
        else:
            font_size -= 1
            if font_size < min_size:
                return font_size

def plot_qr_code(ctx: cairo.Context, data: str, qr_code_width: int, plot_width: int):
    qr = qrcode.QRCode(
        error_correction=qrcode.ERROR_CORRECT_H,
        border=0,
    )

    qr.add_data(data)
    qr.make(fit=True)

    # Get QR code matrix
    matrix = qr.get_matrix()
    size = len(matrix)
    # box_size = qr.box_size
    # border = qr.border

    # Set QR code color
    ctx.set_source_rgb(0, 0, 0)

    offset_x = (plot_width - qr_code_width)
    dot_size = qr_code_width / size

    # Draw QR code modules
    for y in range(size):
        for x in range(size):
            if matrix[y][x]:
                ctx.rectangle(
                    x * dot_size + offset_x,
                    y * dot_size,
                    dot_size, dot_size
                )
                ctx.fill()

def get_center_semicolon_pos(string: str) -> int:
    idx = 0
    length = len(string)
    if string[length // 2] == ';':
        return length // 2

    while True:
        idx += 1
        left_idx = (length // 2) - idx
        right_idx = (length // 2) + idx
        if left_idx >= 0 and string[left_idx] == ';':
            return left_idx
        if right_idx < length and string[right_idx] == ';':
            return right_idx
        if left_idx < 0 and right_idx >= length:
            break
    return -1

def plot_japanese(data: FullMeaning, name: str, width: int = 780, height: int = 460) -> str:
    config_margin_top = 10
    config_margin_right = 10
    config_margin_bottom = 10
    config_margin_left = 10

    container_width  = width
    container_height = height

    plot_width = container_width - config_margin_left - config_margin_right
    plot_height = container_height - config_margin_top - config_margin_bottom

    svg_path = os.path.join("www", "img", f"{name}.svg")

    svg_surface = cairo.SVGSurface(svg_path, container_width, container_height)

    ctx = cairo.Context(svg_surface)

    ctx.save()
    ctx.translate(config_margin_left, config_margin_top)

    ctx.select_font_face("Noto Sans JP",
                         cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)

    ctx.set_source_rgb(0, 0, 0)

    kanji = "".join([str(block.kanji) for block in data.word])
    jisho_url = f"https://jisho.org/search/{kanji}"
    plot_qr_code(ctx, jisho_url, 98, plot_width=plot_width)

    font_size_w = get_font_size_constraint_width(ctx, kanji, plot_width, initial_size=150, min_size=48)
    font_size_h = get_font_size_constraint_height(ctx, kanji, "フリガナ", plot_height/2, initial_size=150, min_size=48)
    font_size = min(font_size_w, font_size_h)

    ctx.set_font_size(font_size)
    extents = ctx.text_extents(kanji)
    x_pos = (plot_width - extents.x_advance) / 2
    y_pos = (plot_height / 2) - config_margin_bottom
    y_pos_furigana = y_pos - extents.height

    for block in data.word:
        # Draw text
        ctx.move_to(x_pos, y_pos)
        kanji = str(block.kanji)
        kanji_extents = ctx.text_extents(kanji)
        ctx.show_text(kanji)


        ctx.set_font_size(font_size/3)
        furigana = block.furigana
        furigana_extents = ctx.text_extents(furigana)
        x_pos_furigana = x_pos + (kanji_extents.x_advance - furigana_extents.x_advance) / 2
        ctx.move_to(x_pos_furigana, y_pos_furigana)

        ctx.show_text(furigana)
        ctx.set_font_size(font_size)
        x_pos += kanji_extents.x_advance + 3


    ctx.select_font_face("Noto Sans JP",
                        cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    meaning = data.meaning

    semicolon_pos = get_center_semicolon_pos(meaning)
    meaning_font_size = 20
    meaning_padding_top = 20
    font_size = get_font_size_constraint_width(ctx, meaning, plot_width, initial_size=meaning_font_size, min_size=8)
    ctx.set_font_size(meaning_font_size)

    if font_size != meaning_font_size and semicolon_pos != -1:
        # break into two lines
        meaning_left  = meaning[:semicolon_pos] + ";"
        meaning_right = meaning[semicolon_pos+2:]
        extents = ctx.text_extents(meaning_left)
        x_pos = (plot_width - extents.x_advance) / 2
        y_pos = y_pos + extents.height + meaning_padding_top
        meaning_left_height = extents.height
        ctx.move_to(x_pos, y_pos)
        ctx.show_text(meaning_left)
        extents = ctx.text_extents(meaning_right)
        x_pos = (plot_width - extents.x_advance) / 2
        y_pos = y_pos + meaning_left_height
        ctx.move_to(x_pos, y_pos)
        ctx.show_text(meaning_right)
    else:
        extents = ctx.text_extents(meaning)
        x_pos = (plot_width - extents.x_advance) / 2
        y_pos = y_pos + extents.height + meaning_padding_top
        ctx.move_to(x_pos, y_pos)
        ctx.show_text(meaning)

    japanese_sentence = ""
    for furigana, kanji in data.japanese:
        japanese_sentence += kanji if kanji is not None else ""
    font_size_jp = get_font_size_constraint_width(ctx, japanese_sentence, plot_width, initial_size=28, min_size=8)
    font_size_en = get_font_size_constraint_width(ctx, data.english, plot_width, initial_size=20, min_size=8)

    ctx.set_font_size(font_size_jp)
    height_kanji = ctx.text_extents("漢字").height
    ctx.set_font_size(font_size_jp/3)
    height_furigana = ctx.text_extents("ふりがな").height
    ctx.set_font_size(font_size_en)
    height_english = ctx.text_extents("English").height

    ctx.set_font_size(font_size_jp)
    extents = ctx.text_extents(japanese_sentence)
    x_pos = (plot_width - extents.x_advance) / 2

    y_pos_en = plot_height - 10
    y_pos_kanji = y_pos_en - height_english - 5
    y_pos_furigana = y_pos_kanji - height_kanji

    for furigana, kanji in data.japanese:
        if kanji is None:
            raise ValueError("Kanji cannot be None in japanese sentence")

        ctx.set_font_size(font_size_jp)
        kanji_extents = ctx.text_extents(kanji)
        ctx.move_to(x_pos, y_pos_kanji)
        ctx.show_text(kanji)

        if furigana is not None:
            ctx.set_font_size(font_size_jp/2)
            extents = ctx.text_extents(furigana)
            ctx.move_to(x_pos, y_pos_furigana)
            ctx.show_text(furigana)

        x_pos += kanji_extents.x_advance

    ctx.set_font_size(font_size_en)
    extents = ctx.text_extents(data.english)
    x_pos = (plot_width - extents.x_advance) / 2
    ctx.move_to(x_pos, y_pos_en)
    ctx.show_text(data.english)

    ctx.restore()
    svg_surface.finish()

    return svg_path

def plot_word(word, width: int = 780, height: int = 460) -> str:
    try:
        word_id = word["word_id"]
        meaning_wrapper_id = word["meaning_wrapper_id"]
        repr = extract_representation(word["representation"])
        meaning, japanese, english = extract_meaning(word["meaning_wrapper"])
        full = FullMeaning(repr, meaning, japanese, english)
        return plot_japanese(full, f"word-{word_id}-{meaning_wrapper_id}", width, height)
    except ValueError as e:
        print(f"Error processing word_id {d['word_id']}: {e}")
        print(d["representation"])
        print(d["meaning_wrapper"])
        return ""

def generate_word(width: int = 780, height: int = 460, word_id: int = 0) -> str:
    data = get_all_words()
    d = data[word_id]
    return plot_word(d, width, height)

def generate_word_date(width: int = 780, height: int = 460, date_str: str = "", offset: int = 0) -> str:
    data = get_all_words()
    seed = int(hashlib.md5(date_str.encode()).hexdigest(), 16) % (2**32)
    random.seed(seed)
    data_rand = random.sample(data, 4)
    return plot_word(data_rand[offset % 4], width, height)

if __name__ == '__main__':
    data = get_all_words()
    for d in data:
        plot_word(d, 780, 460)
        # plot_word(d, int(780/2), int(460/2))
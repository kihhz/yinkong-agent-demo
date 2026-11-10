"""Extract small, citable passages from conversation uploads."""
import csv
import io
from dataclasses import dataclass
from itertools import islice
from pathlib import PurePosixPath
from zipfile import ZipFile

FILE_TYPES = ("pdf", "docx", "xlsx", "csv")
MAX_FILE_MB = 3
MAX_FILES = 3
MAX_ROWS = 300
MAX_COLUMNS = 30
MAX_SHEETS = 12
MAX_FRAGMENTS = 300
MAX_FRAGMENT_CHARS = 1600


@dataclass(frozen=True)
class Attachment:
    name: str
    fragments: tuple[tuple[str, str], ...]
    truncated: bool = False


class AttachmentError(ValueError):
    pass


def display_name(name):
    name = PurePosixPath(name.replace("\\", "/")).name
    name = "".join(char for char in name if char.isprintable())
    return name[:112] + "…" + name[-12:] if len(name) > 125 else name


def _check_office_archive(data):
    with ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) > 1000 or sum(member.file_size for member in members) > 24 * 1024 * 1024:
            raise AttachmentError("Office 文件展开后过大。请另存为精简文件。")


def _table_fragments(rows, label, start, state):
    header = ""
    for index, cells in enumerate(rows, start):
        if index >= start + MAX_ROWS:
            state["truncated"] = True
            break
        values = ["" if cell is None else " ".join(str(cell).split()) for cell in cells]
        if not any(values):
            continue
        if len(values) > MAX_COLUMNS or any(len(value) > 180 for value in values[:MAX_COLUMNS]):
            state["truncated"] = True
        values = [value[:180] for value in values[:MAX_COLUMNS]]
        if not header:
            header = " | ".join(f"{col}={value}" for col, value in enumerate(values, 1) if value)
            if len(header) > 480:
                state["truncated"] = True
            yield f"{label}第 {index} 行", f"列标题或首行：{header}"
            continue
        entries = " | ".join(f"{col}={value}" for col, value in enumerate(values, 1) if value)
        yield f"{label}第 {index} 行", f"列标题或首行：{header[:480]}\n本行：{entries}"


def _word_fragments(data, state):
    from docx import Document
    from docx.table import Table

    document = Document(io.BytesIO(data))
    paragraph_number = table_number = 0
    for item in document.iter_inner_content():
        if isinstance(item, Table):
            table_number += 1
            rows = (tuple(cell.text for cell in row.cells) for row in item.rows)
            yield from _table_fragments(rows, f"表 {table_number} · ", 1, state)
        else:
            paragraph_number += 1
            text = item.text.strip()
            for offset in range(0, len(text), MAX_FRAGMENT_CHARS):
                yield f"第 {paragraph_number} 段", text[offset:offset + MAX_FRAGMENT_CHARS]


def _excel_fragments(data, state):
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
    try:
        if len(workbook.worksheets) > MAX_SHEETS:
            state["truncated"] = True
        sheets = workbook.worksheets[:MAX_SHEETS]
        quota = MAX_FRAGMENTS // max(1, len(sheets))
        for sheet in sheets:
            if (sheet.max_row or 0) > MAX_ROWS or (sheet.max_column or 0) > MAX_COLUMNS:
                state["truncated"] = True
            rows = sheet.iter_rows(max_row=min(sheet.max_row or MAX_ROWS, MAX_ROWS),
                                   max_col=min(sheet.max_column or MAX_COLUMNS, MAX_COLUMNS),
                                   values_only=True)
            fragments = _table_fragments(rows, f"工作表「{sheet.title}」· ", 1, state)
            sample = list(islice(fragments, quota + 1))
            if len(sample) > quota:
                state["truncated"] = True
            yield from sample[:quota]
    finally:
        workbook.close()


def _csv_fragments(data, state):
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            content = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise AttachmentError("CSV 编码无法识别。请另存为 UTF-8 CSV。")
    if "\0" in content:
        raise AttachmentError("CSV 包含二进制数据。请另存为 UTF-8 CSV。")
    yield from _table_fragments(csv.reader(io.StringIO(content)), "", 1, state)


def read_attachment(data, name, read_pdf):
    filename = display_name(name)
    kind = PurePosixPath(filename).suffix.lower().lstrip(".")
    if kind not in FILE_TYPES:
        raise ValueError("请选择 PDF、DOCX、XLSX 或 CSV 文件。")
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise ValueError(f"单个文件最大 {MAX_FILE_MB} MB。")
    if kind == "pdf":
        pages = read_pdf(data, filename)
        return Attachment(filename, tuple((f"第 {page} 页", text) for page, text in pages),
                          any(len(text) >= 1800 for _, text in pages))

    state = {"truncated": False}
    try:
        if kind in {"docx", "xlsx"}:
            _check_office_archive(data)
        parse = {"docx": _word_fragments, "xlsx": _excel_fragments, "csv": _csv_fragments}[kind]
        fragments = list(islice(parse(data, state), MAX_FRAGMENTS + 1))
    except AttachmentError:
        raise
    except Exception:
        raise ValueError("文件读取失败。请确认文件可打开，再用原软件另存后上传。") from None
    if not fragments:
        raise ValueError("没有找到可读取的文字或单元格数据。")
    truncated = state["truncated"] or len(fragments) > MAX_FRAGMENTS or any(
        len(text) > MAX_FRAGMENT_CHARS for _, text in fragments
    )
    return Attachment(filename, tuple((locator, text[:MAX_FRAGMENT_CHARS])
                     for locator, text in fragments[:MAX_FRAGMENTS]), truncated)

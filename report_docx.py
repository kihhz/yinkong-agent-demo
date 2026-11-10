"""Word export adapted from the C V0.11.4 Markdown renderer."""
from io import BytesIO
import re


def _set_run_font(run, name='宋体', size=10.5, bold=None):
    from docx.oxml.ns import qn
    from docx.shared import Pt
    run.font.name = name
    run.font.size = Pt(size)
    run._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), name)
    if bold is not None:
        run.bold = bold


def _style(document):
    from docx.enum.text import WD_LINE_SPACING
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt
    section = document.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(2.2)
    section.left_margin = section.right_margin = Cm(2.4)
    normal = document.styles['Normal']
    normal.font.name = '宋体'
    normal.font.size = Pt(10.5)
    normal._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    normal.paragraph_format.space_after = Pt(5)
    for name, size, font in (('Title', 18, '黑体'), ('Heading 1', 15, '黑体'),
                             ('Heading 2', 12.5, '黑体'), ('Heading 3', 11, '黑体')):
        style = document.styles[name]
        style.font.name = font
        style.font.size = Pt(size)
        style._element.rPr.rFonts.set(qn('w:eastAsia'), font)


def _plain(value):
    value = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', str(value or ''))
    return value.replace('**', '').replace('__', '').replace('`', '').strip()


def _add_paragraph(document, text, style=None):
    paragraph = document.add_paragraph(style=style)
    run = paragraph.add_run(_plain(text))
    _set_run_font(
        run,
        size=10.5 if style is None else
        {'Title': 18, 'Heading 1': 15, 'Heading 2': 12.5, 'Heading 3': 11}.get(style, 10.5),
        bold=style in ('Title', 'Heading 1', 'Heading 2', 'Heading 3'),
    )
    return paragraph


def _table_rows(lines):
    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if not cells or all(re.fullmatch(r':?-{2,}:?', cell) for cell in cells):
            continue
        rows.append(cells)
    return rows


def _add_table(document, rows):
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.shared import Cm, Pt
    if not rows:
        return
    columns = max(len(row) for row in rows)
    rows = [row + [''] * (columns-len(row)) for row in rows]
    table = document.add_table(rows=len(rows), cols=columns)
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    available = 16.0
    widths = [available/columns] * columns
    if columns == 5:
        widths = [3.0, 4.0, 2.8, 3.4, 2.8]
    header_properties = table.rows[0]._tr.get_or_add_trPr()
    repeat_header = OxmlElement('w:tblHeader')
    repeat_header.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', 'true')
    header_properties.append(repeat_header)
    for row_index, values in enumerate(rows):
        row_properties = table.rows[row_index]._tr.get_or_add_trPr()
        row_properties.append(OxmlElement('w:cantSplit'))
        for column_index, value in enumerate(values):
            cell = table.cell(row_index, column_index)
            cell.width = Cm(widths[column_index])
            cell.text = ''
            run = cell.paragraphs[0].add_run(_plain(value))
            _set_run_font(run, size=9, bold=row_index == 0)
    document.add_paragraph()


def build(markdown, title=None):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    document = Document()
    _style(document)
    lines = str(markdown or '').splitlines()
    first_heading = next((_plain(line[2:]) for line in lines if line.startswith('# ')), None)
    report_title = title or first_heading or '低空经济发展条件与应用场景分析报告'
    heading = document.add_paragraph(style='Title')
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = heading.add_run(report_title)
    _set_run_font(run, name='黑体', size=18, bold=True)
    index = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if not stripped:
            index += 1
            continue
        if stripped.startswith('|'):
            table_lines = []
            while index < len(lines) and lines[index].strip().startswith('|'):
                table_lines.append(lines[index])
                index += 1
            _add_table(document, _table_rows(table_lines))
            continue
        if stripped.startswith('# '):
            if _plain(stripped[2:]) != report_title:
                _add_paragraph(document, stripped[2:], 'Heading 1')
        elif stripped.startswith('## '):
            _add_paragraph(document, stripped[3:], 'Heading 1')
        elif stripped.startswith('### '):
            _add_paragraph(document, stripped[4:], 'Heading 2')
        elif stripped.startswith(('- ', '• ')):
            paragraph = document.add_paragraph(style='List Bullet')
            run = paragraph.add_run(_plain(stripped[2:]))
            _set_run_font(run, size=10.5)
        elif re.match(r'^\d+[.、]\s+', stripped):
            paragraph = document.add_paragraph(style='List Number')
            text = re.sub(r'^\d+[.、]\s+', '', stripped)
            run = paragraph.add_run(_plain(text))
            _set_run_font(run, size=10.5)
        elif stripped.startswith('> '):
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.left_indent = Pt(14)
            run = paragraph.add_run(_plain(stripped[2:]))
            _set_run_font(run, size=9.5)
            run.italic = True
        else:
            _add_paragraph(document, stripped)
        index += 1

    footer = document.sections[0].footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run('因空制宜 Agent · 评委体验版')
    _set_run_font(run, size=8)
    output = BytesIO()
    document.save(output)
    return output.getvalue()

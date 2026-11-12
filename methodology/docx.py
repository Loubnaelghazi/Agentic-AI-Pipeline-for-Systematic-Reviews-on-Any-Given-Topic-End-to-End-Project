"""Small OOXML writer for readable headings, evidence tables and PRISMA figures."""

import re
import struct
import zipfile
from xml.sax.saxutils import escape


def write_document(path, text, figure_path=None, *, scientific=False):
    def runs(value, bold=False):
        value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", value)
        chunks = re.split(r"(\*\*.*?\*\*)", value)
        output = []
        for chunk in chunks:
            marked = chunk.startswith("**") and chunk.endswith("**")
            if marked:
                chunk = chunk[2:-2]
            chunk = chunk.replace("\\|", "|")
            props = "<w:rPr><w:b/></w:rPr>" if bold or marked else ""
            output.append(
                f'<w:r>{props}<w:t xml:space="preserve">{escape(chunk)}</w:t></w:r>'
            )
        return "".join(output)

    def paragraph(value, style=None):
        props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        return f"<w:p>{props}{runs(value)}</w:p>"

    def table(lines):
        rows = []
        for line in lines:
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
            if all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in cells):
                continue
            rows.append(cells)
        width = max(map(len, rows), default=1)
        body = []
        for index, cells in enumerate(rows):
            properties = "<w:trPr><w:tblHeader/></w:trPr>" if index == 0 else ""
            tds = []
            for cell in cells + [""] * (width - len(cells)):
                fill = (
                    "FFFFFF"
                    if scientific
                    else (
                        "E8EEF8"
                        if index == 0
                        else ("F6F8FC" if index % 2 else "FFFFFF")
                    )
                )
                tds.append(
                    f'<w:tc><w:tcPr><w:tcW w:w="{9000 // width}" w:type="dxa"/><w:shd w:fill="{fill}"/></w:tcPr><w:p>{runs(cell, index == 0)}</w:p></w:tc>'
                )
            if scientific:
                properties = (
                    properties.replace("</w:trPr>", "<w:cantSplit/></w:trPr>")
                    if properties
                    else "<w:trPr><w:cantSplit/></w:trPr>"
                )
                if index == 0:
                    tds = [
                        cell.replace(
                            "</w:tcPr>",
                            '<w:tcBorders><w:bottom w:val="single" w:sz="4" w:color="000000"/></w:tcBorders></w:tcPr>',
                        )
                        for cell in tds
                    ]
            body.append("<w:tr>" + properties + "".join(tds) + "</w:tr>")
        borders = "".join(
            f'<w:{edge} w:val="single" w:sz="4" w:color="D8E0EB"/>'
            for edge in (
                ("top", "bottom")
                if scientific
                else ("top", "left", "bottom", "right", "insideH", "insideV")
            )
        )
        if scientific:
            borders = borders.replace("D8E0EB", "000000")
        margins = "".join(
            f'<w:{side} w:w="90" w:type="dxa"/>'
            for side in ("top", "left", "bottom", "right")
        )
        return (
            f'<w:tbl><w:tblPr><w:tblW w:w="9000" w:type="dxa"/><w:tblBorders>{borders}</w:tblBorders><w:tblCellMar>{margins}</w:tblCellMar></w:tblPr><w:tblGrid>'
            + "".join(f'<w:gridCol w:w="{9000 // width}"/>' for _ in range(width))
            + "</w:tblGrid>"
            + "".join(body)
            + "</w:tbl>"
        )

    has_figure = figure_path is not None and figure_path.exists()
    figure = ""
    if has_figure:
        png = figure_path.read_bytes()
        width, height = struct.unpack(">II", png[16:24])
        scale = min(5943600 / width, 7000000 / height)
        cx, cy = int(width * scale), int(height * scale)
        keep_caption = "<w:keepNext/>" if scientific else ""
        figure = f'<w:p><w:pPr>{keep_caption}<w:jc w:val="center"/></w:pPr><w:r><w:drawing><wp:inline><wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="1" name="PRISMA selection flow" descr="Colored flow of search, eligibility and provisional evidence"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="0" name="prisma.png"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="rIdFigure"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
    blocks = []
    lines = text.splitlines()
    index, inserted = 0, False
    while index < len(lines):
        line = lines[index]
        if scientific and not line.strip():
            index += 1
            continue
        if line.strip().startswith("|"):
            group = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                group.append(lines[index])
                index += 1
            blocks.append(table(group))
            continue
        image = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", line.strip())
        if image and has_figure and image[2] == figure_path.name:
            if not inserted:
                blocks.append(figure)
                inserted = True
            index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)", line)
        if re.match(r"^\*\*Table \d+\.", line):
            blocks.append(paragraph(line, "TableCaption"))
        elif re.match(r"^\*Figure \d+\.", line):
            blocks.append(paragraph(line.replace("*", ""), "FigureCaption"))
        elif line.startswith("*Note.*"):
            blocks.append(paragraph(line.replace("*", ""), "TableNote"))
        elif heading:
            blocks.append(
                paragraph(heading[2], "Heading" + str(min(len(heading[1]), 3)))
            )
            if has_figure and not inserted and heading[2] == "PRISMA selection diagram":
                blocks.append(figure)
                inserted = True
        elif line.startswith("> "):
            blocks.append(paragraph(line[2:], "Quote"))
        elif line.startswith("- "):
            blocks.append(paragraph("• " + line[2:]))
        elif not line.startswith("```"):
            blocks.append(paragraph(line))
        index += 1
    if has_figure and not inserted:
        blocks.extend([paragraph("PRISMA selection diagram", "Heading2"), figure])
    styles = '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:pPr><w:spacing w:after="120" w:line="276"/></w:pPr><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:color w:val="243449"/><w:sz w:val="22"/></w:rPr></w:style>'
    for level, size in [(1, 36), (2, 29), (3, 24)]:
        styles += f'<w:style w:type="paragraph" w:styleId="Heading{level}"><w:name w:val="heading {level}"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="{level - 1}"/></w:pPr><w:rPr><w:b/><w:color w:val="1E3A5F"/><w:sz w:val="{size}"/></w:rPr></w:style>'
    styles += '<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="280"/><w:shd w:fill="F3F6FA"/></w:pPr><w:rPr><w:i/><w:color w:val="475569"/></w:rPr></w:style>'
    for name in ("TableCaption", "FigureCaption", "TableNote"):
        keep = "<w:keepNext/>" if name == "TableCaption" else ""
        styles += (
            f'<w:style w:type="paragraph" w:styleId="{name}"><w:name w:val="{name}"/>'
            f'<w:basedOn w:val="Normal"/><w:pPr>{keep}<w:spacing w:before="100" w:after="100"/></w:pPr>'
            '<w:rPr><w:sz w:val="20"/></w:rPr></w:style>'
        )
    if scientific:
        styles = styles.replace(
            'w:ascii="Calibri" w:hAnsi="Calibri"',
            'w:ascii="Times New Roman" w:hAnsi="Times New Roman"',
        )
        styles = styles.replace('w:val="243449"', 'w:val="000000"').replace(
            'w:val="1E3A5F"', 'w:val="000000"'
        )
        styles = styles.replace('w:line="276"', 'w:line="288"')
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    types = '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    rels = '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    if has_figure:
        types += '<Default Extension="png" ContentType="image/png"/>'
        rels += '<Relationship Id="rIdFigure" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/prisma.png"/>'
    footer_reference = ""
    if scientific:
        types += '<Override PartName="/word/footer.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
        rels += '<Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer.xml"/>'
        footer_reference = '<w:footerReference w:type="default" r:id="rIdFooter"/>'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as output:
        output.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            + types
            + "</Types>",
        )
        output.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        )
        output.writestr(
            "word/_rels/document.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + rels
            + "</Relationships>",
        )
        output.writestr("word/styles.xml", f"<w:styles {ns}>{styles}</w:styles>")
        output.writestr(
            "word/document.xml",
            f'<w:document {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:body>{"".join(blocks)}<w:sectPr>{footer_reference}<w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr></w:body></w:document>',
        )
        if scientific:
            output.writestr(
                "word/footer.xml",
                f'<w:ftr {ns}><w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:fldSimple w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple></w:p></w:ftr>',
            )
        if has_figure:
            output.writestr("word/media/prisma.png", png)

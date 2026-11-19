# Writes a small Word document (OOXML) with a heading, a paragraph and a picture, using the standard library only.
# The picture is a PNG drawn here (a simple bar chart), so the check also sees Collabora render an image.
import struct
import sys
import zipfile
import zlib

W, H = 600, 300


def png(width, height, pixel):
    raw = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width)) for y in range(height))

    def chunk(kind, data):
        c = kind + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


BARS = [(40, 0.45, (0, 130, 200)), (170, 0.8, (0, 160, 90)), (300, 0.6, (240, 160, 0)), (430, 0.95, (210, 60, 60))]


def pixel(x, y):
    if y >= H - 20:                                    # base line
        return (60, 60, 60) if y < H - 16 else (255, 255, 255)
    for left, share, colour in BARS:
        if left <= x < left + 110 and y >= (H - 20) - share * (H - 50):
            return colour
    return (245, 247, 250)


image = png(W, H, pixel)
EMU = 9525  # one pixel at 96 dpi
cx, cy = W * EMU, H * EMU
text = "Monitoring-Testdokument. Wenn du das liest, hat Collabora das Dokument geöffnet."
NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
drawing = (f'<w:p><w:r><w:drawing><wp:inline><wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="1" name="Diagramm"/>'
           '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
           '<pic:pic><pic:nvPicPr><pic:cNvPr id="1" name="chart.png"/><pic:cNvPicPr/></pic:nvPicPr>'
           '<pic:blipFill><a:blip r:embed="rIdImg"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
           f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
           '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
           '</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')
files = {
    "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
    "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
    "word/_rels/document.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdImg" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/chart.png"/></Relationships>',
    "word/document.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {NS}><w:body>'
                         '<w:p><w:r><w:rPr><w:b/><w:sz w:val="36"/></w:rPr><w:t>E2E-Check</w:t></w:r></w:p>'
                         f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>{drawing}</w:body></w:document>',
}
with zipfile.ZipFile(sys.argv[1], "w", zipfile.ZIP_DEFLATED) as z:
    for name, content in files.items():
        z.writestr(name, content)
    z.writestr("word/media/chart.png", image)

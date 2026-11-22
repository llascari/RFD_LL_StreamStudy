"""A tiny, dependency-free PDF writer.

Enough of PDF 1.4 for a multi-page report: Helvetica text, lines, rectangles,
polylines and circles. Coordinates are given top-left (like a canvas); the
writer converts to PDF's bottom-left origin.
"""

from __future__ import annotations

from pathlib import Path

PAGE_W = 612.0
PAGE_H = 792.0


def _colour(rgb) -> str:
    return "{:.3f} {:.3f} {:.3f}".format(*rgb)


def _escape(text: str) -> str:
    safe = str(text).encode("cp1252", "replace").decode("cp1252")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class PdfPage:
    def __init__(self) -> None:
        self.ops: list[str] = []

    def text(
        self,
        x: float,
        y: float,
        text: str,
        *,
        size: float = 10,
        bold: bool = False,
        italic: bool = False,
        colour=(0.1, 0.12, 0.15),
    ) -> None:
        font = "F2" if bold else ("F3" if italic else "F1")
        self.ops.append(
            f"BT /{font} {size} Tf {_colour(colour)} rg "
            f"1 0 0 1 {x:.2f} {PAGE_H - y:.2f} Tm ({_escape(text)}) Tj ET"
        )

    def line(self, x1, y1, x2, y2, *, colour=(0.6, 0.65, 0.7), width=1.0) -> None:
        self.ops.append(
            f"{_colour(colour)} RG {width} w {x1:.2f} {PAGE_H - y1:.2f} m "
            f"{x2:.2f} {PAGE_H - y2:.2f} l S"
        )

    def rect(self, x, y, w, h, *, fill=None, stroke=None, width=1.0) -> None:
        if fill is not None:
            self.ops.append(
                f"{_colour(fill)} rg {x:.2f} {PAGE_H - y - h:.2f} {w:.2f} {h:.2f} re f"
            )
        if stroke is not None:
            self.ops.append(
                f"{_colour(stroke)} RG {width} w {x:.2f} {PAGE_H - y - h:.2f} "
                f"{w:.2f} {h:.2f} re S"
            )

    def polyline(self, points, *, colour=(0.25, 0.55, 0.85), width=1.2) -> None:
        if len(points) < 2:
            return
        ops = [f"{_colour(colour)} RG {width} w"]
        x0, y0 = points[0]
        ops.append(f"{x0:.2f} {PAGE_H - y0:.2f} m")
        for x, y in points[1:]:
            ops.append(f"{x:.2f} {PAGE_H - y:.2f} l")
        ops.append("S")
        self.ops.append(" ".join(ops))

    def circle(self, cx, cy, radius, *, fill=(0.2, 0.45, 0.8), stroke=None) -> None:
        k = 0.5522847498 * radius
        y = PAGE_H - cy
        path = [
            f"{cx + radius:.2f} {y:.2f} m",
            f"{cx + radius:.2f} {y + k:.2f} {cx + k:.2f} {y + radius:.2f} {cx:.2f} {y + radius:.2f} c",
            f"{cx - k:.2f} {y + radius:.2f} {cx - radius:.2f} {y + k:.2f} {cx - radius:.2f} {y:.2f} c",
            f"{cx - radius:.2f} {y - k:.2f} {cx - k:.2f} {y - radius:.2f} {cx:.2f} {y - radius:.2f} c",
            f"{cx + k:.2f} {y - radius:.2f} {cx + radius:.2f} {y - k:.2f} {cx + radius:.2f} {y:.2f} c",
        ]
        self.ops.append(f"{_colour(fill)} rg " + " ".join(path) + " f")


class PdfDocument:
    def __init__(self, title: str = "StreamStudy report") -> None:
        self.title = title
        self.pages: list[PdfPage] = []

    def add_page(self) -> PdfPage:
        page = PdfPage()
        self.pages.append(page)
        return page

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        objects: list[bytes | None] = [None]
        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        objects.append(None)  # Pages, filled after page ids are known
        objects.append(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        )
        objects.append(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            b"/Encoding /WinAnsiEncoding >>"
        )
        objects.append(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique "
            b"/Encoding /WinAnsiEncoding >>"
        )

        page_ids: list[int] = []
        for page in self.pages:
            content = "\n".join(page.ops).encode("cp1252", "replace")
            content_id = len(objects)
            objects.append(
                b"<< /Length "
                + str(len(content)).encode()
                + b" >>\nstream\n"
                + content
                + b"\nendstream"
            )
            page_id = len(objects)
            objects.append(
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W:.0f} {PAGE_H:.0f}] "
                f"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> "
                f"/Contents {content_id} 0 R >>".encode()
            )
            page_ids.append(page_id)

        kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
        objects[2] = (
            f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
        )

        header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
        output = bytearray(header)
        offsets = [0] * len(objects)
        for index in range(1, len(objects)):
            offsets[index] = len(output)
            body = objects[index] or b""
            output += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"

        xref = len(output)
        output += f"xref\n0 {len(objects)}\n".encode()
        output += b"0000000000 65535 f \n"
        for index in range(1, len(objects)):
            output += f"{offsets[index]:010d} 00000 n \n".encode()
        output += (
            f"trailer\n<< /Size {len(objects)} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode()
        target.write_bytes(bytes(output))
        return target

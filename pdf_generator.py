import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

FONT_NAME = "MalgunGothic"
FONT_PATH = r"C:\Windows\Fonts\malgun.ttf"

def create_pdf(title, result):
    if not os.path.exists(REPORTS_DIR):
        os.makedirs(REPORTS_DIR)

    safe_title = title.replace("/", "_").replace("\\", "_").replace(":", "_")
    file_path = os.path.join(REPORTS_DIR, f"{safe_title}.pdf")

    pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH))

    c = canvas.Canvas(file_path, pagesize=A4)
    width, height = A4

    text = c.beginText(40, height - 40)
    text.setFont(FONT_NAME, 11)

    lines = str(result).split("\n")
    line_count = 0

    for line in lines:
        text.textLine(line)
        line_count += 1

        if line_count >= 45:
            c.drawText(text)
            c.showPage()
            text = c.beginText(40, height - 40)
            text.setFont(FONT_NAME, 11)
            line_count = 0

    c.drawText(text)
    c.save()

    return file_path
import smtplib
import os
from email.message import EmailMessage

GMAIL_USER = "hover9710@gmail.com"
GMAIL_APP_PASSWORD = "vdjyqzejpdcwhnfx"

def send_email(to_email, subject, content, file_path):
    msg = EmailMessage()
    msg["From"] = GMAIL_USER
    msg["To"] = str(to_email)
    msg["Subject"] = str(subject)

    # 본문 UTF-8
    msg.set_content(str(content), charset="utf-8")

    # PDF 첨부
    if file_path and os.path.exists(file_path):
        with open(file_path, "rb") as f:
            file_data = f.read()
            file_name = os.path.basename(file_path)

        msg.add_attachment(
            file_data,
            maintype="application",
            subtype="pdf",
            filename=file_name
        )

    # 핵심: local_hostname을 ASCII로 고정
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, local_hostname="localhost") as smtp:
        smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        smtp.send_message(msg)

    print("이메일 발송 완료:", to_email)
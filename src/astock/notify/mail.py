import smtplib
from email.mime.text import MIMEText
from email.header import Header


def push(smtp_host: str, smtp_port: int, user: str, password: str,
         to: str, title: str, body: str, use_ssl: bool = True) -> None:
    """通过 SMTP 发邮件。"""
    if not (smtp_host and user and password and to):
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(title, "utf-8")
    msg["From"] = user
    msg["To"] = to
    if use_ssl:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
    else:
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
        server.starttls()
    try:
        server.login(user, password)
        server.sendmail(user, [to], msg.as_string())
    finally:
        server.quit()

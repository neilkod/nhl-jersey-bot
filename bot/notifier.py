import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

from .models import Jersey

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def send_notification(
    team: str,
    jersey_type: str,
    jerseys: List[Jersey],
    config: dict,
) -> None:
    gmail_user = config["from_email"]
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not gmail_password:
        raise EnvironmentError("GMAIL_APP_PASSWORD environment variable is not set.")

    to_email = config["notify_email"]
    subject = f"[Jersey Bot] {team} {jersey_type} jerseys on clearance at Fanatics"

    body = _build_body(team, jersey_type, jerseys)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_email
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, to_email, msg.as_string())

    logger.info(f"Email sent → {to_email}: {subject}")


def _build_body(team: str, jersey_type: str, jerseys: List[Jersey]) -> str:
    lines = [
        f"{team} {jersey_type} jerseys are on clearance at Fanatics!",
        f"Found {len(jerseys)} matching jersey(s) in your target sizes.",
        "",
    ]

    for j in jerseys:
        lines.append(f"  {j.name}")
        lines.append(f"    Price  : {j.format_price()}")
        lines.append(f"    Sizes  : {j.format_sizes()}")
        if j.url:
            lines.append(f"    Link   : {j.url}")
        lines.append("")

    lines += [
        "You will not receive another alert for this category until these",
        "jerseys sell out and new ones appear.",
        "",
        "— Jersey Bot",
    ]
    return "\n".join(lines)

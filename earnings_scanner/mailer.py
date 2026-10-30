"""Email the daily report: a short digest in the body, the full report attached as an HTML page."""

from __future__ import annotations

import html
import logging
import smtplib
import ssl
from email.message import EmailMessage

import markdown

from .config import Config

log = logging.getLogger(__name__)

CSS = """
body { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; font-size: 14px; line-height: 1.45;
       color: #1a1a1a; max-width: 980px; margin: 0 auto; padding: 16px; }
h1 { font-size: 20px; } h2 { font-size: 17px; margin-top: 26px; } h3 { font-size: 15px; margin-top: 22px; }
table { border-collapse: collapse; font-size: 12px; }
th, td { border: 1px solid #ddd; padding: 3px 6px; text-align: left; white-space: nowrap; }
th { background: #f4f4f4; }
blockquote { color: #666; margin: 0; padding-left: 10px; border-left: 3px solid #ddd; }
summary { cursor: pointer; color: #555; }
"""


def to_html(md_text: str, title: str) -> str:
    body = markdown.markdown(md_text, extensions=["tables", "md_in_html"])
    return (
        f'<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
        f"<style>{CSS}</style></head><body>{body}</body></html>"
    )


def missing_settings(cfg: Config) -> list[str]:
    return [k for k, v in (("EMAIL_TO", cfg.email_to), ("SMTP_USER", cfg.smtp_user), ("SMTP_PASSWORD", cfg.smtp_password)) if not v]


def _send(cfg: Config, msg: EmailMessage) -> None:
    msg["From"] = cfg.smtp_user
    msg["To"] = cfg.email_to
    host = cfg.get("email", "smtp_host", "smtp.gmail.com")
    port = cfg.get("email", "smtp_port", 465)
    with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=60) as smtp:
        smtp.login(cfg.smtp_user, cfg.smtp_password)
        smtp.send_message(msg)
    log.info("emailed %r to %s", msg["Subject"], cfg.email_to)


def send_report(cfg: Config, run_date: str, subject: str, digest_md: str, full_md: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg.set_content(digest_md)
    msg.add_alternative(to_html(digest_md, subject), subtype="html")
    msg.add_attachment(
        to_html(full_md, f"Earnings scanner — {run_date}").encode(),
        maintype="text", subtype="html", filename=f"earnings-{run_date}.html",
    )
    _send(cfg, msg)


def send_failure(cfg: Config, run_date: str, error: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = f"Earnings scanner FAILED — {run_date}"
    msg.set_content(f"The {run_date} run failed:\n\n{error}\n\nSee logs/run-{run_date}.log on the Mac for details.")
    _send(cfg, msg)

"""Sends enquiry emails. Every enquiry is also stored in the database (Admin > Messages), so nothing is lost
if email is not configured yet.

Set these environment variables to turn sending on (the recipient is set in Admin > Settings):
    SMTP_HOST, SMTP_PORT (default 587; 465 uses SSL), SMTP_USER, SMTP_PASSWORD, SMTP_FROM (default SMTP_USER)
"""
import os
import smtplib
import threading
from email.message import EmailMessage

import db


def configured():
    return bool(os.environ.get("SMTP_HOST"))


def _send(msg_id, to, subject, body, reply_to):
    try:
        host = os.environ["SMTP_HOST"]
        port = int(os.environ.get("SMTP_PORT") or 587)
        user, pw = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")
        sender = os.environ.get("SMTP_FROM") or user or to
        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = sender, to, subject
        m["Reply-To"] = reply_to
        m.set_content(body)
        smtp = smtplib.SMTP_SSL(host, port, timeout=15) if port == 465 else smtplib.SMTP(host, port, timeout=15)
        with smtp as s:
            if port != 465:
                s.starttls()
            if user:
                s.login(user, pw or "")
            s.send_message(m)
        db.update_message(msg_id, emailed=1, email_error="")
    except Exception as e:  # noqa: BLE001 - recorded for the admin to see
        db.update_message(msg_id, emailed=0, email_error=str(e)[:200])


def notify(msg_id, to, subject, body, reply_to):
    """Queue an email in the background. Returns False when email is not set up."""
    if not (configured() and to):
        return False
    subject = " ".join(subject.split())[:200]          # headers must be one line
    threading.Thread(target=_send, args=(msg_id, to, subject, body, reply_to), daemon=True).start()
    return True

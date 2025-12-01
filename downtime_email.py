import logging
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from typing import List, Dict

from dotenv import load_dotenv

load_dotenv()


class EmailNotifier:

    def __init__(self, sender_email: str, sender_password: str, smtp_server: str, smtp_port: int):
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("EmailNotifier initialized")

    def send_notification(self, recipient_email: str, subject: str, body: str) -> bool:
        self.logger.info(f"Sending email to {recipient_email}")

        # Create message object
        message = MIMEMultipart()
        message['From'] = self.sender_email
        message['To'] = recipient_email
        message['Subject'] = subject

        server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=30)
        server.starttls()
        server.login(self.sender_email, self.sender_password)

        text = message.as_string()
        server.sendmail(self.sender_email, recipient_email, text)
        server.quit()

        self.logger.info(f"Email sent successfully to {recipient_email}")

        return True

    def send_downtime_alert(self, recipient_email: str,
                            devices: List[Dict], ticket_ids: Dict[str, str]) -> bool:
        """Send downtime alert email with device details"""

        self.logger.info(f"Preparing downtime alert email for {len(devices)} device(s)")

        subject = f"OLT Downtime Alert - {len(devices)} Device(s) Offline"

        body = f"""OLT Downtime Alert

Detected {len(devices)} offline device(s) at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

Offline Devices:
"""
        for device in devices:
            ticket_id = ticket_ids.get(device['device_name'], 'N/A')
            body += f"""
- Device: {device['device_name']}
  Description: {device['original_desc']}
  Start Time: {device.get('last_offline_time', 'N/A')}
  Ticket ID: {ticket_id}
"""

        body += """

This is an automated alert from the OLT Monitoring System.
Please investigate and resolve the issues promptly.

---
OLT Monitoring System
"""

        try:
            return self.send_notification(recipient_email, subject, body)
        except Exception as e:
            self.logger.error(f"Failed to send downtime alert after retries: {e}")
            return False


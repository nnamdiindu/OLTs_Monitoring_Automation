import os
import smtplib
import requests
import time
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Optional
from functools import wraps
import json
from dotenv import load_dotenv

load_dotenv()

# Configure logging
def setup_logging(log_file: str = "olt_automation.log", level=logging.INFO):
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()  # Also print to console
        ]
    )
    return logging.getLogger(__name__)


class Config:

    # Email Configuration
    SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
    SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
    SMTP_SERVER = os.environ.get("SMTP_SERVER")
    SMTP_PORT = 587

    # OLT Monitor API Configuration
    OLT_API_URL = os.environ.get("OLT_API_URL")
    OLT_API_TOKEN = os.environ.get("OLT_API_TOKEN")

    # osTicket Configuration
    OSTICKET_URL = os.environ.get("OSTICKET_URL", "")
    OSTICKET_API_KEY = os.environ.get("API_KEY", "")

    # Retry Configuration
    MAX_RETRY_ATTEMPTS = 3
    RETRY_DELAY = 5  # seconds
    REQUEST_TIMEOUT = 30  # seconds

    # Device Name Mapping
    DEVICE_NAME_MAP = {
        "16PORTOLT(10.0.4.103)": "YABACLUSTER-TEMP-16PORTOLT",
        "OLT": "GLO-CLS",
        "LAB": "OAM-LAB",
        "OFFICE": "OAM-OFFICE",
        "001(10.0.4.78)": "OSBORNE"
    }


class OLTMonitor:
    """Monitors OLT devices and detects downtime"""

    def __init__(self, api_url: str, api_token: str, device_map: Dict[str, str],
                 timeout: int = 30, max_retries: int = 3):
        self.api_url = api_url
        self.api_token = api_token
        self.device_map = device_map
        self.timeout = timeout
        self.max_retries = max_retries
        self.logger = logging.getLogger(self.__class__.__name__)
        self.headers = {
            "Content-Type": "application/json",
            "X-Token": self.api_token
        }
        self.logger.info("OLTMonitor Status Detector initialized")

    def get_offline_devices(self, page_size: int = 100, page_num: int = 1) -> List[Dict]:

        params = {
            "size": page_size,
            "current": page_num,
            "category": "OLT",
            "runningState": "offline"
        }

        self.logger.info(f"Fetching offline devices (page {page_num}, size {page_size})")

        response = requests.get(
            self.api_url,
            headers=self.headers,
            params=params,
        )
        response.raise_for_status()

        data = response.json()
        olt_list = data.get("data", {}).get("page", {}).get("records", [])

        self.logger.info(f"Found {len(olt_list)} offline device(s)")
        processed_devices = self._process_devices(olt_list)

        return processed_devices

    def _process_devices(self, olt_list: List[Dict]) -> List[Dict]:
        """Process and normalize device information"""
        processed_devices = []

        for olt in olt_list:
            device_desc = olt.get("deviceDesc", "")
            parts = device_desc.split("-")

            if len(parts) >= 3:
                device_code = parts[2]
            else:
                device_code = device_desc

            # Map device name
            device_name = self.device_map.get(device_code, device_code)

            device_info = {
                "original_desc": device_desc,
                "device_name": device_name,
                "device_code": device_code,
                "last_offline_time": olt.get("lastOfflineTime"),
                "raw_data": olt
            }

            processed_devices.append(device_info)
            self.logger.debug(f"Processed device: {device_name}")

        return processed_devices


class TicketManager:
    def __init__(self, base_url: str, api_key: str, timeout: int = 40):
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self.endpoint = f"{base_url}/api/http.php/tickets.json"
        self.headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        }
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("TicketManager initialized")


    def create_ticket(self, device_info: Dict, priority: str = 3) -> Optional[str]:

        olt_name = device_info["device_name"]
        self.logger.info(f"Creating ticket for device: {olt_name}")

        ticket_data = {
            "alert": True,
            "autorespond": True,
            "source": "API",
            "name": "OLT Monitoring System",
            "email": "noc@openaccessmetro.net",
            "phone": "807-3138-700",
            "subject": f"DOWNTIME AT {olt_name}",
            "message": self._format_ticket_message(device_info),
            "ip": self._get_public_ip(),
            "priority": priority,
            "topicId": "6",
            "department": "4",
            "incident": "4",
            "category": "4",
            "Start_Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "rca": "WIP"
        }

        response = requests.post(
            self.endpoint,
            headers=self.headers,
            json=ticket_data,
        )

        if response.status_code == 201:
            ticket_id = self._extract_ticket_id(response)
            self.logger.info(f"Ticket created successfully for {olt_name} (ID: {ticket_id})")
            return ticket_id
        else:
            error_msg = f"Failed to create ticket: {response.status_code} - {response.text}"
            self.logger.error(error_msg)
            return None


    def _format_ticket_message(self, device_info: Dict) -> str:
        """Format the ticket message body"""
        message = f"""data:text/html,
        <h3>OLT Device Downtime Detected</h3>
        <p><strong>Device Name:</strong> {device_info['device_name']}</p>
        <p><strong>Device Description:</strong> {device_info['original_desc']}</p>
        <p><strong>Last Offline Time:</strong> {device_info.get('last_offline_time', 'N/A')}</p>
        <p><strong>Detection Time:</strong> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        <p>This ticket was automatically generated by the OLT Monitoring System.</p>
        """
        return message


    def _extract_ticket_id(self, response) -> Optional[str]:
        """Extract ticket ID from response"""
        try:
            response_data = response
            return response_data.text
        except:
            return None


    def _get_public_ip(self) -> str:
        """Get public IP address with retry"""
        try:
            return requests.get('https://api.ipify.org', timeout=5).text
        except:
            self.logger.warning("Could not fetch public IP, using fallback")
            return "154.66.246.206"


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

        subject = f"SERVICE DOWNTIME NOTIFICATION - {ticket_ids} "

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


class OLTAutomationOrchestrator:
    """Main orchestrator for OLT downtime automation"""

    def __init__(self, monitor: OLTMonitor, ticket_manager: TicketManager,
                 notifier: EmailNotifier):
        self.monitor = monitor
        self.ticket_manager = ticket_manager
        self.notifier = notifier
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("OLTAutomationOrchestrator initialized")

    def run(self, notification_email: str = "lucky.odi@openaccessmetro.net") -> Dict:
        """Execute the complete automation workflow"""

        self.logger.info("=" * 60)
        self.logger.info("OLT AUTOMATION SYSTEM - Starting")
        self.logger.info("=" * 60)

        try:
            # Step 1: Monitor for offline devices
            self.logger.info("[1/3] Checking for offline OLT devices...")
            offline_devices = self.monitor.get_offline_devices()

            if not offline_devices:
                self.logger.info("No offline devices detected")
                return {"status": "success", "offline_devices": 0}

            self.logger.warning(f"Found {len(offline_devices)} offline device(s)")
            for device in offline_devices:
                self.logger.warning(f"DOWNTIME ALERT - {device['device_name']}")

            # Step 2: Create tickets
            self.logger.info(f"[2/3] Creating tickets for offline devices...")
            ticket_ids = {}

            for device in offline_devices:
                try:
                    ticket_id = self.ticket_manager.create_ticket(device)
                    if ticket_id:
                        ticket_ids[device['device_name']] = ticket_id
                except Exception as e:
                    self.logger.error(f"Failed to create ticket for {device['device_name']}: {e}")

            # Step 3: Send email notification
            self.logger.info(f"[3/3] Sending email notification...")
            email_sent = self.notifier.send_downtime_alert(
                notification_email,
                offline_devices,
                ticket_ids
            )

            self.logger.info("=" * 60)
            self.logger.info("AUTOMATION COMPLETE")
            self.logger.info("=" * 60)

            result = {
                "status": "success",
                "offline_devices": len(offline_devices),
                "tickets_created": len(ticket_ids),
                "email_sent": email_sent,
                "devices": offline_devices,
                "ticket_ids": ticket_ids
            }

            self.logger.info(f"Summary: {len(offline_devices)} devices offline, "
                             f"{len(ticket_ids)} tickets created, "
                             f"email sent: {email_sent}")

            return result

        except Exception as e:
            self.logger.critical(f"Automation workflow failed: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "offline_devices": 0,
                "tickets_created": 0,
                "email_sent": False
            }


def main():

    # Setup logging
    logger = setup_logging(log_file="olt_automation.log", level=logging.INFO)
    logger.info("Application started")

    try:
        # Initialize components
        config = Config()

        monitor = OLTMonitor(
            api_url=config.OLT_API_URL,
            api_token=config.OLT_API_TOKEN,
            device_map=config.DEVICE_NAME_MAP,
            timeout=config.REQUEST_TIMEOUT,
            max_retries=config.MAX_RETRY_ATTEMPTS
        )

        ticket_manager = TicketManager(
            base_url=config.OSTICKET_URL,
            api_key=config.OSTICKET_API_KEY,
            timeout=config.REQUEST_TIMEOUT
        )

        notifier = EmailNotifier(
            sender_email=config.SENDER_EMAIL,
            sender_password=config.SENDER_PASSWORD,
            smtp_server=config.SMTP_SERVER,
            smtp_port=config.SMTP_PORT
        )

        # Create orchestrator and run
        orchestrator = OLTAutomationOrchestrator(monitor, ticket_manager, notifier)
        result = orchestrator.run(notification_email="lucky.odi@openaccessmetro.net")

        # print(f"\nFinal Result: {json.dumps(result, indent=2, default=str)}")
        logger.info("Application completed successfully")

    except Exception as e:
        logger.critical(f"Application failed with fatal error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
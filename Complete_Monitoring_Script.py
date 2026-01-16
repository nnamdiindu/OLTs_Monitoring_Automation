import os
import smtplib
import requests
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Optional
import json
from pathlib import Path
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

    # Team Scheduler Configuration
    ROTATION_START_DATE = "2026-01-17"

    # Device Name Mapping
    DEVICE_NAME_MAP = {
        "16PORTOLT(10.0.4.103)": "YABACLUSTER-TEMP-16PORTOLT",
        "OLT": "GLO-CLS",
        "LAB": "OAM-LAB",
        "OFFICE": "OAM-OFFICE",
        "001(10.0.4.78)": "OSBORNE",
    }

class TeamScheduler:
    # Team configuration
    TEAMS = {
        'Kenny': {
            'id': 't2',
            'offset': 0,
            'schedule': {
                1: 'morning', 2: 'morning',
                3: 'evening', 4: 'evening',
                5: 'off', 6: 'off', 7: 'off', 8: 'off'
            }
        },
        'Capacity': {
            'id': 't4',
            'offset': 2,
            'schedule': {
                1: 'off', 2: 'off',
                3: 'morning', 4: 'morning',
                5: 'evening', 6: 'evening',
                7: 'off', 8: 'off'
            }
        },
        'GLO': {
            'id': 't3',
            'offset': 4,
            'schedule': {
                1: 'off', 2: 'off', 3: 'off', 4: 'off',
                5: 'morning', 6: 'morning',
                7: 'evening', 8: 'evening'
            }
        },
        'Ntekim': {
            'id': 't5',
            'offset': 6,
            'schedule': {
                1: 'evening', 2: 'evening',
                3: 'off', 4: 'off', 5: 'off', 6: 'off',
                7: 'morning', 8: 'morning'
            }
        }
    }

    # Shift time boundaries
    MORNING_SHIFT_START = 8
    MORNING_SHIFT_END = 17
    EVENING_SHIFT_START = 17
    EVENING_SHIFT_END = 8

    def __init__(self, start_date: str = "2026-01-17"):
        """Initialize the team scheduler."""
        self.start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info(f"TeamScheduler initialized with start date: {self.start_date}")

    def get_cycle_day(self, check_date: datetime) -> int:
        """Calculate which day of the 8-day cycle we're currently in."""
        days_since_start = (check_date.date() - self.start_date).days
        cycle_day = (days_since_start % 8) + 1
        return cycle_day

    def get_shift_type(self, check_time: datetime) -> str:
        """Determine if current time falls in morning or evening shift."""
        hour = check_time.hour

        # Evening shift: 17:00-23:59 or 00:00-07:59
        if hour >= self.EVENING_SHIFT_START or hour < self.EVENING_SHIFT_END:
            return 'evening'
        # Morning shift: 08:00-16:59
        elif self.MORNING_SHIFT_START <= hour < self.MORNING_SHIFT_END:
            return 'morning'
        else:
            return 'evening'

    def get_team_on_duty(self, check_datetime: Optional[datetime] = None) -> Optional[str]:
        """Get the team ID that is on duty at the specified datetime."""
        if check_datetime is None:
            check_datetime = datetime.now()

        cycle_day = self.get_cycle_day(check_datetime)
        shift_type = self.get_shift_type(check_datetime)

        self.logger.debug(f"Checking duty for {check_datetime}: Cycle Day {cycle_day}, Shift: {shift_type}")

        # Check each team to find who's on duty
        for team_name, team_config in self.TEAMS.items():
            team_shift = team_config['schedule'][cycle_day]

            if team_shift == shift_type:
                team_id = team_config['id']
                self.logger.info(f"Team {team_name} ({team_id}) is on duty - "
                                 f"Cycle Day {cycle_day}, {shift_type.capitalize()} shift")
                return team_id

        self.logger.error(f"No team found on duty for Cycle Day {cycle_day}, {shift_type} shift")
        return None

    def get_team_name(self, team_id: str) -> Optional[str]:
        """Get team name from team ID."""
        for name, config in self.TEAMS.items():
            if config['id'] == team_id:
                return name
        return None


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
            device_name = self.device_map.get(device_code, None)

            if device_name is None:
                device_name = self._format_estate_name(device_code)

            # Parse lastOnlineTime
            last_online_raw = olt.get("lastOnlineTime")
            last_offline_time = None
            if last_online_raw:
                try:
                    dt = datetime.strptime(last_online_raw, "%Y-%m-%d %H:%M:%S")
                    last_offline_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError as e:
                    self.logger.warning(f"Failed to parse lastOnlineTime '{last_online_raw}': {e}")
                    last_offline_time = last_online_raw  # Use raw value as fallback

            device_info = {
                "original_desc": device_desc,
                "device_name": device_name,
                "device_code": device_code,
                "last_offline_time": last_offline_time,
                "raw_data": olt
            }

            processed_devices.append(device_info)
            self.logger.debug(f"Processed device: {device_name}")

        return processed_devices

    def _format_estate_name(self, estate_code: str) -> str:
        """Format estate names to be more readable"""
        estate = estate_code.capitalize()

        if "estate" in estate.lower():
            estate = estate.replace("estate", " Estate").replace("Estate", " Estate")

        estate = estate.replace("_", " ").replace("-", " ")
        estate = " ".join(estate.split())

        return estate

class TicketManager:
    def __init__(self, base_url: str, api_key: str, team_scheduler: TeamScheduler, timeout: int = 40):
        self.base_url = base_url
        self.api_key = api_key
        self.team_scheduler=team_scheduler
        self.timeout = timeout
        self.endpoint = f"{base_url}/api/http.php/tickets.json"
        self.headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        }
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("TicketManager initialized with TeamScheduler integration")


    def create_ticket(self, device_info: Dict, priority: str = 3) -> Optional[str]:

        olt_name = device_info["device_name"]
        self.logger.info(f"Creating ticket for device: {olt_name}")

        last_offline_time = device_info.get('last_offline_time', 'N/A')

        # Get team on duty at current time
        team_id = self.team_scheduler.get_team_on_duty()
        team_name = self.team_scheduler.get_team_name(team_id)

        if team_id:
            self.logger.info(f"Assigning ticket to Team {team_name} ({team_id})")
        else:
            self.logger.warning("Unable to determine team on duty - ticket will not be auto-assigned")


        ticket_data = {
            "alert": True,
            "autorespond": True,
            "source": "API",
            "name": "OLT Monitoring System",
            "email": "noc@openaccessmetro.net",
            "phone": "807-3138-700",
            "subject": f"Downtime at {olt_name}",
            "message": self._format_ticket_message(device_info),
            "ip": self._get_public_ip(),
            "priority": priority,
            "topicId": "5",
            "department": "4",
            "incident": "2",
            "category": "4",
            "Start_Time": last_offline_time,
            "rca": "WIP",
            # "assignId": "t5"
        }
        # Add team assignment if available
        if team_id:
            ticket_data["assignId"] = team_id

        response = requests.post(
            self.endpoint,
            headers=self.headers,
            json=ticket_data,
        )

        if response.status_code == 201:
            ticket_id = self._extract_ticket_id(response)
            self.logger.info(f"Ticket created successfully for {olt_name} (ID: {ticket_id}), Assigned to Team {team_name}")
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
            import re
            # Log the raw response for debugging
            self.logger.debug(f"Raw ticket response: {response.text}")

            match = re.search(r'([A-Z]+\-\d+)', response.text)
            if match:
                ticket_id = match.group(1)
                self.logger.debug(f"Extracted ticket ID: {ticket_id}")
                return ticket_id

            # Fallback: if no pattern found, return cleaned text
            self.logger.warning(f"Could not extract ticket ID from: {response.text}")
            return response.text.strip()

        except Exception as e:
            self.logger.error(f"Error extracting ticket ID: {e}")
            return None


    def _get_public_ip(self) -> str:
        """Get public IP address with retry"""
        try:
            return requests.get('https://api.ipify.org', timeout=5).text

        except:
            self.logger.warning("Could not fetch public IP, using fallback")
            return "102.134.21.254"


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

        try:
            # Create message object
            message = MIMEMultipart()
            message['From'] = self.sender_email
            message['To'] = recipient_email
            message['Subject'] = subject

            # FIXED: Actually attach the body to the message
            message.attach(MIMEText(body, 'plain'))

            server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=30)
            server.starttls()
            server.login(self.sender_email, self.sender_password)

            text = message.as_string()
            server.sendmail(self.sender_email, recipient_email, text)
            server.quit()

            self.logger.info(f"Email sent successfully to {recipient_email}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to send email: {e}")
            return False

    def send_downtime_alert(self, recipient_email: str,
                                       device: Dict, ticket_id: str) -> bool:
        """Send individual downtime alert email for a single device"""

        self.logger.info(f"Preparing downtime alert for device: {device['device_name']}")

        subject = f"SERVICE DOWNTIME NOTIFICATION - {device['device_name']} - #{ticket_id}"

        body = f"""OLT Downtime Alert

Device Offline Detected at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

Device Details:
- Device Name: {device['device_name']}
- Description: {device['original_desc']}
- Last Offline Time: {device.get('last_offline_time', 'N/A')}
- Ticket ID: {ticket_id}

This is an automated alert from the OLT Monitoring System.
Please investigate and resolve the issue promptly.

---
OLT Monitoring System
"""

        try:
            return self.send_notification(recipient_email, subject, body)
        except Exception as e:
            self.logger.error(f"Failed to send downtime alert for {device['device_name']}: {e}")
            return False



class DowntimeTracker:
    """Tracks active downtime tickets to prevent duplicates"""

    def __init__(self, state_file: str = "active_downtimes.json"):
        self.state_file = Path(state_file)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.active_downtimes = self._load_state()
        self.logger.info("DowntimeTracker initialized")

    def _load_state(self) -> Dict:
        """Load active downtimes from file"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"Failed to load state: {e}")
                return {}
        return {}

    def _save_state(self):
        """Save active downtimes to file"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.active_downtimes, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")

    def has_active_ticket(self, device_name: str) -> bool:
        """Check if device already has an active ticket"""
        return device_name in self.active_downtimes

    def get_ticket_id(self, device_name: str) -> Optional[str]:
        """Get existing ticket ID for device"""
        return self.active_downtimes.get(device_name, {}).get('ticket_id')

    def add_downtime(self, device_name: str, ticket_id: str, timestamp: str):
        """Record a new downtime"""
        self.active_downtimes[device_name] = {
            'ticket_id': ticket_id,
            'start_time': timestamp,
            'last_checked': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self._save_state()
        self.logger.info(f"Recorded downtime for {device_name} (Ticket: {ticket_id})")

    def update_last_checked(self, device_name: str):
        """Update last checked timestamp for existing downtime"""
        if device_name in self.active_downtimes:
            self.active_downtimes[device_name]['last_checked'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._save_state()

    def remove_downtime(self, device_name: str):
        """Remove downtime when device comes back online"""
        if device_name in self.active_downtimes:
            ticket_id = self.active_downtimes[device_name]['ticket_id']
            del self.active_downtimes[device_name]
            self._save_state()
            self.logger.info(f"Removed downtime for {device_name} (Ticket: {ticket_id})")
            return ticket_id
        return None

    def get_all_active(self) -> Dict:
        """Get all active downtimes"""
        return self.active_downtimes.copy()


class OLTAutomationOrchestrator:
    """Main orchestrator for OLT downtime automation"""

    def __init__(self, monitor: OLTMonitor, ticket_manager: TicketManager,
                 notifier: EmailNotifier, tracker: DowntimeTracker):
        self.monitor = monitor
        self.ticket_manager = ticket_manager
        self.notifier = notifier
        self.tracker = tracker  # Add tracker
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("OLTAutomationOrchestrator initialized")

    def run(self, notification_email: str = os.environ.get("RECIPIENT_EMAIL")) -> Dict:
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

                # Check if any previously offline devices are now online
                self._check_recovered_devices()

                return {"status": "success", "offline_devices": 0}

            self.logger.warning(f"Found {len(offline_devices)} offline device(s)")

            # Step 2: Group devices and filter out those with existing tickets
            from collections import defaultdict
            device_groups = defaultdict(list)
            for device in offline_devices:
                device_groups[device['device_name']].append(device)

            # Separate new downtimes from existing ones
            new_downtimes = {}
            existing_downtimes = {}

            for device_name, devices in device_groups.items():
                if self.tracker.has_active_ticket(device_name):
                    existing_ticket = self.tracker.get_ticket_id(device_name)
                    existing_downtimes[device_name] = existing_ticket
                    self.tracker.update_last_checked(device_name)
                    self.logger.info(f"Device '{device_name}' already has ticket: {existing_ticket} - SKIPPING")
                else:
                    new_downtimes[device_name] = devices
                    self.logger.warning(f"NEW DOWNTIME DETECTED - {device_name}")

            if not new_downtimes:
                self.logger.info("No new downtimes detected. All offline devices already have tickets.")
                return {
                    "status": "success",
                    "offline_devices": len(offline_devices),
                    "new_downtimes": 0,
                    "existing_downtimes": len(existing_downtimes)
                }

            # Step 3: Create tickets ONLY for NEW downtimes
            self.logger.info(f"[2/3] Creating tickets for {len(new_downtimes)} NEW downtime(s)...")

            device_ticket_map = {}

            for device_name, devices in new_downtimes.items():
                try:
                    ticket_id = self.ticket_manager.create_ticket(devices[0])
                    if ticket_id:
                        device_ticket_map[device_name] = ticket_id
                        # Record in tracker
                        self.tracker.add_downtime(
                            device_name,
                            ticket_id,
                            devices[0].get('last_offline_time', 'N/A')
                        )
                except Exception as e:
                    self.logger.error(f"Failed to create ticket for {device_name}: {e}")

            # Step 4: Send emails ONLY for NEW downtimes
            self.logger.info(f"[3/3] Sending email notifications for NEW downtimes...")
            emails_sent = 0

            for device_name, ticket_id in device_ticket_map.items():
                device = new_downtimes[device_name][0]

                if self.notifier.send_downtime_alert(
                        notification_email,
                        device,
                        ticket_id
                ):
                    emails_sent += 1

            self.logger.info(f"Sent {emails_sent}/{len(device_ticket_map)} email notifications")

            self.logger.info("=" * 60)
            self.logger.info("AUTOMATION COMPLETE")
            self.logger.info("=" * 60)

            result = {
                "status": "success",
                "offline_devices": len(offline_devices),
                "unique_devices": len(device_groups),
                "new_downtimes": len(new_downtimes),
                "existing_downtimes": len(existing_downtimes),
                "tickets_created": len(device_ticket_map),
                "emails_sent": emails_sent
            }

            self.logger.info(f"Summary: {len(offline_devices)} total offline, "
                             f"{len(new_downtimes)} NEW downtimes, "
                             f"{len(existing_downtimes)} existing downtimes, "
                             f"{len(device_ticket_map)} tickets created, "
                             f"emails sent: {emails_sent}")

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

    def _check_recovered_devices(self):
        """Check if any devices with active tickets have recovered"""
        active_downtimes = self.tracker.get_all_active()

        if not active_downtimes:
            return

        self.logger.info(f"Checking {len(active_downtimes)} device(s) with active tickets...")

        # Get current offline devices
        current_offline = self.monitor.get_offline_devices()
        current_offline_names = {d['device_name'] for d in current_offline}

        # Find devices that are now online
        for device_name in list(active_downtimes.keys()):
            if device_name not in current_offline_names:
                ticket_id = self.tracker.remove_downtime(device_name)
                self.logger.info(f"✓ Device '{device_name}' is BACK ONLINE (was on ticket {ticket_id})")


def main():
    # Setup logging
    logger = setup_logging(log_file="olt_automation.log", level=logging.INFO)
    logger.info("Application started")



    try:
        # Initialize components
        config = Config()

        # Initialize team scheduler
        team_scheduler = TeamScheduler(start_date=config.ROTATION_START_DATE)

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
            team_scheduler=team_scheduler,
            timeout=config.REQUEST_TIMEOUT
        )

        notifier = EmailNotifier(
            sender_email=config.SENDER_EMAIL,
            sender_password=config.SENDER_PASSWORD,
            smtp_server=config.SMTP_SERVER,
            smtp_port=config.SMTP_PORT
        )

        # Add tracker
        tracker = DowntimeTracker(state_file="active_downtimes.json")

        # Create orchestrator and run
        orchestrator = OLTAutomationOrchestrator(monitor, ticket_manager, notifier, tracker)
        result = orchestrator.run(notification_email=os.environ.get("RECIPIENT_EMAIL"))

        logger.info("Application completed successfully")

    except Exception as e:
        logger.critical(f"Application failed with fatal error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
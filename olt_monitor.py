#!/usr/bin/env python3
"""
OLT Downtime Detection Script
Monitors CDATA OLTs via ICMP ping and alerts on downtime
"""

import subprocess
import platform
import time
import logging
from datetime import datetime
from typing import List, Dict, Optional
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('olt_monitor.log'),
        logging.StreamHandler()
    ]
)


class OLTMonitor:
    def __init__(self, olt_list: List[Dict[str, str]], check_interval: int = 60):
        """
        Initialize OLT Monitor

        Args:
            olt_list: List of dicts with 'name', 'ip', and optional 'location'
            check_interval: Seconds between checks (default 60)
        """
        self.olt_list = olt_list
        self.check_interval = check_interval
        self.olt_status = {olt['ip']: {
            'status': 'unknown',
            'last_seen': None,
            'last_state_change': None
        } for olt in olt_list}
        self.is_windows = platform.system().lower() == 'windows'

    def ping_host(self, host: str, timeout: int = 2, count: int = 3) -> bool:
        """
        Ping a host and return True if reachable

        Args:
            host: IP address or hostname
            timeout: Ping timeout in seconds
            count: Number of ping packets
        """
        param = '-n' if self.is_windows else '-c'
        timeout_param = '-w' if self.is_windows else '-W'

        command = ['ping', param, str(count), timeout_param,
                   str(timeout * 1000 if self.is_windows else timeout), host]

        try:
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout * count + 2
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False
        except Exception as e:
            logging.error(f"Error pinging {host}: {e}")
            return False

    def check_olt(self, olt: Dict[str, str]) -> Dict[str, any]:
        """
        Check single OLT status

        Returns:
            Dict with status information
        """
        ip = olt['ip']
        name = olt['name']
        location = olt.get('location', 'N/A')

        is_up = self.ping_host(ip)
        current_time = datetime.now()
        previous_status = self.olt_status[ip]['status']

        result = {
            'name': name,
            'ip': ip,
            'location': location,
            'status': 'up' if is_up else 'down',
            'timestamp': current_time.isoformat(),
            'status_changed': False
        }

        # Detect status change (including from unknown state)
        if previous_status != result['status']:
            result['status_changed'] = True
            result['previous_status'] = previous_status

            if is_up:
                if previous_status == 'down':
                    downtime = (current_time - self.olt_status[ip]['last_state_change']).total_seconds()
                    result['downtime_duration'] = downtime
                    logging.warning(f"OLT RECOVERED: {name} ({ip}) at {location} - Down for {downtime:.0f}s")
                elif previous_status == 'unknown':
                    logging.info(f"OLT UP: {name} ({ip}) at {location}")
            else:
                if previous_status == 'unknown':
                    logging.error(f"OLT DOWN (initial check): {name} ({ip}) at {location}")
                else:
                    logging.error(f"OLT DOWN: {name} ({ip}) at {location}")

        # Update status
        if result['status_changed']:
            self.olt_status[ip]['last_state_change'] = current_time

        self.olt_status[ip]['status'] = result['status']
        if is_up:
            self.olt_status[ip]['last_seen'] = current_time

        return result

    def check_all_olts(self) -> List[Dict[str, any]]:
        """Check all OLTs and return results"""
        results = []
        logging.info(f"Starting check of {len(self.olt_list)} OLTs...")

        for olt in self.olt_list:
            result = self.check_olt(olt)
            results.append(result)

        # Log summary after each round
        up_count = sum(1 for r in results if r['status'] == 'up')
        down_count = len(results) - up_count
        logging.info(f"Check complete: {up_count} UP, {down_count} DOWN")

        return results

    def generate_report(self, results: List[Dict[str, any]]) -> str:
        """Generate status report"""
        up_count = sum(1 for r in results if r['status'] == 'up')
        down_count = len(results) - up_count

        report = f"\n{'=' * 60}\n"
        report += f"OLT Status Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        report += f"{'=' * 60}\n"
        report += f"Total OLTs: {len(results)} | Up: {up_count} | Down: {down_count}\n"
        report += f"{'=' * 60}\n\n"

        for r in results:
            status_icon = "✓" if r['status'] == 'up' else "✗"
            report += f"{status_icon} {r['name']} ({r['ip']}) - {r['location']}: {r['status'].upper()}\n"

            if r.get('status_changed') and r['status'] == 'up':
                report += f"  └─ Recovered after {r['downtime_duration']:.0f}s downtime\n"

        return report

    def run_continuous(self):
        """Run continuous monitoring"""
        logging.info(f"Starting OLT monitoring for {len(self.olt_list)} devices")
        logging.info(f"Check interval: {self.check_interval} seconds")

        try:
            while True:
                results = self.check_all_olts()

                # Log summary
                down_olts = [r for r in results if r['status'] == 'down']
                if down_olts:
                    logging.warning(f"{len(down_olts)} OLT(s) are DOWN")

                time.sleep(self.check_interval)

        except KeyboardInterrupt:
            logging.info("Monitoring stopped by user")

    def run_once(self) -> List[Dict[str, any]]:
        """Run single check and return results"""
        results = self.check_all_olts()
        print(self.generate_report(results))
        return results


# Example usage
if __name__ == "__main__":
    # Configure your OLTs here
    OLT_DEVICES = [
        {'name': 'Google', 'ip': '8.8.8.8', 'location': 'External'},
        {'name': 'YouTube', 'ip': 'www.youtube.com', 'location': 'External'},
        {'name': 'LOS-LekkiGardensPH5-OLT-001', 'ip': '10.0.4.86', 'location': 'Lekki Gardens PH5'},
        {'name': 'LOS-LekkiGardensPH5-OLT-002', 'ip': '10.0.4.87', 'location': 'Lekki Gardens PH5'},
        {'name': 'LOS-IKONECTT-GREENESTATE-001', 'ip': '10.0.4.152', 'location': 'Green Estate'},
        {'name': 'LOS-EricmoreOLT', 'ip': '10.0.4.41', 'location': 'Ericmore'},
        {'name': 'LOS-SpringbayOLT', 'ip': '10.0.4.21', 'location': 'Springbay'},
        {'name': 'LOS29-OLT-001', 'ip': '10.0.4.162', 'location': 'LOS29'},
        {'name': 'LOS-BEACHFRONT-OLT-001', 'ip': '10.0.4.160', 'location': 'Beachfront'},
        {'name': 'LOS-ATLANTICVILLE-001', 'ip': '10.0.4.161', 'location': 'Atlanticville'},
        {'name': 'LOS-IKONECTT-LEKKIGARDENS2-001', 'ip': '10.0.4.138', 'location': 'Lekki Gardens 2'},
        {'name': 'LOS-OAM-ILUPEJU-001', 'ip': '10.0.4.129', 'location': 'Ilupeju'},
        {'name': 'LOS-NEWHORIZON_OFFICE-OLT-001', 'ip': '10.0.4.75', 'location': 'New Horizon Office'},
        {'name': 'LOS-JORAESTATE-OLT-001', 'ip': '10.0.4.96', 'location': 'Jora Estate'},
        {'name': 'LOS-JORAESTATE-OLT-002', 'ip': '10.0.4.97', 'location': 'Jora Estate'},
        {'name': 'LOS-YABACLUSTER3-OLT-001', 'ip': '10.0.4.149', 'location': 'Yaba Cluster 3'},
        {'name': 'LOS-YABACLUSTER3-OLT-002', 'ip': '10.0.4.150', 'location': 'Yaba Cluster 3'},
        {'name': 'LOS-DIVINEESTATE-OLT-001', 'ip': '10.0.4.136', 'location': 'Divine Estate'},
        {'name': 'LOS-SILVERPOINTESTATE-OLT-002', 'ip': '10.0.4.91', 'location': 'Silverpoint Estate'},
        {'name': 'LOS-SILVERPOINTESTATE-OLT-001', 'ip': '10.0.4.130', 'location': 'Silverpoint Estate'},
        {'name': 'LOSDOLPHINESTATE-OLT-001', 'ip': '10.0.4.134', 'location': 'Dolphin Estate'},
        {'name': 'LOS-SEASIDEESTATE-OLT-003', 'ip': '10.0.4.128', 'location': 'Seaside Estate'},
        {'name': 'LOS-MANORESTATE-OLT-001', 'ip': '10.0.4.125', 'location': 'Manor Estate'},
        {'name': 'LOS-MANORESTATE-OLT-002', 'ip': '10.0.4.126', 'location': 'Manor Estate'},
        {'name': 'LOS-IKONECCT-MIJIL', 'ip': '10.0.4.69', 'location': 'Mijil'},
        {'name': 'LOS-MIJIL-OLT-002', 'ip': '10.0.4.140', 'location': 'Mijil'},
        {'name': 'LOS-RACKCENTER', 'ip': '10.0.4.131', 'location': 'Rack Center'},
        {'name': 'LOS-SOUTHDRIFTESTATE-OLT-001', 'ip': '10.0.4.117', 'location': 'South Drift Estate'},
        {'name': 'LOS-SOUTHDRIFTESTATE-OLT-002', 'ip': '10.0.4.118', 'location': 'South Drift Estate'},
        {'name': 'LOS-OLALEYE-OLT-001', 'ip': '10.0.4.123', 'location': 'Olaleye'},
        {'name': 'LOS-OLALEYE-OLT-002', 'ip': '10.0.4.124', 'location': 'Olaleye'},
        {'name': 'LOS-ATUNRASE-OLT-1', 'ip': '10.0.4.110', 'location': 'Atunrase'},
        {'name': 'Bashorun-Wacs Redundancy Leg', 'ip': '10.0.4.17', 'location': 'Bashorun'},
        {'name': 'LOS-SunshineEstate-OLT-001', 'ip': '10.0.4.90', 'location': 'Sunshine Estate'},
        {'name': 'LOS-SunshineEstate-OLT-002', 'ip': '10.0.4.142', 'location': 'Sunshine Estate'},
        {'name': 'LOS-MILLENIUMGBAGADA-OLT-001', 'ip': '10.0.4.106', 'location': 'Millenium Gbagada'},
        {'name': 'LOS-MILLENIUMGBAGADA-OLT-002', 'ip': '10.0.4.107', 'location': 'Millenium Gbagada'},
        {'name': 'LOS-MILLENIUMGBAGADA-OLT-003', 'ip': '10.0.4.108', 'location': 'Millenium Gbagada'},
        {'name': 'LOS-MILLENIUMGBAGADA-OLT-004', 'ip': '10.0.4.109', 'location': 'Millenium Gbagada'},
        {'name': 'LOS-IKONNECT-OCEANPALM-001', 'ip': '10.0.4.42', 'location': 'Ocean Palm'},
        {'name': 'LOS-IKONNECT-OCEANPALM-002', 'ip': '10.0.4.63', 'location': 'Ocean Palm'},
        {'name': 'LOS-IKONNECT-CEDARCOUNTY-001', 'ip': '10.0.4.43', 'location': 'Cedar County'},
        {'name': 'LOS-IKONNECT-CEDARCOUNTY-002', 'ip': '10.0.4.44', 'location': 'Cedar County'},
        {'name': 'LOS-dideolu-OLT-002', 'ip': '10.0.4.50', 'location': 'Dideolu'},
        {'name': 'LOS-UNITYHOMES-OLT-001', 'ip': '10.0.4.40', 'location': 'Unity Homes'},
        {'name': 'LOS-UNITYHOMES-OLT-002', 'ip': '10.0.4.103', 'location': 'Unity Homes'},
        {'name': 'LOS-IKONNECTT-BUENAVISTA-002', 'ip': '10.0.4.48', 'location': 'Buenavista'},
        {'name': 'LOS-OloriMojisolaOnikoyi-001', 'ip': '10.0.4.93', 'location': 'Olori Mojisola Onikoyi'},
        {'name': 'LOS-ACADIA MEWS Outdoor-OLT', 'ip': '10.0.4.92', 'location': 'Acadia Mews'},
        {'name': 'LOS-CWG-OLT', 'ip': '10.0.4.23', 'location': 'CWG'},
        {'name': 'LOS-Chevvy Estate-OLT-001', 'ip': '10.0.4.80', 'location': 'Chevvy Estate'},
        {'name': 'LOS-United Estates-OLT-001', 'ip': '10.0.4.82', 'location': 'United Estates'},
        {'name': 'LOS-UnitedEstates-OLT-002', 'ip': '10.0.4.83', 'location': 'United Estates'},
        {'name': 'LOS-UnitedEstates-OLT-003', 'ip': '10.0.4.84', 'location': 'United Estates'},
        {'name': 'LOS-OguduGRAOLT', 'ip': '10.0.4.61', 'location': 'Ogudu GRA'},
        {'name': 'LOS-ChevvyEstate-OLT-002', 'ip': '10.0.4.88', 'location': 'Chevvy Estate'},
        {'name': 'LOS-ChevvyEstate-OLT-003', 'ip': '10.0.4.89', 'location': 'Chevvy Estate'},
        {'name': 'LOS-OguduGRAOLT-002', 'ip': '10.0.4.74', 'location': 'Ogudu GRA'},
        {'name': 'LOS-WhiteOaks-OLT', 'ip': '10.0.4.62', 'location': 'White Oaks'},
        {'name': 'LOS-Bashorun-OLT', 'ip': '10.0.4.85', 'location': 'Bashorun'},
        {'name': 'LOS-ACA-OLT', 'ip': '10.0.4.20', 'location': 'ACA'},
        {'name': 'LOS-IDS-OLT-001', 'ip': '10.0.4.65', 'location': 'IDS'},
        {'name': 'LOS-IDS-OLT-002', 'ip': '10.0.4.66', 'location': 'IDS'},
        {'name': 'LOS-IDS-OLT-003', 'ip': '10.0.4.67', 'location': 'IDS'},
        {'name': 'LOS-IDS-OLT-004', 'ip': '10.0.4.71', 'location': 'IDS'},
        {'name': 'LOS-OfficeOLT-001', 'ip': '10.0.4.72', 'location': 'Office'},
        {'name': 'LOS-Computervillage-OLT-001', 'ip': '10.0.4.45', 'location': 'Computer Village'},
        {'name': 'LOS-Computervillage-OLT-002', 'ip': '10.0.4.46', 'location': 'Computer Village'},
        {'name': 'LOS-IKONNECTT-BUENAVISTA-001', 'ip': '10.0.4.47', 'location': 'Buenavista'},
        {'name': 'LOS-PeacevilleOLT', 'ip': '10.0.4.52', 'location': 'Peaceville'},
        {'name': 'LOS-AveraOLT-002', 'ip': '10.0.4.60', 'location': 'Avera'},
        {'name': 'LOS01-OLT-001(OADC)', 'ip': '10.0.4.59', 'location': 'OADC'},
        {'name': 'LOS-karimu-OLT-001', 'ip': '10.0.4.64', 'location': 'Karimu'},
        {'name': 'LOS-Oriola', 'ip': '10.0.4.51', 'location': 'Oriola'},
        {'name': 'LOS-OsborneOLT', 'ip': '10.0.4.78', 'location': 'Osborne'},
        {'name': 'LOS-Millenium(Cobranet)OLT', 'ip': '10.0.4.79', 'location': 'Millenium Cobranet'},
        {'name': 'LOS-IKONNECTT-GREENVILLE-002', 'ip': '10.0.4.144', 'location': 'Greenville'},
        {'name': 'LOS-IKONNECTT-GREENVILLE-003', 'ip': '10.0.4.145', 'location': 'Greenville'},
        {'name': 'LOS-IKONNECTT-INFINITYESTATE-001', 'ip': '10.0.4.132', 'location': 'Infinity Estate'},
        {'name': 'LOS-IKONNECTT-INFINITYESTATE-002', 'ip': '10.0.4.133', 'location': 'Infinity Estate'},
        {'name': 'LOS-ACADIAGROOVE-001', 'ip': '10.0.4.148', 'location': 'Acadia Groove'},
        {'name': 'LOS-ATUNRASE-OLT-3 (Test Down)', 'ip': '10.0.4.112', 'location': 'Atunrase'},
    ]

    # Initialize monitor with 60-second check interval
    monitor = OLTMonitor(OLT_DEVICES, check_interval=60)

    # Choose monitoring mode:

    # Option 1: Run once and exit
    # monitor.run_once()

    # Option 2: Run continuously (recommended for daemon/service)
    monitor.run_continuous()
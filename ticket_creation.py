import os
from datetime import datetime
import requests
import json
from dotenv import load_dotenv

load_dotenv()

# First, check what IP we're connecting from
try:
    my_ip = requests.get('https://api.ipify.org').text
    print(f"🌐 Your public IP: {my_ip}")
    print(f"Make sure this IP is whitelisted in osTicket API settings!\n")
except:
    print("Could not determine public IP\n")

# osTicket API Configuration
OSTICKET_URL = os.environ.get("OSTICKET_URL")
API_KEY = os.environ.get("API_KEY") # From your API dashboard

# API endpoint for creating tickets
endpoint = f"{OSTICKET_URL}/api/http.php/tickets.json"

# Headers
headers = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json"
}

# Ticket data
ticket_data = {
    "alert": True,
    "autorespond": True,
    "source": "API",
    "name": "John Doe",
    "email": "noc@openaccessmetro.net",
    "phone": "807-3138-700",
    "subject": "Testing API",
    "message": "data:text/html,We are experiencing slow response times on the production server. The issue started around 2 PM today.",
    "ip": "154.66.246.206",
    "priority": "2",  # 1=Low, 2=Normal, 3=High, 4=Emergency
    "topicId": "6",  # Must match a valid Help Topic ID
    "department": "4",
    "incident": "4",
    "category": "4",
    "Start_Time": f"{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}",
    "rca": "WIP"
}

try:
    print(f"📤 Sending request to: {endpoint}")
    print(f"🔑 Using API Key: {API_KEY[:10]}...{API_KEY[-10:]}")
    print(f"📋 Data: {json.dumps(ticket_data, indent=2)}\n")

    # Send POST request to create ticket
    response = requests.post(endpoint, headers=headers, json=ticket_data)

    # Check response status
    if response.status_code == 201:
        print("✅ Ticket created successfully!")
        print(f"Response: {response.text}")

        # The response typically contains the ticket number
        try:
            response_data = response.json()
            ticket_id = response_data.get('ticket_id') or response_data.get('id') or response_data.get('number')
            if ticket_id:
                print(f"🎫 Ticket ID/Number: {ticket_id}")
        except:
            print("Ticket created but couldn't parse ticket ID from response")
    else:
        print(f"❌ Failed to create ticket")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}\n")

        # Provide troubleshooting tips
        if response.status_code == 401:
            print("💡 Troubleshooting 401 Error:")
            print("   1. Check osTicket System Logs (Admin Panel → Dashboard → System Logs)")
            print("   2. Look for the IP address osTicket is seeing")
            print("   3. Make sure that IP is whitelisted in your API key settings")
            print("   4. Or set API key IP to: 0.0.0.0/0 (allows all IPs)")
            print("   5. Verify API key is Active and not Disabled")
        elif response.status_code == 400:
            print("💡 Troubleshooting 400 Error:")
            print("   - Check that topicId matches a valid Help Topic")
            print("   - Verify email format is correct")
            print("   - Check required fields are present")
        elif response.status_code == 404:
            print("💡 Endpoint not found - verify API URL")

except requests.exceptions.SSLError as e:
    print(f"❌ SSL Error: {e}")
    print("\n💡 SSL Certificate issue detected!")

except requests.exceptions.RequestException as e:
    print(f"❌ Error making request: {e}")


# Helper function to test different endpoints
def test_api_endpoints(api_key, base_url):
    """
    Test multiple possible API endpoints
    """
    endpoints = [
        f"{base_url}/api/http.php/tickets.json",
        f"{base_url}/api/tickets.json",
    ]

    headers = {"X-API-Key": api_key}

    print("\n🔍 Testing API endpoints:")
    for endpoint in endpoints:
        try:
            response = requests.get(endpoint, headers=headers, timeout=5)
            print(f"   {endpoint}")
            print(f"      Status: {response.status_code} | Response: {response.text[:100]}")
        except Exception as e:
            print(f"   {endpoint}")
            print(f"      Error: {str(e)[:100]}")

# Uncomment to test endpoints
# test_api_endpoints(API_KEY, OSTICKET_URL)
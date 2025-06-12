#!/usr/bin/env python3
"""
Pocket API OAuth Authentication Script

This script handles the OAuth authentication flow for the Pocket API:
1. Obtains a request token
2. Opens browser for user authorization
3. Exchanges request token for an access token
4. Saves the access token for later use
"""
import os
import sys
import json
import requests
import webbrowser
from dotenv import load_dotenv, set_key

REQUEST_TOKEN_URL = "https://getpocket.com/v3/oauth/request"
ACCESS_TOKEN_URL = "https://getpocket.com/v3/oauth/authorize"
AUTH_URL = "https://getpocket.com/auth/authorize"

HEADERS = {"Content-Type": "application/json; charset=UTF-8", "X-Accept": "application/json"}

def load_credentials():
    load_dotenv()
    consumer_key = os.getenv("CONSUMER_KEY")
    redirect_uri = os.getenv("REDIRECT_URI", "https://example.com")

    if not consumer_key:
        print("Error: CONSUMER_KEY environment variable is not set.")
        print("Please create a .env file with your CONSUMER_KEY.")
        sys.exit(1)

    return consumer_key, redirect_uri

def get_request_token(consumer_key, redirect_uri):
    try:
        payload = {
            "consumer_key": consumer_key,
            "redirect_uri": redirect_uri
        }

        response = requests.post(
            REQUEST_TOKEN_URL,
            json=payload,
            headers=HEADERS
        )
        response.raise_for_status()

        if "code=" in response.text:
            request_token = response.text.split("=")[-1].strip()
            print(f"✅ Request token obtained: {request_token}")
            return request_token
        else:
            try:
                data = response.json()
                return data.get("code")
            except json.JSONDecodeError:
                print(f"❌ Unexpected response format: {response.text}")
                sys.exit(1)

    except requests.RequestException as e:
        print(f"❌ Failed to get request token: {e}")
        sys.exit(1)

def authorize_app(request_token, redirect_uri):
    """Open browser for user authorization."""
    auth_url = f"{AUTH_URL}?request_token={request_token}&redirect_uri={redirect_uri}"
    print(f"\nOpen this URL in your browser to authorize the app:")
    print(f"\n{auth_url}\n")

    try:
        webbrowser.open(auth_url)
    except webbrowser.Error:
        print("Could not automatically open the browser.")
        print("Please copy the URL above and open it manually.")

    input("Press Enter after you have authorized the app in your browser...")

def get_access_token(consumer_key, request_token):
    """Exchange request token for an access token."""
    try:
        payload = {
            "consumer_key": consumer_key,
            "code": request_token
        }

        response = requests.post(
            ACCESS_TOKEN_URL,
            json=payload,
            headers=HEADERS
        )
        response.raise_for_status()

        if "access_token=" in response.text and "username=" in response.text:
            params = dict(item.split("=") for item in response.text.split("&"))
            access_token = params.get("access_token")
            username = params.get("username")
            return access_token, username
        else:
            try:
                data = response.json()
                return data.get("access_token"), data.get("username")
            except json.JSONDecodeError:
                print(f"❌ Unexpected response format: {response.text}")
                return None, None

    except requests.RequestException as e:
        print(f"❌ Failed to get access token: {e}")
        return None, None

def save_access_token(access_token, username):
    if access_token:
        try:
            dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
            set_key(dotenv_path, "ACCESS_TOKEN", access_token)
            print(f"✅ Access token for user '{username}' saved to .env file")
        except Exception as e:
            print(f"Warning: Could not save to .env file: {e}")
            print(f"Your access token is: {access_token}")
            print("Please save this token to use in other scripts.")

def main():
    print("🔐 Starting Pocket API OAuth Authentication\n")

    consumer_key, redirect_uri = load_credentials()

    request_token = get_request_token(consumer_key, redirect_uri)
    if not request_token:
        return

    authorize_app(request_token, redirect_uri)

    access_token, username = get_access_token(consumer_key, request_token)
    if not access_token:
        print("❌ Failed to obtain access token.")
        return

    save_access_token(access_token, username)
    print("\n🎉 Authentication process completed!")

if __name__ == "__main__":
    main()

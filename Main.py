# main.py - Roblox Activity Tracker

import time
import json
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from Assets import Config, Data

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')


def create_authenticated_session() -> requests.Session:
    """
    Create a requests.Session that:
      - Sets the .ROBLOSECURITY cookie
      - Seeds/attaches a CSRF token if needed
      - Mounts a retry strategy on all HTTP(S) requests
      - Applies a default User-Agent header
    """
    session = requests.Session()
    session.cookies['.ROBLOSECURITY'] = Config.COOKIE
    headers = {'User-Agent': 'Mozilla/5.0'}

    # Retry strategy: retry on connection errors, 502/503/504/429, etc.
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    # Seed CSRF token (make a dummy POST to PRESENCE_URL)
    try:
        r = session.post(
            Config.PRESENCE_URL,
            headers=headers,
            json={'userIds': [Config.TEST_USER_ID]},
            timeout=10
        )
        if r.status_code == 403 and 'x-csrf-token' in r.headers:
            headers['X-CSRF-TOKEN'] = r.headers['x-csrf-token']
    except requests.RequestException as e:
        logging.warning(f"CSRF seed request failed ({Config.PRESENCE_URL}): {e}")

    session.headers.update(headers)
    return session


def get_presence(session: requests.Session, user_ids: list) -> list:
    """
    Fetch presence data for a list of user IDs.
    Returns a list of presence objects (or empty list on failure).
    """
    try:
        response = session.post(
            Config.PRESENCE_URL,
            json={'userIds': user_ids},
            timeout=10
        )
        response.raise_for_status()
        return response.json().get('userPresences', [])
    except requests.RequestException as e:
        logging.error(f"Presence fetch failed ({Config.PRESENCE_URL}): {e}")
        return []


def get_game_info(session: requests.Session, universe_id: int) -> str:
    """
    Fetch the game name by universeId.
    Retries automatically if the request is retriable. Returns "Unknown Game" on failure.
    """
    url = Config.GAMES_URL.format(universe_id=universe_id)
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
        data = response.json().get('data', [])
        return data[0].get('name', "Unknown Game") if data else "Unknown Game"
    except requests.RequestException as e:
        logging.warning(f"Game info fetch failed ({url}): {e}")
        return "Unknown Game"


def get_user_info(session: requests.Session, user_id: str) -> tuple[str, str]:
    """
    Fetch the user’s Roblox username and displayName.
    Returns (username, display_name), or (None, None) on error.
    """
    url = Config.USERS_URL.format(user_id=user_id)
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("name"), data.get("displayName")
    except requests.RequestException as e:
        logging.warning(f"User info fetch failed ({url}): {e}")
        return None, None


def send_webhook(embed: dict) -> None:
    """
    Send a Discord embed via webhook. Logs an error if it fails.
    """
    try:
        resp = requests.post(Config.DISCORD_WEBHOOK, json={'embeds': [embed]}, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        logging.error(f"Webhook failed ({Config.DISCORD_WEBHOOK}): {e}")


def build_embed_in_game(presence: dict, game_name: str, username: str, display_name: str) -> dict:
    """
    Build the embed payload for “user is in-game” with join/details.
    """
    user_id = presence['userId']
    place_id = presence.get('placeId')
    game_id = presence.get('gameId')

    if place_id and game_id:
        join_url = f"https://www.roblox.com/games/start?placeId={place_id}&gameId={game_id}"
        game_page_url = f"https://www.roblox.com/games/{place_id}"
        title = f"{display_name or username} is now in-game"
        description = f"**{game_name}**"
        return {
            'title': title,
            'color': 0x00FF00,
            'description': description,
            'url': join_url,
            'fields': [
                {'name': 'Join Server', 'value': f"[Click Here]({join_url})", 'inline': True},
                {'name': 'Game Page', 'value': f"[View Game]({game_page_url})", 'inline': True}
            ]
        }
    else:
        # Private joins—no placeId/gameId
        title = f"{display_name or username} is in a game"
        return {
            'title': title,
            'color': 0x00FFFF,
            'description': "Joins are off, check badges for hint of game."
        }


def load_user_ids() -> list:
    """
    Load a JSON file (Assets/users.json) containing an array of user IDs to track.
    """
    try:
        with open("Assets/users.json", "r") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Failed to load user IDs: {e}")
        return []


def main():
    session = create_authenticated_session()
    user_ids = load_user_ids()
    if not user_ids:
        logging.error("No user IDs found—exiting.")
        return

    last_states: dict[str, int] = {}
    logging.info("Roblox Activity Tracker is now running…")

    while True:
        presences = get_presence(session, user_ids)

        for presence in presences:
            user_id = str(presence['userId'])
            state = presence.get('userPresenceType', 0)
            last_state = last_states.get(user_id)

            # Only act if state changed
            if state != last_state:
                username, display_name = get_user_info(session, user_id)

                # Offline
                if state == 0:
                    embed = {
                        'title': f"{display_name or username or user_id} is Offline",
                        'color': 0xFF0000
                    }
                    send_webhook(embed)

                # Online (not in-game)
                elif state == 1:
                    embed = {
                        'title': f"{display_name or username or user_id} is Online (not in-game)",
                        'color': 0xFFFF00
                    }
                    send_webhook(embed)

                # In-Game (maybe private joins)
                elif state == 2:
                    universe_id = presence.get('universeId')
                    game_name = "Unknown Game"
                    if universe_id:
                        game_name = get_game_info(session, universe_id)

                    embed = build_embed_in_game(presence, game_name, username, display_name)
                    send_webhook(embed)

                # Update last known state
                last_states[user_id] = state

        time.sleep(Config.CHECK_INTERVAL)


if __name__ == '__main__':
    main()

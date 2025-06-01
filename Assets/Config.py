# Assets/Config.py


# TEST user for CSRF token seeding only
TEST_USER_ID = "1431529325"
COOKIE = "" # Roblox Account Cookie
DISCORD_WEBHOOK = ""  # Discord webhook URL
CHECK_INTERVAL = 30  # in seconds


# API Endpoints
GAMES_URL = "https://games.roproxy.com/v1/games?universeIds={universe_id}"
PRESENCE_URL = "https://presence.roproxy.com/v1/presence/users"
USERS_URL = "https://users.roproxy.com/v1/users/{user_id}"

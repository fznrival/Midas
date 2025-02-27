import cloudscraper
import time
import configparser
import logging
import os
import random
import requests
from typing import Tuple, Dict, Any
from urllib.parse import urlparse
from datetime import datetime, timedelta
import pytz

# Configure logging to save to file and console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),  # Simpan log ke file
        logging.StreamHandler()          # Tampilkan di console
    ]
)
logger = logging.getLogger(__name__)

# Color codes for console output
CYAN = '\033[96m'
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
RESET = '\033[0m'

# Load configuration
config = configparser.ConfigParser()
config.read('config.ini')

AUTH_FILE = config.get('settings', 'auth_file', fallback='auth.txt')
PROXIES_FILE = config.get('settings', 'proxies_file', fallback='proxies.txt')
SLEEP_BETWEEN_ACCOUNTS = config.getint('settings', 'sleep_between_accounts', fallback=10)
MAX_RETRIES = config.getint('settings', 'max_retries', fallback=3)

# Zona waktu WIB (UTC+7)
WIB = pytz.timezone('Asia/Jakarta')

# Global variable untuk menyimpan daftar proxy dan IP info
PROXY_LIST = []
PROXY_IP_INFO = {}

def load_proxies(filename: str) -> list:
    """Load proxies from file."""
    try:
        with open(filename, 'r') as file:
            proxies = [line.strip() for line in file if line.strip()]
            logger.info(f"Loaded {len(proxies)} proxies from {filename}")
            return proxies
    except FileNotFoundError:
        logger.error(f"Proxy file {filename} not found.")
        return []

def get_random_proxy() -> str:
    """Get random proxy from the list."""
    if PROXY_LIST:
        return random.choice(PROXY_LIST)
    return None

def parse_proxy(proxy_string):
    """Parse proxy string in format protocol://user:pass@host:port"""
    try:
        if not proxy_string:
            return None
        parsed = urlparse(proxy_string)
        protocol = parsed.scheme
        if '@' in proxy_string:
            auth, host_port = proxy_string.split('://', 1)[1].split('@')
            username, password = auth.split(':')
        else:
            username = password = None
            host_port = proxy_string.split('://', 1)[1]
        if ':' in host_port:
            host, port = host_port.split(':')
        else:
            host = host_port
            port = '80' if protocol == 'http' else '443'
        proxy_dict = {}
        if username and password:
            proxy_url = f"{protocol}://{username}:{password}@{host}:{port}"
        else:
            proxy_url = f"{protocol}://{host}:{port}"
        proxy_dict[protocol] = proxy_url
        return proxy_dict
    except Exception as e:
        logger.error(f"Invalid proxy format. Error: {str(e)}")
        return None

def get_ip_info(proxy: str) -> dict:
    """Get IP information using httpbin.org to verify the IP."""
    try:
        url = "https://httpbin.org/ip"
        response = requests.get(url, proxies={"http": proxy, "https": proxy}, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch IP info for proxy {proxy}. Error: {e}")
        return {}

def create_scraper_with_proxy(proxy_string=None):
    """Creates a cloudscraper instance with proxy support."""
    try:
        scraper = cloudscraper.create_scraper()
        if proxy_string:
            parsed_proxy = parse_proxy(proxy_string)
            if parsed_proxy:
                scraper.proxies = parsed_proxy
                logger.info(f"Using proxy: {YELLOW}{proxy_string}{RESET}")
        return scraper
    except Exception as e:
        logger.error(f"Error creating scraper with proxy: {str(e)}")
        return None

def post_request(url: str, headers: Dict[str, str], payload: Any = None, retries: int = 0, proxy: str = None) -> Tuple[Any, Any]:
    """Makes a POST request using cloudscraper with proxy support."""
    try:
        scraper = create_scraper_with_proxy(proxy)
        if not scraper:
            raise Exception("Failed to create scraper")
        response = scraper.post(url, json=payload, headers=headers)
        response.raise_for_status()
        try:
            return response.json(), response.cookies
        except ValueError:
            return response.text, response.cookies
    except Exception as e:
        if retries < MAX_RETRIES:
            logger.warning(f"Request failed: {e}. Retrying in 5 seconds... (Attempt {retries + 1}/{MAX_RETRIES})")
            time.sleep(5)
            return post_request(url, headers, payload, retries + 1, proxy)
        else:
            logger.error(f"Request failed after multiple retries: {e}")
            return None, None

def get_request(url: str, headers: Dict[str, str], retries: int = 0, proxy: str = None) -> Any:
    """Makes a GET request using cloudscraper with proxy support."""
    try:
        scraper = create_scraper_with_proxy(proxy)
        if not scraper:
            raise Exception("Failed to create scraper")
        response = scraper.get(url, headers=headers)
        response.raise_for_status()
        try:
            return response.json()
        except ValueError:
            logger.warning("Response is not JSON.")
            return None
    except Exception as e:
        if retries < MAX_RETRIES:
            logger.warning(f"Request failed: {e}. Retrying in 5 seconds... (Attempt {retries + 1}/{MAX_RETRIES})")
            time.sleep(5)
            return get_request(url, headers, retries + 1, proxy)
        else:
            logger.error(f"Request failed after multiple retries: {e}")
            return None

def read_init_data(filename: str) -> list[str]:
    """Reads init data from a file."""
    try:
        with open(filename, 'r') as file:
            init_data_list = [line.strip() for line in file if line.strip()]
            return init_data_list
    except FileNotFoundError:
        logger.error(f"File {filename} not found.")
        return []

def get_streak_info(headers: Dict[str, str], proxy: str):
    """Gets and prints streak information."""
    url_streak = "https://api-tg-app.midas.app/api/streak"
    streak_data = get_request(url_streak, headers, proxy=proxy)
    if streak_data:
        streak_days_count = streak_data.get("streakDaysCount", "Not found")
        next_rewards = streak_data.get("nextRewards", {})
        points = next_rewards.get("points", "Not found")
        tickets = next_rewards.get("tickets", "Not found")
        claimable = streak_data.get("claimable", False)
        logger.info(f"Streak Days Count: {streak_days_count}")
        logger.info(f"Claimable Rewards - Points: {GREEN}{points}{RESET}, Tickets: {GREEN}{tickets}{RESET}")
        if claimable:
            logger.info(f"{GREEN}Streak available to claim.{RESET}")
            claim_streak(headers, proxy)
        else:
            logger.warning(f"{YELLOW}Streak not available to claim.{RESET}")
    else:
        logger.error("Error: Could not access streak API.")

def claim_streak(headers: Dict[str, str], proxy: str):
    """Claims the daily streak reward."""
    url_claim = "https://api-tg-app.midas.app/api/streak"
    response, _ = post_request(url_claim, headers, proxy=proxy)
    if response:
        points = response.get("points", "Not found")
        tickets = response.get("tickets", "Not found")
        logger.info(f"{GREEN}Daily ticket and point claim successful!{RESET}")
    else:
        logger.error(f"{RED}Error: Failed to claim daily reward.{RESET}")

def get_user_info(headers: Dict[str, str], proxy: str) -> Tuple[int, int]:
    """Gets and prints user information."""
    url_user = "https://api-tg-app.midas.app/api/user"
    user_data = get_request(url_user, headers, proxy=proxy)
    if user_data:
        telegram_id = user_data.get("telegramId", "Not found")
        username = user_data.get("username", "Not found")
        first_name = user_data.get("firstName", "Not found")
        points = user_data.get("points", "Not found")
        tickets = user_data.get("tickets", 0)
        games_played = user_data.get("gamesPlayed", "Not found")
        streak_days_count = user_data.get("streakDaysCount", "Not found")
        logger.info(f"Telegram ID: {telegram_id}")
        logger.info(f"Username: {CYAN}{username}{RESET}")
        logger.info(f"First Name: {CYAN}{first_name}{RESET}")
        logger.info(f"Points: {GREEN}{points}{RESET}")
        logger.info(f"Tickets: {GREEN if tickets > 0 else RED}{tickets}{RESET}")
        logger.info(f"Games Played: {games_played}")
        logger.info(f"Streak Days Count: {streak_days_count}")
        return tickets, points
    else:
        logger.error("Error: Could not access user API.")
        return 0, 0

def check_referral_status(headers: Dict[str, str], proxy: str) -> Tuple[int, int]:
    """Checks and claims referral rewards if available."""
    url_referral = "https://api-tg-app.midas.app/api/referral/status"
    url_referral_claim = "https://api-tg-app.midas.app/api/referral/claim"
    referral_data = get_request(url_referral, headers, proxy=proxy)
    if referral_data:
        can_claim = referral_data.get("canClaim", False)
        if can_claim:
            logger.info(f"{GREEN}Referral claim available! Executing claim...{RESET}")
            claim_response, _ = post_request(url_referral_claim, headers, proxy=proxy)
            if claim_response:
                total_points = claim_response.get("totalPoints", 0)
                total_tickets = claim_response.get("totalTickets", 0)
                logger.info(f"{GREEN}Referral claim successful!{RESET} You received {GREEN}{total_points}{RESET} points and {GREEN}{total_tickets}{RESET} tickets.")
                return total_points, total_tickets
            else:
                logger.error(f"{RED}Error executing referral claim.{RESET}")
                return 0, 0
        else:
            logger.warning(f"{YELLOW}No referral claims available at this time.{RESET}")
            return 0, 0
    else:
        logger.error(f"{RED}Request error.{RESET}")
        return 0, 0

def play_game(headers: Dict[str, str], tickets: int, proxy: str) -> int:
    """Plays the game using available tickets."""
    url_game = "https://api-tg-app.midas.app/api/game/play"
    total_points = 0
    while tickets > 0:
        for i in range(3, 0, -1):
            print(f"Starting game in {YELLOW}{i}{RESET} seconds...", end='\r')
            time.sleep(1)
        logger.info(f"{YELLOW}Starting game...{RESET}")
        game_data, _ = post_request(url_game, headers, proxy=proxy)
        if game_data:
            points_earned = game_data.get("points", 0)
            total_points += points_earned
            tickets -= 1
            logger.info(f"Earned {GREEN}{points_earned}{RESET} points, Total Points: {GREEN}{total_points}{RESET}, Remaining Tickets: {YELLOW}{tickets}{RESET}")
        else:
            logger.error(f"{RED}Error playing game.{RESET}")
            break
    return total_points

def process_init_data(init_data: str, proxy_index: int):
    """Processes the initData and performs game actions using proxy from the list."""
    if proxy_index < len(PROXY_LIST):
        current_proxy = PROXY_LIST[proxy_index]
        logger.info(f"Processing initData with proxy: {YELLOW}{current_proxy}{RESET}")
    else:
        logger.error("No more proxies available for this cycle.")
        return

    url_register = "https://api-tg-app.midas.app/api/auth/register"
    headers_register = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Mobile Safari/537.36"
    }
    payload = {"initData": init_data}
    response_text, cookies = post_request(url_register, headers_register, payload, proxy=current_proxy)

    if response_text:
        logger.info(f"Token received: {YELLOW}...{response_text[-20:]}{RESET}")
        cookies_dict = cookies.get_dict() if cookies else {}
        cookies_preview = {key: f"...{value[-20:]}" for key, value in cookies_dict.items()}
        logger.info(f"Cookies received: {YELLOW}{cookies_preview}{RESET}")
        token = response_text.strip()
        if not token:
            logger.error("Error: Token is empty or invalid.")
            return
        headers_user = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Mobile Safari/537.36",
            "Cookie": "; ".join([f"{key}={value}" for key, value in cookies_dict.items()])
        }
        try:
            get_streak_info(headers_user, current_proxy)
            check_referral_status(headers_user, current_proxy)
            tickets, points = get_user_info(headers_user, current_proxy)
            if tickets > 0:
                total_points = play_game(headers_user, tickets, current_proxy)
                logger.info(f"Total Points after playing games: {GREEN}{total_points}{RESET}")
            else:
                logger.warning("No tickets available to play games.")
        except Exception as e:
            logger.error(f"Error during subsequent actions: {e}")
    else:
        logger.error("Error: Could not get token. Registration failed.")

def get_next_reset_time():
    """Menghitung waktu berikutnya untuk reset harian pada pukul 08:00 WIB."""
    now = datetime.now(WIB)
    next_reset = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if now >= next_reset:
        next_reset += timedelta(days=1)  # Jika sudah lewat 08:00 hari ini, ke besok
    return next_reset

def countdown_to_next_reset(next_reset):
    """Menampilkan countdown hingga waktu reset berikutnya."""
    try:
        while True:
            now = datetime.now(WIB)
            time_left = next_reset - now
            if time_left.total_seconds() <= 0:
                break
            hours, remainder = divmod(int(time_left.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            countdown_str = f"Next reset in: {hours:02d}:{minutes:02d}:{seconds:02d}"
            print(f"\r{YELLOW}{countdown_str}{RESET}", end='', flush=True)
            time.sleep(1)
        print(f"\r{YELLOW}Starting next cycle...{RESET}", end='', flush=True)
    except KeyboardInterrupt:
        logger.info("Countdown interrupted by user (Ctrl+C). Exiting gracefully...")
        print(f"\n{YELLOW}Script terminated by user.{RESET}")
        exit(0)

def main():
    """Main execution with cycle running at 08:00 WIB daily and countdown."""
    # Clear terminal di awal
    os.system('cls' if os.name == 'nt' else 'clear')

    # Watermark print di awal
    watermark = f"""
    {CYAN}========================================{RESET}
    {GREEN}       Midas Bot - Daily Script   {RESET}
    {CYAN}========================================{RESET}
    {YELLOW}Developed by: Rivalz{RESET}
    {YELLOW}Version: 1.0 | Date: 2025-02-27{RESET}
    {YELLOW}Purpose: Automate daily login at 08:00 WIB{RESET}
    {CYAN}========================================{RESET}
    """
    print(watermark)

    global PROXY_LIST, PROXY_IP_INFO
    PROXY_LIST = load_proxies(PROXIES_FILE)
    init_data_list = read_init_data(AUTH_FILE)

    if not init_data_list:
        logger.error("No init data found. Exiting...")
        return
    if not PROXY_LIST:
        logger.error("No proxies found. Exiting...")
        return

    # Cek IP info untuk semua proxy di awal
    logger.info("Checking IP info for all proxies...")
    for proxy in PROXY_LIST:
        PROXY_IP_INFO[proxy] = get_ip_info(proxy)
        logger.info(f"IP Info for proxy {YELLOW}{proxy}{RESET}: {PROXY_IP_INFO[proxy]}")

    logger.info(f"Starting script with {len(init_data_list)} accounts and {len(PROXY_LIST)} proxies")
    logger.info("Cycles will run daily at 08:00 WIB")

    cycle_count = 0
    try:
        while True:
            cycle_count += 1
            logger.info(f"Starting cycle {cycle_count} at {datetime.now(WIB)}")

            proxy_index = 0
            for init_data in init_data_list:
                try:
                    process_init_data(init_data, proxy_index)
                except Exception as e:
                    logger.error(f"Error processing init_data with proxy index {proxy_index}: {str(e)}")
                time.sleep(SLEEP_BETWEEN_ACCOUNTS)
                proxy_index = (proxy_index + 1) % len(PROXY_LIST)  # Rotasi proxy

            # Hitung waktu tunggu hingga 08:00 WIB berikutnya dan tampilkan countdown
            next_reset = get_next_reset_time()
            logger.info(f"Cycle {cycle_count} completed at {datetime.now(WIB)}. Waiting until next reset at {next_reset}")
            countdown_to_next_reset(next_reset)
    except KeyboardInterrupt:
        logger.info("Script interrupted by user (Ctrl+C). Exiting gracefully...")
        print(f"\n{YELLOW}Script terminated by user.{RESET}")
        exit(0)

if __name__ == "__main__":
    main()

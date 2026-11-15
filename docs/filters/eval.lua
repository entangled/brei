Set = {}

function Set.contains(self, e)
    return self[e] ~= nil
end

function Set.new(tbl)
    result = {}
    for _, x in ipairs(tbl) do
        result[x] = 1
    end
    setmetatable(result, {__index=Set})
    return result
end

-- ANSI escape codes ----------------------------------------------------------
-- Commands may print colours and other styles with ANSI escape codes. For HTML
-- we turn these into `<span>` elements with classes `ansi-bold`, `ansi-fg-1`
-- etc., see `dark.css`. Colours outside the standard sixteen are given as an
-- inline style. For other formats, and for escape codes other than styles, we
-- remove them.

local function html_escape(s)
    return (s:gsub("[&<>]", {["&"] = "&amp;", ["<"] = "&lt;", [">"] = "&gt;"}))
end

-- Colour `n` of the 256 colour palette: one of the sixteen standard colours,
-- or a CSS colour.
local function color_256(n)
    if n < 16 then
        return n
    elseif n < 232 then
        local levels = {0, 95, 135, 175, 215, 255}
        n = n - 16
        return string.format("#%02x%02x%02x",
            levels[n // 36 + 1], levels[n // 6 % 6 + 1], levels[n % 6 + 1])
    else
        local v = 8 + 10 * (n - 232)
        return string.format("#%02x%02x%02x", v, v, v)
    end
end

local function apply_sgr(style, params)
    local codes = {}
    for n in (params .. ";"):gmatch("(%d*);") do
        codes[#codes + 1] = tonumber(n) or 0
    end
    local i = 1
    while i <= #codes do
        local c = codes[i]
        if c == 0 then
            for k in pairs(style) do style[k] = nil end
        elseif c == 1 then style.bold = true
        elseif c == 2 then style.dim = true
        elseif c == 3 then style.italic = true
        elseif c == 4 then style.underline = true
        elseif c == 22 then style.bold = nil; style.dim = nil
        elseif c == 23 then style.italic = nil
        elseif c == 24 then style.underline = nil
        elseif c >= 30 and c <= 37 then style.fg = c - 30
        elseif c == 39 then style.fg = nil
        elseif c >= 40 and c <= 47 then style.bg = c - 40
        elseif c == 49 then style.bg = nil
        elseif c >= 90 and c <= 97 then style.fg = c - 90 + 8
        elseif c >= 100 and c <= 107 then style.bg = c - 100 + 8
        elseif (c == 38 or c == 48) and codes[i + 1] == 5 then
            style[c == 38 and "fg" or "bg"] = color_256(codes[i + 2] or 0)
            i = i + 2
        elseif (c == 38 or c == 48) and codes[i + 1] == 2 then
            style[c == 38 and "fg" or "bg"] = string.format("#%02x%02x%02x",
                codes[i + 2] or 0, codes[i + 3] or 0, codes[i + 4] or 0)
            i = i + 4
        end
        i = i + 1
    end
end

local function open_span(style)
    local classes, css = {}, {}
    for _, k in ipairs({"bold", "dim", "italic", "underline"}) do
        if style[k] then classes[#classes + 1] = "ansi-" .. k end
    end
    for _, k in ipairs({"fg", "bg"}) do
        if type(style[k]) == "number" then
            classes[#classes + 1] = "ansi-" .. k .. "-" .. style[k]
        elseif style[k] then
            css[#css + 1] = (k == "fg" and "color" or "background-color") .. ": " .. style[k]
        end
    end
    if #classes == 0 and #css == 0 then
        return nil
    end
    local attrs = ""
    if #classes > 0 then attrs = attrs .. ' class="' .. table.concat(classes, " ") .. '"' end
    if #css > 0 then attrs = attrs .. ' style="' .. table.concat(css, "; ") .. '"' end
    return "<span" .. attrs .. ">"
end

-- Convert text with ANSI escape codes. With `html`, styles become spans and
-- the text is escaped; otherwise all escape codes are removed.
local function convert_ansi(text, html)
    local out, style, span_open = {}, {}, false
    local pos = 1
    while pos <= #text do
        local esc = text:find("\27", pos, true)
        local plain = text:sub(pos, (esc or #text + 1) - 1)
        out[#out + 1] = html and html_escape(plain) or plain
        if not esc then break end

        local params, final, after = text:match("^\27%[([0-9;?]*)[ -/]*([@-~])()", esc)
        if final == "m" and not params:find("?", 1, true) then
            if html then
                apply_sgr(style, params)
                if span_open then out[#out + 1] = "</span>" end
                local span = open_span(style)
                if span then out[#out + 1] = span end
                span_open = span ~= nil
            end
            pos = after
        elseif after then
            pos = after
        else
            -- Operating system commands, like hyperlinks, or a lone escape.
            pos = text:match("^\27%].-\7()", esc) or text:match("^\27%].-\27\\()", esc) or esc + 1
        end
    end
    if span_open then out[#out + 1] = "</span>" end
    return table.concat(out)
end

function CodeBlock(elem)
    classes = Set.new(elem.classes)
    if not classes:contains("eval") then
        return
    end
    if classes:contains("bash") then
        result = pandoc.system.with_temporary_directory("bash-eval", function (path)
            print("Executing: "..elem.text)
            out_file = path .. "/out"
            -- Colours, at the same width and with the same palette wherever
            -- the documentation is built.
            os.execute("env -u COLORTERM TERM=xterm FORCE_COLOR=1 COLUMNS=80 bash -c '"
                .. elem.text .. "' > " .. out_file)
            return io.open(out_file):read("a")
        end)
        result = result:gsub("\n$", "")

        local output
        if FORMAT:match("html") then
            local html = convert_ansi(result, true)
            -- A browser drops a newline directly after `<pre>`.
            if html:sub(1, 1) == "\n" then html = "\n" .. html end
            output = pandoc.RawBlock("html",
                '<div class="sourceCode"><pre class="sourceCode ansi"><code>'
                .. html .. "</code></pre></div>")
        else
            output = pandoc.CodeBlock(convert_ansi(result, false), {class="txt"})
        end
        return pandoc.Div({
            pandoc.Div({elem}, {class="doctestInput"}),
            pandoc.Div({output}, {class="doctestResult"})
        }, {class="doctest", status="SUCCESS"})
    end
end

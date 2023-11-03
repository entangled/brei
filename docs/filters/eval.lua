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

function CodeBlock(elem)
    classes = Set.new(elem.classes)
    if not classes:contains("eval") then
        return
    end
    if classes:contains("bash") then
        result = pandoc.system.with_temporary_directory("bash-eval", function (path)
            print("Executing: "..elem.text)
            out_file = path .. "/out"
            os.execute("bash -c '"..elem.text.."' > "..out_file)
            return io.open(out_file):read("a")
        end)
        return pandoc.Div({
            pandoc.Div({elem}, {class="doctestInput"}),
            pandoc.Div({pandoc.CodeBlock(result, {class="txt"})}, {class="doctestResult"})
        }, {class="doctest", status="SUCCESS"})
    end
end

function Link(elem)
	if elem.target:match("%.md$") then
		new_link = elem.target:gsub("%.md$", ".html")
		elem.target = new_link
		return elem
	end
end

import re

def preprocess(item):
    titles = item.findall('title')
    itemTitle = None
    for title in titles:
        if not itemTitle:
            itemTitle = title
        else:
            # Prioritise English or Original language titles
            if title.attrib["lang"] in ["en", "xx"]:
                item.remove(itemTitle)
                itemTitle = title
            else:
                item.remove(itemTitle)

    # Workaround for some grabbers appending garbage to subtitle element
    subtitle = item.find('sub-title')
    if subtitle is not None:
        subtitle.text = re.sub('"},"parentId.*', '', subtitle.text)

    # Remove multiple whitespace and shorten polish football titles
    titles = item.findall('title')
    for title in titles:
        title.text = re.sub("  *", " ", title.text)
        title.text = re.sub("Piłka nożna: ", "", title.text)

    return item

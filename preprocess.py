# -*- coding: utf-8 -*-
import xml.etree.ElementTree as et
import re

def preprocess(item):
    titles = item.findall('title')
    itemTitle = None
    for title in titles:
        if itemTitle == None:
            itemTitle = title
        else:
            if title.attrib["lang"] == "xx":
                item.remove(itemTitle)
                itemTitle = title
            else:
                item.remove(itemTitle)
    
    return item

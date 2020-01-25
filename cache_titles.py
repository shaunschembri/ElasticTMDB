#!/usr/bin/env python3
import argparse
import logging
from elastictmdb.movie import Movie
from elastictmdb.tvshow import Tvshow

argParser = argparse.ArgumentParser()
argParser._action_groups.pop()
optional = argParser.add_argument_group('optional arguments')
optional.add_argument("-m", "--movie", action="store_true", help="Cache Only Movie Titles")
optional.add_argument("-t", "--tvshow", action="store_true", help="Cache Only TV Titles")
optional.add_argument("-l", "--limit", type=int, nargs='?', default=1000, help="Limit cache number (Default: 1000)")
optional.add_argument("-d", "--debug", action="store_true", help="Enable debug output")
args = argParser.parse_args()

if args.debug:
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(message)s")
else:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

titleObjs = []
if args.movie:
    titleObjs.append(Movie())
if args.tvshow:
    titleObjs.append(Tvshow())
if not args.movie and not args.tvshow:
    titleObjs.append(Movie())
    titleObjs.append(Tvshow())

for titleObj in titleObjs:
    page = 1
    titlesCached = 0

    while True:
        logging.info("Getting page {} ({})".format(page, titleObj.config["title_type"]))
        titles = titleObj.discover_title(page=page)
        for title in titles:
            titleObj.cache_title(title=title, force=False, record={})
            titlesCached += 1
            if titlesCached >= args.limit:
                break
        if titlesCached >= args.limit:
            break
        page += 1
        logging.info("Found and cached {} title {}".format(titlesCached, titleObj.config["title_type"]))
    logging.info("Done caching titles {} ({})".format(titlesCached, titleObj.config["title_type"]))

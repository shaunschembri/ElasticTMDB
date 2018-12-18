# -*- coding: utf-8 -*-
import argparse
import logging
import json
import elastictmdb

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

#Initialise ElasticTMDB
ElasticTMDB = elastictmdb.ElasticTMDB()

#Parse command line arguments
argParser = argparse.ArgumentParser()
argParser._action_groups.pop()
required = argParser.add_argument_group('required arguments')
optional = argParser.add_argument_group('optional arguments')
required.add_argument("-t", "--title", type=str, help="Movie title", required=True)
optional.add_argument("-d", "--director", type=str, action='append', help="Name of director. Can be used more then once to specify more the 1 director")
optional.add_argument("-c", "--cast", action='append', type=str, help="Name of actor. Can be used more then once to specify more cast members")
optional.add_argument("-y", "--year", type=int, help="Movie release year")
optional.add_argument("-f", "--force", action="store_true", help="Force a search on TMDB before returning results")

args = argParser.parse_args()
msg = {}
msg["title"] = args.title
if args.year:
    msg["year"] = args.year
if args.director:
    msg["director"] = args.director
if args.cast:
    msg["cast"] = args.cast
if args.year:
    msg["year"] = args.year
if args.force:
    msg["force"] = args.force

print(json.dumps(ElasticTMDB.search_movie(msg), indent=1))

#!/usr/bin/env python3
import argparse
import json
import sys
import logging
from elastictmdb.movie import Movie
from elastictmdb.tvshow import Tvshow

# Parse command line arguments
argParser = argparse.ArgumentParser()
argParser._action_groups.pop()
required = argParser.add_argument_group('required arguments')
optional = argParser.add_argument_group('optional arguments')
optional.add_argument("-m", "--movie", action="store_true", help="Cache Only Movie Titles")
optional.add_argument("-t", "--tvshow", action="store_true", help="Cache Only TV Titles")
required.add_argument("-n", "--title", type=str, help="Name of title", required=True)
optional.add_argument("-d", "--director", type=str, action='append', help="Name of director. Can be used more then once to specify more the 1 director")
optional.add_argument("-a", "--actor", action='append', type=str, help="Name of actor. Can be used more then once to specify more cast members")
optional.add_argument("-y", "--year", type=int, help="Movie release year")
optional.add_argument("-s", "--minscore", type=int, help="Minimum score to accept as a valid result")
optional.add_argument("-f", "--force", action="store_true", help="Force a search on TMDB before returning results")
optional.add_argument("-j", "--json", action="store_true", help="Output result in JSON")
optional.add_argument("-v", "--verbose", action="store_true", help="Enable debug/verbose output")
args = argParser.parse_args()

if args.verbose:
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(message)s")
else:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

if args.movie and args.tvshow:
    logging.error('Specify either "-m" or "-t" argument')
elif args.movie:
    titleObj = Movie()
elif args.tvshow:
    titleObj = Tvshow()
else:
    logging.error('Specify "-m" for a movie or "-t" for a tvshow')
    sys.exit(-1)

query = {}
query["title"] = [args.title]
if args.year:
    query["year"] = args.year
if args.director:
    query["director"] = args.director
if args.actor:
    query["actor"] = args.actor
if args.year:
    query["year"] = args.year
if args.force:
    query["force"] = args.force
if args.minscore:
    titleObj.config["min_score"] = args.minscore
    titleObj.config["min_score_exact"] = args.minscore
    titleObj.config["score_increment_per_actor"] = 0

result = titleObj.search(search=query)
if result:
    if args.json:
        print(json.dumps(result, indent=3))
    else:
        print("Title : {}\n".format(result["_source"]["title"]))
        print(titleObj.render_template(record=result, template="description"))

# -*- coding: utf-8 -*-
import argparse
import logging
import elastictmdb
import json

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

# Initialise ElasticTMDB
ElasticTMDB = elastictmdb.ElasticTMDB()

# Parse command line arguments
argParser = argparse.ArgumentParser()
argParser._action_groups.pop()
required = argParser.add_argument_group('required arguments')
optional = argParser.add_argument_group('optional arguments')
required.add_argument("-t", "--title", type=str, help="Movie title", required=True)
optional.add_argument("-d", "--director", type=str, action='append', help="Name of director. Can be used more then once to specify more the 1 director")
optional.add_argument("-c", "--cast", action='append', type=str, help="Name of actor. Can be used more then once to specify more cast members")
optional.add_argument("-y", "--year", type=int, help="Movie release year")
optional.add_argument("-f", "--force", action="store_true", help="Force a search on TMDB before returning results")
optional.add_argument("-j", "--json", action="store_true", help="Output result in JSON")

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

def build_movie_description(tmdbResult):
    if tmdbResult:
        desc = []
        if 'cast' in tmdbResult["_source"]:
            desc.append("Cast: " + ", ".join(tmdbResult["_source"]["cast"][:5]))

        if 'director' in tmdbResult["_source"]:
            desc.append("Director: " + ", ".join(tmdbResult["_source"]["director"]))

        if 'rating' in tmdbResult["_source"]:
            desc.append("Rating: " + str(tmdbResult["_source"]["rating"]))

        if 'description' in tmdbResult["_source"]:
            desc.append("\n" + tmdbResult["_source"]["description"] + "\n")

        if 'year' in tmdbResult["_source"]:
            desc.append("Year: " + str(tmdbResult["_source"]["year"]))

        if 'genre' in tmdbResult["_source"]:
            desc.append("Genre: " + ", ".join(tmdbResult["_source"]["genre"]))

        if 'country' in tmdbResult["_source"]:
            desc.append("Country: " + ", ".join(tmdbResult["_source"]["country"]))

        if 'popularity' in tmdbResult["_source"]:
            desc.append("Popularity: " + str(round(tmdbResult["_source"]["popularity"], 1)))

        if '_score' in tmdbResult:
            desc.append("Score: " + str(round(tmdbResult["_score"], 1)))

        return "\n".join(desc)

result = ElasticTMDB.search_movie(msg)
if args.json:
    print(json.dumps(ElasticTMDB.search_movie(msg), indent=3))
else:
    print(build_movie_description(result))

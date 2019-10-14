#!/usr/bin/env python3
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
            desc.append("Cast: {}".format(", ".join(tmdbResult["_source"]["cast"][:5])))

        if 'director' in tmdbResult["_source"]:
            desc.append("Director: {}".format(", ".join(tmdbResult["_source"]["director"])))

        if 'rating' in tmdbResult["_source"]:
            desc.append("Rating: {}".format(tmdbResult["_source"]["rating"]))

        if 'description' in tmdbResult["_source"]:
            desc.append("\n{}\n".format(tmdbResult["_source"]["description"]))

        if 'year' in tmdbResult["_source"]:
            desc.append("Year: {}".format(tmdbResult["_source"]["year"]))

        if 'genre' in tmdbResult["_source"]:
            desc.append("Genre: {}".format(", ".join(tmdbResult["_source"]["genre"])))

        if 'language' in tmdbResult["_source"]:
            desc.append("Language: {}".format(ElasticTMDB.get_language(tmdbResult["_source"]["language"])))

        if 'country' in tmdbResult["_source"]:
            desc.append("Country: {}".format(", ".join(tmdbResult["_source"]["country"])))

        if 'popularity' in tmdbResult["_source"]:
            desc.append("Popularity: {:.1f}".format(tmdbResult["_source"]["popularity"]))

        if '_score' in tmdbResult:
            desc.append("Score: {:.1f}".format(tmdbResult["_score"]))

        return "\n".join(desc)

result = ElasticTMDB.search_movie(msg)
if args.json:
    print(json.dumps(ElasticTMDB.search_movie(msg), indent=3))
else:
    print(build_movie_description(result))

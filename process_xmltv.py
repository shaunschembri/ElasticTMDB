#!/usr/bin/env python3
import argparse
import logging
import json
import os
import io
import re
import configparser
import xml.etree.ElementTree as et
import traceback
from datetime import datetime, timedelta
import time
import elastictmdb
import preprocess

class xmltv(object):
    def __init__(self, force=False):
        # Initialise ElasticTMDB
        self.ElasticTMDB = elastictmdb.ElasticTMDB()

        # Initialise output XMLTV object
        self.output = et.Element("tv")

        # Set force flag
        self.force = force

        # Read config
        config = configparser.ConfigParser()
        config.read(os.path.join(os.path.dirname(__file__), "elastictmdb.conf"))
        self.enablePreprocessing = config.getboolean("process_xmltv", "enable_preprocess_function")
        self.mainLanguage = config.get("main", "main_language")
        self.exceptionLanguage = config.get("main", "exception_language")

        # Programme Categories as specified by the DVB EIT Standard under which movies and tvshows are listed
        self.categoryMovie = ["Movie / Drama",
                              "Detective / Thriller",
                              "Adventure / Western / War",
                              "Science fiction / Fantasy / Horror",
                              "Comedy",
                              "Soap / Melodrama / Folkloric",
                              "Romance",
                              "Serious / Classical / Religious / Historical movie / Drama",
                              "Adult movie / Drama"]

        # Load list of mapping to map catagories in XMLTV files to DVB EIT Standard list
        with open(os.path.join(os.path.dirname(__file__), "epg_category.json"), mode="r") as jsonfile:
            self.epgCategory = json.load(jsonfile, encoding="utf-8")

        # Store last channel definition position. This is used so that all channel elemnets are at the top of the file as required by the XMLTV standard
        self.channelPos = 0

    def process_file(self, filename):
        logging.info("Parsing {}".format(filename))
        xmlTree = et.parse(filename).getroot()
        logging.info("Parsing events")

        for item in xmlTree:
            try:
                if item.tag == 'channel':
                    # Remove icons
                    icons = item.findall('icon')
                    for icon in icons:
                        item.remove(icon)

                    # Remove URL
                    urls = item.findall('url')
                    for url in urls:
                        item.remove(url)

                    self.output.insert(self.channelPos, item)
                    self.channelPos += 1

                elif item.tag == 'programme':
                    if self.enablePreprocessing:
                        item = preprocess.preprocess(item)
                    self.output.append(item)

                    # Determine Category
                    isSeries = False
                    itemContentType = None
                    categories = item.findall('category')
                    for category in categories:
                        categoryName = category.text.lower()
                        # Add category if it does not exists and tries to automap movie categories
                        if categoryName not in self.epgCategory:
                            if re.search("film|movie|cinema|drama|thriller", categoryName, re.IGNORECASE):
                                logging.info("Adding category - {} and mapping it to Movie / Drama".format(categoryName))
                                self.epgCategory[categoryName] = "Movie / Drama"
                            else:
                                logging.info("Adding category - {}".format(categoryName))
                                self.epgCategory[categoryName] = None

                        if self.epgCategory[categoryName] is not None:
                            if not itemContentType:
                                itemContentType = self.epgCategory[categoryName]
                        if re.search("serie|téléfilm", categoryName, re.IGNORECASE):
                            isSeries = True

                        item.remove(category)
                    if itemContentType is not None:
                        category = et.SubElement(item, 'category', lang="en")
                        category.text = itemContentType

                    # Remove rating as we will use the ones we have obtained from TMDB
                    ratings = item.findall('rating')
                    for rating in ratings:
                        item.remove(rating)

                    # Remove rating as we will use the ones we have obtained from TMDB
                    starratings = item.findall('star-rating')
                    for starrating in starratings:
                        item.remove(starrating)

                    # Check if programme has a year and director, if both are present programme might be a movie
                    hasYear = False
                    year = item.find("date")
                    if year is not None:
                        hasYear = True

                    hasDirector = False
                    persons = item.find("credits")
                    if persons is not None:
                        for director in persons.findall("director"):
                            hasDirector = True
                            break

                    # Perform extra checks to determine if programme is actually a Movie
                    if itemContentType is not None or not isSeries:
                        if itemContentType in self.categoryMovie or (hasYear and hasDirector):
                            # Check if length is 70min (4200sec) or more to be considered a movie, else consider it a TV show
                            start = item.attrib["start"]
                            stop = item.attrib["stop"]
                            if self.get_unixtime_from_ts(stop) - self.get_unixtime_from_ts(start) >= 4200:
                                item = self.process_movie(item)

            except Exception:
                logging.error(traceback.format_exc())

        # Save epg category
        with io.open(os.path.join(os.path.dirname(__file__), "epg_category.json"), 'w', encoding="utf-8") as jsonfile:
            jsonfile.write(json.dumps(self.epgCategory, ensure_ascii=False, indent=3, sort_keys=True))

    def process_movie(self, item):
        itemTitle = item.findall("title")[0]
        msg = {}
        msg["title"] = itemTitle.text
        msg["force"] = self.force

        # Date
        year = item.find("date")
        if year is not None:
            msg["year"] = int(year.text)

        # Director and cast
        persons = item.find("credits")
        if persons is not None:
            for director in persons.findall("director"):
                if "director" not in msg:
                    msg["director"] = []
                msg["director"].append(director.text)
            for cast in persons.findall("actor"):
                if "cast" not in msg:
                    msg["cast"] = []
                msg["cast"].append(cast.text)

        tmdbResult = self.ElasticTMDB.search_movie(msg)
        if tmdbResult:
            # Remove all titles, so to create a new one with the title found
            titles = item.findall('title')
            for title in titles:
                item.remove(title)

            # Set title
            title = et.Element('title')
            # Try to decode title as unicode, if it fails use it undecoded
            try:
                title.text = tmdbResult["_source"]["title"]
            except Exception:
                title.text = tmdbResult["_source"]["title"]
            title.set("lang", tmdbResult["_source"]["language"])
            item.insert(0, title)

            # Set Subtitle
            subtitle = item.find('sub-title')
            if subtitle is None:
                subtitle = et.SubElement(item, 'sub-title')

            if tmdbResult["_source"]["genre"]:
                subtitle.text = "{} - {}".format(tmdbResult["_source"]["year"], ", ".join(tmdbResult["_source"]["genre"]))
            else:
                subtitle.text = str(tmdbResult["_source"]["year"])

            subtitle.set("lang", self.mainLanguage)

            # Set Image
            if tmdbResult["_source"]["image"]:
                icon = item.find('icon')
                if icon is None:
                    icon = et.SubElement(item, 'icon')
                icon.set("src", tmdbResult["_source"]["image"])

            # Set description
            desc = item.find('desc')
            if desc is None:
                desc = et.SubElement(item, 'desc')
            desc.text = self.build_movie_description(tmdbResult)
            if tmdbResult["_source"]["language"] == self.exceptionLanguage:
                desc.set("lang", self.exceptionLanguage)
            else:
                desc.set("lang", self.mainLanguage)

            # Set date
            if year is None:
                year = et.SubElement(item, 'year')
            year.text = str(tmdbResult["_source"]["year"])

            # Set director and cast
            if persons is not None:
                item.remove(persons)
            persons = et.SubElement(item, 'credits')
            if "director" in tmdbResult["_source"]:
                for person in tmdbResult["_source"]["director"]:
                    director = et.SubElement(persons, 'director')
                    director.text = person
            if "cast" in tmdbResult["_source"]:
                for person in tmdbResult["_source"]["cast"]:
                    cast = et.SubElement(persons, 'actor')
                    cast.text = person

            # Set rating
            if "rating" in tmdbResult["_source"]:
                rating = et.SubElement(item, 'star-rating')
                value = et.SubElement(rating, 'value')
                value.text = "{}/10".format(str(tmdbResult["_source"]["rating"]))

        return item

    def build_movie_description(self, tmdbResult):
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
                desc.append("Language: {}".format(self.ElasticTMDB.get_language(tmdbResult["_source"]["language"])))

            if 'country' in tmdbResult["_source"]:
                desc.append("Country: {}".format(", ".join(tmdbResult["_source"]["country"])))

            if 'popularity' in tmdbResult["_source"]:
                desc.append("Popularity: {:.1f}".format(tmdbResult["_source"]["popularity"]))

            if '_score' in tmdbResult:
                desc.append("Score: {:.1f}".format(tmdbResult["_score"]))

            result = "\n".join(desc)
            # Remove this character which crashes importing in enigma2 devices
            result = re.sub('', '', result)
            return result

    def get_unixtime_from_ts(self, t):
        ret = datetime.strptime(t[0:13], "%Y%m%d%H%M%S")
        if t[15] == '-':
            ret += timedelta(hours=int(t[16:18]), minutes=int(t[18:20]))
        elif t[15] == '+':
            ret -= timedelta(hours=int(t[16:18]), minutes=int(t[18:20]))
        return int(time.mktime(ret.timetuple()))

    def save_file(self, filename):
        # Saving final xmltv file
        logging.info("Saving to {}".format(filename))
        with open(os.path.join(filename), 'wb') as xmlFile:
            xmlFile.write(et.tostring(self.output, encoding="UTF-8"))

if __name__ == "__main__":
    # Parse command line arguments
    argParser = argparse.ArgumentParser()
    argParser._action_groups.pop()
    required = argParser.add_argument_group('required arguments')
    optional = argParser.add_argument_group('optional arguments')
    required.add_argument("-i", "--input", type=str, action='append', help="Input XMLTV file")
    required.add_argument("-o", "--output", type=str, help="Output XMLTV file")
    optional.add_argument("-l", "--logfile", type=str, help="Output log to file")
    optional.add_argument("-f", "--force", action="store_true", help="Force search for all movies")
    args = argParser.parse_args()

    if args.logfile:
        logging.basicConfig(level=logging.INFO, filename=args.logfile, format="%(asctime)s %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    XMLTV = xmltv(force=args.force)
    # Process input files
    for filename in args.input:
        XMLTV.process_file(filename)
    # Save file
    XMLTV.save_file(args.output)
    logging.info("Done")

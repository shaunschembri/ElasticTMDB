# -*- coding: utf-8 -*-
import argparse
import logging
import json
import os
import io
import re
import sys
import configparser
import xml.etree.ElementTree as et
from datetime import datetime, timedelta
import time
import elastictmdb
import preprocess

class xmltv(object):
    def __init__(self):
        self.logging = logging.getLogger()
        
        #Initialise ElasticTMDB
        self.ElasticTMDB = elastictmdb.ElasticTMDB()
        
        #Initialise output XMLTV object
        self.output = et.Element("tv")

        #Read config
        config = configparser.ConfigParser()
        config.read(os.path.join(os.path.dirname(__file__), "elastictmdb.conf"))
        self.enablePreprocessing = config.getboolean("process_xmltv", "enable_preprocess_function")
        self.mainLanguage = config.get("main", "main_language")
        self.exceptionLanguage = config.get("main", "exception_language")

        #Programme Categories as specified by the DVB EIT Standard under which movies and tvshows are listed
        self.categoryMovie = ["Movie / Drama",\
                              "Detective / Thriller",\
                              "Adventure / Western / War",\
                              "Science fiction / Fantasy / Horror",\
                              "Comedy",\
                              "Soap / Melodrama / Folkloric",\
                              "Romance",\
                              "Serious / Classical / Religious / Historical movie / Drama",\
                              "Adult movie / Drama"]

        #Load list of mapping to map catagories in XMLTV files to DVB EIT Standard list
        with open(os.path.join(os.path.dirname(__file__), "epg_category.json"), mode="r") as jsonfile:
            self.epgCategory = json.load(jsonfile, encoding="utf-8")

        #Store last channel defiition position. This is used so that all channel elemnets are at the top of the file as required by the XMLTV standard
        self.channelPos = 0

    def process_file(self, filename):
        self.logging.info("Parsing " + filename)
        xmlTree = et.parse(filename).getroot()
        self.logging.info("Parsing events")

        for item in xmlTree:
            #try:                
                if item.tag == 'channel':
                    #Remove icons
                    icons = item.findall('icon')
                    for icon in icons:
                        item.remove(icon)

                    #Remove URL
                    urls = item.findall('url')
                    for url in urls:
                        item.remove(url)

                    self.output.insert(self.channelPos, item)
                    self.channelPos += 1

                elif item.tag == 'programme':
                    if self.enablePreprocessing:
                        item = preprocess.preprocess(item)
                    self.output.append(item)

                    #Determine Category
                    isSeries = False
                    itemContentType = None
                    categories = item.findall('category')
                    for category in categories:
                        categoryName = category.text.lower()
                        #Add category if it does not exists and tries to automap movie categories
                        if categoryName not in self.epgCategory:
                            if re.search("film|movie|cinema|drama|thriller", categoryName, re.IGNORECASE):
                                self.logging.info("Adding category - %s and mapping it to Movie / Drama" % (categoryName))
                                self.epgCategory[categoryName] = "Movie / Drama"
                            else:
                                self.logging.info("Adding category - %s" % (categoryName))
                                self.epgCategory[categoryName] = None

                        if self.epgCategory[categoryName] != None:
                            if not itemContentType:
                                itemContentType = self.epgCategory[categoryName]
                        if re.search("serie|téléfilm", categoryName, re.IGNORECASE):
                            isSeries = True

                        item.remove(category)
                    if itemContentType != None:
                        category = et.SubElement(item, 'category', lang="en")
                        category.text = itemContentType

                    #Remove rating as we will use the ones we have obtained from TMDB
                    ratings = item.findall('rating')
                    for rating in ratings:
                        item.remove(rating)

                    #Remove rating as we will use the ones we have obtained from TMDB
                    starratings = item.findall('star-rating')
                    for starrating in starratings:
                        item.remove(starrating)

                    #Perform extra checks to determine if programme is actually a Movie
                    if itemContentType != None or not isSeries:
                        if itemContentType in self.categoryMovie:
                            if not item.findall("episode-num"):
                                #Check if length is 70min (4200sec) pr more to be considered a movie, else consider it a TV show
                                start = item.attrib["start"]
                                stop = item.attrib["stop"]
                                if self.get_unixtime_from_ts(stop) - self.get_unixtime_from_ts(start) >= 4200:
                                    item = self.process_movie(item)
            
            # except Exception as e:
            #     exc_type, exc_obj, tb = sys.exc_info()
            #     f = tb.tb_frame
            #     lineno = tb.tb_lineno
            #     filename = f.f_code.co_filename
            #     template = "Exception: {0}. in file {1} line {2}\nArguments:{3!r}\n"
            #     message = template.format(type(e).__name__, filename, lineno, e.args)
            #     logging.error(message)

        #Save epg category
        with io.open(os.path.join(os.path.dirname(__file__), "epg_category.json"), 'w', encoding="utf-8") as jsonfile:
            jsonfile.write(unicode(json.dumps(self.epgCategory, ensure_ascii=False, indent=3, sort_keys=True)))

    def process_movie(self, item):
        itemTitle = item.findall('title')[0]
        msg = {}
        msg["title"] = itemTitle.text.encode("utf-8")

        #Date
        year = item.find('date')
        if year != None:
            msg["year"] = int(year.text)

        #Comment this to always force update from TMDB (use only for testing)
        #msg["force"] = True

        #Director and cast
        persons = item.find("credits")
        if persons != None:
            for director in persons.findall("director"):
                if "director" not in msg:
                    msg["director"] = []
                msg["director"].append(director.text.encode('utf-8'))
            for cast in persons.findall("actor"):
                if "cast" not in msg:
                    msg["cast"] = []
                msg["cast"].append(cast.text.encode('utf-8'))

        tmdbResult = self.ElasticTMDB.search_movie(msg)
        if tmdbResult:
            #Remove all titles, so to create a new one with the title found
            titles = item.findall('title')
            for title in titles:
                item.remove(title)

            #Set title
            title = et.Element('title')
            title.text = tmdbResult["_source"]["title"]
            title.set("lang", tmdbResult["_source"]["language"])
            item.insert(0, title)

            #Set Subtitle
            subtitle = item.find('sub-title')
            if subtitle is None:
                subtitle = et.SubElement(item, 'sub-title')

            if tmdbResult["_source"]["genre"]:
                subtitle.text = str(tmdbResult["_source"]["year"]).encode("UTF-8") + " - " + ", ".join(tmdbResult["_source"]["genre"]).encode("UTF-8")
            else:
                subtitle.text = str(tmdbResult["_source"]["year"]).encode("UTF-8")

            subtitle.set("lang", self.mainLanguage)

            #Set Image
            if tmdbResult["_source"]["image"]:
                icon = item.find('icon')
                if icon is None:
                    icon = et.SubElement(item, 'icon')
                icon.set("src", tmdbResult["_source"]["image"])

            #Set description
            desc = item.find('desc')
            if desc is None:
                desc = et.SubElement(item, 'desc')
            desc.text = self.build_movie_description(tmdbResult)
            if tmdbResult["_source"]["language"] == self.exceptionLanguage:
                desc.set("lang", self.exceptionLanguage)
            else:
                desc.set("lang", self.mainLanguage)

            #Set date
            if year is None:
                year = et.SubElement(item, 'year')
            year.text = str(tmdbResult["_source"]["year"])

            #Set director and cast
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

            #Set rating
            if "rating" in tmdbResult["_source"]:
                rating = et.SubElement(item, 'star-rating')
                value = et.SubElement(rating, 'value')
                value.text = str(tmdbResult["_source"]["rating"]) + "/10"
        
        return item

    def build_movie_description(self, tmdbResult):
        if tmdbResult != None:
            desc = []
            if 'cast' in tmdbResult["_source"]:
                desc.append("Cast: " + ", ".join(tmdbResult["_source"]["cast"][:5]).encode("UTF-8"))

            if 'director' in tmdbResult["_source"]:
                desc.append("Director: " + ", ".join(tmdbResult["_source"]["director"]).encode("UTF-8"))
            
            if 'rating' in tmdbResult["_source"]:
                desc.append("Rating: " + str(tmdbResult["_source"]["rating"]).encode("UTF-8"))
            
            if 'description' in tmdbResult["_source"]:
                desc.append("\n" + tmdbResult["_source"]["description"].encode("UTF-8") +"\n")

            if 'year' in tmdbResult["_source"]:
                desc.append("Year: " + str(tmdbResult["_source"]["year"]).encode("UTF-8"))
            
            if 'genre' in tmdbResult["_source"]:
                desc.append("Genre: " + ", ".join(tmdbResult["_source"]["genre"]).encode("UTF-8"))
            
            if 'language' in tmdbResult["_source"]:
                desc.append("Language: " + self.ElasticTMDB.get_language(tmdbResult["_source"]["language"]).encode("UTF-8"))
            
            if 'country' in tmdbResult["_source"]:
                desc.append("Country: " + ", ".join(tmdbResult["_source"]["country"]).encode("UTF-8"))
            
            if 'popularity' in tmdbResult["_source"]:
                desc.append("Popularity: " + str(round(tmdbResult["_source"]["popularity"], 1)).encode("UTF-8"))

            if '_score' in tmdbResult:
                desc.append("Score: " + str(round(tmdbResult["_score"], 1)).encode("UTF-8"))
            
            return "\n".join(desc)

    def get_unixtime_from_ts(self, t):
        ret = datetime.strptime(t[0:13], "%Y%m%d%H%M%S")
        if t[15] == '-':
            ret += timedelta(hours=int(t[16:18]), minutes=int(t[18:20]))
        elif t[15] == '+':
            ret -= timedelta(hours=int(t[16:18]), minutes=int(t[18:20]))
        return int(time.mktime(ret.timetuple()))

    def save_file(self, filename):
        #Saving final xmltv file
        self.logging.info("Saving to " + filename)
        with open(os.path.join(filename), 'wb') as xmlFile:
            xmlFile.write(et.tostring(self.output, encoding="UTF-8"))

if __name__ == "__main__":
    #Parse command line arguments
    argParser = argparse.ArgumentParser()
    argParser._action_groups.pop()
    required = argParser.add_argument_group('required arguments')
    optional = argParser.add_argument_group('optional arguments')
    required.add_argument("-i", "--input", type=str, action='append', help="Input XMLTV file")
    required.add_argument("-o", "--output", type=str, help="Output XMLTV file")
    optional.add_argument("-l", "--logfile", type=str, help="Output log to file")
    args = argParser.parse_args()

    if args.logfile:
        logging.basicConfig(level=logging.INFO, filename=args.logfile, format="%(asctime)s %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    XMLTV = xmltv()
    #Process input files
    for filename in args.input:
        XMLTV.process_file(filename)
    #Save file
    XMLTV.save_file(args.output)
    logging.info("Done")

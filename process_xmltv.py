#!/usr/bin/env python3
import argparse
import logging
import re
from lxml import etree
from elastictmdb.movie import Movie
from elastictmdb.tvshow import Tvshow
import collections
import datetime
import traceback

class epg(object):
    def __init__(self, force=False):
        # Initialise ElasticTMDB Objects
        self.movie = Movie()
        self.tvshow = Tvshow()

        self.force = force

        self.outputXmltv = xmltv()

    def process_file(self, filename):
        inputXmltv = xmltv()
        inputXmltv.load_xmltv(filename=filename)

        # Add channels to output file
        self.outputXmltv.channels += inputXmltv.channels

        # Parse programmes
        for programmeElement in inputXmltv.programmes:
            try:
                programme = inputXmltv.parse_element(element=programmeElement)
                programmeType = self.get_programme_type(programme=programme)
                if programmeType == "movie":
                    programme = self.process_movie(programme=programme)
                elif programmeType == "tvshow":
                    programme = self.process_tvshow(programme=programme)
                self.outputXmltv.build_programme_element(record=programme)
            except Exception:
                logging.error(traceback.format_exc())

    def get_programme_type(self, programme):
        # Ignore the catagories
        for category in programme.get("category", []):
            regex = re.search("sport|news", category["_text"], flags=re.IGNORECASE)
            if regex:
                return None

        # Loop through categories to detect TV Shows
        for category in programme.get("category", []):
            regex = re.search("tvshow|episode|telefilm|serial|series", category["_text"], flags=re.IGNORECASE)
            if regex:
                return "tvshow"

        # Loop again through categories to detect movies
        for category in programme.get("category", []):
            regex = re.search("movie|cinema|kino|featurefilm|cine", category["_text"], flags=re.IGNORECASE)
            if regex:
                return "movie"
            regex = re.search("documentary", category["_text"], flags=re.IGNORECASE)
            if regex:
                return self.get_programme_type_by_duration(start=programme["_attrib"]["start"], stop=programme["_attrib"]["stop"])

        # If episode-num tag present then consider it a tvshow
        if "episode-num" in programme:
            return "tvshow"

        # If credits tag is present then use the duration to determine if its a tvshow or movie
        if "credits" in programme:
            return self.get_programme_type_by_duration(start=programme["_attrib"]["start"], stop=programme["_attrib"]["stop"])

    def get_programme_type_by_duration(self, start, stop):
        if self.get_unixtime_from_ts(stop) - self.get_unixtime_from_ts(start) >= 4200:
            return "movie"
        else:
            return "tvshow"

    def save_file(self, filename):
        self.outputXmltv.save_xmltv(filename=filename)

    def process_movie(self, programme):
        request = self.build_query(programme=programme)
        if "date" in programme:
            request["year"] = programme["date"][0]["_text"][:4]

        response = self.movie.search(search=request)
        if response:
            programme["desc"] = [self.outputXmltv.add_text_element(text=self.movie.render_template(record=response, template="description"), lang="en")]
            programme["sub-title"] = [self.outputXmltv.add_text_element(text=self.movie.render_template(record=response, template="subtitle"), lang="en")]
            programme = self.update_programme(programme=programme, response=response)

        return programme

    def process_tvshow(self, programme):
        request = self.build_query(programme=programme)
        if "episode-num" in programme:
            for episodeNum in programme["episode-num"]:
                regex = re.search(r"^S([0-9]+)", episodeNum["_text"], flags=re.IGNORECASE)
                if regex:
                    request["season"] = int(regex.group(1))
                regex = re.search(r"E([0-9]+)", episodeNum["_text"], flags=re.IGNORECASE)
                if regex:
                    request["episode"] = int(regex.group(1))
            if "season" in request and "episode" in request:
                episodeNum = "S{:02d}E{:02d}".format(request["season"], request["episode"])
                programme["episode-num"] = [self.outputXmltv.add_episode_num_element(episodeNum=episodeNum)]

        if "sub-title" in programme:
            request["subtitle"] = []
            for subtitle in programme["sub-title"]:
                request["subtitle"].append(subtitle["_text"])

        if "date" in programme:
            request["episode_year"] = []
            for episodeYear in programme["date"]:
                request["episode_year"].append(episodeYear["_text"][:4])

        response = self.tvshow.search(search=request)
        if response:
            programme["desc"] = [self.outputXmltv.add_text_element(text=self.tvshow.render_template(record=response, template="description"), lang="en")]
            programme["sub-title"] = [self.outputXmltv.add_text_element(text=self.tvshow.render_template(record=response, template="subtitle"), lang="en")]

            # Add episode number
            if "season" in response and "episode" in response:
                episodeNum = "S{:02d}E{:02d}".format(response["season"], response["episode"])
                programme["episode-num"] = [self.outputXmltv.add_episode_num_element(episodeNum=episodeNum)]

            programme = self.update_programme(programme=programme, response=response)

        return programme

    def build_query(self, programme):
        # Build query for ElasticTMDB
        request = {}
        request["force"] = self.force
        # Add titles
        if "title" in programme:
            request["title"] = []
            for title in programme["title"]:
                request["title"].append(title["_text"])
        # Add Country
        if "country" in programme:
            request["country"] = []
            for country in programme["country"]:
                request["country"].append(country["_text"])
        # Add Credits
        if "credits" in programme:
            for credit in programme["credits"]:
                for creditName, creditValue in credit.items():
                    if creditName == "director":
                        request["director"] = []
                        for director in creditValue:
                            request["director"].append(director["_text"])
                    elif creditName == "actor" or creditName == "presenter":
                        request["actor"] = []
                        for actor in creditValue:
                            request["actor"].append(actor["_text"])
                    else:
                        if "other" not in request:
                            request["other"] = []
                        for person in creditValue:
                            request["other"].append(person["_text"])

        return request

    def update_programme(self, programme, response):
        # Replace Title
        programme["title"] = [self.outputXmltv.add_text_element(text=response["_source"]["title"], lang="en")]

        # Replace Image
        if "image" in response["_source"]:
            programme["icon"] = [self.outputXmltv.add_icon_element(url=response["_source"]["image"])]

        # Replace Credits
        programmeCredits = {}
        if "director" in response["_source"]["credits"]:
            programmeCredits["director"] = []
            for director in response["_source"]["credits"]["director"]:
                programmeCredits["director"].append(self.outputXmltv.add_text_element(text=director, lang=None))

        if "actor" in response["_source"]["credits"]:
            programmeCredits["actor"] = []
            for actor in response["_source"]["credits"]["actor"]:
                programmeCredits["actor"].append(self.outputXmltv.add_text_element(text=actor, lang=None))

        if programmeCredits:
            programme["credits"] = [programmeCredits]

        # Replace year
        programme["date"] = [self.outputXmltv.add_text_element(text=response["_source"]["year"])]

        # Replace country
        if response["_source"]["country"]:
            programme["country"] = []
            for country in response["_source"]["country"]:
                programme["country"].append(self.outputXmltv.add_text_element(text=country, lang="en"))

        # Replace categories
        programme["category"] = []
        for genre in response["_source"]["genre"]:
            programme["category"].append(self.outputXmltv.add_text_element(text=genre, lang="en"))

        # Replace rating
        if "rating" in response["_source"]:
            programme["star-rating"] = self.outputXmltv.add_element_value_subelement(text="{}/10".format(response["_source"]["rating"]["tmdb"]["average"]))

        return programme

    def get_unixtime_from_ts(self, timestamp):
        parsedTs = datetime.datetime.strptime(timestamp[0:13], "%Y%m%d%H%M%S")
        if timestamp[15] == '-':
            parsedTs += datetime.timedelta(hours=int(timestamp[16:18]), minutes=int(timestamp[18:20]))
        elif timestamp[15] == '+':
            parsedTs -= datetime.timedelta(hours=int(timestamp[16:18]), minutes=int(timestamp[18:20]))
        return parsedTs.timestamp()

class xmltv(object):
    def __init__(self):
        self.channels = []
        self.programmes = []

    def load_xmltv(self, filename):
        logging.info("Parsing {}".format(filename))
        parser = etree.XMLParser(remove_blank_text=True)
        xmltvFile = etree.parse(filename, parser).getroot()

        # Load channels
        channels = xmltvFile.findall("channel")
        logging.info("Found {} channels".format(len(channels)))
        for channel in channels:
            self.channels.append(channel)

        # Load programmes
        programmes = xmltvFile.findall("programme")
        logging.info("Found {} programmes".format(len(programmes)))
        for programme in programmes:
            self.programmes.append(programme)

    def save_xmltv(self, filename):
        tvElement = etree.Element("tv")

        # Save channels
        for channel in self.channels:
            tvElement.append(channel)

        # Save programme
        for programme in self.programmes:
            tvElement.append(programme)

        # Save XML file
        with open(filename, "wb") as xmlFileObj:
            xmlFileObj.write(etree.tostring(tvElement, pretty_print=True, encoding="utf-8"))

    def parse_element(self, element):
        record = collections.OrderedDict()
        # Get element attributes, add them to a list to preserve order
        if element.attrib:
            record["_attrib"] = collections.OrderedDict()
            for attrib in element.attrib.items():
                record["_attrib"][attrib[0]] = attrib[1]
        # Get element text
        if element.text:
            record["_text"] = element.text
        # Parse subelements
        if len(element) > 0:
            for subElement in element.getchildren():
                if subElement.tag not in record:
                    record[subElement.tag] = []
                record[subElement.tag].append(self.parse_element(element=subElement))
        return record

    def build_programme_element(self, record):
        element = self.build_element(record=record, elementName="programme")
        self.programmes.append(element)

    def build_element(self, record, elementName):
        element = etree.Element(elementName)
        #  Insert attributes
        if "_attrib" in record:
            for attribName, attribValue in record["_attrib"].items():
                element.set(attribName, attribValue)
        # Add text to element
        if "_text" in record:
            element.text = record["_text"]
        # Add children
        for childName, childValue in record.items():
            if childName[0] == "_":
                continue
            for childValue in record[childName]:
                subElement = self.build_element(record=childValue, elementName=childName)
                element.append(subElement)
        return element

    def add_text_element(self, text, lang=None):
        record = {}
        record["_text"] = str(text)
        if lang:
            record["_attrib"] = {"lang": lang}
        return record

    def add_element_value_subelement(self, text):
        record = []
        record.append({"value": []})
        record[0]["value"].append(self.add_text_element(text=text, lang=None))
        return record

    def add_episode_num_element(self, episodeNum):
        record = {}
        record["_text"] = episodeNum
        record["_attrib"] = {"system": "onscreen"}
        return record

    def add_icon_element(self, url):
        record = {"_attrib": {}}
        record["_attrib"]["src"] = url
        return record

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
    optional.add_argument("-d", "--debug", action="store_true", help="Enable debug")
    args = argParser.parse_args()

    if args.debug:
        logLevel = logging.DEBUG
    else:
        logLevel = logging.INFO

    if args.logfile:
        logging.basicConfig(level=logLevel, filename=args.logfile, format="%(asctime)s %(message)s")
    else:
        logging.basicConfig(level=logLevel, format="%(asctime)s %(message)s")

    epg = epg(force=args.force)
    # Process input files
    for filename in args.input:
        epg.process_file(filename)
    # Save file
    epg.save_file(args.output)
    logging.info("Done")

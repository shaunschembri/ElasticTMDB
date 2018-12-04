# -*- coding: utf-8 -*-
import json
import datetime
import logging
import requests
import ConfigParser
import argparse
import elasticsearch
import sys
import os
import re

class ElasticTMDB(object):
    def __init__(self, logging):
        #Logging
        self.logging = logging

        config = ConfigParser.ConfigParser()
        config.read(os.path.join(os.path.dirname(__file__), "elastictmdb.ini"))

        self.request = {}
        self.headers = {}
        self.headers["content-type"] = "application/json;charset=utf-8"
        self.headers["Accept-Encoding"] = "gzip, deflate, br"

        #Default request
        self.defaultRequest = {}
        self.defaultRequest["api_key"] = config.get("tmdb", "api_key")
        self.request = self.defaultRequest

        #ElasticSearch
        elasticAuth = (config.get("elasticsearch", "username"), config.get("elasticsearch", "password"))
        self.es = elasticsearch.Elasticsearch([config.get("elasticsearch", "host")], \
                                                port=config.getint("elasticsearch", "port"),\
                                                http_auth=elasticAuth)

        #Load languages
        self.iso639 = self.load_iso639_languages()

        self.MAIN_LANGUAGE = config.get("main", "main_language")
        self.IMAGE_BASE_URL = self.get_backgrounds_baseurl()
        if self.IMAGE_BASE_URL:
            self.IMAGE_BASE_URL += config.get("tmdb", "image_type")
        else:
            #Something failed with first request of TMDB, quiting
            quit()

        #Misc parameters
        self.EXCEPTION_LANGUAGE = config.get("main", "exception_language")
        self.LANGUAGES = config.get("main", "languages").split(",")
        self.COUNTRIES = config.get("main", "countries").split(",")
        self.YEAR_DIFF = config.getint("main", "year_diff")
        self.IMAGE_ASPECT_RATIO = config.getfloat("main", "image_aspect_ratio")
        self.MIN_SCORE_VALID = config.getint("main", "min_score_valid")
        self.MIN_SCORE_NO_SEARCH = config.getint("main", "min_score_no_search")

        #Elasticsearch document version control
        self.LATEST_VERSION = 2
        self.MIN_VERSION_FOR_DIFF_UPDATE = 2

        if not config.getboolean("main", "extra_logging"):
            logging.getLogger("elasticsearch").setLevel(logging.WARNING)
            logging.getLogger("urllib3").setLevel(logging.WARNING)
            logging.getLogger("requests").setLevel(logging.WARNING)

        #Check for indices in elastic search. IF none found create them.
        self.check_elastic_indices()

    def check_elastic_indices(self):
        if not self.es.indices.exists(index="tmdb"):
            response = self.es.indices.create(index='tmdb')
            if response["acknowledged"]:
                self.logging.info("Created tmdb index")

        if not self.es.indices.exists(index="tmdb_search"):
            body = {}
            body["mappings"] = {}
            body["mappings"]["search"] = {}
            body["mappings"]["search"]["properties"] = {}
            body["mappings"]["search"]["properties"]["movie_title"] = {}
            body["mappings"]["search"]["properties"]["movie_title"]["type"] = "keyword"
            body["mappings"]["search"]["properties"]["movie_title"]["index"] = True
            body["mappings"]["search"]["properties"]["director_name"] = {}
            body["mappings"]["search"]["properties"]["director_name"]["type"] = "keyword"
            body["mappings"]["search"]["properties"]["director_name"]["index"] = True
            body["mappings"]["search"]["properties"]["year"] = {}
            body["mappings"]["search"]["properties"]["year"]["type"] = "integer"
            body["mappings"]["search"]["properties"]["year"]["index"] = True
            response = self.es.indices.create(index='tmdb_search', body=body)
            if response["acknowledged"]:
                self.logging.info("Created tmdb_search index")

    def send_request_get(self, endPoint=None):
        if "language" not in self.request:
            self.request["language"] = self.MAIN_LANGUAGE
        if endPoint != None:
            response = requests.get("https://api.themoviedb.org/3/" + endPoint, params=self.request)
            if response:
                if response.status_code < 400:
                    self.request = self.defaultRequest # Reset request
                    return json.loads(response.content)
                else:
                    self.logging.error("Error Code " + str(response.status_code))
                    self.logging.error(response.content)
                    return None
            else:
                self.logging.error("Error Code " + str(response.status_code))
                self.logging.error(response.content)
                return None

    def get_backgrounds_baseurl(self):
        response = self.send_request_get("configuration")
        if response:
            return response["images"]["base_url"]

    def search_movie(self, msg=None):
        if msg != None:
            self.msg = msg
        if "force" not in self.msg:
            self.msg["force"] = False

        #Lookup movie in elastic
        result = self.query_for_movie()
        #if score is less then MIN_SCORE_NO_SEARCH perform a search
        if result[1] < self.MIN_SCORE_NO_SEARCH:
            #Search by director/year if both are avaliable else search by title
            searchByDirector = False
            if "director" in self.msg and "year" in self.msg:
                searchByDirector = True
                self.search_movie_by_director()
            else:
                self.search_movie_tmdb_by_name()

            #Lookup movie in elastic again
            result = self.query_for_movie()
            if result[1] < self.MIN_SCORE_NO_SEARCH:
                #Perform query using non prefered method if required
                if searchByDirector:
                    self.search_movie_tmdb_by_name()
                    result = self.query_for_movie()
        else:
            self.logging.debug("Found " + result[0]["_source"]["title"] + " without quering TMDB - Score " + str(result[1]))
        
        if result[1] < self.MIN_SCORE_NO_SEARCH and "year" in self.msg:
            result = self.query_for_movie(yearDiff=1)
            if result[1] < self.MIN_SCORE_NO_SEARCH:
                result = self.query_for_movie(yearDiff=2)

        if result[0] != None:
            #If version of movie is not the latest force an update
            if result[0]["_source"]["version"] < self.LATEST_VERSION or self.msg["force"]:
                movie = self.send_request_get("movie/" + str(result[0]["_id"]))
                if "id" in movie:
                    self.cache_movie(movie)
                    #Fetch again updated result from DB and save score from search done before
                    score = result[0]["_score"]
                    result = self.es.get(index='tmdb', doc_type='movie', id=result[0]["_id"], ignore=404)
                    result["_score"] = score
                    result["_source"]["image"] = self.IMAGE_BASE_URL + result["_source"]["image"]
                    return result
                else:
                    self.logging.info("Deleting " + result[0]["_source"]["title"] + " as its not found on TMDB")
                    self.es.delete(index='tmdb', doc_type='movie', id=result[0]["_id"])
                    return result[0]
            else:
                result[0]["_source"]["image"] = self.IMAGE_BASE_URL + result[0]["_source"]["image"]
                return result[0]
        else:
            return None

    def query_for_movie(self, msg=None, yearDiff=0):
        if msg != None:
            self.msg = msg
        
        query = {}
        query["query"] = {}
        query["from"] = 0
        query["size"] = 1
        query["query"]["bool"] = {}
        query["query"]["bool"]["must"] = []
        query["query"]["bool"]["should"] = []

        query["query"]["bool"]["should"].append({"multi_match": {"query":  self.msg["title"], "fields": ["title", "alias"]}})
        
        if "director" in self.msg:
            for director in self.msg["director"]:
                query["query"]["bool"]["should"].append({"match": {"director":  director}})
        
        if "cast" in self.msg:
            for cast in self.msg["cast"]:
                query["query"]["bool"]["should"].append({"match": {"cast":  cast}})
        
        if "year" in self.msg:
            year = {}
            year["bool"] = {}
            year["bool"]["should"] = []
            year["bool"]["should"].append({"range": {"year":  {"gte": self.msg["year"] - yearDiff, "lte": self.msg["year"] + yearDiff}}})
            year["bool"]["should"].append({"match": {"year_other": self.msg["year"]}})
            query["query"]["bool"]["must"].append(year)

        #print json.dumps(query, indent=3)

        self.es.indices.refresh(index='tmdb')
        result = self.es.search(index="tmdb", doc_type='movie', body=query)
        if result["hits"]["total"] > 0:
            if result["hits"]["hits"][0]["_score"] >= self.MIN_SCORE_VALID:
                return result["hits"]["hits"][0], result["hits"]["hits"][0]["_score"]
            else:
                return None, 0
        else:
            return None, 0

    def get_movie_from_tmdb(self, tmdbId=None):
        return self.send_request_get("movie/" + str(tmdbId))

    def search_movie_by_director(self, msg=None):
        if msg != None:
            self.msg = msg

        #Check if person and year has already been made on TMDB
        query = {}
        query["query"] = {}
        query["query"]["bool"] = {}
        query["query"]["bool"]["must"] = []
        query["query"]["bool"]["must"].append({"term": {"director_name":  self.msg["director"][0]}})
        query["query"]["bool"]["must"].append({"term": {"year":  self.msg["year"]}})
        self.es.indices.refresh(index='tmdb_search')
        result = self.es.search(index="tmdb_search", doc_type='search', body=query)

        if result["hits"]["total"] == 0:
            #Query TMDB for person
            self.request["include_adult"] = "false"
            self.request["page"] = 1
            self.request["query"] = self.msg["director"][0]

            response = self.send_request_get("search/person")
            if "total_results" in response:
                if response["total_results"] > 0:
                    for person in response["results"][:1]:
                        #Search for filmography of director
                        self.logging.info("Getting filmography for " + person["name"] + " ("+ str(self.msg["year"]) +")")
                        credits = self.send_request_get("person/" + str(person["id"]) + "/credits")
                        #Find movies directed during years of movie being searched
                        if "crew" in credits:
                            for credit in credits["crew"]:
                                if credit["job"] == 'Director':
                                    if "release_date" in credit:
                                        if credit["release_date"] != '' and credit["release_date"] != None:
                                            year = int(credit["release_date"][:4])
                                            if abs(self.msg["year"] - year) <= self.YEAR_DIFF:
                                                movie = self.send_request_get("movie/" + str(credit["id"]))
                                                if "id" in movie:
                                                    self.cache_movie(movie)
                                                #print json.dumps(movie, indent=3)

                #Save that director name and year to avoid doing the same search again
                body = {}
                body["director_name"] = self.msg["director"][0]
                body["year"] = self.msg["year"]
                self.es.index(index='tmdb_search', doc_type='search', body=body)

            else:
                self.logging.debug("Already searched for " + self.msg["director"][0] + " filmography for year " + str(self.msg["year"]))

    def search_movie_tmdb_by_name(self, msg=None):
        if msg != None:
            self.msg = msg

        #Check if search has already been made on TMDB
        query = {}
        query["query"] = {}
        query["query"]["term"] = {}
        query["query"]["term"]["movie_title"] = self.msg["title"]
        self.es.indices.refresh(index='tmdb_search')
        result = self.es.search(index="tmdb_search", doc_type='search', body=query)
        #print json.dumps(result, indent=3)
        
        if result["hits"]["total"] == 0:
            self.request["include_adult"] = "false"
            self.request["page"] = 1
            self.request["query"] = self.msg["title"]

            self.logging.info("Searching for " + self.msg["title"])
            response = self.send_request_get("search/movie")
            #print json.dumps(response, indent=3)
            if "total_results" in response:
                if response["total_results"] > 0:
                    for index, movie in enumerate(response["results"]):
                        #If year is avaliable match only movies around the year provided else cache top 3 movies returned
                        if "year" in self.msg:
                            if movie["release_date"] != '' and movie["release_date"] != None:
                                year = int(movie["release_date"][:4])
                                if abs(self.msg["year"] - year) <= self.YEAR_DIFF:
                                    if "id" in movie:
                                        self.cache_movie(movie)
                        else:
                            if index < 3:
                                self.cache_movie(movie)

            #Save that movie title to avoid doing the same search again
            body = {}
            body["movie_title"] = self.msg["title"]
            self.es.index(index='tmdb_search', doc_type='search', body=body)

        else:
            self.logging.debug("Already searched for movie " + self.msg["title"])

    def cache_movie(self, movie=None):
        #Search elastic to get current version stored
        record = self.es.get(index='tmdb', doc_type='movie', id=movie["id"], ignore=404)

        #print json.dumps(record, indent=3)
        if record["found"] == True:
            record = record["_source"]
            if record["version"] < self.MIN_VERSION_FOR_DIFF_UPDATE or self.msg["force"]:
                #Create a new record to overwrite record in database
                record = {}
                record["version"] = 0
        else:
            #Create new record
            record = {}
            record["version"] = 0

        #Always update rating if more then 10 votes and popularity
        if movie["vote_count"] > 10:
            record["rating"] = movie["vote_average"]
        record["popularity"] = movie["popularity"]

        #Check if record is at current version
        if record["version"] < 1:
            #Get original language
            if "original_language" in movie:
                record["language"] = movie["original_language"]
            else:
                record["language"] = "Unknown"

            #if original language is self.LANGUAGES then use orginal title else stick with english version
            record["alias"] = []
            if record["language"] in self.LANGUAGES:
                record["title"] = movie["original_title"]
                record["alias"].append(movie["title"])
            else:
                record["title"] = movie["title"]
                record["alias"].append(movie["original_title"])

            #Release year
            record["year"] = None
            record["year_other"] = []
            if movie["release_date"] != "":
                record["year"] = int(movie["release_date"][:4])

            self.logging.info("Getting details for " + record["title"] + " (" + str(record["year"]) + ")")

            #Get cast and director
            cast = self.send_request_get("movie/" + str(movie["id"]) + "/credits")
            #print json.dumps(cast, indent=3)
            for person in cast["cast"]:
                if person["order"] < 10:
                    if "cast" not in record:
                        record["cast"] = []
                    record["cast"].append(person["name"])
            for person in cast["crew"]:
                if person["job"] == 'Director':
                    if "director" not in record:
                        record["director"] = []
                    record["director"].append(person["name"])

            #Get titles in different languages
            for language in self.LANGUAGES:
                self.request["language"] = language
                alias = self.send_request_get("movie/" + str(movie["id"]))

                if language == "en":
                    #Get production country
                    record["country"] = []
                    for country in alias["production_countries"]:
                        name = country["name"]
                        name = name.replace("United States of America", "USA")
                        name = name.replace("United Kingdom", "UK")
                        record["country"].append(name)

                    #Get genre
                    record["genre"] = []
                    for genre in alias["genres"]:
                        record["genre"].append(genre["name"])

                    if movie["original_language"] != self.EXCEPTION_LANGUAGE:
                        #Use English description for everything but Italian movies
                        record["description"] = alias["overview"]

                #Keep original title and replace description with italian description if movie is in Italian
                if movie["original_language"] == self.EXCEPTION_LANGUAGE and language == self.EXCEPTION_LANGUAGE:
                    record["alias"].append(record["title"])
                    record["title"] = alias["title"]
                    if alias["title"] in record["alias"]:
                        record["alias"].remove(alias["title"])
                    record["description"] = alias["overview"]

                #Add Aliases to movie
                if self.check_for_dup(alias["title"], record["alias"], record["title"]):
                    record["alias"].append(alias["title"])
            
            #Get alternative titles
            altTitles = self.send_request_get("movie/" + str(movie["id"]) + "/alternative_titles")
            #print json.dumps(altTitles, indent=3)
            for title in altTitles["titles"]:
                if title["iso_3166_1"] in self.COUNTRIES:
                    if self.check_for_dup(title["title"], record["alias"], record["title"]):
                        record["alias"].append(title["title"])

            #Get other release dates
            record["year_other"] = []
            releaseDates = self.send_request_get("movie/" + str(movie["id"]) + "/release_dates")
            for countryDate in releaseDates["results"]:
                if countryDate["iso_3166_1"] in self.COUNTRIES:
                    for releaseDate in countryDate["release_dates"]:
                        if releaseDate["release_date"] != "":
                            year = int(releaseDate["release_date"][:4])
                            if abs(year-record["year"]) > 2:
                                if year not in record["year_other"]:
                                    record["year_other"].append(year)

            #Get images
            record["image"] = ""
            if record["language"] in self.LANGUAGES:
                self.request["language"] = record["language"]
            else:
                self.request["language"] = "en"

            images = self.send_request_get("movie/" + str(movie["id"]) + "/images")
            imageAspectRatio = 0
            for image in images["posters"] + images["backdrops"]:
                if abs(image["aspect_ratio"] - self.IMAGE_ASPECT_RATIO) < abs(imageAspectRatio - self.IMAGE_ASPECT_RATIO):
                    record["image"] = image["file_path"]
                    imageAspectRatio = image["aspect_ratio"]
            if record["image"] != "":
                self.logging.debug("Storing image with AR " + str(round(imageAspectRatio, 2)))

        else:
            self.logging.debug("No update required for " + movie["title"])
        
        record["version"] = self.LATEST_VERSION
        #record["last_updated"] = datetime.datetime.now().isoformat()
        self.es.index(index='tmdb', doc_type='movie', id=movie["id"], body=record)

    def check_for_dup(self, title, alias, orgTitle):
        if not alias:
            for altTitle in alias:
                if re.search("^" + title + "$", altTitle, flags=re.IGNORECASE):
                    return False
        if re.search("^" + title + "$", orgTitle, flags=re.IGNORECASE):
            return False
        return True

    def load_iso639_languages(self):
        jsonFile = open(os.path.join(os.path.dirname(__file__), "iso639.json"), "r")
        jsonObject = json.loads(jsonFile.read())
        jsonFile.close()
        return jsonObject

    def get_language(self, code=None):
        if code in self.iso639:
            return self.iso639[code]
        else:
            return "Unknown"

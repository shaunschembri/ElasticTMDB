import json
import logging
import requests
import configparser
import elasticsearch
import datetime
import os
import re

class ElasticTMDB(object):
    def __init__(self):
        config = configparser.ConfigParser()
        config.read(os.path.join(os.path.dirname(__file__), "elastictmdb.conf"))

        self.request = {}
        self.headers = {}
        self.headers["content-type"] = "application/json;charset=utf-8"
        self.headers["Accept-Encoding"] = "gzip, deflate, br"

        # Default request
        self.defaultRequest = {}
        self.defaultRequest["api_key"] = config.get("tmdb", "api_key")
        self.request = self.defaultRequest

        # ElasticSearch
        elasticAuth = (config.get("elasticsearch", "username"), config.get("elasticsearch", "password"))
        self.es = elasticsearch.Elasticsearch([config.get("elasticsearch", "host")],
                                                port=config.getint("elasticsearch", "port"),
                                                scheme=config.get("elasticsearch", "scheme"),
                                                http_auth=elasticAuth)

        # Load languages
        self.iso639 = self.load_iso639_languages()

        self.MAIN_LANGUAGE = config.get("main", "main_language")
        self.IMAGE_BASE_URL = self.get_backgrounds_baseurl()
        if self.IMAGE_BASE_URL:
            self.IMAGE_BASE_URL += config.get("tmdb", "image_type")

        # Misc parameters
        self.EXCEPTION_LANGUAGE = config.get("main", "exception_language")
        self.LANGUAGES = config.get("main", "languages").split(",")
        self.COUNTRIES = config.get("main", "countries").split(",")
        self.YEAR_DIFF = config.getint("main", "year_diff")
        self.IMAGE_ASPECT_RATIO = config.getfloat("main", "image_aspect_ratio")
        self.MIN_SCORE_VALID = config.getint("main", "min_score_valid")
        self.MIN_SCORE_NO_SEARCH = config.getint("main", "min_score_no_search")
        self.REFRESH_AFTER_DAYS = config.getint("main", "refresh_after_days")
        self.REFRESH_IF_OLDER = datetime.datetime.strptime(config.get("main", "refresh_if_older"), "%Y-%m-%d")

        if not config.getboolean("main", "extra_logging"):
            logging.getLogger("elasticsearch").setLevel(logging.WARNING)
            logging.getLogger("urllib3").setLevel(logging.WARNING)
            logging.getLogger("requests").setLevel(logging.WARNING)

        # Check for indices in elastic search. IF none found create them.
        self.check_elastic_indices()

    def check_elastic_indices(self):
        if not self.es.indices.exists(index="tmdb"):
            mappingFile = open(os.path.join(os.path.dirname(__file__), "mapping", "tmdb.json"), "r")
            indexSettings = mappingFile.read()
            mappingFile.close()
            response = self.es.indices.create(index='tmdb', body=indexSettings)
            if response["acknowledged"]:
                logging.info("Created tmdb index")

        if not self.es.indices.exists(index="tmdb_search"):
            mappingFile = open(os.path.join(os.path.dirname(__file__), "mapping", "tmdb_search.json"), "r")
            indexSettings = mappingFile.read()
            mappingFile.close()
            response = self.es.indices.create(index='tmdb_search', body=indexSettings)
            if response["acknowledged"]:
                logging.info("Created tmdb_search index")

    def send_request_get(self, endPoint=None):
        if "language" not in self.request:
            self.request["language"] = self.MAIN_LANGUAGE
        if endPoint:
            response = requests.get("https://api.themoviedb.org/3/{}".format(endPoint), params=self.request)
            if response:
                if response.status_code < 400:
                    self.request = self.defaultRequest  # Reset request
                    return json.loads(response.content)
                else:
                    logging.error("Error Code {}".format(response.status_code))
                    logging.error(response.content)
                    return None
            else:
                logging.error("Error Code {}".format(response.status_code))
                logging.error(response.content)
                return None

    def get_backgrounds_baseurl(self):
        response = self.send_request_get("configuration")
        if response:
            return response["images"]["base_url"]

    def search_movie(self, msg=None):
        if msg:
            self.msg = msg
        if "force" not in self.msg:
            self.msg["force"] = False

        # Lookup movie in elasticsearch
        result = self.query_for_movie()
        # If score is less then MIN_SCORE_NO_SEARCH perform a search
        if result[1] < self.MIN_SCORE_NO_SEARCH or self.msg["force"]:
            # Search by director/year if both are avaliable else search by title
            searchByDirector = False
            if "director" in self.msg and "year" in self.msg:
                searchByDirector = True
                self.search_movie_by_director()
            else:
                self.search_movie_tmdb_by_name()

            # Lookup movie in elastic again
            result = self.query_for_movie()
            if result[1] < self.MIN_SCORE_NO_SEARCH:
                # Perform query using non prefered method if required
                if searchByDirector:
                    self.search_movie_tmdb_by_name()
                    result = self.query_for_movie()
        else:
            if result[0]:
                logging.debug("Found {} without quering TMDB - Score {}".format(result[0]["_source"]["title"], result[1]))
            else:
                logging.debug("No results found {}".format(result[1]))

        if result[1] < self.MIN_SCORE_NO_SEARCH and "year" in self.msg:
            result = self.query_for_movie(yearDiff=1)
            if result[1] < self.MIN_SCORE_NO_SEARCH:
                result = self.query_for_movie(yearDiff=2)

        if result[0]:
            # Get time records has been updated.  If timestamp is missing assign it self.REFRESH_IF_OLDER so it forces an update
            if "last_updated" in result[0]["_source"]:
                lastUpdated = datetime.datetime.strptime(result[0]["_source"]["last_updated"], "%Y-%m-%dT%H:%M:%S.%f")
            else:
                lastUpdated = self.REFRESH_IF_OLDER
                
            if lastUpdated < datetime.datetime.utcnow() - datetime.timedelta(days=self.REFRESH_AFTER_DAYS) or lastUpdated <= self.REFRESH_IF_OLDER:
                movie = self.send_request_get("movie/{}".format(result[0]["_id"]))
                if movie:
                    if "id" in movie:
                        self.cache_movie(movie)
                        # Fetch again updated result from DB and save score from search done before
                        score = result[0]["_score"]
                        result = self.es.get(index='tmdb', id=result[0]["_id"], ignore=404)
                        result["_score"] = score
                        result["_source"]["image"] = "{}{}".format(self.IMAGE_BASE_URL, result["_source"]["image"])
                        return result
                else:
                    logging.info("Deleting {} as its not found on TMDB".format(result[0]["_source"]["title"]))
                    self.es.delete(index='tmdb', id=result[0]["_id"])
                    return None
            else:
                result[0]["_source"]["image"] = "{}{}".format(self.IMAGE_BASE_URL, result[0]["_source"]["image"])
                return result[0]
        else:
            return None

    def query_for_movie(self, msg=None, yearDiff=0):
        if msg:
            self.msg = msg

        query = {}
        query["query"] = {}
        query["from"] = 0
        query["size"] = 1
        query["query"]["bool"] = {}
        query["query"]["bool"]["must"] = []
        query["query"]["bool"]["should"] = []

        query["query"]["bool"]["should"].append({"multi_match": {"query": self.msg["title"], "fields": ["title", "alias"]}})

        if "director" in self.msg:
            for director in self.msg["director"]:
                query["query"]["bool"]["should"].append({"match": {"director": director}})

        if "cast" in self.msg:
            for cast in self.msg["cast"]:
                query["query"]["bool"]["should"].append({"match": {"cast": cast}})

        if "year" in self.msg:
            year = {}
            year["bool"] = {}
            year["bool"]["should"] = []
            year["bool"]["should"].append({"range": {"year": {"gte": self.msg["year"] - yearDiff, "lte": self.msg["year"] + yearDiff}}})
            year["bool"]["should"].append({"match": {"year_other": self.msg["year"]}})
            query["query"]["bool"]["must"].append(year)

        result = self.es.search(index="tmdb", body=query)
        if result["hits"]["total"]["value"] > 0:
            if result["hits"]["hits"][0]["_score"] >= self.MIN_SCORE_VALID:
                return result["hits"]["hits"][0], result["hits"]["hits"][0]["_score"]
            else:
                return None, 0
        else:
            return None, 0

    def get_movie_from_tmdb(self, tmdbId=None):
        return self.send_request_get("movie/{}".format(tmdbId))

    def search_movie_by_director(self, msg=None):
        if msg:
            self.msg = msg

        # Check if person and year has already been made on TMDB
        query = {}
        query["query"] = {}
        query["query"]["bool"] = {}
        query["query"]["bool"]["must"] = []
        query["query"]["bool"]["must"].append({"term": {"director_name": self.msg["director"][0]}})
        query["query"]["bool"]["must"].append({"term": {"year": self.msg["year"]}})
        result = self.es.search(index="tmdb_search", body=query)

        if result["hits"]["total"]["value"] == 0:
            # Query TMDB for person
            self.request["include_adult"] = "false"
            self.request["page"] = 1
            self.request["query"] = self.msg["director"][0]

            response = self.send_request_get("search/person")
            if "total_results" in response:
                if response["total_results"] > 0:
                    for person in response["results"][:1]:
                        # Search for filmography of director
                        logging.info("Getting filmography for {} ({})".format(person["name"], self.msg["year"]))
                        credits = self.send_request_get("person/{}/movie_credits".format(person["id"]))
                        # Find movies directed during years of movie being searched
                        if "crew" in credits:
                            for credit in credits["crew"]:
                                if credit["job"] == 'Director':
                                    if "release_date" in credit:
                                        if credit["release_date"] != '' and credit["release_date"]:
                                            year = int(credit["release_date"][:4])
                                            if abs(self.msg["year"] - year) <= self.YEAR_DIFF:
                                                movie = self.send_request_get("movie/{}".format(credit["id"]))
                                                if "id" in movie:
                                                    self.cache_movie(movie)

                # Save that director name and year to avoid doing the same search again
                body = {}
                body["director_name"] = self.msg["director"][0]
                body["year"] = self.msg["year"]
                self.es.index(index='tmdb_search', body=body, params={"refresh": "true"})

            else:
                logging.debug("Already searched for {} filmography for year {}".format(self.msg["director"][0], self.msg["year"]))

    def search_movie_tmdb_by_name(self, msg=None):
        if msg:
            self.msg = msg

        # Check if search has already been made on TMDB
        query = {}
        query["query"] = {}
        query["query"]["term"] = {}
        query["query"]["term"]["movie_title"] = self.msg["title"]
        result = self.es.search(index="tmdb_search", body=query)

        if result["hits"]["total"]["value"] == 0:
            self.request["include_adult"] = "false"
            self.request["page"] = 1
            self.request["query"] = self.msg["title"]

            logging.info("Searching for {}".format(self.msg["title"]))
            response = self.send_request_get("search/movie")
            # print json.dumps(response, indent=3)
            if "total_results" in response:
                if response["total_results"] > 0:
                    for index, movie in enumerate(response["results"]):
                        # If year is avaliable match only movies around the year provided else cache top 3 movies returned
                        if "year" in self.msg:
                            if movie.get("release_date", "") != "":
                                year = int(movie["release_date"][:4])
                                if abs(self.msg["year"] - year) <= self.YEAR_DIFF:
                                    if "id" in movie:
                                        self.cache_movie(movie)
                        else:
                            if index < 3:
                                self.cache_movie(movie)

            # Save that movie title to avoid doing the same search again
            body = {}
            body["movie_title"] = self.msg["title"]
            self.es.index(index='tmdb_search', body=body, params={"refresh": "true"})

        else:
            logging.debug("Already searched for movie {}".format(self.msg["title"]))

    def cache_movie(self, movie=None, force=False):
        record = {}

        # Always update rating if more then 10 votes and popularity
        if movie["vote_count"] > 10:
            record["rating"] = movie["vote_average"]
        record["popularity"] = movie["popularity"]

        # Get original language
        if "original_language" in movie:
            record["language"] = movie["original_language"]
        else:
            record["language"] = "Unknown"

        # If original language is self.LANGUAGES then use original title else stick with english version
        record["alias"] = []
        if record["language"] in self.LANGUAGES:
            record["title"] = movie["original_title"]
            if movie["title"] != movie["original_title"]:
                record["alias"].append(movie["title"])
        else:
            record["title"] = movie["title"]
            if movie["title"] != movie["original_title"]:
                record["alias"].append(movie["original_title"])

        # Release year
        record["year"] = None
        record["year_other"] = []
        if movie["release_date"] != "":
            record["year"] = int(movie["release_date"][:4])

        logging.info("Getting details for {} ({})".format(record["title"], record["year"]))

        # Get cast and director
        cast = self.send_request_get("movie/{}/credits".format(movie["id"]))
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

        # Get titles in different languages
        for language in self.LANGUAGES:
            self.request["language"] = language
            alias = self.send_request_get("movie/{}".format(movie["id"]))

            if language == "en":
                # Get production country
                record["country"] = []
                for country in alias["production_countries"]:
                    name = country["name"]
                    name = name.replace("United States of America", "USA")
                    name = name.replace("United Kingdom", "UK")
                    record["country"].append(name)

                # Get genre
                record["genre"] = []
                for genre in alias["genres"]:
                    record["genre"].append(genre["name"])

                if movie["original_language"] != self.EXCEPTION_LANGUAGE:
                    # Use English description for everything but self.EXCEPTION_LANGUAGE
                    record["description"] = alias["overview"]

            # Keep original title and replace description with self.EXCEPTION_LANGUAGE description if movie is in self.EXCEPTION_LANGUAGE language
            if movie["original_language"] == self.EXCEPTION_LANGUAGE and language == self.EXCEPTION_LANGUAGE:
                record["alias"].append(record["title"])
                record["title"] = alias["title"]
                if alias["title"] in record["alias"]:
                    record["alias"].remove(alias["title"])
                record["description"] = alias["overview"]

            # Add Aliases to movie
            if self.check_for_dup(alias["title"], record["alias"], record["title"]):
                record["alias"].append(alias["title"])

        # Get alternative titles
        altTitles = self.send_request_get("movie/{}/alternative_titles".format(movie["id"]))
        for title in altTitles["titles"]:
            if title["iso_3166_1"] in self.COUNTRIES:
                if self.check_for_dup(title["title"], record["alias"], record["title"]):
                    record["alias"].append(title["title"])

        # Get other release dates
        record["year_other"] = []
        releaseDates = self.send_request_get("movie/{}/release_dates".format(movie["id"]))
        for countryDate in releaseDates["results"]:
            if countryDate["iso_3166_1"] in self.COUNTRIES:
                for releaseDate in countryDate["release_dates"]:
                    if releaseDate["release_date"] != "":
                        year = int(releaseDate["release_date"][:4])
                        if abs(year - record["year"]) > 2:
                            if year not in record["year_other"]:
                                record["year_other"].append(year)

        # Get images
        record["image"] = ""
        if record["language"] in self.LANGUAGES:
            self.request["language"] = record["language"]
        else:
            self.request["language"] = "en"

        images = self.send_request_get("movie/{}/images".format(movie["id"]))
        imageAspectRatio = 0
        for image in images["posters"] + images["backdrops"]:
            if abs(image["aspect_ratio"] - self.IMAGE_ASPECT_RATIO) < abs(imageAspectRatio - self.IMAGE_ASPECT_RATIO):
                record["image"] = image["file_path"]
                imageAspectRatio = image["aspect_ratio"]
        if record["image"] != "":
            logging.debug("Storing image with AR {}".format(round(imageAspectRatio, 2)))

        record["last_updated"] = datetime.datetime.utcnow().isoformat()
        self.es.index(index='tmdb', id=movie["id"], body=record, params={"refresh": "true"})

    def check_for_dup(self, title, alias, orgTitle):
        if alias:
            for altTitle in alias:
                if re.search("^{}$".format(re.escape(title)), altTitle, flags=re.IGNORECASE):
                    return False
        if re.search("^{}$".format(re.escape(title)), orgTitle, flags=re.IGNORECASE):
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

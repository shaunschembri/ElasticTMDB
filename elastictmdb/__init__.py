import logging
import requests
import elasticsearch
import datetime
import os
import re
from .config import set_defaults
from jinja2 import Template

class ElasticTMDB(object):
    def load_config(self):
        set_defaults(self)

        # Set HTTP headers for TMDB requests
        self.headers = {}
        self.headers["content-type"] = "application/json;charset=utf-8"
        self.headers["Accept-Encoding"] = "gzip"

        if not self.config["extra_logging"]:
            logging.getLogger("elasticsearch").setLevel(logging.WARNING)
            logging.getLogger("urllib3").setLevel(logging.WARNING)
            logging.getLogger("requests").setLevel(logging.WARNING)

        # ElasticSearch
        elasticAuth = (self.config["es_username"], self.config["es_password"])
        self.es = elasticsearch.Elasticsearch(hosts=self.config["es_host"],
                                                port=self.config["es_port"],
                                                scheme=self.config["es_scheme"],
                                                http_auth=elasticAuth)

        # Generate Index names and create them if they do not exists
        self.config["title_index"] = "{}_{}_title".format(self.config["index_prefix"], self.config["title_type"])
        self.config["search_index"] = "{}_{}_search".format(self.config["index_prefix"], self.config["title_type"])
        self.check_index(indexName=self.config["title_index"], indexMappingFile="title.json")
        self.check_index(indexName=self.config["search_index"], indexMappingFile="search.json")

        # Get countries, generes, background base URL and languages from TMDB
        if self.config["initial_cache_tmdb"]:
            self.cache_configuration()
        else:
            logging.debug("Skipping Initial TMDB config...some functions might break")

    def load_template(self, templateFile):
        with open(os.path.join(os.path.dirname(__file__), "templates", templateFile), "r") as templateFile:
            return Template(templateFile.read())

    def send_request_get(self, endPoint=None, params=None):
        if not params:
            params = {}
        if "language" not in params:
            params["language"] = self.config["main_language"]
        elif params["language"] == "":
            del params["language"]
        params["api_key"] = self.config["tmdb_api_key"]

        if endPoint:
            response = requests.get("https://api.themoviedb.org/3/{}".format(endPoint), params=params, headers=self.headers)
            if response:
                if response.status_code < 400:
                    return response.json()
                else:
                    logging.error("Error Code {} - Message {}".format(response.status_code, response.json()["status_message"]))
                    del params["api_key"]
                    logging.error("Error Endpoint {} - Params {}".format(endPoint, params))
                    return None
            else:
                logging.error("Error Code {} - Message {}".format(response.status_code, response.json()["status_message"]))
                del params["api_key"]
                logging.error("Error Endpoint {} - Params {}".format(endPoint, params))
                return None

    def discover_title(self, page):
        params = {}
        params["sort_by"] = "popularity.desc"
        params["page"] = page
        discover = self.send_request_get(endPoint="discover/{}".format(self.config["title_type"]), params=params)
        if discover:
            return discover["results"]

    def cache_title(self, title, force, record):
        recordId = None
        # Check if record exists in elasticsearch
        if not record:
            query = {"query": {"term": {"ids.tmdb": title["id"]}}}
            esRecord = self.get_record_by_query(index=self.config["title_index"], query=query)
            if esRecord["hits"]["hits"]:
                recordId = esRecord["hits"]["hits"][0]["_id"]
                record = esRecord["hits"]["hits"][0]["_source"]
        else:
            recordId = record["_id"]
            esRecord = {"hits": {"hits": [record]}}
            record = record["_source"]

        if record:
            # Check if record is up for an update
            if self.check_update_required(timestamp=record["@timestamp"]):
                force = True

        if not recordId or force:
            # Get details of title
            params = {}
            if title["original_language"] == self.config["exception_language"]:
                params["language"] = self.config["exception_language"]
            else:
                params["language"] = self.config["main_language"]
            title = self.send_request_get(endPoint="{}/{}".format(self.config["title_type"], title["id"]), params=params)

            if title:
                # Get title year, to be used for display
                if not title.get(self.attrib["date"]):
                    titleYear = "None"
                else:
                    titleYear = title[self.attrib["date"]][:4]

                if recordId:
                    logging.info("Updating details : {} ({}) ({})".format(title.get(self.attrib["title"], "N/A"), titleYear, self.config["title_type"]))
                else:
                    logging.info("Getting details : {} ({}) ({})".format(title.get(self.attrib["title"], "N/A"), titleYear, self.config["title_type"]))

                # Add langauge if not in record
                if "language" not in record:
                    record["language"] = title["original_language"]

                # Add title if not in record
                if "title" not in record:
                    record["title"] = title[self.attrib["title"]]

                # Add country if not in record
                if "country" not in record:
                    record["country"] = []
                if "production_countries" in title:
                    for country in title["production_countries"]:
                        if country["iso_3166_1"] not in record["country"]:
                            record["country"].append(country["iso_3166_1"])
                if "origin_country" in title:
                    for country in title["origin_country"]:
                        if country not in record["country"]:
                            record["country"].append(country)

                # Add rating and number of votes
                if "rating" not in record:
                    record["rating"] = {}
                    record["rating"]["tmdb"] = {}
                    record["rating"]["tmdb"]["votes"] = title["vote_count"]
                    record["rating"]["tmdb"]["average"] = title["vote_average"]

                # Add original title to aliases if different
                if "alias" not in record:
                    record["alias"] = []
                if title[self.attrib["title"]] != title[self.attrib["original_title"]]:
                    if self.check_for_dup(title[self.attrib["original_title"]], record["alias"], record["title"]):
                        record["alias"].append(title[self.attrib["original_title"]])

                # Release year
                if "year" not in record:
                    record["year"] = None
                    if title[self.attrib["date"]] != "None":
                        if title[self.attrib["date"]]:
                            record["year"] = int(title[self.attrib["date"]][:4])

                # Get genres
                if "genre" not in record:
                    record["genre"] = []
                for genre in title["genres"]:
                    if genre["id"] not in record["genre"]:
                        record["genre"].append(genre["id"])

                # Get cast, director and other crew
                if "credits" not in record:
                    record["credits"] = {}
                cast = self.send_request_get(endPoint="{}/{}/credits".format(self.config["title_type"], title["id"]))
                # Save top 10 cast
                for person in sorted(cast["cast"], key=lambda k: (k["order"])):
                    if "actor" not in record["credits"]:
                        record["credits"]["actor"] = []
                    if len(record["credits"]["actor"]) < 10:
                        if self.check_for_dup(person["name"], record["credits"]["actor"]):
                            record["credits"]["actor"].append(person["name"])

                # Save director and 5 other members of crew (producers etc)
                for person in cast["crew"]:
                    if person["job"] == 'Director':
                        if "director" not in record["credits"]:
                            record["credits"]["director"] = []
                        if self.check_for_dup(person["name"], record["credits"]["director"]):
                            record["credits"]["director"].append(person["name"])
                    else:
                        if "other" not in record["credits"]:
                            record["credits"]["other"] = []
                        if len(record["credits"]["other"]) < 5:
                            if self.check_for_dup(person["name"], record["credits"]["other"]):
                                record["credits"]["other"].append(person["name"])

                # Get description (and only keep first paragraph) save it only if longer then record if present
                if "overview" in title:
                    if "description" not in record:
                        record["description"] = ""
                    # Keep only first paragraph of overview
                    regex = re.search(r'^(.+?)\n\n', title["overview"])
                    if regex:
                        overview = regex.group(1)
                    else:
                        overview = title["overview"]
                    # Keep longer one
                    if len(overview) > len(record["description"]):
                        record["description"] = overview

                # Save tagline if incoming one is longer
                if "tagline" in title:
                    if "tagline" not in record:
                        record["tagline"] = ""
                    if len(record["tagline"]) > len(record["tagline"]):
                        record["tagline"] = title["tagline"]

                # Get translations
                translations = self.send_request_get(endPoint="{}/{}/translations".format(self.config["title_type"], title["id"]))
                for translation in translations["translations"]:
                    if translation["iso_639_1"] in self.config["languages"]:
                        # Add Aliases
                        if self.check_for_dup(translation["data"][self.attrib["title"]], record["alias"], record["title"]):
                            record["alias"].append(translation["data"][self.attrib["title"]])

                # Get alternative titles
                altTitles = self.send_request_get(endPoint="{}/{}/alternative_titles".format(self.config["title_type"], title["id"]))
                for titleName in altTitles[self.attrib["alt_titles"]]:
                    if titleName["iso_3166_1"] in self.config["countries"]:
                        if self.check_for_dup(titleName["title"], record["alias"], record["title"]):
                            record["alias"].append(titleName["title"])

                # Get images not not is avaliable
                if "image" not in record:
                    record["image"] = ""
                    if title["original_language"] == self.config["exception_language"]:
                        params = {"language": title["original_language"]}
                    else:
                        params = {"language": self.config["main_language"]}

                    images = self.send_request_get(endPoint="{}/{}/images".format(self.config["title_type"], title["id"]), params=params)
                    if not images["posters"] and not images["backdrops"]:
                        # Try to search without any language for art
                        images = self.send_request_get(endPoint="{}/{}/images".format(self.config["title_type"], title["id"]), params={"language": ""})
                    imageAspectRatio = 10
                    for image in images["posters"] + images["backdrops"]:
                        if abs(image["aspect_ratio"] - self.config["image_aspect_ratio"]) < abs(imageAspectRatio - self.config["image_aspect_ratio"]):
                            record["image"] = image["file_path"][1:]
                            imageAspectRatio = abs(imageAspectRatio - self.config["image_aspect_ratio"])

                # Get TMDB Record IDs
                if "ids" not in record:
                    record["ids"] = {}
                    if "tmdb" not in record["ids"]:
                        record["ids"]["tmdb"] = title["id"]

                self.index_record(index=self.config["title_index"], recordId=recordId, record=record)
        else:
            logging.debug("No update required for {} ({}) ({})".format(esRecord["hits"]["hits"][0]["_source"]["title"], esRecord["hits"]["hits"][0]["_source"]["year"], self.config["title_type"]))

        return record

    def search_title(self, search):
        # First query elasticsearch and check if title is returned without any additional caching
        result = self.query_title(search=search)

        # If no title has been returned, search by director and actors
        if not result or search.get("force"):
            crew = search.get("director", []) + search.get("actor", []) + search.get("other", [])
            for person in crew:
                self.search_person_tmdb(person=person, year=search.get("year"), force=search.get("force"))
                # Query again in elasticsearch and if match then break
                result = self.query_title(search=search)
                if result:
                    break

            # If no result found, search by name and year if avaliable
            if not result or search.get("force"):
                if "title" in search:
                    for title in search["title"]:
                        self.search_title_tmdb(title=title, year=search.get("year"), force=search.get("force"))
                result = self.query_title(search=search)

            # Try an exact match if no result yet
            if not result:
                if "title" in search:
                    result = self.query_title_exact(search=search)

            # Try adjacent years if provided year is not a hit.  This is a workaround as the year supplied by some providers is inaccurate
            if not result:
                if search.get("year"):
                    for yearDiff in range(0, self.config["year_diff"] + 1):
                        final = False
                        if yearDiff == self.config["year_diff"]:
                            final = True
                        result = self.query_title(search=search, yearDiff=yearDiff, final=final)
                        if result:
                            break
                else:
                    result = self.query_title(search=search, final=True)

        if result:
            logging.debug("Found {} ({}) in elasticsearch (Score: {:.1f})".format(result["_source"]["title"], self.config["title_type"], result["_score"]))
            result = self.process_result(result=result, force=search.get("force"))
            return result

    def query_title_exact(self, search):
        query = {"from": 0, "size": 1, "query": {}}
        query["query"]["bool"] = {}
        query["query"]["bool"]["should"] = []

        if "title" in search:
            for title in search["title"]:
                query["query"]["bool"]["should"].append({"multi_match": {"query": title, "fields": ["title.keyword", "alias.keyword"]}})
                result = self.get_record_by_query(index=self.config["title_index"], query=query)
                if result["hits"]["total"]["value"] > 0:
                    if result["hits"]["hits"][0]["_score"] >= self.config["min_score_exact"]:
                        return result["hits"]["hits"][0]

    def query_title(self, search, final=False, yearDiff=0):
        query = {"from": 0, "size": 1, "query": {}}
        query["query"]["bool"] = {}
        query["query"]["bool"]["must"] = []
        query["query"]["bool"]["should"] = []
        if "title" in search:
            for title in search["title"]:
                query["query"]["bool"]["should"].append({"multi_match": {"query": title, "fields": ["title", "alias"]}})

        if "director" in search:
            for director in search["director"]:
                query["query"]["bool"]["should"].append({"match": {"credits.director": director}})

        if "actor" in search:
            for actor in search["actor"]:
                query["query"]["bool"]["should"].append({"match": {"credits.actor": actor}})

        if "other" in search:
            for producer in search["other"]:
                query["query"]["bool"]["should"].append({"match": {"credits.other": producer}})

        if "country" in search:
            for country in search["country"]:
                countryCode = self.countryCodes.get(country)
                if countryCode:
                    query["query"]["bool"]["should"].append({"match": {"country": countryCode}})

        if "year" in search:
            search["year"] = int(search["year"])
            year = {}
            year["bool"] = {}
            year["bool"]["should"] = []
            year["bool"]["should"].append({"range": {"year": {"gte": search["year"] - yearDiff, "lte": search["year"] + yearDiff}}})
            query["query"]["bool"]["must"].append(year)

        # Calculate min score
        if not final:
            minScore = self.config["min_score_no_search"]
        else:
            minScore = self.config["min_score"]
            if "actor" in search:
                minScore += len(search["actor"] * self.config["score_increment_per_actor"])

        result = self.get_record_by_query(index=self.config["title_index"], query=query)

        if result["hits"]["total"]["value"] > 0:
            if result["hits"]["hits"][0]["_score"] >= minScore:
                return result["hits"]["hits"][0]
            if final:
                logging.debug("Best result {} (Score: {:.1f} Min Score: {})".format(result["hits"]["hits"][0]["_source"]["title"], result["hits"]["hits"][0]["_score"], minScore))
        else:
            if final:
                logging.debug("No results found for {}".format(search["title"][0]))

    def process_result(self, result, force):
        # Check if record requires updating
        title = {"id": result["_source"]["ids"]["tmdb"], "original_language": result["_source"]["language"]}
        result["_source"] = self.cache_title(title=title, force=force, record=result)

        # Generate full image URL if missing
        result["_source"]["image"] = self.get_image_url(image=result["_source"]["image"])

        # Convert country code to full name
        countries = []
        for countryCode in result["_source"]["country"]:
            countries.append(self.countries.get(countryCode, "Unknown"))
        result["_source"]["country"] = countries

        # Convert language code to full name
        result["_source"]["language"] = self.languages.get(result["_source"]["language"], "Unknown")

        # Convert genre code
        genres = []
        for genreId in result["_source"]["genre"]:
            genre = self.genres.get(genreId)
            if genre:
                genres.append(self.genres[genreId])
        if genres:
            result["_source"]["genre"] = genres

        return result

    def search_person_tmdb(self, person, year, force):
        performSearch = force
        recordId = None

        # Check if search was already performed
        query = {"query": {"bool": {"must": []}}}
        query["query"]["bool"]["must"].append({"term": {"person": person}})
        query["query"]["bool"]["must"].append({"term": {"year": year or -1}})

        result = self.get_record_by_query(index=self.config["search_index"], query=query)
        if result["hits"]["total"]["value"] == 0:
            performSearch = True
        else:
            # Check if person is up for an update:
            if self.check_update_required(timestamp=result["hits"]["hits"][0]["_source"]["@timestamp"]):
                performSearch = True
                recordId = result["hits"]["hits"][0]["_id"]

        if performSearch:
            # Query TMDB for person
            params = {"include_adult": "false", "page": 1}
            params["query"] = person
            logging.info("Searching for person : {}".format(person))
            response = self.send_request_get("search/person", params=params)
            if "total_results" in response:
                if response["total_results"] > 0:
                    for personRecord in response["results"]:
                        # Search credits of person found
                        logging.info("Getting credits : {} ({}) ({})".format(personRecord["name"], year, self.config["title_type"]))
                        credits = self.send_request_get("person/{}/{}_credits".format(personRecord["id"], self.config["title_type"]))
                        # Find titles during years around query or if year=-1 all credits
                        if "crew" in credits:
                            for credit in credits["crew"] + credits["cast"]:
                                if "release_date" in credit and year:
                                    if credit["release_date"] != '' and credit["release_date"]:
                                        creditYear = int(credit["release_date"][:4])
                                        if abs(year - creditYear) > self.config["year_diff"]:
                                            continue
                                self.cache_title(title=credit, force=force, record={})

            # Save that name and year to avoid doing the same search again
            record = {}
            record["person"] = person
            record["year"] = year or -1
            self.index_record(index=self.config["search_index"], record=record, recordId=recordId)
        else:
            logging.debug("Already searched credits for {} ({}) ({})".format(person, year, self.config["title_type"]))

    def search_title_tmdb(self, title, year, force):
        performSearch = force
        recordId = None

        # Check if search was already performed
        query = {"query": {"bool": {"must": []}}}
        query["query"]["bool"]["must"].append({"term": {"title": title}})
        query["query"]["bool"]["must"].append({"term": {"year": year or -1}})

        result = self.get_record_by_query(index=self.config["search_index"], query=query)
        if result["hits"]["total"]["value"] == 0:
            performSearch = True
        else:
            # Check if person is up for an update:
            if self.check_update_required(timestamp=result["hits"]["hits"][0]["_source"]["@timestamp"]):
                performSearch = True
                recordId = result["hits"]["hits"][0]["_id"]

        if performSearch:
            params = {"include_adult": "false", "page": 1}
            params["query"] = title
            if year:
                params["year"] = year
            logging.info("Searching for title : {} ({}) ({})".format(title, year, self.config["title_type"]))
            response = self.send_request_get(endPoint="search/{}".format(self.config["title_type"]), params=params)
            if "total_results" in response:
                if response["total_results"] > 0:
                    for result in response["results"][:5]:
                        self.cache_title(title=result, force=force, record={})

            # Save title and year to avoid doing the same search again
            record = {}
            record["title"] = title
            record["year"] = year or -1
            self.index_record(index=self.config["search_index"], record=record, recordId=recordId)
        else:
            logging.debug("Already searched title {} ({}) ({})".format(title, year, self.config["title_type"]))

    def get_image_url(self, image):
        if "http" not in image:
            return "{}/{}".format(self.config["image_base_url"], image)
        else:
            return image

    def check_for_dup(self, title, alias, orgTitle=""):
        if title == "":
            return False
        if alias:
            for altTitle in alias + [orgTitle]:
                if re.search("^{}$".format(re.escape(title)), altTitle, flags=re.IGNORECASE):
                    return False
            else:
                return True
        if orgTitle:
            if re.search("^{}$".format(re.escape(title)), orgTitle, flags=re.IGNORECASE):
                return False
        return True

    def render_template(self, record, template):
        if template == "description":
            return self.description_template.render(record=record)
        elif template == "subtitle":
            return self.subtitle_template.render(record=record)

    def check_index(self, indexName, indexMappingFile):
        if not self.es.indices.exists(index=indexName):
            with open(os.path.join(os.path.dirname(__file__), "index_mapping", indexMappingFile), "r") as mappingFile:
                indexSettings = mappingFile.read()
            response = self.es.indices.create(index=indexName, body=indexSettings)
            if response["acknowledged"]:
                logging.info("Created {} index".format(indexName))

    def get_record_by_query(self, index, query, refreshIndex=True):
        if refreshIndex:
            self.es.indices.refresh(index=index)
        return self.es.search(index=index, body=query)

    def index_record(self, index, record, recordId=None):
        record["@timestamp"] = datetime.datetime.utcnow().isoformat()
        self.es.index(index=index, id=recordId, body=record)

    def check_update_required(self, timestamp):
        timestamp = datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%f")
        if timestamp < datetime.datetime.utcnow() - datetime.timedelta(days=self.config["refresh_after_days"]) or timestamp <= self.config["refresh_if_older"]:
            return True
        else:
            return False

    def cache_configuration(self):
        self.genres = {}
        self.countries = {}
        self.countryCodes = {}
        self.languages = {}

        genres = self.send_request_get(endPoint="genre/{}/list".format(self.config["title_type"]))
        if genres:
            for genre in genres["genres"]:
                self.genres[genre["id"]] = genre["name"]

        countries = self.send_request_get(endPoint="configuration/countries")
        if countries:
            for country in countries:
                self.countries[country["iso_3166_1"]] = country["english_name"]
                self.countryCodes[country["english_name"]] = country["iso_3166_1"]

        languages = self.send_request_get(endPoint="configuration/languages")
        if languages:
            for language in languages:
                self.languages[language["iso_639_1"]] = language["english_name"]

        backgroundUrl = self.send_request_get(endPoint="configuration")
        if backgroundUrl:
            self.config["image_base_url"] = backgroundUrl["images"]["base_url"]
            self.config["image_base_url"] += self.config["tmdb_image_type"]

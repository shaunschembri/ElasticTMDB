import logging
import datetime
from .__init__ import ElasticTMDB

class Tvshow(ElasticTMDB):
    def __init__(self, initialCacheTMDB=True):
        self.config = {}
        self.config["title_type"] = "tv"
        self.config["description_template"] = "tvshow_description.j2"
        self.config["subtitle_template"] = "tvshow_subtitle.j2"
        self.config["initial_cache_tmdb"] = initialCacheTMDB
        self.load_config()

        # Generate episode index name and create them if they do not exists
        self.config["episode_index"] = "{}_{}_episode".format(self.config["index_prefix"], self.config["title_type"])
        self.check_index(indexName=self.config["episode_index"], indexMappingFile="episode.json")

        # Load template
        self.description_template = self.load_template(templateFile=self.config["description_template"])
        self.subtitle_template = self.load_template(templateFile=self.config["subtitle_template"])

        # TMDB mappings
        self.attrib = {}
        self.attrib["title"] = "name"
        self.attrib["original_title"] = "original_name"
        self.attrib["alt_titles"] = "results"
        self.attrib["date"] = "first_air_date"

    def search(self, search):
        tvshow = self.search_title(search=search)
        if tvshow:
            episode = self.search_episode(tvshow=tvshow, search=search)
            if episode:
                tvshow["_score"] = tvshow["_score"] + episode["_score"]
                if "title" in episode["_source"]:
                    tvshow["_source"]["episode_title"] = episode["_source"]["title"]
                if "image" in episode["_source"]:
                    tvshow["_source"]["image"] = self.get_image_url(image=episode["_source"]["image"])
                if "year" in episode["_source"]:
                    tvshow["_source"]["year"] = episode["_source"]["air_date"][:4]
                if "description" in episode["_source"]:
                    tvshow["_source"]["description"] = episode["_source"]["description"]
                if "air_date" in episode["_source"]:
                    tvshow["_source"]["air_date"] = episode["_source"]["air_date"]
                tvshow["_source"]["season"] = episode["_source"]["season"]
                tvshow["_source"]["episode"] = episode["_source"]["episode"]
            return tvshow

    def query_episode(self, tvshow, search):
        # Search for episode in elasticsearch
        query = {"from": 0, "size": 1, "query": {}}
        query["query"]["bool"] = {}
        query["query"]["bool"]["must"] = []
        query["query"]["bool"]["should"] = []
        query["query"]["bool"]["must"].append({"term": {"tvshow_id": tvshow["_source"]["ids"]["tmdb"]}})
        if "season" in search:
            query["query"]["bool"]["must"].append({"term": {"season": search["season"]}})

        # Use episode number
        if "episode" in search:
            query["query"]["bool"]["must"].append({"term": {"episode": search["episode"]}})

        # Use episode name (usually in subtitle)
        if "subtitle" in search:
            for subtitle in search["subtitle"]:
                query["query"]["bool"]["should"].append({"match": {"title": subtitle}})

        # Use year which is usually the year it was first aried
        if "episode_year" in search:
            for episodeYear in search["episode_year"]:
                yearFormat = "{}||/y".format(episodeYear)
                query["query"]["bool"]["should"].append({"range": {"air_date": {"gte": yearFormat, "lte": yearFormat, "format": "yyyy"}}})

        result = self.get_record_by_query(index=self.config["episode_index"], query=query)

        if result["hits"]["total"]["value"] > 0:
            logging.debug("Found episode {} (S{:02d}E{:02d}) in elasticsearch".format(tvshow["_source"]["title"], result["hits"]["hits"][0]["_source"]["season"], result["hits"]["hits"][0]["_source"]["episode"]))
            return result

    def query_season(self, tvshow, search):
        query = {"from": 0, "size": 0, "query": {}}
        query["query"]["bool"] = {}
        query["query"]["bool"]["must"] = []
        query["query"]["bool"]["must"].append({"term": {"tvshow_id": tvshow["_source"]["ids"]["tmdb"]}})
        query["query"]["bool"]["must"].append({"term": {"season": search["season"]}})
        result = self.get_record_by_query(index=self.config["episode_index"], query=query)
        if result["hits"]["total"]["value"] > 0:
            return True
        else:
            return False

    def search_episode(self, tvshow, search):
        performSearch = search.get("force")
        result = None
        if not performSearch:
            result = self.query_episode(tvshow=tvshow, search=search)

        # Search for entire season (with only 1 call we get the same data as querying per episode)
        if performSearch or not result:
            if "season" in search:
                # Check if season was searched before
                if not self.query_season(tvshow=tvshow, search=search):
                    self.search_season_tmdb(tvshow=tvshow, search=search)
                    result = self.query_episode(tvshow=tvshow, search=search)
                    # If no result found for season save a dummy entry with episode -1 to avoid doing the search again
                    if not result:
                        record = {}
                        record["tvshow_id"] = tvshow["_source"]["ids"]["tmdb"]
                        record["season"] = search["season"]
                        record["episode"] = -1
                        # Save record as a stub to avoid querying this season again
                        self.index_record(index=self.config["episode_index"], record=record)

        if not result:
            # Query again to get data
            result = self.query_episode(tvshow=tvshow, search=search)

        if result:
            # Check if episode was cached prior to its air date, if true then force an update
            result = result["hits"]["hits"][0]
            if "air_date" in result["_source"]:
                if datetime.datetime.strptime(result["_source"]["air_date"], "%Y-%m-%d") > datetime.datetime.strptime(result["_source"]["@timestamp"][:10], "%Y-%m-%d"):
                    search["season"] = result["_source"]["season"]
                    self.search_season_tmdb(tvshow=tvshow, search=search)
                    result = self.query_episode(tvshow=tvshow, search=search)
                    result = result["hits"]["hits"][0]

            return result

    def search_season_tmdb(self, tvshow, search):
        logging.info("Getting details for {} (S{:02d})".format(tvshow["_source"]["title"], search["season"]))
        endPoint = "tv/{}/season/{}".format(tvshow["_source"]["ids"]["tmdb"], search["season"])
        response = self.send_request_get(endPoint=endPoint)
        if response:
            for episode in response["episodes"]:
                # Only cache aired episodes
                if episode["air_date"]:
                    releaseDate = datetime.datetime.strptime(episode["air_date"], "%Y-%m-%d")
                    if releaseDate <= datetime.datetime.now():
                        record = {}
                        record["tvshow_id"] = tvshow["_source"]["ids"]["tmdb"]
                        record["season"] = search["season"]
                        record["episode"] = episode["episode_number"]
                        record["title"] = episode["name"]
                        if episode["air_date"]:
                            record["air_date"] = episode["air_date"]
                        if episode["overview"]:
                            record["description"] = episode["overview"]
                        if episode["still_path"]:
                            record["image"] = episode["still_path"][1:]
                        if episode["vote_average"]:
                            record["rating"] = {}
                            record["rating"]["tmdb"] = {}
                            record["rating"]["tmdb"]["votes"] = episode["vote_count"]
                            record["rating"]["tmdb"]["average"] = episode["vote_average"]
                        record["ids"] = {"tmdb": episode["id"]}
                        self.index_record(index=self.config["episode_index"], record=record)

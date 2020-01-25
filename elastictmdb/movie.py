from .__init__ import ElasticTMDB

class Movie(ElasticTMDB):
    def __init__(self, initialCacheTMDB=True):
        self.config = {}
        self.config["title_type"] = "movie"
        self.config["description_template"] = "movie_description.j2"
        self.config["subtitle_template"] = "movie_subtitle.j2"
        self.config["initial_cache_tmdb"] = initialCacheTMDB
        self.load_config()

        # Check for indices in elastic search. If none found create them.
        self.check_index(indexName=self.config["title_index"], indexMappingFile="title.json")
        self.check_index(indexName=self.config["search_index"], indexMappingFile="search.json")

        # Load template
        self.description_template = self.load_template(templateFile=self.config["description_template"])
        self.subtitle_template = self.load_template(templateFile=self.config["subtitle_template"])

        # TMDB mappings
        self.attrib = {}
        self.attrib["title"] = "title"
        self.attrib["original_title"] = "original_title"
        self.attrib["alt_titles"] = "titles"
        self.attrib["date"] = "release_date"

    def search(self, search):
        return self.search_title(search=search)

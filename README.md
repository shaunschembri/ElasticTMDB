# ElasticTMDB

ElasticTMDB is a Python3 class which sources movie details from The Movie Database (TMDB) and caches them in an Elasticsearch index to speed up subsequent queries to the same movie. The class will store a lot of information about a movie (cast, director, synopsis, user ratings, release year, poster etc) together with the movie title in a number of languages.  This is particularly useful to convert a movie programme listed in its foreign language title to its original language title.

## Getting Started

### Prerequisites
* Python 3.6 or newer (for Python 2.7 use the python2 tag/release)
* Elasticsearch Server 6.0 or newer
* TMDB API key

### Python Modules
Install dependencies by executing
```
pip3 install -r requirements.txt
```

### Elasticsearch Server
Follow the instructions [here](https://www.elastic.co/downloads/elasticsearch) to install a fresh Elasticsearch server.  If you already have Elasticsearch installed, you can use it along side other applications as ElasticTMDB will create 2 new indexes on first execution and will not interfere with any other indexes present.

### TMDB API Key
Obtain a key to The Movie Database to access the API. To obtain the API key, follow these steps:

* Register and verify an account.
* Log into your account.
* Select the API section on left side of your account page or follow this [link](https://www.themoviedb.org/settings/api)
* Click on the link to generate a new API key and follow the instructions.

### Configuring
Clone or [download](https://github.com/shaunschembri/ElasticTMDB/archive/master.zip) this repository.
Review settings in elastictmdb.conf. All options are documented in the file but if you are starting with a new/empty cache you only need to set the TMDB API key and the Elasticsearch connection details.

## Usage

### get_movie_details

The simplest way to use ElasticTMDB (but not really useful) is to run the get_movie_details.py and pass the query details via command line.  It will return a JSON document with the movie details.  This utility can also serve as an example to integrate ElasticTMDB in you own applications. 

```
usage: get_movie_details.py [-h] -t TITLE [-d DIRECTOR] [-c CAST] [-y YEAR]
                            [-f]
required arguments:
  -t TITLE, --title TITLE
                        Movie title
optional arguments:
  -d DIRECTOR, --director DIRECTOR
                        Name of director. Can be used more then once to
                        specify more the 1 director
  -c CAST, --cast CAST  Name of actor. Can be used more then once to specify
                        more cast members
  -y YEAR, --year YEAR  Movie release year
  -f, --force           Force a search on TMDB before returning results
```
Example
```
python get_movie_details.py -t "Stirb langsam" -y 1988 -c "Bruce Willis" -c "Alan Rickman" -d "John McTiernan"
```
Result
```
{
   "_type": "movie", 
   "_source": {
      "rating": 7.5, 
      "description": "NYPD cop, John McClane's plan to reconcile with his estranged wife is thrown for a serious loop when minutes after he arrives at her office, the entire building is overtaken by a group of terrorists. With little help from the LAPD, wisecracking McClane sets out to single-handedly rescue the hostages and bring the bad guys down.", 
      "language": "en", 
      "title": "Die Hard", 
      "country": [
         "USA"
      ], 
      "year_other": [
         1999, 
         2007
      ], 
      "popularity": 21.527401, 
      "director": [
         "John McTiernan"
      ], 
      "cast": [
         "Bruce Willis", 
         "Alan Rickman", 
         "Alexander Godunov", 
         "Bonnie Bedelia", 
         "Reginald VelJohnson", 
         "Paul Gleason", 
         "De'voreaux White", 
         "William Atherton", 
         "Clarence Gilyard Jr.", 
         "Hart Bochner"
      ], 
      "alias": [
         "Die Hard", 
         "Stirb langsam", 
         "Die Hard - Trappola di cristallo", 
         "Jungla de cristal", 
         "Pi\u00e8ge de cristal", 
         "Stirb Langsam 1", 
         "Die Hard 1 Pi\u00e8ge de cristal"
      ], 
      "version": 2, 
      "year": 1988, 
      "genre": [
         "Action", 
         "Thriller"
      ], 
      "image": "http://image.tmdb.org/t/p/w300/mc7MubOLcIw3MDvnuQFrO9psfCa.jpg"
   }, 
   "_score": 43.040012, 
   "_index": "tmdb", 
   "_version": 17, 
   "found": true, 
   "_id": "562"
}
```

### process_xmltv

A more useful application of ElasticTMDB class is the process_xmltv.py utlity, which takes one or more [XMLTV](http://wiki.xmltv.org/index.php/Main_Page) files, detect movies in the programmes listed and outputs an XMLTV file with the detected movie's description replaced with data sourced from TMDB.  Other programme listings are not touched.

The utility will detect a movie based on the category of the programme.  According to the DVB EIT specification a movie should have one of the below categories, however as many XMLTV files contains different terms for these categories, you can map the provider categories to any one of the below in the epg_category.json. New categories are automatically added in epg_category.json as discovered by process_xmltv.py.
```
Movie / Drama
Detective / Thriller
Adventure / Western / War
Science fiction / Fantasy / Horror
Comedy
Soap / Melodrama / Folkloric
Romance
Serious / Classical / Religious / Historical movie / Drama
Adult movie / Drama
```
As the above categories also include TV shows, a programme should be a minimum of 70 minutes in length to be considered a movie.

The preprocess.py file includes a python function that is executed before a programme is processed. The included function will remove all title tags except one with the attribute lang set to "xx" if this is present. This attribute contains the original name of the program hence replacing any localised version of the programme.  Pre-processing can be switched on inside the elastictmdb.conf config file.

```
usage: process_xmltv.py [-h] [-i INPUT] [-o OUTPUT] [-l LOGFILE]
required arguments:
  -i INPUT, --input INPUT
                        Input XMLTV file
  -o OUTPUT, --output OUTPUT
                        Output XMLTV file
optional arguments:
  -l LOGFILE, --logfile LOGFILE
                        Output log to file
```
Example
```
python process_xmltv.py -i input.xml -o output.xml
```
Input XMLTV file (input.xml)
```
<?xml version="1.0" encoding="UTF-8"?>
<tv>
	<channel id="moviechannel.de">
		<display-name lang="en">Die Movie Channel</display-name>
	</channel>
	<programme start="20180425210000 +0000" stop="20180425223000 +0000" channel="moviechannel.de">
		<title lang="de">Stirb langsam</title>
		<desc lang="de">Der New Yorker Polizist John McClane fährt zum Weihnachtsfest nach Kalifornien, um sich dort mit seiner Frau, die bei einem japanischen Konzern Karriere gemacht hat, zu versöhnen. Als er in dem riesigen Bürohaus ankommt und sich gerade im Waschraum frischmacht, stürmen dreißig schwerbewaffnete Gangs... </desc>
		<credits>
			<director>John McTiernan</director>
			<actor>Bruce Willis</actor>
			<actor>Alan Rickman</actor>
			<actor>Bonnie Bedelia</actor>
		</credits>
		<date>1988</date>
		<category lang="de">Film</category>
	</programme>
</tv>
```
Output XMLTV file (output.xml)
```
<?xml version='1.0' encoding='UTF-8'?>
<tv>
	<channel id="moviechannel.de">
		<display-name lang="en">Die Movie Channel</display-name>
	</channel>
	<programme channel="moviechannel.de" start="20180425210000 +0000" stop="20180425223000 +0000">
		<title lang="xx">Die Hard</title>
		<desc lang="de">Cast: Bruce Willis, Alan Rickman, Alexander Godunov, Bonnie Bedelia, Reginald VelJohnson
Director: John McTiernan
Rating: 7.5

NYPD cop, John McClane's plan to reconcile with his estranged wife is thrown for a serious loop when minutes after he arrives at her office, the entire building is overtaken by a group of terrorists. With little help from the LAPD, wisecracking McClane sets out to single-handedly rescue the hostages and bring the bad guys down.

Year: 1988
Genre: Action, Thriller
Language: English
Country: USA
Popularity: 21.5
Score: 53.5</desc>
		<date>1988</date>
		<category>Movie / Drama</category>
		<sub-title lang="xx">1988 - Action, Thriller</sub-title>
		<icon src="http://image.tmdb.org/t/p/w300/mc7MubOLcIw3MDvnuQFrO9psfCa.jpg" />
		<credits>
			<director>John McTiernan</director>
			<actor>Bruce Willis</actor>
			<actor>Alan Rickman</actor>
			<actor>Alexander Godunov</actor>
			<actor>Bonnie Bedelia</actor>
			<actor>Reginald VelJohnson</actor>
			<actor>Paul Gleason</actor>
			<actor>De'voreaux White</actor>
			<actor>William Atherton</actor>
			<actor>Clarence Gilyard Jr.</actor>
			<actor>Hart Bochner</actor>
		</credits>
		<star-rating>
			<value>7.5/10</value>
		</star-rating>
	</programme>
</tv>
```
## Caveats
* Changing the languages or countries in elastictmdb.conf will not automatically update the languages and/or countries of the movies that have already been cached in the database.
* Matching improves as more and more movies are cached in Elasticsearch and might not be that accurate with only a few movies cached.

## Future Work
This project has been developed for my personal use and I consider it as feature complete as it accomplishes the original deliverable of this project.  The below are list of ideas and improvements which I may implement in future but I cannot give any timelines.

* Create a utility to pre-cache a few hundred or a few thousand movies, to solve the low accuracy with a few movies cached
* Dynamically increase min_score_valid and min_score_no_search parameters based on the number of movies already cached in ElasticSearch.
* Allow for customisation of the description string returned by process_xmltv.py to be able to change order and allow for non-English static text.
* Extend ElasticTMDB to cover also TV shows.
* ~~Migrate to Python3 as Python2 will soon approch [EOL](https://pythonclock.org/).~~
* Ability to increase the document version in Elasticsearch, so that movies can be updated after a language or country has been added to the configuration.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details

## Acknowledgments

* The Movie Database for their awesome database, API and service to the community.
* Elastic.co for developing such great tools and their really best-of-class documentation.

# ElasticTMDB

ElasticTMDB is a Python3 module which sources movie and TV show details from The Movie Database (TMDB) and caches them in an Elasticsearch index to speed up subsequent queries to the same title.

## Features
- Leverages the power of Elasticsearch to search and match titles
- Stores titles in various languages so that a title can be matched with its foreign title. This is particularly useful to match a programme listed in its foreign language
- Uses Jinja2 templates to provide a flexible way to display the data
- Can be used to enrich data stored in [XMLTV](http://wiki.xmltv.org/index.php/Main_Page) format 

## Getting Started

### Prerequisites
* Python 3.6+
* Elasticsearch 7.x (7.5+ is recommended)
* TMDB API key

### Python Modules
Install dependencies by executing
```
pip3 install -r requirements.txt
```

### Elasticsearch
There are various ways to get started with Elasticseach by following [these instructions.](https://www.elastic.co/downloads/elasticsearch) The easiest ways are:
- Install through [Docker](https://www.elastic.co/guide/en/elasticsearch/reference/current/docker.html)
- Setup a 14-day trail on [Elastic Cloud](https://cloud.elastic.co/)

Storing tens of thousands of records will only require a few hundred MBs and since Elasticsearch is used just for caching, it can be setup as a single node cluster as all data can be retrieved back from TMDB.
The indexes will be created with 1 shard and no replicas so optimised for a single node cluster. You can modify the `number_of_shards` and `number_of_replicas` value in the [mapping](elastictmdb/index_mapping) files if you would like to create the indexes with more shards and with replicas.

If you already have Elasticsearch installed, you can use it along side other applications as ElasticTMDB will create 5 indexes on first execution and will not interfere with any other indexes present.

### TMDB API Key
Obtain a key to The Movie Database to access the API. To obtain the API key, follow these steps:

* Register and verify an account.
* Log into your account.
* Select the API section on left side of your account page or follow this [link](https://www.themoviedb.org/settings/api)
* Click on the link to generate a new API key and follow the instructions.

### Configuring
Clone or [download](https://github.com/shaunschembri/ElasticTMDB/archive/master.zip) this repository.
Default settings are fine to get started with but you can change the settings by modifying the [config](elastictmdb/config.py) file. 
Empty indexes are not useful so it highly recommended to cache a few titles first.  Once can use the `cache_title.py` utility to cache the most popular movies and shows. By default the utility will cache 1000 movies and TV shows, but this can be changed via command line parameters.

## Usage

### get_movie_details

The simplest way to use ElasticTMDB (but not really useful) is to run the `get_details.py` and pass the query details as command line parameters.
It will either return a JSON document with the details or uses a Jinja2 template to format the results

```
usage: get_details.py [-h] [-m] [-t] -n TITLE [-d DIRECTOR] [-a ACTOR]
                      [-y YEAR] [-s MINSCORE] [-f] [-j] [-v]

required arguments:
  -n TITLE, --title TITLE
                        Name of title

optional arguments:
  -m, --movie           Cache Only Movie Titles
  -t, --tvshow          Cache Only TV Titles
  -d DIRECTOR, --director DIRECTOR
                        Name of director. Can be used more then once to
                        specify more the 1 director
  -a ACTOR, --actor ACTOR
                        Name of actor. Can be used more then once to specify
                        more cast members
  -y YEAR, --year YEAR  Movie release year
  -s MINSCORE, --minscore MINSCORE
                        Minimum score to accept as a valid result
  -f, --force           Force a search on TMDB before returning results
  -j, --json            Output result in JSON
  -v, --verbose         Enable debug/verbose output
```
Example
```
$ TMDB_API_KEY=<api_key> python3 get_details.py -m -n "Star Wars Skywalker" -y 2019 -a "Adam Driver" -a "Carrie Fisher" -d "J.J. Abrams"
Title : Star Wars: The Rise of Skywalker

The surviving Resistance faces the First Order once again as the journey of Rey, Finn and Poe Dameron continues. With the power and knowledge of generations behind them, the final battle begins.

Cast: Carrie Fisher, Mark Hamill, Adam Driver, Daisy Ridley, John Boyega
Director: J.J. Abrams
Genre: Action, Adventure, Science Fiction
Year: 2019
Country: United States of America
Rating: 6.6
Language: English
Score: 67.1
```

### process_xmltv

A more useful application of ElasticTMDB is to process an XMLTV file with `process_xmltv.py` which takes one or more XMLTV files as input.
The utility will try to guess which programmes are movies or tvshows and updates the programme entry with details as sourced from TMDB. Other programmes are not touched.

```
usage: process_xmltv.py [-h] [-i INPUT] [-o OUTPUT] [-l LOGFILE] [-f] [-d]

required arguments:
  -i INPUT, --input INPUT
                        Input XMLTV file
  -o OUTPUT, --output OUTPUT
                        Output XMLTV file

optional arguments:
  -l LOGFILE, --logfile LOGFILE
                        Output log to file
  -f, --force           Force search for all movies
  -d, --debug           Enable debug
```
Example
```
TMDB_API_KEY=<api_key> python3 process_xmltv.py -i input.xml -o output.xml
```
Input XMLTV file (input.xml)
```xml
<tv>
  <programme start="20200101203000 +0000" stop="20200101213000 +0000" channel="channel.id">
    <title lang="it">Covert affairs</title>
    <credits>
      <actor>Piper Perabo</actor>
    </credits>
    <category lang="en">Episode</category>
    <episode-num system="onscreen">S05E05</episode-num>
  </programme>
<programme start="20200102203000 +0000" stop="20200102234500 +0000" channel="channel.id">
    <title lang="it">Terminator 2: il giorno del giudizio</title>
    <desc lang="it">Secondo capitolo della saga e vincitore di 4 premi Oscar. Sarah e suo figlio sono minacciati da un nuovo Terminator, ma qualcuno accorre in loro aiuto. Regia di J. Cameron; USA 1991</desc>
    <credits>
      <director>James Cameron</director>
      <actor>Arnold Schwarzenegger</actor>
    </credits>
    <date>1991</date>
    <category lang="it">Film</category>
  </programme>
</tv>
```
Output XMLTV file (output.xml)
```xml
<tv>
  <programme start="20200101203000 +0000" stop="20200101213000 +0000" channel="channel.id">
    <title lang="en">Covert Affairs</title>
    <credits>
      <actor>Piper Perabo</actor>
      <actor>Christopher Gorham</actor>
      <actor>Kari Matchett</actor>
      <actor>Peter Gallagher</actor>
      <actor>Nic Bishop</actor>
      <actor>Hill Harper</actor>
      <actor>Michelle Ryan</actor>
    </credits>
    <category lang="en">Drama</category>
    <category lang="en">Action &amp; Adventure</category>
    <episode-num system="onscreen">S05E05</episode-num>
    <desc lang="en">A young CIA operative, Annie Walker, is mysteriously summoned to headquarters for duty as a field operative. While Annie believes she's been promoted for her exceptional linguistic skills, there may be something or someone from her past that her CIA bosses are really after. Auggie Anderson is a CIA military intelligence agent who was blinded while on assignment and is Annie's guide in this world of bureaucracy, excitement and intrigue.

Title: Elevate Me Later
Number: S05E05
First Aired: 2014-07-22
Score: 12.1</desc>
    <sub-title lang="en">S05E05 - Elevate Me Later</sub-title>
    <icon src="http://image.tmdb.org/t/p/w300/9IA2X82vyoOXX570Pa6bEgemyNJ.jpg"/>
    <date>2010</date>
    <country lang="en">United States of America</country>
    <star-rating>
      <value>6.6/10</value>
    </star-rating>
  </programme>
  <programme start="20200102203000 +0000" stop="20200102234500 +0000" channel="channel.id">
    <title lang="en">Terminator 2: Judgment Day</title>
    <desc lang="en">Nearly 10 years have passed since Sarah Connor was targeted for termination by a cyborg from the future. Now her son, John, the future leader of the resistance, is the target for a newer, more deadly terminator. Once again, the resistance has managed to send a protector back to attempt to save John and his mother Sarah.

Cast: Arnold Schwarzenegger, Linda Hamilton, Robert Patrick, Edward Furlong, Michael Edwards
Director: James Cameron
Genre: Action, Thriller, Science Fiction
Year: 1991
Country: United States of America
Rating: 8.0
Language: English
Score: 52.8</desc>
    <credits>
      <director>James Cameron</director>
      <actor>Arnold Schwarzenegger</actor>
      <actor>Linda Hamilton</actor>
      <actor>Robert Patrick</actor>
      <actor>Edward Furlong</actor>
      <actor>Michael Edwards</actor>
      <actor>Joe Morton</actor>
      <actor>Earl Boen</actor>
      <actor>Jenette Goldstein</actor>
      <actor>Xander Berkeley</actor>
      <actor>S. Epatha Merkerson</actor>
    </credits>
    <date>1991</date>
    <category lang="en">Action</category>
    <category lang="en">Thriller</category>
    <category lang="en">Science Fiction</category>
    <sub-title lang="en">1991 - Action, Thriller, Science Fiction</sub-title>
    <icon src="http://image.tmdb.org/t/p/w300/4xc8LiXJgscRzMnVvL7xn8vhjxR.jpg"/>
    <country lang="en">United States of America</country>
    <star-rating>
      <value>8.0/10</value>
    </star-rating>
  </programme>
</tv>
```

## Future Work
* Containerise the application
* Create a Docker Compose file to easily get started
* Publish to PyPy

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details

## Acknowledgments

* The Movie Database (TMDB) for their awesome database, API and service to the community.
* Elastic.co for developing such great tools and their really best-of-class documentation.

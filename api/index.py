from flask import Flask, request, jsonify, render_template, redirect, url_for
from pymongo import MongoClient
from pymongo.server_api import ServerApi
import requests
from datetime import datetime, timedelta
import os
import xml.etree.ElementTree as ET

app = Flask(__name__)

app.config["MONGO_URI"] = os.environ.get('MONGODB_URI')
client = MongoClient(app.config["MONGO_URI"], server_api=ServerApi('1'))
db = client.arewethereyet
cancer_collection = db.cancer

EUTILS_API_KEY = os.environ.get('EUTILS_API_KEY')





@app.route('/cancer-feed')
def cancer_feed():
    current_time = datetime.now()
    three_days_ago = current_time - timedelta(days=3)
    today_start = datetime(current_time.year, current_time.month, current_time.day)
    
    # Fetch and limit publications from the cancer collection
    publications_cursor = cancer_collection.find({
        "published_date": {"$gte": three_days_ago.strftime('%Y-%b-%d %H:%M:%S')}
    }).sort("published_date", -1).limit(50)  # Sort by published_date in descending order and limit to 50 results
    
    publications = list(publications_cursor)

    today_count = cancer_collection.count_documents({
        "published_date": {"$gte": today_start.strftime('%Y-%b-%d %H:%M:%S')}
    })
    
    return render_template('cancer-feed.html', publications=publications, today_count=today_count)







@app.route('/update-feed', methods=['POST'])
def update_feed():
    current_time = datetime.now()
    date_key = current_time.strftime('%Y-%b-%d')
    time_key = current_time.strftime('%H:%M:%S')

    three_days_ago = (current_time - timedelta(days=3)).strftime('%Y-%b-%d')
    base_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi'
    params = {
        'db': 'pubmed',
        'term': 'cancer',
        'retmax': '100',
        'datetype': 'pdat',
        'mindate': (current_time - timedelta(days=1)).strftime('%Y/%m/%d'),
        'maxdate': current_time.strftime('%Y/%m/%d'),
        'usehistory': 'y',
        'api_key': EUTILS_API_KEY
    }
    response = requests.get(base_url, params=params)
    root = ET.fromstring(response.content)

    web_env = root.find(".//WebEnv").text
    query_key = root.find(".//QueryKey").text

    if web_env and query_key:
        fetch_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi'
        fetch_params = {
            'db': 'pubmed',
            'query_key': query_key,
            'WebEnv': web_env,
            'retmode': 'xml',
            'rettype': 'abstract',
            'api_key': EUTILS_API_KEY
        }
        articles_response = requests.get(fetch_url, params=fetch_params)
        articles_root = ET.fromstring(articles_response.content)

        for article in articles_root.findall(".//PubmedArticle"):
            article_id = article.find(".//PMID").text
            existing_article = cancer_collection.find_one({"pmid": article_id})
            if not existing_article:
                article_info = extract_article_info(article)
                article_info["pmid"] = article_id
                cancer_collection.insert_one(article_info)

        return jsonify({"message": "Feed updated successfully"}), 200
    else:
        return jsonify({"error": "Failed to fetch data from PubMed"}), 500





def extract_article_info(article):
    # Extract and return all necessary article information
    return {
        "title": article.find(".//ArticleTitle").text,
        "abstract": article.find(".//Abstract/AbstractText").text if article.find(".//Abstract/AbstractText") is not None else "No abstract available",
        "authors": [author.find('LastName').text + ", " + author.find('ForeName').text for author in article.findall(".//Author") if author.find('LastName') is not None and author.find('ForeName') is not None],
        "published_date": datetime.now().strftime('%Y-%b-%d %H:%M:%S'),
        "language": article.find(".//Language").text if article.find(".//Language") is not None else "Not specified",
        "publication_type": [pt.text for pt in article.findall(".//PublicationType")],
        "citation_count": article.find(".//CitedMediumCount").text if article.find(".//CitedMediumCount") is not None else "0",
        "journal_info": article.find(".//Journal/Title").text if article.find(".//Journal/Title") is not None else "Journal info not available",
        "link": f"https://pubmed.ncbi.nlm.nih.gov/{article.find('.//PMID').text}/"
    }

if __name__ == '__main__':
    app.run(debug=True)














# Incremental: These are publications that contribute small, yet important, pieces of knowledge to existing research. They often validate, refute, or refine previous findings. Such studies might not revolutionize understanding or treatment but are essential for the gradual advancement of scientific knowledge.

# Major Advance: Articles in this category represent significant progress in the field. They might introduce new understanding, novel methodologies, or substantial improvements in treatment efficacy. These publications often influence future research directions and can lead to new therapeutic approaches or diagnostic tools.

# Breakthrough: This is reserved for the most impactful articles, which you've already defined. Breakthrough studies introduce revolutionary ideas or findings that fundamentally change understanding or significantly alter treatment paradigms. These might include a new cure, a highly effective vaccine, or a groundbreaking technology in cancer research.
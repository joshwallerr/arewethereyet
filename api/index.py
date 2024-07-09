from flask import Flask, request, jsonify, render_template, redirect, url_for
from pymongo import MongoClient, UpdateOne
from pymongo.server_api import ServerApi
import requests
from datetime import datetime, timedelta
import os
import xml.etree.ElementTree as ET
import boto3
from botocore.exceptions import ClientError

app = Flask(__name__)

app.config["MONGO_URI"] = os.environ.get('MONGODB_URI')
client = MongoClient(app.config["MONGO_URI"], server_api=ServerApi('1'))

db = client.arewethereyet
cancer_collection = db.cancer
heart_disease_collection = db.heart_disease
alzheimers_collection = db.alzheimers
diabetes_collection = db.diabetes
lung_disease_collection = db.lung_disease



subscribers_collection = db.subscribers

EUTILS_API_KEY = os.environ.get('EUTILS_API_KEY')





collection_mapping = {
    'cancer': db.cancer,
    'cardio': db.heart_disease,
    'alzheimer': db.alzheimers,
    'diabetes': db.diabetes,
    'pulmonary': db.lung_disease
}





@app.route('/')
def index():
    return render_template('index.html')


@app.route('/subscribe', methods=['POST'])
def subscribe():
    email = request.form.get('email')
    cancer_type = request.form.get('cancer_type')

    existing_subscriber = subscribers_collection.find_one({"email": email, "cancer_type": cancer_type})
    if existing_subscriber:
        return jsonify({"error": "You are already subscribed"}), 400

    if email and cancer_type:
        subscribers_collection.insert_one({
            "email": email,
            "cancer_type": cancer_type,
            "subscribed_date": datetime.now().strftime('%Y-%b-%d %H:%M:%S')
        })
        return jsonify({"message": "Subscription successful"}), 200
    else:
        return jsonify({"error": "Invalid email"}), 400








def get_publications(collection):
    current_time = datetime.now()
    three_days_ago = current_time - timedelta(days=3)
    today_start = datetime(current_time.year, current_time.month, current_time.day)

    # get the most recent 50 publications. published_date is a string in the format 'YYYY-MMM-DD HH:MM:SS'
    publications_cursor = collection.find().sort("published_date", -1).limit(50)

    publications = list(publications_cursor)

    today_count = collection.count_documents({
        "published_date": {"$gte": today_start.strftime('%Y-%b-%d %H:%M:%S')}
    })

    print(today_start)
    print(today_start.strftime('%Y-%b-%d %H:%M:%S'))

    return publications, today_count



@app.route('/cancer')
def cancer_feed():
    publications, today_count = get_publications(cancer_collection)
    return render_template('feed.html', publications=publications, today_count=today_count)

@app.route('/heart-disease')
def heart_disease_feed():
    publications, today_count = get_publications(heart_disease_collection)
    return render_template('feed.html', publications=publications, today_count=today_count)

@app.route('/alzheimers')
def alzheimers_feed():
    publications, today_count = get_publications(alzheimers_collection)
    return render_template('feed.html', publications=publications, today_count=today_count)

@app.route('/diabetes')
def diabetes_feed():
    publications, today_count = get_publications(diabetes_collection)
    return render_template('feed.html', publications=publications, today_count=today_count)

@app.route('/lung-disease')
def lung_disease_feed():
    publications, today_count = get_publications(lung_disease_collection)
    return render_template('feed.html', publications=publications, today_count=today_count)

@app.route('/load-more/<int:offset>')
def load_more(offset):
    publications_cursor = cancer_collection.find().sort("published_date", -1).skip(offset).limit(50)
    publications = list(publications_cursor)
    return render_template('partials/publications.html', publications=publications)











# Make seperate template for search results or make the table into a partial and render it in the same template

@app.route('/cancer/search')
def search_cancer():
    query = request.args.get('q')
    if query:
        current_time = datetime.now()
        today_start = datetime(current_time.year, current_time.month, current_time.day)

        search_criteria = {
            "$or": [
                {"title": {"$regex": query, "$options": "i"}},
                {"abstract": {"$regex": query, "$options": "i"}}
            ]
        }
        publications_cursor = cancer_collection.find(search_criteria).sort("published_date", -1).limit(50)
        publications = list(publications_cursor)
        
        today_count = cancer_collection.count_documents({
            "published_date": {"$gte": today_start.strftime('%Y-%b-%d %H:%M:%S')}
        })

        return render_template('feed.html', publications=publications, query=query, today_count=today_count)
    else:
        return redirect(url_for('cancer_feed'))
















@app.route('/update-feed', methods=['POST'])
def update_feed():
    start_time = datetime.now()  # Start timing

    search_term = request.json['disease']

    if search_term not in collection_mapping:
        return jsonify({"error": "Invalid disease"}), 400

    current_collection = collection_mapping.get(search_term)

    current_time = datetime.now()
    base_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi'
    params = {
        'db': 'pubmed',
        'term': search_term,
        'retmax': '100',
        'datetype': 'pdat',
        'mindate': (current_time - timedelta(days=1)).strftime('%Y/%m/%d'),
        'maxdate': current_time.strftime('%Y/%m/%d'),
        'usehistory': 'y',
        'api_key': EUTILS_API_KEY
    }
    response = requests.get(base_url, params=params)

    # print the time taken so far
    print('Fetched search results. Time elapsed so far:', (datetime.now() - start_time).total_seconds(), 'seconds')

    root = ET.fromstring(response.content)

    # print the time taken so far
    print('Parsed search results. Time elapsed so far:', (datetime.now() - start_time).total_seconds(), 'seconds')

    web_env = root.find(".//WebEnv").text
    query_key = root.find(".//QueryKey").text

    print('Found WebEnv and QueryKey:', web_env, 'and QueryKey:', query_key)

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

        print('Fetched articles. Time elapsed so far:', (datetime.now() - start_time).total_seconds(), 'seconds')

        articles_root = ET.fromstring(articles_response.content)

        # Print the time taken so far
        mid_time = datetime.now()
        print('Starting bulk write. Time elapsed so far:', (mid_time - start_time).total_seconds(), 'seconds')

        bulk_operations = []
        new_articles = []
        for article in articles_root.findall(".//PubmedArticle"):
            article_info = extract_article_info(article)
            new_articles.append(article_info)
            operation = UpdateOne(
                {'abstract': article_info['abstract']},  # Condition
                {'$setOnInsert': article_info},  # Update
                upsert=True  # Upsert option
            )
            bulk_operations.append(operation)

        existing_abstracts = [article['abstract'] for article in current_collection.find({"abstract": {"$in": [article['abstract'] for article in new_articles]}})]

        print('Existing articles:', len(existing_abstracts))

        if bulk_operations:
            current_collection.bulk_write(bulk_operations)

        new_articles = [article for article in new_articles if article['abstract'] not in existing_abstracts]

        print('New articles:', len(new_articles))

        subscribers = subscribers_collection.find()
        for subscriber in subscribers:
            matching_articles = [article for article in new_articles if subscriber['cancer_type'].lower() in ((article['title'] if article['title'] is not None else '') + ' ' + (article['abstract'] if article['abstract'] is not None else '')).lower()]
            if matching_articles:
                send_notification_email(subscriber['email'], matching_articles)


        # Final time print before sending response
        end_time = datetime.now()
        print('Bulk write completed. Total time elapsed:', (end_time - start_time).total_seconds(), 'seconds')

        return jsonify({"message": "Feed updated successfully"}), 200
    else:
        end_time = datetime.now()
        print('Failed to fetch data. Time elapsed:', (end_time - start_time).total_seconds(), 'seconds')
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







def send_notification_email(email, articles):
    # Your AWS region, e.g., 'us-west-2', 'us-east-1', etc.
    AWS_REGION = "us-east-1"

    # The subject line for the email.
    SUBJECT = "New Cancer Studies Update"

    # The email body for recipients with non-HTML email clients.
    BODY_TEXT = ("New Cancer Studies Update\r\n"
                 "Here are the latest articles related to your interest:\n" +
                 "\n".join([f"{article['title']} - {article['link']}" for article in articles]))

    # The HTML body of the email.
    BODY_HTML = """<html>
    <head></head>
    <body>
      <h1>New Cancer Studies Update</h1>
      <p>Here are the latest articles related to your interest:</p>
      <ul>""" + "".join([f"<li><a href='{article['link']}'>{article['title']}</a></li>" for article in articles]) + """</ul>
    </body>
    </html>
    """

    # The character encoding for the email.
    CHARSET = "UTF-8"

    # Create a new SES resource and specify a region.
    client = boto3.client('ses', region_name=AWS_REGION)

    # Try to send the email.
    try:
        # Provide the contents of the email.
        response = client.send_email(
            Destination={
                'ToAddresses': [
                    email,
                ],
            },
            Message={
                'Body': {
                    'Html': {
                        'Charset': CHARSET,
                        'Data': BODY_HTML,
                    },
                    'Text': {
                        'Charset': CHARSET,
                        'Data': BODY_TEXT,
                    },
                },
                'Subject': {
                    'Charset': CHARSET,
                    'Data': SUBJECT,
                },
            },
            Source="josh@arewethereyet.info",
        )
    # Display an error if something goes wrong.
    except ClientError as e:
        print(e.response['Error']['Message'])
    else:
        print("Email sent! Message ID:"),
        print(response['MessageId'])













if __name__ == '__main__':
    app.run(debug=True)














# Incremental: These are publications that contribute small, yet important, pieces of knowledge to existing research. They often validate, refute, or refine previous findings. Such studies might not revolutionize understanding or treatment but are essential for the gradual advancement of scientific knowledge.

# Major Advance: Articles in this category represent significant progress in the field. They might introduce new understanding, novel methodologies, or substantial improvements in treatment efficacy. These publications often influence future research directions and can lead to new therapeutic approaches or diagnostic tools.

# Breakthrough: This is reserved for the most impactful articles, which you've already defined. Breakthrough studies introduce revolutionary ideas or findings that fundamentally change understanding or significantly alter treatment paradigms. These might include a new cure, a highly effective vaccine, or a groundbreaking technology in cancer research.
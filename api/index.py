import os
from flask import Flask, request, render_template, redirect, url_for
from pymongo import MongoClient
import boto3
import requests
from datetime import datetime, timedelta
from bson.objectid import ObjectId

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your_secret_key')  # Replace with a secure key

# MongoDB setup
MONGODB_URI = os.environ.get('MONGODB_URI')
client = MongoClient(MONGODB_URI)
db = client['pubmed_app']
subscriptions = db['subscriptions']

# AWS SES setup
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')

ses_client = boto3.client(
    'ses',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION
)

# Home route: Display form
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        email = request.form.get('email')
        disease = request.form.get('disease')

        if not email or not disease:
            return redirect(url_for('index'))

        # Insert into MongoDB
        subscription = {
            'email': email,
            'disease': disease,
            'subscribed_at': datetime.utcnow()
        }
        subscriptions.insert_one(subscription)
        return redirect(url_for('index'))

    return render_template('index.html')

# Trigger route: Called by GitHub Action
@app.route('/trigger', methods=['POST'])
def trigger():
    token = request.headers.get('Authorization')
    if token != f"Bearer {os.environ.get('TRIGGER_TOKEN')}":
        return {'status': 'Unauthorized'}, 401

    try:
        users = list(subscriptions.find())
        for user in users:
            email = user['email']
            disease = user['disease']
            studies = search_pubmed(disease)
            if studies:
                send_email(email, disease, studies)
        return {'status': 'Emails sent successfully.'}, 200
    except Exception as e:
        return {'status': 'An error occurred.', 'error': str(e)}, 500

def search_pubmed(disease):
    """
    Search PubMed for studies related to the disease published in the last 24 hours.
    Returns a list of studies with title and URL.
    """
    base_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi'
    params = {
        'db': 'pubmed',
        'term': disease,
        'sort': 'pub date',
        'retmode': 'json',
        'retmax': 100,
        'reldate': 1,  # Last 1 day
        'datetype': 'pdat'
    }

    response = requests.get(base_url, params=params)
    if response.status_code != 200:
        print(f"Error fetching PubMed data: {response.status_code}")
        return []

    data = response.json()
    id_list = data.get('esearchresult', {}).get('idlist', [])

    if not id_list:
        return []

    # Fetch details for each ID
    fetch_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi'
    fetch_params = {
        'db': 'pubmed',
        'id': ','.join(id_list),
        'retmode': 'xml',
        'rettype': 'abstract'
    }

    fetch_response = requests.get(fetch_url, params=fetch_params)
    if fetch_response.status_code != 200:
        print(f"Error fetching PubMed abstracts: {fetch_response.status_code}")
        return []

    from xml.etree import ElementTree as ET
    root = ET.fromstring(fetch_response.content)
    studies = []
    for article in root.findall('.//PubmedArticle'):
        title = article.find('.//ArticleTitle')
        article_id = article.find('.//PMID')
        if title is not None and article_id is not None:
            studies.append({
                'title': title.text,
                'url': f"https://pubmed.ncbi.nlm.nih.gov/{article_id.text}/"
            })

    return studies

def send_email(recipient, disease, studies):
    """
    Sends an email via AWS SES to the recipient with the list of studies.
    """
    subject = f"New PubMed Studies on {disease}"
    if not studies:
        body = f"No new studies found for {disease} in the last 24 hours."
    else:
        body = f"Hello,\n\nHere are the new PubMed studies related to {disease} published in the last 24 hours:\n\n"
        for study in studies:
            body += f"- {study['title']}\n  Link: {study['url']}\n\n"
        body += "Best regards,\nYour PubMed Alert Service"

    response = ses_client.send_email(
        Source=SENDER_EMAIL,
        Destination={
            'ToAddresses': [recipient]
        },
        Message={
            'Subject': {
                'Data': subject,
                'Charset': 'UTF-8'
            },
            'Body': {
                'Text': {
                    'Data': body,
                    'Charset': 'UTF-8'
                }
            }
        }
    )
    print(f"Email sent to {recipient}: Message ID {response['MessageId']}")

if __name__ == '__main__':
    # For local development only; Vercel handles deployment
    app.run(host='0.0.0.0', port=5000, debug=True)
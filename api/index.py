import os
from flask import Flask, request, render_template, redirect, url_for
from pymongo import MongoClient
import boto3
import requests
from datetime import datetime, timedelta
from bson.objectid import ObjectId
from collections import Counter
import calendar

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your_secret_key')  # Replace with a secure key

# MongoDB setup
MONGODB_URI = os.environ.get('MONGODB_URI')
client = MongoClient(MONGODB_URI)
db = client['arewethereyet']
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
        print('Form submitted')
        email = request.form.get('email')
        disease = request.form.get('disease')

        print(f'Email: {email}, Disease: {disease}')

        if not email or not disease:
            print('Invalid form data')
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
    print(f"{token}")
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

# New route for overview
@app.route('/overview')
def overview():
    disease = request.args.get('q')
    if not disease:
        return redirect(url_for('index'))

    # Search PubMed for the last 7 days
    studies = search_pubmed_overview(disease)

    if not studies:
        # No studies found, handle accordingly
        return render_template('overview.html', disease=disease, message='No studies found for the last 7 days.')

    # Process data for analytics
    # Volume of publications per day
    # Proportion of publication types
    # List of clinical trials

    # Count publications per day
    date_counts = Counter()
    publication_types_counts = Counter()
    clinical_trials = []

    for study in studies:
        pub_date = study.get('pub_date')
        if pub_date:
            date_str = pub_date.strftime('%Y-%m-%d')
            date_counts[date_str] += 1

        # Count publication types
        for pub_type in study.get('publication_types', []):
            publication_types_counts[pub_type] += 1

        # Collect clinical trials
        if 'Clinical Trial' in study.get('publication_types', []):
            clinical_trials.append(study)

    # Prepare data for line graph (volume per day)
    today = datetime.utcnow().date()
    dates_list = [(today - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(6, -1, -1)]
    volume_per_day = {
        'dates': dates_list,
        'counts': [date_counts.get(date, 0) for date in dates_list]
    }

    # Prepare data for pie chart (proportion of publication types)
    pub_types = list(publication_types_counts.keys())
    pub_counts = list(publication_types_counts.values())
    proportion_of_publication_types = {
        'types': pub_types,
        'counts': pub_counts
    }

    return render_template('overview.html',
                           disease=disease,
                           volume_per_day=volume_per_day,
                           proportion_of_publication_types=proportion_of_publication_types,
                           clinical_trials=clinical_trials)

def search_pubmed_overview(disease):
    """
    Search PubMed for studies related to the disease published in the last 7 days.
    Returns a list of studies with title, URL, publication date, and publication types.
    """
    base_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi'
    params = {
        'db': 'pubmed',
        'term': disease,
        'sort': 'pub date',
        'retmode': 'json',
        'retmax': 1000,  # Increased max results
        'reldate': 7,  # Last 7 days
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
        title_elem = article.find('.//ArticleTitle')
        article_id_elem = article.find('.//PMID')
        pub_date = extract_pub_date(article)
        publication_types_elems = article.findall('.//PublicationType')
        if title_elem is not None and article_id_elem is not None:
            # Extract publication types
            publication_types = []
            for pub_type_elem in publication_types_elems:
                if pub_type_elem.text:
                    publication_types.append(pub_type_elem.text)
            studies.append({
                'title': title_elem.text,
                'url': f"https://pubmed.ncbi.nlm.nih.gov/{article_id_elem.text}/",
                'pub_date': pub_date,
                'publication_types': publication_types
            })

    return studies

def extract_pub_date(article):
    """
    Extracts the publication date from a PubMed article XML element.
    """
    # Try PubDate in MedlineCitation/Article/Journal/JournalIssue/PubDate
    pub_date_elem = article.find('.//JournalIssue/PubDate')
    if pub_date_elem is not None:
        year = pub_date_elem.findtext('Year')
        month = pub_date_elem.findtext('Month')
        day = pub_date_elem.findtext('Day')
        if year and month:
            try:
                # Convert month to number
                if month.isdigit():
                    month_number = int(month)
                else:
                    month_number = list(calendar.month_abbr).index(month[:3].capitalize())
                    if month_number == 0:
                        month_number = list(calendar.month_name).index(month.capitalize())
                day_number = int(day) if day else 1
                return datetime(int(year), month_number, day_number)
            except ValueError:
                pass
    # Try ArticleDate in MedlineCitation/Article/ArticleDate
    article_date_elem = article.find('.//ArticleDate')
    if article_date_elem is not None:
        year = article_date_elem.findtext('Year')
        month = article_date_elem.findtext('Month')
        day = article_date_elem.findtext('Day')
        if year and month and day:
            try:
                return datetime(int(year), int(month), int(day))
            except ValueError:
                pass
    # Try PubMedPubDate in PubmedData/History/PubMedPubDate
    pubmed_pub_date_elems = article.findall('.//PubMedPubDate')
    for pubmed_pub_date_elem in pubmed_pub_date_elems:
        if pubmed_pub_date_elem.get('PubStatus') == 'pubmed':
            year = pubmed_pub_date_elem.findtext('Year')
            month = pubmed_pub_date_elem.findtext('Month')
            day = pubmed_pub_date_elem.findtext('Day')
            if year and month and day:
                try:
                    return datetime(int(year), int(month), int(day))
                except ValueError:
                    pass
    return None

if __name__ == '__main__':
    # For local development only; Vercel handles deployment
    app.run(host='0.0.0.0', port=5000, debug=True)
import csv
from datetime import datetime, timedelta
from fec_api import get_schedule_a, get_committee, get_affiliated_committees, get_party, get_candidate
from twitter import fetch_data_and_build_tweets, TweetStatus

# Runs once per day #TODO update to hourly, will need to track what has been posted
min_date = datetime.now() - timedelta(days=1)
transactions = []
with open('transactions.csv', 'r') as csv_file:
    reader_obj = csv.reader(csv_file)
    # Iterate over each row in the csv
    # file using reader object
    for row in reader_obj:
        transactions.append(row[0])

tweets = fetch_data_and_build_tweets(min_load_date=min_date.strftime('%Y-%m-%d'), min_amount=1e6, transactions=transactions)

for tweet in tweets:
    if tweet.status == TweetStatus.PENDING:
        tweet.post()


#TODO
# 1. shorten URL
# 2. tweet class
# 3. wikipedia intergration
# 4. Get pictures from website of committee
# 5. Generate pictures
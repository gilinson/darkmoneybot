import csv
import sys
import argparse
import logging
from datetime import datetime, timedelta
from fec_api import get_schedule_a, get_committee, get_affiliated_committees, get_party, get_candidate
from twitter import fetch_schedule_a_data_and_build_tweets, fetch_schedule_e_data_and_build_tweets, TweetStatus


logging.basicConfig(format='%(asctime)s: %(message)s', stream=sys.stdout, level=logging.INFO)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run_level", type=int)
    args = vars(parser.parse_args())
    run_level = args['run_level']

    logging.info(f'Run level: {run_level}')
    min_load_date = datetime.now() - timedelta(days=1)
    min_file_date = datetime.now() - timedelta(days=14)

    total_posts = 0
    POST_CAP = 3

    transactions = []
    with open('transactions.csv', 'r') as csv_file:
        reader_obj = csv.reader(csv_file)
        # Iterate over each row in the csv
        # file using reader object
        for row in reader_obj:
            transactions.append(row[0])

    tweets_a = fetch_schedule_a_data_and_build_tweets(
       min_load_date=min_load_date.strftime('%Y-%m-%d'),
       min_amount=2.5e5,
       contributor_type='individual',
       transactions=transactions
    )

    for tweet in tweets_a:
        if total_posts > POST_CAP:
            logging.info(f'Hit Post Cap')
            break
        if tweet.status == TweetStatus.PENDING:
            try:
                tweet.post(run_level=run_level)
                total_posts += 1
            except Exception as error:
                logging.info(error)
        else:
            logging.info(f'Skipping {tweet.transaction_id} because {tweet.build_issues}')

    min_load_date = datetime.now() - timedelta(days=3)
    tweets_e = fetch_schedule_e_data_and_build_tweets(
        min_filing_date=min_file_date.strftime('%Y-%m-%d'),
        min_load_date=min_load_date.strftime('%Y-%m-%d'),
        min_dissemination_date=min_load_date.strftime('%Y-%m-%d'),
        min_amount=1e5,
        transactions=transactions
    )


    for tweet in tweets_e:
        if total_posts > POST_CAP:
            logging.info(f'Hit Post Cap')
            break
        if tweet.status == TweetStatus.PENDING:
            try:
                tweet.post(run_level=run_level)
                total_posts += 1
            except Exception as error:
                logging.info(error)
        else:
            logging.info(f'Skipping {tweet.transaction_id} because {tweet.build_issues}')

    for tweet in tweets_e:
        if tweet.status == TweetStatus.POSTED:
            reply_tweet = tweet.gen_reply_tweet()
            if reply_tweet.status == TweetStatus.PENDING:
                reply_tweet.post(run_level=run_level)

    logging.info('Run complete')
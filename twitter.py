import urllib
import csv
import requests
import tweepy
import locale
import re
import sys
import logging
from bs4 import BeautifulSoup
from fec_api import get_schedule_a, get_committee, get_affiliated_committees, get_party, get_candidate
from open_secrets import get_committee_info
from states import abbrev_to_us_state
from credentials import twitter_keys

locale.setlocale(locale.LC_ALL, 'en_CA.UTF-8')
logging.basicConfig(format='%(asctime)s: %(message)s', stream=sys.stdout, level=logging.INFO)

base_string = """According to a new filing {contributor_name} gave {amount} to {recipient}, {recipient_description}.

FEC filing: {disclosure_url}
{hashtags}
"""

base_string_no_disclosure_url = \
    """According to a new filing {contributor_name} gave {amount} to {recipient}, {recipient_description}.

{hashtags}
"""


class TweetStatus:
    """
    The status of a tweet
    """
    BLOCKED = -1  # An issue prevents the tweet from being posted
    PENDING = 0  # The tweet has not been posted
    POSTED = 1  # The tweet has been posted


class Tweet:

    def __init__(self, schedule_a):

        self.status = TweetStatus.PENDING
        self.build_issues = []
        self.schedule_a = schedule_a

        self.contributor_name = None
        self.amount = None
        self.recipient = None
        self.recipient_description = None
        self.disclosure_url = None
        self.hashtags = []
        self.emoji = None

        self.lean = None
        self.party = None
        self.designation = None
        self.state_abbrev = None
        self.state_name = None
        self.office = None
        self.candidate_first_name = None
        self.candidate_last_name = None
        self.candidate_description = None
        self.committee_website = None

        self.text = None
        self.media_obj = None
        self.response = None

        self.transaction_id = schedule_a['transaction_id']

    def post(self):
        if self.status != TweetStatus.PENDING:
            raise Exception(f'Tweet with status {self.status} cannot be posted')

        client = tweepy.Client(
            consumer_key=twitter_keys['api_key'],
            consumer_secret=twitter_keys['api_secret_key'],
            access_token=twitter_keys['access_token'],
            access_token_secret=twitter_keys['access_token_secret']
        )
        print(self.text)  # TODO replace with logging
        if self.media_obj is not None:
            self.response = client.create_tweet(text=self.text, media_ids=[self.media_obj.media_id])
        else:
            self.response = client.create_tweet(text=self.text)

        with open('transactions.csv', 'a') as csv_file:
            writer_object = csv.writer(csv_file)
            writer_object.writerow([self.transaction_id])

    def handle_build_error(self, error):
        self.status = self.build_issues.append(error)
        self.status = TweetStatus.BLOCKED

    def build_contributor_name(self):
        """
        Build a string with name of contributor from schedule a
        """
        first = to_title(self.schedule_a['contributor_first_name'])
        middle = to_title(self.schedule_a['contributor_middle_name'])
        last = to_title(self.schedule_a['contributor_last_name'])

        if last is None:
            self.handle_build_error('No last name available')
            return

        if re.search(r'^[a-zA-Z]\.$', first) is not None and middle is not None:
            # First name is just an initial and middle is provided
            self.contributor_name = f'{first} {middle} {last}'
        else:
            self.contributor_name = f'{first} {last}'

    def build_amount(self):
        """
        Build a string with amount of contribution
        """
        amount = self.schedule_a['contribution_receipt_amount']

        if amount is None:
            self.handle_build_error('Amount not available')
            return

        if amount >= 1e6:
            end = 'M'
            amount = round(amount / 1e6, 1)
        else:
            end = ''

        self.amount = locale.currency(amount, grouping=True).rstrip('0').rstrip('.') + end

    def build_recipient(self):
        self.designation = self.schedule_a['committee']['designation']

        if self.designation is None:
            self.handle_build_error('Designation not available')
            return

        if self.designation not in ('P', 'U', 'B', 'D', 'J'):
            # Designation A is not expected, so not implemented
            self.handle_build_error(f'No recipient logic implemented for designation {self.designation}')
            return

        if self.designation == 'P':
            # When we have a candidate associated with schedule_a

            # Candidate isn't always directly listed, so look up always #TODO this logic could be better
            candidate = get_candidate(name=self.schedule_a['contributor_first_name'] + ' ' +
                                           self.schedule_a['contributor_last_name'])
            self.candidate_first_name = to_title(candidate['first_name'])
            self.candidate_last_name = to_title(candidate['last_name'])
            self.office = to_title(candidate['office_full'])
            self.state_abbrev = candidate['state']
            self.party = format_party(candidate['party_full'])
            self.state_name = abbrev_to_us_state[self.state_abbrev]

            self.recipient = f'{self.candidate_first_name} {self.candidate_last_name}'
            self.build_candidate_description()
            self.recipient_description = self.candidate_description
            return

        else:
            self.recipient = to_title(self.schedule_a['committee']['name'])

        if self.designation in ('U', 'B'):
            # U unauthorized
            # B lobbyist/registrant PAC
            self.recipient = to_title(self.schedule_a['committee']['name'])

            # When should we call something using a definite article?
            # When the name ends with "Fund"
            if re.search(r'fund$', self.recipient, flags=re.IGNORECASE) is not None and \
                    not re.search(r'^the', self.recipient, flags=re.IGNORECASE):
                self.recipient = 'The ' + self.recipient

            # Should the entire name be capitalized?
            # When its one word
            if re.search(r'^\w+$', self.recipient) is not None:
                self.recipient = self.recipient.upper()

            # Search open secrets for information on outside funding group
            self.lean, os_candidate_name, os_state, os_party = get_committee_info(
                self.schedule_a['committee']['committee_id'],
                2022  # TODO don't hardcode
            )

            self.lean = self.lean.lower()
            self.recipient_description = f'a {self.lean} group'

            if os_candidate_name is not None and os_state is not None:
                candidate = get_candidate(name=os_candidate_name, state=os_state)
                if candidate is not None:
                    self.candidate_first_name = to_title(candidate['first_name'])
                    self.candidate_last_name = to_title(candidate['last_name'])
                    self.office = to_title(candidate['office_full'])
                    self.state_abbrev = candidate['state']
                    self.party = format_party(candidate['party_full'])
                    self.state_name = abbrev_to_us_state[self.state_abbrev]
                    self.build_candidate_description()
                    self.recipient_description += \
                        f' associated with {self.candidate_first_name} {self.candidate_last_name} '
                    self.recipient_description += self.candidate_description

        if self.designation == 'D':
            # Leadership PAC
            self.recipient = to_title(self.schedule_a['committee']['name'])

            # Look at list of sponsor candidates, extract candidate if possible
            candidate_ids = self.schedule_a['committee'].get('sponsor_candidate_ids')
            if candidate_ids is not None:
                candidate_id = candidate_ids[0]
                candidate = get_candidate(candidate_id=candidate_id)
                self.candidate_first_name = to_title(candidate['first_name'])
                self.candidate_last_name = to_title(candidate['last_name'])
                self.office = to_title(candidate['office_full'])
                self.state_abbrev = candidate['state']
                self.party = format_party(candidate['party_full'])
                self.state_name = abbrev_to_us_state[self.state_abbrev]
                self.build_candidate_description()
                self.recipient_description = \
                    f'leadership PAC associated with {self.candidate_first_name} {self.candidate_last_name} '
                self.recipient_description += self.candidate_description

            else:
                self.recipient_description = 'a leadership PAC'

        if self.designation == 'J':
            # Joint funding group
            affiliated_committees = get_affiliated_committees(self.schedule_a)
            self.party = to_title(get_party(affiliated_committees))
            self.recipient = to_title(self.schedule_a['committee']['name'])
            if self.party is not None:
                self.recipient_description = f'a joint funding raising committee associated with the {self.party} party.'
            else:
                self.recipient_description = 'a joint funding raising committee'

    def build_disclosure_url(self):
        self.disclosure_url = self.schedule_a['pdf_url']

    def build_hashtags(self):
        self.hashtags.append('Election2022')
        if self.state_name is not None and self.state_name != 'US':
            self.hashtags.append(self.state_name.replace(' ', ''))
        if self.state_name is not None and self.state_name != 'US' and self.office is not None:
            state_race = self.state_name + self.office
            self.hashtags.append(state_race.replace(' ', ''))
        if self.candidate_first_name is not None and self.candidate_last_name is not None:
            candidate_name = self.candidate_first_name + self.candidate_last_name
            self.hashtags.append(candidate_name.replace(' ', ''))
        self.hashtags.append('vote')
        self.hashtags.append('politics')
        # TODO breakout list from string
        self.hashtags = ' '.join(['#' + hashtag for hashtag in self.hashtags])

    def build_candidate_description(self):
        if self.office is None or self.state_name is None or self.party is None:
            self.handle_build_error('Element missing for candidate description.')
            return

        if self.office == 'House':
            self.candidate_description = f'{self.party} candidate for the {self.office} in {self.state_name}'
        elif self.office == 'Senate':
            self.candidate_description = f'{self.party} candidate for {self.office} in {self.state_name}'
        elif self.office == 'President':
            self.candidate_description = f'{self.party} candidate for President'

    def build_emoji(self):
        if self.party == 'Republican' or self.lean == 'conservative':
            self.emoji = '🚨🐘'
        elif self.party == 'Democratic' or self.lean == 'liberal':
            self.emoji = '🗳️🐴'
        elif self.party == 'Independent' or self.lean == 'non-partisan':
            self.emoji = '⭐'

    def build_tweet_string(self):
        self.text = base_string.format(
            contributor_name=self.contributor_name,
            amount=self.amount,
            recipient=self.recipient,
            recipient_description=self.recipient_description,
            disclosure_url=self.disclosure_url,
            hashtags=self.hashtags
        )

        if self.emoji is not None:
            self.text = self.emoji + ' ' + self.text

        self.text = re.sub(r'[^\S\r\n]+', ' ', self.text)  # Remove any extra white space
        self.text = re.sub(r'\b(pac)\b', 'PAC', self.text, flags=re.IGNORECASE)  # Capitalize PAC

        # TODO clean up this very hacky fix
        if len(self.text) > 280:
            self.text = base_string_no_disclosure_url.format(
                contributor_name=self.contributor_name,
                amount=self.amount,
                recipient=self.recipient,
                recipient_description=self.recipient_description,
                hashtags=self.hashtags
            )

            if self.emoji is not None:
                self.text = self.emoji + ' ' + self.text

            self.text = re.sub(r'[^\S\r\n]+', ' ', self.text)  # Remove any extra white space
            self.text = re.sub(r'\b(pac)\b', 'PAC', self.text, flags=re.IGNORECASE)  # Capitalize PAC

        if len(self.text) > 280:
            self.handle_build_error('Tweet is too long.')

    def get_committee_media(self):
        committee = get_committee(committee_id=self.schedule_a['committee_id'])
        self.committee_website = committee['website']
        if self.committee_website is not None:
            url = self.committee_website.lower()
            if not re.match('(?:http|ftp|https)://', url):
                url = 'http://' + url.strip()

            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/537.36 (KHTML, like Gecko) '
                              'Chrome/50.0.2661.102 Safari/537.36'}
            response = requests.get(
                url,
                headers=headers
            )
            html = response.text
            soup = BeautifulSoup(html, 'html.parser')
            media_url = soup.find("meta", {"property": "og:image"})
            if media_url is None:
                media_url = soup.find("meta", {"property": "twitter: image"})

            if media_url is not None:
                opener = urllib.request.build_opener()
                opener.addheaders = [('User-agent', 'Mozilla/5.0')]
                urllib.request.install_opener(opener)
                urllib.request.urlretrieve(media_url['content'], './tmpimg')
                auth = tweepy.OAuthHandler(twitter_keys['api_key'], twitter_keys['api_secret_key'])
                auth.set_access_token(twitter_keys['access_token'], twitter_keys['access_token_secret'])
                api = tweepy.API(auth)
                media_obj = api.media_upload('./tmpimg')
                self.media_obj = media_obj


def to_title(text):
    """
    Coverts string to title and strips empty white space. Returns empty sting if text is None
    :param text: input text
    :return: title case text
    """
    if text is not None:
        return text.title().strip()
    else:
        return None


def format_party(text):
    """
    Coverts string with party
    :param text: input text
    :return: title case text
    """
    return to_title(text).replace('Party', '').strip()


def fetch_data_and_build_tweets(min_load_date, min_amount, transactions, **kwargs):
    """

    :param transactions:
    :param min_load_date:
    :param min_amount:
    :param kwargs:
    :return:
    """
    schedule_as = get_schedule_a(min_load_date=min_load_date, min_amount=min_amount, **kwargs)
    tweets = []

    # schedule_a = schedule_as[1]
    for schedule_a in schedule_as:
        if not schedule_a['is_individual']:
            continue
        tweet = Tweet(schedule_a)
        # No duplicates
        if tweet.transaction_id in transactions:
            tweet.status = TweetStatus.BLOCKED
            logging.info(f'Skipping already posted transaction: {tweet.transaction_id}')
            continue
        try:
            tweet.get_committee_media()
            tweet.build_contributor_name()
            tweet.build_amount()
            tweet.build_recipient()
            tweet.build_emoji()
            tweet.build_disclosure_url()
            tweet.build_hashtags()
            tweet.build_tweet_string()
        except Exception as error:
            tweet.handle_build_error(str(error))
            print(error)
            continue

        tweets.append(tweet)
    return tweets

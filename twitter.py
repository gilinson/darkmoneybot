import time
import urllib
import csv
import requests
import tweepy
import locale
import re
import os
import logging
import titlecase
from bs4 import BeautifulSoup
from PIL import Image, ImageOps
from datetime import datetime
import credentials
from fec_api import get_schedule_a, get_schedule_e, get_committee, get_affiliated_committees, get_party, get_candidate
from open_secrets import get_committee_info
from funding_chart import generate_committee_chart
from wikipedia import get_image
from open_ai import generate_tweet, shorten_tweet
from states import abbrev_to_us_state
from credentials import twitter_keys

locale.setlocale(locale.LC_ALL, 'en_CA.UTF-8')


class TweetStatus:
    """
    The status of a tweet
    """
    BLOCKED = -1  # An issue prevents the tweet from being posted
    PENDING = 0  # The tweet has not been posted
    POSTED = 1  # The tweet has been posted


class Tweet:

    def __init__(self):

        self.status = TweetStatus.PENDING
        self.build_issues = []
        self.hashtags = []
        self.text = None
        self.in_reply_to_tweet_id = None
        self.media_objs = []
        self.response = None
        self.transaction_id = None

    def post(self, run_level=0):
        if self.status != TweetStatus.PENDING:
            reasons = ', '.join(self.build_issues)
            logging.info(f'Tweet blocked due to: {reasons}')
            raise Exception(f'Tweet with status {self.status} cannot be posted')

        client = tweepy.Client(
            consumer_key=twitter_keys['api_key'],
            consumer_secret=twitter_keys['api_secret_key'],
            access_token=twitter_keys['access_token'],
            access_token_secret=twitter_keys['access_token_secret']
        )
        logging.info(self.text)  # TODO replace with logging

        if run_level == 1:
            if len(self.media_objs) > 0:
                media_ids = [obj.media_id for obj in self.media_objs]
                logging.info(f'Posting with {len(media_ids)} attachments')
                self.response = client.create_tweet(text=self.text, media_ids=media_ids, in_reply_to_tweet_id=self.in_reply_to_tweet_id)
                self.status = TweetStatus.POSTED
            else:
                self.response = client.create_tweet(text=self.text)
                self.status = TweetStatus.POSTED
            if len(self.response.errors) > 0:
                logging.info(self.response.errors)
            with open('transactions.csv', 'a') as csv_file:
                writer_object = csv.writer(csv_file)
                writer_object.writerow([self.transaction_id])
        else:
            logging.info(f'In debug mode, not posting. Post would have {len(self.media_objs)} media')

    def upload_media_from_url(self, media_url, adjust_aspect=False):
        if len(media_url) == 0:
            logging.info(f'Empty media URL')
            return
        if self.status != TweetStatus.BLOCKED:
            opener = urllib.request.build_opener()
            opener.addheaders = [('User-agent', 'Mozilla/5.0')]
            urllib.request.install_opener(opener)
            filename = './' + media_url.split('/')[len(media_url.split('/')) - 1]
            # remove anything strange in filename
            filename = re.sub(r'(?<=png|jpg|bmp).*$', '', filename)
            if 'blank' in filename:
                # TODO could be some better quality check
                logging.info(f'Not uploading possible blank {media_url}')
                return
            urllib.request.urlretrieve(media_url, filename)
            if adjust_aspect:
                img = Image.open(filename)
                required_height = (2/1.5) * img.width
                required_padding = int(required_height - img.height)
                if required_padding > 0:
                    img = ImageOps.expand(img, border=required_padding // 2, fill='black')
                    img = img.crop((required_padding // 2, 0, img.width - required_padding // 2, img.height))
                    img.save(filename)
            auth = tweepy.OAuthHandler(twitter_keys['api_key'], twitter_keys['api_secret_key'])
            auth.set_access_token(twitter_keys['access_token'], twitter_keys['access_token_secret'])
            api = tweepy.API(auth)
            media_obj = api.media_upload(filename)
            os.remove(filename)
            self.media_objs.append(media_obj)

    def upload_media_from_file(self, filename):
        auth = tweepy.OAuthHandler(twitter_keys['api_key'], twitter_keys['api_secret_key'])
        auth.set_access_token(twitter_keys['access_token'], twitter_keys['access_token_secret'])
        api = tweepy.API(auth)
        media_obj = api.media_upload(filename)
        os.remove(filename)
        self.media_objs.append(media_obj)

    def handle_build_error(self, error):
        self.status = self.build_issues.append(error)
        self.status = TweetStatus.BLOCKED

    def build(self):
        pass

    def build_hashtags(self):
        self.hashtags.append('Election2024')
        self.hashtags.append('Vote')


class ScheduleATweet(Tweet):
    base_string = """According to a new filing {contributor_name} gave {amount} to {recipient}, {recipient_description}.

FEC filing: {short_url}
{hashtags}
"""

    base_string_no_disclosure_url = \
        """According to a new filing {contributor_name} gave {amount} to {recipient}, {recipient_description}.

{hashtags}
"""

    base_string_input = """According to a new filing {contributor_name} gave {amount} to {recipient}, {recipient_description}."""

    def __init__(self, schedule_a):

        super().__init__()
        self.schedule_a = schedule_a
        self.contributor_name = None
        self.amount = None
        self.recipient = None
        self.recipient_description = None
        self.disclosure_url = None
        self.short_url = None
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
        self.transaction_id = self.transaction_id = f"{self.schedule_a['transaction_id']}{self.schedule_a['committee']['committee_id']}-{self.schedule_a['contribution_receipt_amount']}"

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
        else:
            self.amount = format_amount(amount)

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
            self.recipient = format_committee_name(self.recipient)

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
            affiliated_committees = get_affiliated_committees(self.schedule_a['committee'])
            if affiliated_committees is not None:
                self.party = format_party(get_party(affiliated_committees))
            self.recipient = to_title(self.schedule_a['committee']['name'])
            if self.party is not None:
                self.recipient_description = f'a joint funding raising committee associated ' \
                                             f'with the {self.party} party'
            else:
                self.recipient_description = 'a joint funding raising committee'

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

    def build_disclosure_url(self):
        self.disclosure_url = self.schedule_a['pdf_url']
        self.short_url = get_short_url(self.disclosure_url)

    def build_hashtags(self):
        super().build_hashtags()
        # if self.state_name is not None and self.state_name != 'US':
        #    self.hashtags.append(self.state_name.replace(' ', ''))
        if self.state_name is not None and self.state_name != 'US' and self.office is not None:
            state_race = self.state_name + self.office
            self.hashtags.append(state_race.replace(' ', ''))
        if self.candidate_first_name is not None and self.candidate_last_name is not None:
            candidate_name = self.candidate_first_name + self.candidate_last_name
            self.hashtags.append(candidate_name.replace(' ', ''))
        # TODO breakout list from string
        self.hashtags = ' '.join(['#' + hashtag for hashtag in self.hashtags])

    def build_emoji(self):
        if self.party == 'Republican' or self.lean == 'conservative':
            self.emoji = '🚨🐘'
        elif self.party == 'Democratic' or self.lean == 'liberal':
            self.emoji = '🗳️🐴'
        elif self.party == 'Independent' or self.lean == 'non-partisan':
            self.emoji = '⭐'

    def build_tweet_string(self):
        input_string = self.base_string_input.format(
            contributor_name=self.contributor_name,
            amount=self.amount,
            recipient=self.recipient,
            recipient_description=self.recipient_description
        )

        logging.info('Generating tweet with chatapi')
        tweet_string = generate_tweet(input_string, self.short_url)
        if tweet_string is None:
            self.handle_build_error('No usable tweet generated by AI')

        self.text = tweet_string + ' ' + self.hashtags
        self.text = re.sub(r'[^\S\r\n]+', ' ', self.text)  # Remove any extra white space

        # if self.emoji is not None:
        #     self.text = self.emoji + ' ' + self.text
        #
        # self.text = re.sub(r'[^\S\r\n]+', ' ', self.text)  # Remove any extra white space
        #
        # # TODO clean up this very hacky fix
        # if len(self.text) > 280:
        #     logging.info(f'Removing link because tweet is too long. {self.short_url}')
        #     self.text = self.base_string_no_disclosure_url.format(
        #         contributor_name=self.contributor_name,
        #         amount=self.amount,
        #         recipient=self.recipient,
        #         recipient_description=self.recipient_description,
        #         hashtags=self.hashtags
        #     )
        #
        #     if self.emoji is not None:
        #         self.text = self.emoji + ' ' + self.text
        #
        # if len(self.text) > 280:
        #     logging.info(f'Removing hashtags because tweet is too long. {self.short_url}')
        #     self.text = self.base_string_no_disclosure_url.format(
        #         contributor_name=self.contributor_name,
        #         amount=self.amount,
        #         recipient=self.recipient,
        #         recipient_description=self.recipient_description,
        #         hashtags=''
        #     )

        if(len(self.text)) > 280:
            logging.info(f'Shortening with chat bot. {self.short_url}')
            if tweet_string is None:
                self.handle_build_error('No usable tweet generated by AI')
            self.text = shorten_tweet(self.text)

        if len(self.text) > 280:
            logging.info(f'Removing hashtags because tweet is too long. {self.short_url}')
            self.text = tweet_string
            self.text = re.sub(r'[^\S\r\n]+', ' ', self.text)  # Remove any extra white space

        if len(self.text) > 280:
            self.handle_build_error('Cannot shorten tweet.')

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
            try:
                response = requests.get(
                    url,
                    headers=headers
                )
            except:
                # if we can't get media, just move on
                return
            html = response.text
            soup = BeautifulSoup(html, 'html.parser')
            media_url = soup.find("meta", {"property": "og:image"})
            if media_url is None:
                media_url = soup.find("meta", {"property": "twitter: image"})

            if media_url is not None:
                # Upload (padding if a media is already uploaded)
                self.upload_media_from_url(media_url['content'], len(self.media_objs) == 1)

    def get_contributor_media(self):

        if self.contributor_name is None:
            return

        try:
            media_url = get_image(self.contributor_name)
        except:
            return  # TODO this is not great handling

        if media_url is not None:
            self.upload_media_from_url(media_url)

    def build(self):
        self.build_contributor_name()
        self.build_amount()
        self.build_recipient()
        self.build_emoji()
        self.build_disclosure_url()
        self.build_hashtags()
        self.get_contributor_media()
        self.get_committee_media()
        self.build_tweet_string()


class ScheduleETweet(Tweet):
    base_string = """{emoji} {committee_name} spent {amount} for {reason} starting {date} to {os} {candidate_name}, {candidate_description}

FEC filing: {short_url}
{hashtags}
"""
    base_string_no_disclosure_url = """{emoji} {committee_name} spent {amount} for {reason} starting {date} to {os} {candidate_name}, {candidate_description}

    {hashtags}
    """

    base_string_input = """{committee_name} spent {amount} for {reason} starting {date} to {os} {candidate_name}, {candidate_description}"""

    def __init__(self, schedule_e):

        super().__init__()
        self.reason = None
        self.emoji = None
        self.candidate_name = None
        self.short_url = None
        self.disclosure_url = None
        self.os = None
        self.date = None
        self.committee_name = None
        self.schedule_e = schedule_e
        self.amount = None
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
        self.transaction_id = f"{self.schedule_e['transaction_id']}{self.schedule_e['committee_id']}-{self.schedule_e['candidate_id']}-{self.schedule_e['expenditure_amount']}"

    def build(self):
        self.build_contributor_name()
        self.build_amount()
        self.build_date()
        self.build_candidate()
        self.build_candidate_description()
        self.get_committee_media()
        self.build_hashtags()
        self.build_os()
        self.build_emoji()
        self.build_reason()
        self.build_disclosure_url()
        self.build_tweet_string()

    def build_contributor_name(self):
        self.committee_name = to_title(self.schedule_e['committee']['name'])
        self.committee_name = format_committee_name(self.committee_name)

    def get_committee_media(self):
        # TODO copy-paste
        committee = get_committee(committee_id=self.schedule_e['committee_id'])
        self.committee_website = committee['website']
        if self.committee_website is not None:
            url = self.committee_website.lower()
            if not re.match('(?:http|ftp|https)://', url):
                url = 'http://' + url.strip()

            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/537.36 (KHTML, like Gecko) '
                              'Chrome/50.0.2661.102 Safari/537.36'}
            try:
                response = requests.get(
                    url,
                    headers=headers
                )
            except:
                # if we can't get media just move on
                return
            html = response.text
            soup = BeautifulSoup(html, 'html.parser')
            media_url = soup.find("meta", {"property": "og:image"})
            if media_url is None:
                media_url = soup.find("meta", {"property": "twitter: image"})

            if media_url is not None:
                # Upload (padding if a media is already uploaded)
                self.upload_media_from_url(media_url['content'], len(self.media_objs) == 1)

    def build_amount(self):
        amount = self.schedule_e['expenditure_amount']

        if amount is None:
            self.handle_build_error('Amount not available')
            return
        else:
            self.amount = format_amount(amount)

    def build_date(self):
        dt = datetime.strptime(self.schedule_e['dissemination_date'], '%Y-%m-%dT%H:%M:%S')
        self.date = dt.strftime('%b {S}').replace('{S}', str(dt.day) + suffix(dt.day))

    def build_candidate(self):
        if self.schedule_e['candidate_id'] is not None:
            candidate = get_candidate(candidate_id=self.schedule_e['candidate_id'])
        else:
            candidate = get_candidate(
                name='{first_name} {last_name}'.format(
                    first_name=self.schedule_e['candidate_first_name'],
                    last_name=self.schedule_e['candidate_last_name']
                ),
                state=self.schedule_e['candidate_office_state']
            )

        self.candidate_first_name = to_title(candidate['first_name'])
        self.candidate_last_name = to_title(candidate['last_name'])
        self.candidate_name = f'{self.candidate_first_name} {self.candidate_last_name}'
        self.office = to_title(candidate['office_full'])
        self.state_abbrev = candidate['state']
        self.party = format_party(candidate['party_full'])
        self.state_name = abbrev_to_us_state[self.state_abbrev]

        try:
            media_url = get_image(self.candidate_name)
        except:
            return  # TODO this is not great handling

        if media_url is not None:
            self.upload_media_from_url(media_url)

    def build_candidate_description(self):
        if self.office is None or self.state_name is None or self.party is None:
            self.handle_build_error('Element missing for candidate description.')
            return

        if self.party == 'Unknown':
            self.party = ''

        if self.office == 'House':
            self.candidate_description = f'{self.party} candidate for the {self.office} in {self.state_name}'
        elif self.office == 'Senate':
            self.candidate_description = f'{self.party} candidate for {self.office} in {self.state_name}'
        elif self.office == 'President':
            self.candidate_description = f'{self.party} candidate for President'
        self.candidate_description = self.candidate_description.strip()

    def build_os(self):
        if self.schedule_e['support_oppose_indicator'] == 'O':
            self.os = 'oppose'
        elif self.schedule_e['support_oppose_indicator'] == 'S':
            self.os = 'support'
        else:
            self.handle_build_error('support_oppose_indicator is missing')

    def build_disclosure_url(self):
        self.disclosure_url = self.schedule_e['pdf_url']
        self.short_url = get_short_url(self.disclosure_url)

    def build_hashtags(self):
        super().build_hashtags()
        # if self.state_name is not None and self.state_name != 'US':
        #    self.hashtags.append(self.state_name.replace(' ', ''))
        if self.state_name is not None and self.state_name != 'US' and self.office is not None:
            state_race = self.state_name + self.office
            self.hashtags.append(state_race.replace(' ', ''))
        if self.candidate_first_name is not None and self.candidate_last_name is not None:
            candidate_name = self.candidate_first_name + self.candidate_last_name
            self.hashtags.append(candidate_name.replace(' ', ''))
        self.hashtags = ' '.join(['#' + hashtag for hashtag in self.hashtags])

    def build_reason(self):
        if self.schedule_e['expenditure_description'] is None:
            self.handle_build_error('expenditure_description is missing')
            return

        self.reason = to_lower(self.schedule_e['expenditure_description'])
        self.reason = re.sub(r'\(.*\)', '', self.reason).replace('  ', ' ').strip()
        self.reason = re.sub(r'-', '', self.reason).replace('  ', ' ').strip()
        self.reason = self.reason.replace('ie ', ' ').strip()
        self.reason = re.sub(r'estimate.{0,1}', '', self.reason, flags=re.IGNORECASE).replace('  ', ' ').strip()

        # Should we add an S?
        if re.search(r'.*ing$', self.reason, flags=re.IGNORECASE) is None and \
                re.search(r'.*s$', self.reason, flags=re.IGNORECASE) is None and \
                self.reason != 'media':
            self.reason = self.reason + 's'

    def build_emoji(self):
        rep_emoji = "🚨🐘💸"
        dem_emoji = "️🗳️🐴💸"
        ind_emoji = "⭐💸"

        # Search open secrets for information on outside funding group
        self.lean, os_candidate_name, os_state, os_party = get_committee_info(
            self.schedule_e['committee_id'],
            2022  # TODO don't hardcode
        )

        if self.party == 'Republican' or self.lean == 'conservative':
            if self.os == 'support':
                self.emoji = rep_emoji
            elif self.os == 'oppose':
                self.emoji = dem_emoji
        elif self.party == 'Democratic' or self.lean == 'liberal':
            if self.os == 'support':
                self.emoji = dem_emoji
            elif self.os == 'oppose':
                self.emoji = rep_emoji
        elif self.party == 'Independent' or self.lean == 'non-partisan':
            self.emoji = ind_emoji

        if self.emoji is None:
            self.emoji = '💸'
            logging.info(f'Cannot determine emoji for candidate {self.candidate_name} of party {self.party}')

    def build_tweet_string(self):

        input_string = self.base_string_input.format(
            committee_name=self.committee_name,
            amount=self.amount,
            date=self.date,
            candidate_name=self.candidate_name,
            candidate_description=self.candidate_description,
            os=self.os,
            reason=self.reason
        )

        logging.info('Generating tweet with chatapi')
        tweet_string = generate_tweet(input_string, self.short_url)
        if tweet_string is None:
            self.handle_build_error('No usable tweet generated by AI')

        self.text = tweet_string + ' ' + self.hashtags
        self.text = re.sub(r'[^\S\r\n]+', ' ', self.text)  # Remove any extra white space

        # TODO clean up this very hacky fix
        # if len(self.text) > 280:
        #     logging.info(f'Removing link because tweet is too long. {self.short_url}')
        #     self.text = self.base_string_no_disclosure_url.format(
        #         committee_name=self.committee_name,
        #         amount=self.amount,
        #         date=self.date,
        #         candidate_name=self.candidate_name,
        #         candidate_description=self.candidate_description,
        #         os=self.os,
        #         hashtags=self.hashtags,
        #         reason=self.reason,
        #         emoji=self.emoji
        #     )
        #
        # if len(self.text) > 280:
        #     self.text = self.base_string_no_disclosure_url.format(
        #         committee_name=self.committee_name,
        #         amount=self.amount,
        #         date=self.date,
        #         candidate_name=self.candidate_name,
        #         candidate_description=self.candidate_description,
        #         os=self.os,
        #         hashtags='',
        #         reason=self.reason,
        #         emoji=self.emoji
        #     )
        #     logging.info(f'Removing hashtags because tweet is too long. {self.hashtags}')

        if(len(self.text)) > 280:
            logging.info(f'Shortening with chat bot. {self.short_url}')
            self.text = shorten_tweet(self.text)

        if len(self.text) > 280:
            logging.info(f'Removing hashtags because tweet is too long. {self.short_url}')
            self.text = tweet_string
            self.text = re.sub(r'[^\S\r\n]+', ' ', self.text)  # Remove any extra white space

        if len(self.text) > 280:
            self.handle_build_error('Cannot shorten tweet.')

    def gen_reply_tweet(self):
        reply_tweet = Tweet()
        filename = generate_committee_chart(
            self.committee_name,
            self.schedule_e['committee_id'],
            self.os,
            self.schedule_e['expenditure_amount'],
            self.candidate_name
        )
        if filename is None:
            reply_tweet.handle_build_error(f'No funding chart generated.')
        else:
            reply_tweet.upload_media_from_file(filename)
            reply_tweet.text = f'How {self.committee_name} raised {self.amount} to {self.os} {self.candidate_name} 👇'
            reply_tweet.in_reply_to_tweet_id = self.response.data['id']
        return reply_tweet


def to_title(text):
    """
    Coverts string to title and strips empty white space. Returns empty sting if text is None
    :param text: input text
    :return: title case text
    """
    if text is not None:
        text = titlecase.titlecase(text.lower())
        return text.strip()
    else:
        return None


def to_lower(text):
    """
    Coverts string to lower and strips empty white space. Returns empty sting if text is None
    :param text: input text
    :return: title case text
    """
    if text is not None:
        return text.lower().strip()
    else:
        return None


def format_party(text):
    """
    Coverts string with party
    :param text: input text
    :return: title case text
    """
    return to_title(text).replace('Party', '').strip()


def get_short_url(url):
    """
    Use API to shorten URL
    :param url: URL to shorten
    :return: short link
    """
    logging.info('URL shorten')
    endpoint = "https://cutt.ly/api/api.php"
    response = requests.get(
        endpoint,
        params={
            'key': credentials.cuttly_api_key,
            'short': url
        }
    )
    if response.status_code == 200:
        return response.json()['url']['shortLink']
    elif response.text == 'Too many requests - see API limits - https://cutt.ly/pro-prcing':
        logging.info('Sleeping to avoid API Cap')
        time.sleep(60)
        logging.info('Awake, retrying')
        return get_short_url(url)


def format_committee_name(committee_name):
    # When the name ends with "Fund"
    if re.search(r'fund$', committee_name, flags=re.IGNORECASE) is not None and \
            not re.search(r'^the', committee_name, flags=re.IGNORECASE):
        committee_name = 'The ' + committee_name

    # remove anything in parens
    committee_name = re.sub(r'\(.*\)', '', committee_name).replace('  ', ' ')

    # remove anything with dba and after
    committee_name = re.sub(r'\sdba.*$', '', committee_name, flags=re.IGNORECASE)

    # Should the entire name be capitalized?
    # When its one word
    if re.search(r'^\w+$', committee_name) is not None:
        committee_name = committee_name.upper()

    committee_name = re.sub(r'\b(pac)\b', 'PAC', committee_name, flags=re.IGNORECASE)  # Capitalize PAC
    committee_name = re.sub(r'\b(usa)\b', 'USA', committee_name, flags=re.IGNORECASE)  # Capitalize USA
    committee_name = re.sub(r'\b(nra)\b', 'NRA', committee_name, flags=re.IGNORECASE)  # Capitalize NRA
    committee_name = re.sub(r'\b(goa)\b', 'GOA', committee_name, flags=re.IGNORECASE)  # Capitalize GOA

    return committee_name


def format_amount(amount):
    amount = round(amount)
    if amount >= 1e6:
        end = 'M'
        amount = round(amount / 1e6, 1)
    else:
        end = ''

    return locale.currency(amount, grouping=True).rstrip('0').rstrip('.') + end


def fetch_schedule_a_data_and_build_tweets(min_load_date, min_amount, transactions, post_cap, **kwargs):
    """
    :param transactions:
    :param min_load_date:
    :param min_amount:
    :param post_cap:
    :param kwargs:
    :return:
    """
    logging.info('Starting fetch_schedule_a_data_and_build_tweets')
    schedule_as = get_schedule_a(min_load_date=min_load_date, min_amount=min_amount, **kwargs)

    tweets = []
    total_posts = 0

    logging.info(f'Retrieved {len(schedule_as)} transactions')
    for schedule_a in schedule_as:
        tweet = ScheduleATweet(schedule_a=schedule_a)
        # No duplicates
        if tweet.transaction_id in transactions:
            tweet.status = TweetStatus.BLOCKED
            logging.info(f'Skipping already posted transaction: {tweet.transaction_id}')
            continue
        if total_posts == post_cap:
            logging.info(f'Hit Post Cap')
            break
        try:
            tweet.build()
            total_posts += 1
        except Exception as error:
            tweet.handle_build_error('Unknown error: ' + str(error))
        tweets.append(tweet)
        transactions.append(tweet.transaction_id)
    logging.info('Completed fetch_schedule_a_data_and_build_tweets')
    return tweets


def fetch_schedule_e_data_and_build_tweets(min_load_date, min_amount, min_filing_date, transactions, post_cap, **kwargs):
    """
    :param min_filing_date:
    :param transactions:
    :param min_load_date:
    :param min_amount:
    :param post_cap:
    :param kwargs:
    :return:
    """
    logging.info('Starting fetch_schedule_e_data_and_build_tweets')
    schedule_es = get_schedule_e(min_load_date=min_load_date, min_filing_date=min_filing_date, min_amount=min_amount,
                                 **kwargs)
    tweets = []
    total_posts = 0

    logging.info(f'Retrieved {len(schedule_es)} transactions')
    for schedule_e in schedule_es:
        tweet = ScheduleETweet(schedule_e=schedule_e)
        # No duplicates
        if tweet.transaction_id in transactions:
            tweet.handle_build_error('Duplicate transaction')
            logging.info(f'Skipping already posted transaction: {tweet.transaction_id}')
            continue
        if total_posts == post_cap:
            logging.info(f'Hit Post Cap')
            break
        try:
            tweet.build()
            total_posts += 1
        except Exception as error:
            tweet.handle_build_error('Unknown error: ' + str(error))
        tweets.append(tweet)
    logging.info('Completed fetch_schedule_e_data_and_build_tweets')
    return tweets


def suffix(d):
    return 'th' if 11 <= d <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d % 10, 'th')



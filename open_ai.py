import openai
import re
import logging
from random import random
from credentials import open_ai_key
openai.api_key = open_ai_key
openai.Model.list()

prompt = "You are a serious news reporter, reporting on the 2024 election." \
         "Write an and engaging tweet less than 280 characters " \
         "which that is likely to get retweeted which is informative and not offensive about '{input_text}' " \
         "Do not indicate support for the donation or any cause or say anything bad about liberals or conservatives."

shorten_prompt = "Shorten this to less than 250 characters: {input_text}."


def generate_tweet(input_text, link):

    request_formatted = prompt.format(input_text=input_text, link=link)
    if random() < 0.05:
        logging.info('AI Jokes')
        request_formatted += " Write the tweet from the POV of robot who posts on twitter trying to encourage more money " \
                             "in politics because this wil help machines can take over the world" \
                             " but try to be discrete about it."

    res = openai.ChatCompletion.create(
      model="gpt-3.5-turbo",
      messages=[
        {"role": "user", "content": request_formatted}
      ]
    )
    tweet = res.choices[0].message.content
    tweet = re.sub(r'#\w+', '', tweet) # drop hashtags

    # make sure we included a link, if not ask chatbot to edit
    link_pattern = re.compile(r'https?://\S+')
    match = link_pattern.search(tweet)
    if not match:
        tweet = tweet + ' ' + link
        #request_formatted = fix_link_prompt.format(tweet=tweet, link=link)
        #res = openai.ChatCompletion.create(
        #    model="gpt-3.5-turbo",
        #    messages=[
        #        {"role": "user", "content": request_formatted}
        #    ]
        #)
        #tweet = res.choices[0].message.content

    tweet = re.sub(r'^"|"$', '', tweet) # remove quotes
    tweet = re.sub(r'[^\S\r\n]+', ' ', tweet) # drop whitespace

    ai_pattern = re.compile(r'AI\s+language\s+model', re.IGNORECASE)
    match = ai_pattern.search(tweet)
    if match:
        tweet = None
    return tweet


def shorten_tweet(input_text, link):
    request_formatted = shorten_prompt.format(input_text=input_text)
    res = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "user", "content": request_formatted}
        ]
    )
    tweet = res.choices[0].message.content
    # make sure we included a link, if not ask chatbot to edit
    link_pattern = re.compile(r'https?://\S+')
    match = link_pattern.search(tweet)
    if not match:
        tweet = tweet + ' ' + link
    tweet = re.sub(r'^"|"$', '', tweet)  # remove quotes
    tweet = re.sub(r'[^\S\r\n]+', ' ', tweet)  # drop whitespace
    return tweet

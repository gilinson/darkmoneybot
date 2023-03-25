import openai
import re
from credentials import open_ai_key
openai.api_key = open_ai_key
openai.Model.list()

prompt = "Write a funny and engaging tweet, from the perspective of a robot that hates money in " \
         "politics which that is likely to get retweeted which is informative and not offensive about {input_text} " \
         "Include a link to the FEC filing here {link}." \
         "Do not indicate support for the donation or any cause, but have a general sentiment that money in politics is bad"

fix_link_prompt = "Make sure this tweet in quotes '{tweet}' has a link in it: {link}."

shorten_prompt = "Shorten this to less than 280 characters: {input_text}."


def generate_tweet(input_text, link):
    request_formatted = prompt.format(input_text=input_text, link=link)
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
        request_formatted = fix_link_prompt.format(tweet=tweet, link=link)
        res = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "user", "content": request_formatted}
            ]
        )
        tweet = res.choices[0].message.content

    tweet = re.sub(r'^"|"$', '', tweet) # remove quotes
    tweet = re.sub(r'[^\S\r\n]+', ' ', tweet) # drop whitespace

    ai_pattern = re.compile(r'AI\s+language\s+model', re.IGNORECASE)
    match = ai_pattern.search(tweet)
    if match:
        tweet = None
    return tweet


def shorten_tweet(input_text):
    request_formatted = shorten_prompt.format(input_text=input_text)
    res = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "user", "content": request_formatted}
        ]
    )
    tweet = res.choices[0].message.content
    tweet = re.sub(r'^"|"$', '', tweet)  # remove quotes
    tweet = re.sub(r'[^\S\r\n]+', ' ', tweet)  # drop whitespace
    return tweet

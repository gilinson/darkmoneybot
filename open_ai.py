import openai
import re
from credentials import open_ai_key
openai.api_key = open_ai_key
openai.Model.list()

prompt = "write a funny or engaging tweet, that is informative and not offensive about {input_text} Make sure it is less than 220 characters. " \
         "If possible include this linked FEC filing: {link}. Do not indicate support for the donation or any cause, but have a light sentiment that money in politics is bad"


def generate_tweet(input_text, link):
    prompt_formatted = prompt.format(input_text=input_text, link=link)
    res = openai.ChatCompletion.create(
      model="gpt-3.5-turbo",
      messages=[
        {"role": "user", "content": prompt_formatted}
      ]
    )
    tweet = res.choices[0].message.content
    tweet = re.sub(r'#\w+', '', tweet) # drop hashtags
    tweet = re.sub(r'^"|"$', '', tweet) # remove quotes
    tweet = re.sub(r'[^\S\r\n]+', ' ', tweet) # drop whitespace
    return tweet

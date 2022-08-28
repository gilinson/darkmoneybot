import requests
from credentials import google_api_key


def api_get(endpoint, params):
    """
    Call API and handle exceptions
    :param endpoint: API endpoint
    :param params: a dictionary of parameters
    :return: a json dictionary returned by the API
    """
    params = {
        **params,
        **{
            'key': google_api_key
        }
    }

    response = requests.get(endpoint, params)
    if response.status_code != 200:
        raise Exception('API error: ' + response.text)
        return response.json()
    else:
        return response.json()


def search_person(query):
    endpoint = 'https://kgsearch.googleapis.com/v1/entities:search'
    response = api_get(
        endpoint=endpoint,
        params={
            'query': query,
            'types': 'person',
            'languages': 'en',
            'limit': 1
        }
    )
    if len(response['itemListElement']) > 0:
        return response['itemListElement'][0]['result']

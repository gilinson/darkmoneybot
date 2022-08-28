import requests

def search_for_person(name):
    endpoint = "https://en.wikipedia.org/w/api.php"

    response = requests.get(
        endpoint,
        params={
            'action': 'opensearch',
            'search': name,
            'limit': 1
        }
    )
    if response.status_code == 200:
        page_url = response.json()[3][0]
        # Enforce strict match
        if name.title().replace(' ', '_') == page_url.split('/')[len(page_url.split('/')) - 1]:
            return response.json()[3][0]

    return None


def get_lead_image(pageid):
    endpoint = f'https://en.wikipedia.org/api/rest_v1/page/media-list/{pageid}'
    response = requests.get(
        endpoint,
        params={
        }
    )

    if response.status_code == 200:
        response = response.json()
        leadimage = [item for item in response['items'] if item['leadImage']]
        if len(leadimage) > 0:
            # Look for "lead image"
            src = [src for src in leadimage[0]['srcset'] if src['scale'] == '1x'][0]['src']
            return 'https:' + src
        else:
            # Look at gallery
            gallery = [item for item in response['items'] if item['showInGallery']]
            if len(gallery) > 0:
                src = [src for src in gallery[0]['srcset'] if src['scale'] == '1x'][0]['src']
                return 'https:' + src
    return None


def get_image(name):
    page = search_for_person(name)
    if page is not None:
        split_url = page.split('/')
        pageid = split_url[len(split_url) - 1]
        return get_lead_image(pageid)
    else:
        return None
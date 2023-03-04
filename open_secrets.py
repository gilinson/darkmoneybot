import requests
import re
from bs4 import BeautifulSoup


def get_committee_info(committee_id, cycle):
    """
    Get info on a committee from open secrets
    :param committee_id: id of committee used across open secrets and FEC
    :param cycle: two-year funding cycle
    :return: a tuple of viewpoint, candidate, state and party extracted from open secrets website
    """
    endpoint = "https://www.opensecrets.org/outsidespending/detail.php"

    response = requests.get(
        endpoint,
        params={'cmte': committee_id, 'cycle': cycle}
    )

    html = response.text
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')

    text = soup.get_text()
    viewpoint_search = re.search('Viewpoint:(.*)\nType of group:', text)
    supports_search = re.search('Supports:(.*)\nGrand Total Spent on 2022 Federal Elections:', text)

    if viewpoint_search is not None:
        viewpoint = viewpoint_search.group(1).strip()
    else:
        viewpoint = None

    if supports_search is not None:
        supports = supports_search.group(1).strip()
        candidate = re.sub(r'\([^)]*\)', '', supports)
        state = re.search(r'(?<=-)(..)', supports)[0]
        party = re.search(r'(?<=\()(.)', supports)[0]
    else:
        candidate = None
        state = None
        party = None

    return viewpoint, candidate, state, party

# TODO JFC?
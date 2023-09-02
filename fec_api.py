import requests
from nameparser import HumanName
from credentials import api_key
from datetime import datetime

endpoints = {
    'schedule_a': 'https://api.open.fec.gov/v1/schedules/schedule_a/',
    'schedule_e': 'https://api.open.fec.gov/v1/schedules/schedule_e/',
    'committee': 'https://api.open.fec.gov/v1/committee/{committee_id}/',
    'candidate': 'https://api.open.fec.gov/v1/candidates/',
    'schedule_e_by_candidate': 'https://api.open.fec.gov/v1/schedules/schedule_e/by_candidate/'
}


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
            'api_key': api_key,
            'per_page': 100,
            'sort_null_only': True
        }
    }

    response = requests.get(endpoint, params)
    if response.status_code != 200:
        raise Exception('API error: ' + response.text)
        return response.json()
    else:
        return response.json()


def get_paged_results(endpoint, **kwargs):
    """
    Get all pages of results
    :param endpoint: API endpoint
    :return: a dictionary returned by the API
    """
    # Request first page
    response = api_get(endpoint, kwargs)
    results = response['results']

    pages = response['pagination']['pages']
    for i in range(pages-1):
        params_page = {**kwargs, **response['pagination']['last_indexes']}
        response = api_get(endpoint, params_page)
        results += response['results']

    assert len(results) == response['pagination']['count'], 'Did not receive correct count of results.'
    return results


def get_two_year_transaction_period(year):
    """
    This is a two-year period that is derived from the year a transaction took place in the
    Itemized Schedule A and Schedule B tables. In cases where we have the date of the transaction
    (contribution_receipt_date in schedules/schedule_a, disbursement_date in schedules/schedule_b)
    the two_year_transaction_period is named after the ending, even-numbered year. If we do not
    have the date of the transaction, we fall back to using the report year (report_year in both
    tables) instead, making the same cycle adjustment as necessary. If no transaction year is
    specified, the results default to the most current cycle.
    :param year: input year
    :return: two year transaction period
    """
    if year % 2 == 0:
        return year
    else:
        return year + 1


def get_schedule_a(min_load_date, min_amount, **kwargs):
    """
    Get schedule a data
    :param min_load_date:
    :param min_amount:
    :param kwargs: extra params
    :return: response
    """
    #two_year_transaction_period = get_two_year_transaction_period(datetime.strptime(min_load_date, '%Y-%M-%d').year)
    two_year_transaction_period = 2024
    results = get_paged_results(
        endpoint=endpoints['schedule_a'],
        min_load_date=min_load_date,
        min_amount=min_amount,
        two_year_transaction_period=two_year_transaction_period,
        **kwargs
    )
    return results


def get_schedule_e(min_load_date, min_filing_date, min_amount, **kwargs):
    """
    Get schedule a data
    :param min_load_date:
    :param min_amount:
    :param kwargs: extra params
    :return: response
    """
    results = get_paged_results(
        endpoint=endpoints['schedule_e'],
        min_load_date=min_load_date,
        min_filing_date=min_filing_date,
        min_amount=min_amount,
        **kwargs
    )
    return results


def get_schedule_e_by_candidate(**kwargs):
    """
    Get schedule a data
    :param kwargs: extra params
    :return: response
    """
    results = get_paged_results(
        endpoint=endpoints['schedule_e_by_candidate'],
        **kwargs
    )
    return results


def get_committee(committee_id, cycle=None):
    endpoint = endpoints['committee']
    if cycle is not None:
        endpoint += 'history/' + str(cycle)

    results = get_paged_results(endpoint.format(committee_id=committee_id))
    return results[0]


def get_affiliated_committees(committee):
    if 'jfc_committee' in committee:
        sub_results = []
        for jfc_committee in committee['jfc_committee']:
            if jfc_committee['joint_committee_id'] is not None:
                sub_results.append(get_committee(jfc_committee['joint_committee_id']))
        return sub_results
    else:
        return None


def get_party(committees):
    """

    :param committees:
    :return:
    """
    parties = [i['party_full'] for i in committees if i['party_full'] is not None]
    if len(parties) > 0:
        return max(set(parties), key=parties.count)
    else:
        return None


def get_candidate(multi=False, **kwargs):
    results = get_paged_results(
        endpoint=endpoints['candidate'],
        **kwargs
    )
    if len(results) == 0:
        return None

    if not multi:
        parsed_name = HumanName(results[0]['name'])
        results[0]['first_name'] = parsed_name.first
        results[0]['last_name'] = parsed_name.last
        return results[0]
    else:
        return results



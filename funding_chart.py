from fec_api import get_schedule_a
from math import log
import locale
import requests
from collections.abc import Iterable
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM
from PIL import Image, ImageFont, ImageDraw, ImageOps
from io import BytesIO

all_committees = []

locale.setlocale(locale.LC_ALL, 'en_CA.UTF-8')


class Committee:

    def __init__(self, committee_name, committee_id):
        self.committee_name = committee_name
        self.committee_id = committee_id
        self.funder_type = 'committee'
        self.amount = 0
        self.support_oppose = None
        self.funders = []

    def match(self, committee_name):
        return self.committee_name == committee_name

    def get_name(self):
        return self.committee_name

    def get_display(self):
        # 🗄️
        return self.committee_name


class Individual:

    def __init__(self, name, first_name, last_name):
        self.name = name
        self.funder_type = 'individual'
        self.amount = 0
        self.first_name = first_name
        self.last_name = last_name

    def match(self, name):
        return self.name == name

    def get_name(self):
        return self.name

    def get_display(self):
        # '\U0001F9D1 '
        display = self.first_name + ' ' + self.last_name
        return display.strip()


class Candidate:

    def __init__(self, candidate_name):
        self.party = None
        self.candidate_name = candidate_name

        self.funders = []

    def get_name(self):
        return self.get_display()

    def get_display(self):
        # 🐘
        display = self.candidate_name
        return display.strip()


def agg_by_funder(schedule_as, calling_committee):
    funders = []
    for schedule_a in schedule_as:
        if schedule_a['entity_type'] == 'IND':
            matched = [funder for funder in funders if funder.match(schedule_a['contributor_name'])]
            if len(matched) > 0:
                funder = matched[0]
            else:
                funder = Individual(
                    name=schedule_a['contributor_name'],
                    first_name=schedule_a['contributor_first_name'],
                    last_name=schedule_a['contributor_last_name']
                )
                funders.append(funder)
        else:
            matched = [funder for funder in funders if funder.match(schedule_a['contributor_name'])]
            if len(matched) > 0:
                funder = matched[0]
            else:
                try:
                    funder = Committee(committee_name=schedule_a['contributor_name'],
                                       committee_id=schedule_a['contributor']['committee_id'])
                except Exception as error:
                    funder = Committee(committee_name=schedule_a['contributor_name'],
                                       committee_id=None)

                # Check if we've already built out a tree for this committee, do nothing if we have
                matched = [co for co in all_committees if co.match(funder.committee_name)]
                if len(matched) > 0:
                    pass
                else:
                    # Check if this committee has a circular relationship with the funding committee. If it has
                    # just append the funder so a loop is drawn, but don't call get_funders again
                    matched = [cf for cf in calling_committee.funders if funder.match(cf.committee_name)]
                    if len(matched) > 0:
                        funder = matched[0]
                    else:
                        funder = get_funders(funder)

                funders.append(funder)

        funder.amount += schedule_a['contribution_receipt_amount']

    return funders


def get_funders(committee, min_amount=1e5):
    # Skip committees that have massive donor lists
    if committee.committee_id in ('C00694323', 'C00075820', 'C00401224') or committee.committee_id is None:
        return committee

    schedule_as = get_schedule_a(
        min_load_date='2020-01-01',
        max_load_date='2023-08-05',
        min_amount=min_amount,
        date_type='processed',
        committee_id=committee.committee_id
    )

    all_committees.append(committee)
    committee.funders = agg_by_funder(schedule_as, committee)
    return committee


def gen_edges(obj, min_amount_direct, min_amount_indirect):
    edges = []
    obj.funders.sort(key=lambda x: x.amount, reverse=True)
    for funder in obj.funders:
        if funder.amount < min_amount_direct:
            continue
        if funder.funder_type != 'individual':
            edges += gen_edges(funder, min_amount_indirect, min_amount_indirect)
        getter = obj.get_display()
        giver = funder.get_display()
        # heuristic for determining line weight
        10 * (log(1e6) - log(1e6)) / 4.8
        weight = max(10 * (log(funder.amount) - log(1e6)) / 4.8, 0.5)
        amount = format_amount(funder.amount)
        if hasattr(funder, 'support_oppose'):
            if funder.support_oppose == 'support':
                edge = f""""{giver}" -> "{getter}" [label = "{amount}", color=forestgreen, penwidth={weight}]"""
            elif funder.support_oppose == 'oppose':
                edge = f""""{giver}" -> "{getter}" [label = "{amount}", color=orange, penwidth={weight}]"""
            else:
                edge = f""""{giver}" -> "{getter}" [label = "{amount}", penwidth={weight}]"""
        else:
            edge = f""""{giver}" -> "{getter}" [label = "{amount}", penwidth={weight}]"""
        edges.append(edge)
    return edges


def gen_nodes(obj, min_amount_direct, min_amount_indirect):
    nodes = []
    obj.funders.sort(key=lambda x: x.amount, reverse=True)
    for funder in obj.funders:
        if funder.amount < min_amount_direct:
            continue
        if funder.funder_type != 'individual':
            nodes += gen_nodes(funder, min_amount_indirect, min_amount_indirect)
        giver = funder.get_display()

        if funder.funder_type == 'individual':
            node = f""""{giver}" [shape=box, style="rounded,filled", fillcolor="#BDE5F2"]"""
        else:
            node = f""""{giver}" [shape=box, style="rounded,filled", fillcolor=grey]"""
        nodes.append(node)
    return nodes


def format_amount(amount):
    amount = round(amount)
    if amount >= 1e6:
        end = 'M'
        amount = round(amount / 1e6, 1)
    elif amount >= 1e5:
        end = 'K'
        amount = round(amount / 1e3, 1)
    else:
        end = ''

    return locale.currency(amount, grouping=True).rstrip('0').rstrip('.') + end


def extract_amounts(funders, direct_only):
    amounts = []
    for funder in funders:
        if funder.funder_type != 'individual' and not direct_only:
            # Just look one level back
            amounts.append(extract_amounts(funder.funders, True))
        else:
            amounts.append(funder.amount)
    return amounts


def flatten(xs):
    for x in xs:
        if isinstance(x, Iterable) and not isinstance(x, (str, bytes)):
            yield from flatten(x)
        else:
            yield x


def generate_graphviz_via_api(nodes, edges, upper, lower):
    template = """digraph penn_oz {{
graph [pad="0.1", nodesep="0", ranksep="0"];

node [fontname="Roboto,sans-serif", fontsize=12];
edge [fontname="Roboto,Arial,sans-serif", fontsize=12];
rankdir=LR;
ratio=0.5;
imagescale=15;

{nodes}
{edges}

}}
"""

    graph = template.format(
        nodes='\n'.join(nodes),
        edges='\n'.join(edges),
    )
    r = requests.post('https://quickchart.io/graphviz', json={'graph': graph, 'format': 'svg'})
    filename_base = './tmp_img'
    with open(filename_base + '.svg', 'wb') as f:
        f.write(r.content)
    drawing = svg2rlg(filename_base + '.svg')
    renderPM.drawToFile(drawing, filename_base + '.png')

    img = Image.open(filename_base + '.png')
    padding = img.height // 4
    img = ImageOps.expand(img, border=padding, fill='white')
    draw = ImageDraw.Draw(img)
    draw.fontmode = 'L'
    req = requests.get("https://github.com/googlefonts/roboto/blob/main/src/hinted/Roboto-Regular.ttf?raw=true")
    font_size = round(1.75 * (img.width - 2 * padding) / len(upper))
    font = ImageFont.truetype(BytesIO(req.content), font_size)

    draw.text((padding + 30, 10), upper + '\n' + lower, fill='black', font=font)
    img = img.crop((padding, 0, img.width-padding, img.height-padding))
    img.save(filename_base + '.png')
    return filename_base + '.png'


def generate_committee_chart(committee_name, committee_id, support_oppose, spend_amount, candidate_name, n_direct=10, n_indirect=15):
    candidate = Candidate(candidate_name)
    committee = Committee(committee_name=committee_name, committee_id=committee_id)
    committee = get_funders(committee)
    committee.support_oppose = support_oppose
    candidate.funders = [committee]
    committee.amount = spend_amount

    # Min direct
    amounts_direct = [i for i in flatten(extract_amounts(committee.funders, direct_only=True))]
    if len(amounts_direct) >= n_direct:
        min_amount_direct = sorted(amounts_direct)[-n_direct]
    elif len(amounts_direct) > 0:
        min_amount_direct = min(amounts_direct)
    else:
        min_amount_direct = 250e3

    # Min indirect
    amounts_indirect = [i for i in flatten(extract_amounts(committee.funders, direct_only=False))]
    if len(amounts_indirect) >= n_indirect:
        min_amount_indirect = sorted(amounts_indirect)[-n_indirect]
    elif len(amounts_indirect) > 0:
        min_amount_indirect = min(amounts_indirect)
    else:
        min_amount_indirect = 250e3
    edges = gen_edges(committee, min_amount_direct, min_amount_indirect)
    nodes = gen_nodes(committee, min_amount_direct, min_amount_indirect)
    edges = list(set(edges))
    nodes = list(set(nodes))
    committee.funders = []
    edges_c = gen_edges(candidate, 0, 0)
    nodes_c = gen_nodes(candidate, 0, 0)
    edges += list(set(edges_c))
    nodes += list(set(nodes_c))
    formated_amount = format_amount(spend_amount)
    filename = generate_graphviz_via_api(nodes, edges, upper=f'How {committee.committee_name} Spent {formated_amount} to {support_oppose}', lower=candidate.candidate_name)
    return filename

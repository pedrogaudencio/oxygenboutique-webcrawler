import pyquery
import re
from urllib import urlencode
from urllib2 import urlopen
from urlparse import urljoin

from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule
from scrapy.exceptions import DropItem
from scrapy.http import Request, FormRequest

from oxygendemo.items import OxygendemoItem
from helpers import *


# ---------
# Pipelines
# ---------


class DuplicatesPipeline(object):

    def __init__(self):
        self.codes_seen = set()

    def process_item(self, item, spider):
        if item['code'] in self.ids_seen:
            raise DropItem("Duplicate item found: %s" % item)
        else:
            self.ids_seen.add(item['code'])
            return item


# ------
# Spider
# ------


class OxygenSpider(CrawlSpider):
    name = "oxygenboutique.com"
    download_delay = 2
    allowed_domains = ["oxygenboutique.com"]
    start_urls = [
        "http://www.oxygenboutique.com"
    ]
    rules = (
        Rule(LinkExtractor(allow=('AboutUs.aspx')),
             callback='parse_global_description',
             follow=False),
        Rule(LinkExtractor(allow=('clothing.aspx')),
             callback='parse_page',
             process_links='filter_links',
             follow=True),
        Rule(LinkExtractor(allow=('accessories-all.aspx')),
             callback='parse_page',
             process_links='filter_links',
             follow=True),
        Rule(LinkExtractor(allow=('Shoes-All.aspx')),
             callback='parse_page',
             process_links='filter_links',
             follow=True),
        # Rule(LinkExtractor(allow=('Sale-In.aspx')),
        #      callback='parse_page',
        #      process_links='filter_links',
        #      follow=True),
    )
    pipeline = set([
        DuplicatesPipeline,
    ])

    # sets default currency
    currency = 'usd'
    SESSION_COOKIE = SESSION_COOKIE or {}
    gender = None

    def make_requests_from_url(self, url):
        """Makes sure the same cookie is set for all the requests, this way
        we ensure integrity on the items' currency value, for example."""
        request = super(OxygenSpider, self).make_requests_from_url(url)
        try:
            request.cookies['ASP.NET_SessionId'] = \
                self.SESSION_COOKIE[self.currency]
        except KeyError:
            pass
        return request

    def filter_links(self, links):
        """Does pagination but skips the 'View All' items pages."""
        return [link for link in links if 'ViewAll=1' not in link.url]

    def get_cookie(self, currency):
        """Returns dictionary with thec cookie parameters"""
        return {'ASP.NET_SessionId': self.SESSION_COOKIE[currency],
                'domain': 'www.oxygenboutique.com',
                'host': 'www.oxygenboutique.com',
                'expires': '2018-04-08T07:37:48.899Z',
                'cookie_notified': 'true',
                'path': '/',
                'HttpOnly': 'true',
                'isHttpOnly': 'true',
                'host-only': 'true',
                'isSecure': 'true'}

    def set_cookie(self, currency):
        self.SESSION_COOKIE[currency] = self.get_cookie_for_currency(currency)

    def parse_name(self, product):
        """Parses name from <h3> tag."""
        return product.find('h3').text()

    def parse_code(self, title):
        """Parses name from page title."""
        return title.partition(' | ')[0].lower().replace(' ', '-')

    def parse_description(self, name):
        """Parses description crawling the #accordion div."""
        desc = self.pq_form('#accordion').find('div')[0].text.strip().replace(
            u"\u00A0", " ").encode('UTF-8') or \
            self.pq_form('#accordion').find('div').eq(1).text().replace(
                u"\u00A0", " ").encode('UTF-8') or \
            self.pq_form('#accordion').find('p').text().strip().replace(
                u"\u00A0", " ").encode('UTF-8')

        return desc

    def parse_designer(self, product):
        """Parses designer name from the first element in the .brand_name
        class."""
        return product.find('.brand_name').eq(0).text()

    def parse_global_description(self, response):
        """Since there isn't information about the gender on the individual
        product pages, a quick/rough solution would be to guess the global
        content of the store by peeking on their About page.

        This method can also be used to gather other information."""
        res = pyquery.PyQuery(response.body)
        description = res('#spCMS').text()

        self.gender = self.parse_gender(description)

        return None

    def parse_gender(self, description):
        """Searches for given keywords in the About Us page (in this case) and
        returns the gender results based on a sample dictionary."""
        gender_keywords = {'F': ['women',
                                 'woman',
                                 'female',
                                 'girl'],
                           'M': ['men',
                                 'man',
                                 'male',
                                 'boy'],
                           }

        gender_results = set()

        for g in gender_keywords:
            for keyword in gender_keywords[g]:
                if re.search(r'\b%s\b' % keyword, description, re.IGNORECASE):
                    gender_results.update(g)

        # if it doesn't produce only one result, this method is inconclusive
        return gender_results.pop() if len(gender_results) == 1 else ''

    def strip_small_imgs(self, images):
        """Strips url and joins it with the main one."""
        return [urljoin(self.start_urls[0],
                        img.partition('smallImage: \'')[2][:-2]) for
                img in images] if images else []

    def parse_images(self):
        """Parses the image fields (large and small) and returns them without
        duplicates."""
        img_selector = self.pq_form('#thumbnails-container').find('a')

        if img_selector:
            small = self.strip_small_imgs([a.items()[3][1] for
                                           a in img_selector])
            large = [urljoin(self.start_urls[0], a.items()[0][1]) for
                     a in img_selector]
        else:
            small, large = [''], ['']

        return list(set(small + large))

    def process_color_words(self, seq, ignore):
        """Finds the first color in the item's description, ignores the
        designer's name."""
        wordset = seq.lower().replace(ignore.lower(), '').split(' ')

        try:
            # check for colors in the given word sequence
            raw_color = next(word for word in wordset if word in COLORS)
        except StopIteration:
            raw_color = ''

        return raw_color

    def parse_raw_color(self, item):
        """Checks for colors in the title first and only then checks in the
        item's description. Crosses them against the COLORS dictionary."""
        # check for colors in the item's title
        raw_color = self.process_color_words(item['name'], item['designer'])

        if not raw_color:
            # check for colors in the item's description
            raw_color = self.process_color_words(item['description'],
                                                 item['designer'])

        return raw_color if raw_color else None

    def parse_currency(self):
        """Parses the price from the item's page, removes the currency sign and
        ignores the lowest price if there's more than one."""
        price = re.search('(\d\.*)+', self.pq_form('.price').text())
        p = [float(i) for i in price.group().strip().split(' ')]

        return "%.2f" % max(p) if len(p) == 2 else "%.2f" % p[0]

    def parse_price(self, product):
        """Parses the price from the items' listing page, removes the currency
        sign and splits if there's more than one price (if it has the
        discounted price as well, for instance."""
        price = re.search('( \d+.+)', product.text())
        p = [float(i) for i in price.group().strip().split(' ')]

        return ["%.2f" % max(p), min(p)] if len(p) == 2 else \
            ["%.2f" % p[0], 0.0]

    def parse_stock_status(self):
        """Parses the select field and ignores the first option, assigns 1 to
        out of stock products and 3 to products in stock."""
        selects = [sel for sel in self.pq_form(
            '#ctl00_ContentPlaceHolder1_ddlSize').find('option')
            if sel.items()[0][1] != '-1']

        keys = [re.sub(r'( - Sold Out)', '', sel.text) for sel in selects]
        values = [3 if len(sel.get('value')) > 1 else 1 for sel in selects]

        return dict(zip(keys, values))

    def parse_type(self, description):
        """Checks for the item type in the title and description, crosses the
        words against the ITEM_DICT dictionary. If there's more than one word,
        then the idea is to look for their semantics. Each word in the dict has
        a weigth attribute, based on how meaningful the word is for the item's
        type."""
        wordset = re.findall(r"[\w']+", description.lower())
        matches = [word for word in ITEM_DICT.keys() if word in wordset] or ''

        if len(matches) > 1:
            keys = [(word, ITEM_DICT[word]['weigth']) for word in matches]
            keys.sort(key=lambda tup: tup[1], reverse=True)
            item_type = ITEM_DICT[keys.pop()[0]]['type']
        else:
            item_type = ITEM_DICT[matches[0]]['type'] if matches else ''

        return item_type

    def parse_page(self, response):
        """First method to parse the page feeded by the link extractor."""
        self.pq = pyquery.PyQuery(response.body)
        self.VIEWSTATE = self.pq(
            'input[name="__VIEWSTATE"]')[0].items()[3][1]
        # self.set_cookie(self.currency)
        products = self.pq('.itm')

        for i, product in enumerate(products):
            item = OxygendemoItem()
            item['name'] = self.parse_name(products.eq(i))
            item['code'] = self.parse_code(item['name'])
            item['designer'] = self.parse_designer(products.eq(i))
            href = products.eq(i).find('a')[0].get('href').replace(' ', '-')
            item['link'] = urljoin(self.start_urls[0], href)
            item['usd_price'], item['sale_discount'] = \
                self.parse_price(products.eq(i).find('.price'))
            item['gender'] = self.gender

            request = Request(item['link'],
                              callback=self.parse_form,
                              cookies=self.get_cookie('usd'),
                              meta={'item': item,
                                    'dont_merge_cookies': True})

            request.meta['item'] = item

            yield request

    def parse_form(self, response):
        """Makes a form request to the item's details page, changes the
        currency on the new cookie so it saves one request only to get a
        different currency."""
        item = response.meta['item']

        params = self.get_post_data_for_cookie(self.currency)

        self.currency = 'eur'
        form = FormRequest(url=item['link'],
                           formdata=params,
                           cookies=self.get_cookie(self.currency),
                           callback=self.parse_product)

        form.meta['item'] = item

        yield form

    def parse_product(self, response):
        """Parses the item's fields that are only accessible on the item's
        details page. Again it changes the currency and performs a new form
        request with a new cookie, this time only to get a different
        currency."""
        item = response.meta['item']
        self.pq_form = pyquery.PyQuery(response.body)

        item['description'] = self.parse_description(item['name'])
        item['type'] = self.parse_type(' '.join([item['name'],
                                                 item['description']]))
        item['images'] = self.parse_images()
        item['stock_status'] = self.parse_stock_status()
        item['raw_color'] = self.parse_raw_color(item)

        item['eur_price'] = self.parse_currency()

        self.currency = 'gbp'
        params_gbp = self.get_post_data_for_cookie(self.currency)

        form_eur = FormRequest(url=item['link'],
                               formdata=params_gbp,
                               cookies=self.get_cookie(self.currency),
                               callback=self.parse_last_currency)

        form_eur.meta['item'] = item

        yield form_eur

    def parse_last_currency(self, response):
        """Parses the last currency needed asked on the last form request
        performed. Changes the currency back to the original one."""
        item = response.meta['item']
        self.pq_form = pyquery.PyQuery(response.body)

        item['gbp_price'] = self.parse_currency()

        self.currency = 'usd'

        return item

    def get_post_data_for_cookie(self, currency):
        """Returns the cookie post data parameters."""
        return {
            '__EVENTTARGET': "lnkCurrency",
            '__EVENTARGUMENT': "",
            '__VIEWSTATE': self.VIEWSTATE,
            '__VIEWSTATEGENERATOR': 'B541BF03',
            'ddlCountry1': 'United Kingdom',
            'ddlCurrency': CURRENCY_CODE[currency],
        }

    def get_cookie_for_currency(self, currency):
        """Makes a request to get a new cookie."""
        post_data = self.get_post_data_for_cookie(currency)

        response = urlopen(urljoin(self.start_urls[0], "Currency.aspx"),
                           data=urlencode(post_data))
        m = re.search('(ASP.NET_SessionId=\w+)',
                      response.headers.dict['set-cookie'])
        cookie = m.group().strip()[18:] if m else ''

        return cookie

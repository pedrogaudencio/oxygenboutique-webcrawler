from scrapy import Item, Field


class OxygendemoItem(Item):
    """Oxygen product item."""
    name = Field()
    code = Field()
    designer = Field()
    link = Field()
    description = Field()
    stock_status = Field()
    usd_price = Field()
    sale_discount = Field()
    images = Field()
    raw_color = Field()
    gender = Field()
    type = Field()
    eur_price = Field()
    eur_sale_discount = Field()
    gbp_price = Field()
    gbp_sale_discount = Field()

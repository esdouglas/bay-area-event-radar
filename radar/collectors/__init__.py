"""Collector registry: maps a source's `method` to the function that collects it."""
from .aggregators import (collect_allevents, collect_eventbrite_api, collect_eventbrite_web,
                          collect_songkick)
from .html_llm import collect_html
from .structured import (collect_dice, collect_ics, collect_jsonld, collect_localist, collect_squarespace,
                         collect_tribe)

METHODS = {
    "ics": collect_ics,
    "gcal": collect_ics,
    "jsonld": collect_jsonld,
    "tribe": collect_tribe,
    "squarespace": collect_squarespace,
    "localist": collect_localist,
    "dice": collect_dice,
    "songkick": collect_songkick,
    "eventbrite_api": collect_eventbrite_api,
    "eventbrite_web": collect_eventbrite_web,
    "allevents": collect_allevents,
    "html": collect_html,
}

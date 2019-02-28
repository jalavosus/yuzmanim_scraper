import re
import json
import time
# import arrow
import requests
import datetime
from pprint import pprint
from pymongo import MongoClient

from config import ADMIN_PASSWORD


DBNAME = "yuzmanim"
MONGO_URL = f"mongodb://admin:{ADMIN_PASSWORD}@ds255005.mlab.com:55005/{DBNAME}"
CLIENT = MongoClient(MONGO_URL)
DB = CLIENT[DBNAME]

CHROME_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.109 Safari/537.36"

MINYANIM = [ "shacharis", "mincha", "maariv" ]


def get_date():
  return datetime.datetime.now().strftime("%Y-%m-%d")


def create_cookie_string(cookiejar):
  """
    Takes a requests.cookiejar object, and returns a string with the relevant
    cookie info.
  """
  cookie_string = f"XSRF-TOKEN={cookiejar['XSRF-TOKEN']}; laravel_session={cookiejar['laravel_session']}"

  return cookie_string


def get_header_data():
  """
    Loads the shacharit page of YUZmanim, which fires off an API request
    to its backend. Because the YUZmanim Devs hate people stealing their data,
    they use CSRF tokens and whatnot to prevent regular humans from directly
    querying their API.
    Well, guess what YUZmanim Devs? You can regex the CSRF token out of the page's
    HTML.
    Returns a header dict with all the fields that are present when an API
    request is fired off from the website.
  """
  # never regex HTML
  csrf_re = re.compile(r'<meta name="csrf-token" content=(.+)>')

  url = "https://www.yuzmanim.com/shacharis"
  s = requests.session()
  # The page actually won't load a CSRF token if you're not using
  # a real browser. So, we lie and say we're a real browser.
  req_headers = { "User-Agent": CHROME_USER_AGENT }

  r = s.get(url, headers=req_headers)

  html = r.text

  # Fun fact: the API will respond with a 404 if your user-agent
  # is fake news.
  header_data = {
    "X-CSRF-TOKEN":       "",
    "X-REQUESTED-WITH":   "XMLHttpRequest",
    "Host":               "www.yuzmanim.com",
    "Origin":             "https://www.yuzmanim.com",
    "Referer":            "https://www.yuzmanim.com/shacharis",
    "Cookie":             create_cookie_string(r.cookies),
    "User-Agent":         CHROME_USER_AGENT
  }

  csrf_match = csrf_re.search(html)
  if csrf_match:
    header_data["X-CSRF-TOKEN"] = csrf_match.groups(0)[0].replace("\"", "")
  else:
    print("Womp")


  return header_data


def get_json(header_data, minyan, date=None):
  url = f"https://www.yuzmanim.com/data/{minyan}"

  form_data = {}

  if date:
    form_data["day"] = date

  # I have no fucking idea why this is a post request.
  r = requests.post(url, headers=header_data, data=form_data)

  data = r.text

  data = json.loads(data)

  return data


def sanitize_minyan_data(minyan_data, **kwargs):
  # Ashkenazi hebrew is the worst
  if kwargs["minyan"] == "shacharis":
    kwargs["minyan"] = "shacharit"

  sanitized_data = {
    "name":         minyan_data["name"],
    "location":     minyan_data["slug"],
    "date":         minyan_data["time"]["date"][0:10],
    "time":         minyan_data["time"]["date"][11:19],
    "minyan":       kwargs["minyan"],
    "hebrew_date":  kwargs["hebrew_date"],
    "day_of_week":  kwargs["day_of_week"]
  }

  return sanitized_data


def parse_json_data(json_data, minyan):
  crap_string = "<a class='btn btn-outline-secondary btn-lg' href='https://www.yuzmanim.com/shabbos'>See Shabbos Schedule</a>"

  parsed_data = []

  hebrew_date = json_data["jewish_date"]
  day_of_week = json_data["day_of_week"]

  all_minyanim = json_data["minyanim"][0]
  # Basically, if the schedule is Friday maariv or all of Saturday
  if "text" in all_minyanim and all_minyanim["text"] == crap_string:
    pass
  else:
    all_minyanim = all_minyanim["tefillos"]
    splat_args = { "minyan": minyan, "hebrew_date": hebrew_date, "day_of_week": day_of_week }

    parsed_data += [sanitize_minyan_data(md, **splat_args) for md in all_minyanim]

  return parsed_data


def mongo_insert(data, minyan):
  collection = DB[minyan]

  existing_dates = collection.distinct("date")
  minyanim_to_insert = []
  for d in data:
    if d["date"] not in existing_dates and d["minyan"] == minyan:
      minyanim_to_insert.append(d)

  if len(minyanim_to_insert) > 0:
    collection.insert_many(minyanim_to_insert)


def main():
  header_data = get_header_data()

  date_list = None

  for minyan in MINYANIM:
    raw_data = get_json(header_data, minyan)

    if minyan == "shacharis":
      minyan = "shacharit"

    if not date_list:
      date_list = [d["date"] for d in raw_data["days_list"][1:]]

    parsed_data = parse_json_data(raw_data, minyan)

    for date in date_list:
      raw_data = get_json(header_data, minyan, date=date)
      parsed_data += parse_json_data(raw_data, minyan)

    pprint(parsed_data)
    # mongo_insert(parsed_data, minyan)


if __name__ in '__main__':
  main()

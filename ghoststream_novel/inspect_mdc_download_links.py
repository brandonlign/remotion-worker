#!/usr/bin/env python3
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

url = "https://ceresiaumdc.ta3.sk/downloads"
response = requests.get(url, timeout=120)
response.raise_for_status()
print("PAGE", response.url, response.status_code, len(response.content))
soup = BeautifulSoup(response.text, "html.parser")
for link in soup.find_all("a", href=True):
    text = " ".join(link.get_text(" ", strip=True).split())
    href = urljoin(response.url, link["href"])
    if "template" in href.lower() or "json" in href.lower() or "mean" in text.lower() or "look" in text.lower():
        print(repr(text), href)

for candidate in [
    "https://ceresiaumdc.ta3.sk/downloads/templates_data/template-mean-data.json",
    "https://ceresiaumdc.ta3.sk/downloads/templates_data/template_mean_data.json",
    "https://ceresiaumdc.ta3.sk/downloads/templates_data/template-shower-data.json",
]:
    r = requests.get(candidate, timeout=120)
    print("CANDIDATE", candidate, r.status_code, len(r.content), r.headers.get("content-type"))
    if r.status_code == 200:
        print(r.text[:20000])

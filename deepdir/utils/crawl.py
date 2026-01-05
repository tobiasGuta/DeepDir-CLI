# -*- coding: utf-8 -*-
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#  Author: Mauro Soria

import re
from functools import lru_cache

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

from deepdir.core.settings import (
    CRAWL_ATTRIBUTES, CRAWL_TAGS,
    MEDIA_EXTENSIONS, ROBOTS_TXT_REGEX,
    URI_REGEX,
)
from deepdir.parse.url import clean_path, parse_path
from deepdir.utils.common import merge_path


def _filter(paths):
    return {clean_path(path, keep_queries=True) for path in paths if not path.endswith(MEDIA_EXTENSIONS)}


class Crawler:
    @classmethod
    def crawl(cls, response):
        scope = "/".join(response.url.split("/")[:3]) + "/"
        content_type = response.headers.get("content-type", "")

        if "text/html" in content_type:
            return cls.html_crawl(response.url, scope, response.content)
        elif "javascript" in content_type or response.path.endswith(".js"):
            return cls.js_crawl(response.url, scope, response.content)
        elif response.path == "robots.txt":
            return cls.robots_crawl(response.url, scope, response.content)
        else:
            return cls.text_crawl(response.url, scope, response.content)

    @staticmethod
    @lru_cache(maxsize=None)
    def js_crawl(url, scope, content):
        results = set()

        # 1. Absolute URLs matching scope
        regex_absolute = re.escape(scope) + "[a-zA-Z0-9-._~!$&*+,;=:@?%/]+"
        for match in re.findall(regex_absolute, content):
            results.add(match[len(scope):])

        # 2. Relative paths starting with /
        regex_root = r"['\"](/[a-zA-Z0-9-._~!$&*+,;=:@?%/]+)['\"]"
        for match in re.findall(regex_root, content):
            results.add(match[1:])

        # 3. Relative paths with subdirectories
        regex_subdir = r"['\"]([a-zA-Z0-9-._~!$&*+,;=:@?%]+(?:/[a-zA-Z0-9-._~!$&*+,;=:@?%]+)+)['\"]"
        for match in re.findall(regex_subdir, content):
            if match not in ["application/json", "text/html", "text/plain"]:
                results.add(match)

        # 4. Files with extensions
        regex_files = r"['\"]([a-zA-Z0-9-._~!$&*+,;=:@?%]+\.(?:json|xml|php|asp|aspx|jsp|html|htm|js|css|map|txt|conf|config|sql|db|bak|old))['\"]"
        for match in re.findall(regex_files, content):
            results.add(match)

        return _filter(results)

    @staticmethod
    @lru_cache(maxsize=None)
    def text_crawl(url, scope, content):
        results = []
        regex = re.escape(scope) + "[a-zA-Z0-9-._~!$&*+,;=:@?%/]+"

        for match in re.findall(regex, content):
            results.append(match[len(scope):])

        return _filter(results)

    @staticmethod
    @lru_cache(maxsize=None)
    def html_crawl(url, scope, content):
        results = []
        
        if HAS_BS4:
            # Prefer lxml if available, otherwise html.parser
            # lxml is much faster than html.parser
            try:
                soup = BeautifulSoup(content, 'lxml')
            except Exception:
                soup = BeautifulSoup(content, 'html.parser')

            for tag in CRAWL_TAGS:
                for found in soup.find_all(tag):
                    for attr in CRAWL_ATTRIBUTES:
                        value = found.get(attr)

                        if not value:
                            continue

                        if value.startswith("/"):
                            results.append(value[1:])
                        elif value.startswith(scope):
                            results.append(value[len(scope):])
                        elif not re.search(URI_REGEX, value):
                            new_url = merge_path(url, value)
                            results.append(parse_path(new_url))
        else:
            # Fallback to regex if BS4 is not installed (though it is in requirements)
            # or if we want a lightweight fallback
            regex_href = r'href=["\'](.*?)["\']'
            regex_src = r'src=["\'](.*?)["\']'
            
            for regex in [regex_href, regex_src]:
                for match in re.findall(regex, content):
                    if match.startswith("/"):
                        results.append(match[1:])
                    elif match.startswith(scope):
                        results.append(match[len(scope):])
                    elif not re.search(URI_REGEX, match):
                        new_url = merge_path(url, match)
                        results.append(parse_path(new_url))

        return _filter(results)

    @staticmethod
    @lru_cache(maxsize=None)
    def robots_crawl(url, scope, content):
        return _filter(re.findall(ROBOTS_TXT_REGEX, content))

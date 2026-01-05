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

from urllib.parse import urlparse

from deepdir.core.data import options
from deepdir.core.settings import STANDARD_PORTS, START_TIME
from deepdir.report.csv_report import CSVReport
from deepdir.report.html_report import HTMLReport
from deepdir.report.json_report import JSONReport
from deepdir.report.markdown_report import MarkdownReport
from deepdir.report.mysql_report import MySQLReport
from deepdir.report.plain_text_report import PlainTextReport
from deepdir.report.postgresql_report import PostgreSQLReport
from deepdir.report.simple_report import SimpleReport
from deepdir.report.sqlite_report import SQLiteReport
from deepdir.report.xml_report import XMLReport

# We need to defer the creation of output_handlers until we are inside __init__
# because options is now a Config object and its attributes might not be populated yet
# or we want to access them dynamically.

class ReportManager:
    def __init__(self, formats):
        self.reports = []
        
        # Define handlers dynamically to access current options
        output_handlers = {
            "simple": (SimpleReport, [options.output_file]),
            "plain": (PlainTextReport, [options.output_file]),
            "json": (JSONReport, [options.output_file]),
            "xml": (XMLReport, [options.output_file]),
            "md": (MarkdownReport, [options.output_file]),
            "csv": (CSVReport, [options.output_file]),
            "html": (HTMLReport, [options.output_file]),
            "sqlite": (SQLiteReport, [options.output_file, options.output_table]),
            "mysql": (MySQLReport, [options.mysql_url, options.output_table]),
            "postgresql": (PostgreSQLReport, [options.postgres_url, options.output_table]),
        }

        for format in formats:
            # No output location provided
            if any(not _ for _ in output_handlers[format][1]):
                continue
            self.reports.append((output_handlers[format][0](), output_handlers[format][1]))

    def prepare(self, target):
        for reporter, sources in self.reports:
            reporter.initiate(
                *map(
                    lambda s: self.format(s, target, reporter),
                    sources,
                )
            )

    def save(self, result):
        for reporter, sources in self.reports:
            reporter.save(
                *map(
                    lambda s: self.format(s, result.url, reporter),
                    sources,
                ),
                result,
            )

    def finish(self):
        for reporter, sources in self.reports:
            reporter.finish()

    def format(self, string, target, handler):
        parsed = urlparse(target)

        return string.format(
            datetime=START_TIME.replace(" ", "_"),
            date=START_TIME.split()[0],
            host=parsed.hostname,
            scheme=parsed.scheme,
            port=parsed.port or STANDARD_PORTS[parsed.scheme],
            format=handler.__format__,
            extension=handler.__extension__,
        )

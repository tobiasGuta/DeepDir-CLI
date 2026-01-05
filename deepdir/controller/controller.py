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

from __future__ import annotations

import asyncio
import gc
import os
import signal
import psycopg
import re
import time
import uuid
import mysql.connector
try:
    import cPickle as pickle
except ModuleNotFoundError:
    import pickle

from urllib.parse import urlparse

from deepdir.connection.dns import cache_dns
from deepdir.connection.response import BaseResponse
from deepdir.core.data import blacklists, options
from deepdir.core.decorators import locked
from deepdir.core.dictionary import Dictionary, get_blacklists
from deepdir.core.exceptions import (
    CannotConnectException,
    FileExistsException,
    InvalidRawRequest,
    InvalidURLException,
    RequestException,
    SkipTargetInterrupt,
    QuitInterrupt,
    UnpicklingError,
)
from deepdir.core.logger import enable_logging, logger
from deepdir.core.settings import (
    BANNER,
    DEFAULT_HEADERS,
    DEFAULT_SESSION_FILE,
    EXTENSION_RECOGNITION_REGEX,
    MAX_CONSECUTIVE_REQUEST_ERRORS,
    NEW_LINE,
    STANDARD_PORTS,
    UNKNOWN,
)
from deepdir.core.waf import WAF
from deepdir.parse.rawrequest import parse_raw
from deepdir.parse.url import clean_path, parse_path
from deepdir.report.manager import ReportManager
from deepdir.utils.common import lstrip_once
from deepdir.utils.crawl import Crawler
from deepdir.utils.file import FileUtils
from deepdir.utils.mutation import Mutator
from deepdir.utils.schemedet import detect_scheme
from deepdir.view.terminal import interface
from deepdir.view.colors import set_color


class Controller:
    def __init__(self) -> None:
        if options.session_file:
            self._import(options.session_file)
            self.old_session = True
        else:
            self.setup()
            self.old_session = False

        self.run()

    def _import(self, session_file: str) -> None:
        try:
            with open(session_file, "rb") as fd:
                dict_, last_output, opt = pickle.load(fd)
                options.update(opt)
        except UnpicklingError:
            interface.error(
                f"{session_file} is not a valid session file or it's in an old format"
            )
            exit(1)

        self.__dict__ = {**dict_, **vars(self)}
        print(last_output)

    def _export(self, session_file: str) -> None:
        # Save written output
        last_output = interface.buffer.rstrip()

        dict_ = vars(self).copy()
        # Can't pickle some classes due to _thread.lock objects
        dict_.pop("fuzzer", None)
        dict_.pop("pause_future", None)
        dict_.pop("loop", None)
        dict_.pop("requester", None)

        with open(session_file, "wb") as fd:
            pickle.dump((dict_, last_output, options), fd)

    def setup(self) -> None:
        blacklists.update(get_blacklists())

        if options.raw_file:
            try:
                options.update(
                    zip(
                        ["urls", "http_method", "headers", "data"],
                        parse_raw(options.raw_file),
                    )
                )
            except InvalidRawRequest as e:
                print(str(e))
                exit(1)
        else:
            options.headers = {**DEFAULT_HEADERS, **options.headers}

        self.dictionary = Dictionary(files=options.wordlists)
        self.start_time = time.time()
        self.passed_urls: set[str] = set()
        self.directories: list[str] = []
        self.jobs_processed = 0
        self.errors = 0
        self.consecutive_errors = 0
        self.consecutive_filtered = 0
        self.results: list[BaseResponse] = []

        if options.log_file:
            try:
                FileUtils.create_dir(FileUtils.parent(options.log_file))
                if not FileUtils.can_write(options.log_file):
                    raise Exception

                enable_logging()

            except Exception:
                interface.error(
                    f'Couldn\'t create log file at {options.log_file}'
                )
                exit(1)

        interface.header(BANNER)
        interface.config(len(self.dictionary))

        try:
            self.reporter = ReportManager(options.output_formats)
        except (
            InvalidURLException,
            mysql.connector.Error,
            psycopg.Error,
        ) as e:
            logger.exception(e)
            interface.error(str(e))
            exit(1)

        if options.log_file:
            interface.log_file(options.log_file)

    def run(self) -> None:
        if options.bypass_waf and options.async_mode:
            interface.warning("Disabling async mode because --bypass-waf is enabled (cloudscraper is synchronous)")
            options.async_mode = False

        if options.async_mode:
            from deepdir.connection.requester import AsyncRequester as Requester
            from deepdir.core.fuzzer import AsyncFuzzer as Fuzzer

            try:
                import uvloop
                asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            except ImportError:
                pass
        else:
            from deepdir.connection.requester import Requester
            from deepdir.core.fuzzer import Fuzzer

        # match_callbacks and not_found_callbacks callback values:
        #  - *args[0]: lib.connection.Response() object
        #
        # error_callbacks callback values:
        #  - *args[0]: exception
        match_callbacks = (
            self.match_callback, self.reporter.save, self.reset_consecutive_errors, self.update_progress_bar
        )
        not_found_callbacks = (
            self.update_progress_bar, self.reset_consecutive_errors, self.track_filtered
        )
        error_callbacks = (self.raise_error, self.append_error_log)

        self.requester = Requester()
        if options.async_mode:
            self.loop = asyncio.new_event_loop()

        signal.signal(signal.SIGINT, lambda *_: self.handle_pause())
        signal.signal(signal.SIGTERM, lambda *_: self.handle_pause())

        while options.urls:
            url = options.urls[0]
            self.fuzzer = Fuzzer(
                self.requester,
                self.dictionary,
                match_callbacks=match_callbacks,
                not_found_callbacks=not_found_callbacks,
                error_callbacks=error_callbacks,
            )

            try:
                self.set_target(url)

                if not self.directories:
                    for subdir in options.subdirs:
                        self.add_directory(self.base_path + subdir)

                if not self.old_session:
                    interface.target(self.url)

                self.reporter.prepare(self.url)
                self.start()

            except (
                CannotConnectException,
                FileExistsException,
                InvalidURLException,
                RequestException,
                SkipTargetInterrupt,
                KeyboardInterrupt,
            ) as e:
                self.directories.clear()
                self.dictionary.reset()

                if e.args:
                    interface.error(str(e))

            except QuitInterrupt as e:
                self.reporter.finish()
                interface.error(e.args[0])
                exit(0)

            finally:
                options.urls.pop(0)

        interface.warning("\nTask Completed")
        self.reporter.finish()
        self.interactive_summary()

        if options.session_file:
            try:
                os.remove(options.session_file)
            except Exception:
                interface.error("Failed to delete old session file, remove it to free some space")

    def start(self) -> None:
        start_time = time.time()

        while self.directories:
            try:
                gc.collect()

                current_directory = self.directories[0]

                if not self.old_session:
                    current_time = time.strftime("%H:%M:%S")
                    msg = f"{NEW_LINE}[{current_time}] Scanning: {current_directory}"

                    interface.warning(msg)

                self.fuzzer.set_base_path(current_directory)
                if options.async_mode:
                    # use a future to get exceptions from handle_pause
                    # https://stackoverflow.com/a/64230941
                    self.pause_future = self.loop.create_future()
                    self.loop.run_until_complete(self.start_coroutines(start_time))
                else:
                    self.fuzzer.start()
                    self.process(start_time)

            except (KeyboardInterrupt, asyncio.CancelledError):
                pass

            finally:
                self.dictionary.reset()
                self.directories.pop(0)

                self.jobs_processed += 1
                self.old_session = False

    async def start_coroutines(self, start_time: float) -> None:
        task = self.loop.create_task(self.fuzzer.start())
        timeout = min(
            t for t in [
                options.max_time - (time.time() - self.start_time),
                options.target_max_time - (time.time() - start_time),
            ] if t > 0
        ) if options.max_time or options.target_max_time else None

        try:
            await asyncio.wait_for(
                asyncio.wait(
                    [self.pause_future, task],
                    return_when=asyncio.FIRST_COMPLETED,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            if time.time() - self.start_time > options.max_time > 0:
                raise QuitInterrupt("Runtime exceeded the maximum set by the user")

            raise SkipTargetInterrupt("Runtime for target exceeded the maximum set by the user")

        if self.pause_future.done():
            task.cancel()
            await self.pause_future  # propagate the exception, if raised

        await task  # propagate the exception, if raised

    def process(self, start_time: float) -> None:
        while True:
            while not self.fuzzer.is_finished():
                now = time.time()
                if now - self.start_time > options.max_time > 0:
                    raise QuitInterrupt(
                        "Runtime exceeded the maximum set by the user"
                    )
                if now - start_time > options.target_max_time > 0:
                    raise SkipTargetInterrupt(
                        "Runtime for target exceeded the maximum set by the user"
                    )

                time.sleep(0.5)

            break

    def calibrate(self) -> None:
        interface.warning("Calibrating...")
        random_path = str(uuid.uuid4())
        response = self.requester.request(random_path)
        options.calibration_response = response
        interface.warning(f"Calibration response: {response.status} - {response.length}B")

    def set_target(self, url: str) -> None:
        # If no scheme specified, unset it first
        if "://" not in url:
            url = f'{options.scheme or UNKNOWN}://{url}'
        if not url.endswith("/"):
            url += "/"

        parsed = urlparse(url)
        self.base_path = lstrip_once(parsed.path, "/")

        # Credentials in URL
        if "@" in parsed.netloc:
            cred, parsed.netloc = parsed.netloc.split("@")
            self.requester.set_auth("basic", cred)

        if parsed.scheme not in (UNKNOWN, "https", "http"):
            raise InvalidURLException(f"Unsupported URI scheme: {parsed.scheme}")

        port = parsed.port
        # If no port is specified, set default (80, 443) based on the scheme
        if not port:
            port = STANDARD_PORTS.get(parsed.scheme, None)
        elif not 0 < port < 65536:
            raise InvalidURLException(f"Invalid port number: {port}")

        if options.ip:
            cache_dns(parsed.hostname, port, options.ip)

        try:
            # If no scheme is found, detect it by port number
            scheme = (
                parsed.scheme
                if parsed.scheme != UNKNOWN
                else detect_scheme(parsed.hostname, port)
            )
        except ValueError:
            # If the user neither provides the port nor scheme, guess them based
            # on standard website characteristics
            scheme = detect_scheme(parsed.hostname, 443)
            port = STANDARD_PORTS[scheme]

        self.url = f"{scheme}://{parsed.hostname}"

        if port != STANDARD_PORTS[scheme]:
            self.url += f":{port}"

        self.url += "/"

        self.requester.set_url(self.url)

        if options.bypass_waf:
             # Check root
             try:
                 root_resp = self.requester.request("/")
                 if root_resp.status == 403:
                      interface.warning("Critical: The root path '/' returned 403 Forbidden. WAF bypass might have failed.")
             except:
                 pass

        if options.calibration:
            self.calibrate()

    def reset_consecutive_errors(self, response: BaseResponse) -> None:
        self.consecutive_errors = 0

    def track_filtered(self, response: BaseResponse) -> None:
        self.consecutive_filtered += 1
        if self.consecutive_filtered == 100 and response.status == 403:
             interface.warning("Warning: 100 consecutive requests were filtered. If the wildcard response is 403, you are likely blocked by the WAF.")

    def match_callback(self, response: BaseResponse) -> None:
        self.consecutive_filtered = 0
        self.results.append(response)
        if response.status in options.skip_on_status:
            raise SkipTargetInterrupt(
                f"Skipped the target due to {response.status} status code"
            )

        waf_result = WAF.analyze(response)

        interface.status_report(response, options.full_url, waf_result)

        if response.status in options.recursion_status_codes and any(
            (
                options.recursive,
                options.deep_recursive,
                options.force_recursive,
            )
        ):
            if response.redirect:
                new_path = clean_path(parse_path(response.redirect))
                added_to_queue = self.recur_for_redirect(response.path, new_path)
            elif len(response.history):
                old_path = clean_path(parse_path(response.history[0]))
                added_to_queue = self.recur_for_redirect(old_path, response.path)
            else:
                added_to_queue = self.recur(response.path)

            if added_to_queue:
                interface.new_directories(added_to_queue)

        if options.replay_proxy:
            # Replay the request with new proxy
            if options.async_mode:
                self.loop.create_task(self.requester.replay_request(response.full_path, proxy=options.replay_proxy))
            else:
                self.requester.request(response.full_path, proxy=options.replay_proxy)

        if options.crawl:
            for path in Crawler.crawl(response):
                if not self.dictionary.is_valid(path):
                    continue
                path = lstrip_once(path, self.base_path)
                self.dictionary.add_extra(path)

        if options.mutation:
            for path in Mutator.mutate(response.path):
                if not self.dictionary.is_valid(path):
                    continue
                path = lstrip_once(path, self.base_path)
                self.dictionary.add_extra(path)

    def update_progress_bar(self, response: BaseResponse) -> None:
        jobs_count = (
            # Jobs left for unscanned targets
            len(options.subdirs) * (len(options.urls) - 1)
            # Jobs left for the current target
            + len(self.directories)
            # Finished jobs
            + self.jobs_processed
        )

        interface.last_path(
            self.dictionary.index,
            len(self.dictionary),
            self.jobs_processed + 1,
            jobs_count,
            self.requester.rate,
            self.errors,
        )

    def raise_error(self, exception: RequestException) -> None:
        if options.exit_on_error:
            raise QuitInterrupt("Canceled due to an error")

        self.errors += 1
        self.consecutive_errors += 1

        if self.consecutive_errors > MAX_CONSECUTIVE_REQUEST_ERRORS:
            raise SkipTargetInterrupt("Too many request errors")

    def append_error_log(self, exception: RequestException) -> None:
        logger.exception(exception)

    def handle_pause(self) -> None:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            interface.warning(
                "CTRL+C detected: Pausing threads, please wait...", do_save=False
            )
            self.fuzzer.pause()

            while True:
                msg = "[q]uit / [c]ontinue"

                if len(self.directories) > 1:
                    msg += " / [n]ext"

                if len(options.urls) > 1:
                    msg += " / [s]kip target"

                interface.in_line(msg + ": ")

                option = input()

                if option.lower() == "q":
                    interface.in_line("[s]ave / [q]uit without saving: ")

                    option = input()

                    if option.lower() == "s":
                        msg = f'Save to file [{options.session_file or DEFAULT_SESSION_FILE}]: '

                        interface.in_line(msg)

                        session_file = (
                            input() or options.session_file or DEFAULT_SESSION_FILE
                        )

                        self._export(session_file)
                        quitexc = QuitInterrupt(f"Session saved to: {session_file}")
                        self.fuzzer.quit()
                        if options.async_mode:
                            self.pause_future.set_exception(quitexc)
                            break
                        else:
                            raise quitexc
                    elif option.lower() == "q":
                        quitexc = QuitInterrupt("Canceled by the user")
                        self.fuzzer.quit()
                        if options.async_mode:
                            self.pause_future.set_exception(quitexc)
                            break
                        else:
                            raise quitexc

                elif option.lower() == "c":
                    self.fuzzer.play()
                    break

                elif option.lower() == "n" and len(self.directories) > 1:
                    self.fuzzer.quit()
                    break

                elif option.lower() == "s" and len(options.urls) > 1:
                    skipexc = SkipTargetInterrupt("Target skipped by the user")
                    if options.async_mode:
                        self.pause_future.set_exception(skipexc)
                        break
                    else:
                        raise skipexc
        finally:
            signal.signal(signal.SIGINT, lambda *_: self.handle_pause())

    def add_directory(self, path: str) -> None:
        """Add directory to the recursion queue"""

        # Pass if path is in exclusive directories
        if any(
            path.startswith(dir) or "/" + dir in path
            for dir in options.exclude_subdirs
        ):
            return

        url = self.url + path

        if (
            path.count("/") - self.base_path.count("/") > options.recursion_depth > 0
            or url in self.passed_urls
        ):
            return

        self.directories.append(path)
        self.passed_urls.add(url)

    @locked
    def recur(self, path: str) -> list[str]:
        dirs_count = len(self.directories)
        path = clean_path(path)

        if options.force_recursive and not path.endswith("/"):
            path += "/"

        if options.deep_recursive:
            i = 0
            for _ in range(path.count("/")):
                i = path.index("/", i) + 1
                self.add_directory(path[:i])
        elif (
            options.recursive
            and path.endswith("/")
            and re.search(EXTENSION_RECOGNITION_REGEX, path[:-1]) is None
        ):
            self.add_directory(path)

        # Return newly added directories
        return self.directories[dirs_count:]

    def recur_for_redirect(self, path: str, redirect_path: str) -> list[str]:
        if redirect_path == path + "/":
            return self.recur(redirect_path)
        
        return []

    def interactive_summary(self) -> None:
        if not self.results:
            return

        from collections import Counter
        
        STATUS_DESCRIPTIONS = {
            200: "OK - Request fulfilled",
            201: "Created - Resource created",
            202: "Accepted - Request accepted for processing",
            204: "No Content - Request fulfilled, nothing to return",
            301: "Moved Permanently - Resource has moved",
            302: "Found - Resource temporarily moved",
            304: "Not Modified - Resource has not changed",
            307: "Temporary Redirect",
            308: "Permanent Redirect",
            400: "Bad Request - Invalid syntax",
            401: "Unauthorized - Authentication required",
            403: "Forbidden - Server refuses to fulfill request",
            404: "Not Found - Resource not found",
            405: "Method Not Allowed",
            410: "Gone - Resource no longer available",
            418: "I'm a teapot",
            429: "Too Many Requests - Rate limit exceeded",
            500: "Internal Server Error",
            502: "Bad Gateway",
            503: "Service Unavailable",
            504: "Gateway Timeout"
        }

        # Count status codes
        status_counts = Counter(r.status for r in self.results)
        
        while True:
            interface.header("\n--- Status Code Summary ---")
            
            for status, count in sorted(status_counts.items()):
                # Determine color
                if 200 <= status < 300:
                    color = "green"
                elif 300 <= status < 400:
                    color = "yellow"
                elif 400 <= status < 500:
                    color = "red"
                elif 500 <= status < 600:
                    color = "magenta"
                else:
                    color = "white"
                
                desc = STATUS_DESCRIPTIONS.get(status, "Unknown Status")
                
                # Format: 200: 5 (OK)
                status_str = set_color(f"{status}:", fore=color, style="bright")
                count_str = set_color(str(count), fore="white", style="bright")
                desc_str = set_color(f"({desc})", fore="cyan", style="dim")
                
                print(f"{status_str} {count_str} {desc_str}")
            
            try:
                interface.in_line("\nEnter status code to view URLs (or 'q' to quit): ")
                choice = input().strip().lower()
                
                if choice == 'q':
                    break
                
                if not choice.isdigit():
                    continue
                    
                code = int(choice)
                if code not in status_counts:
                    interface.warning(f"No results found for status code {code}")
                    continue
                
                interface.header(f"\n--- Results for {code} ---")
                for res in self.results:
                    if res.status == code:
                        # Format: [CODE] SIZE - URL
                        msg = f"[{res.status}] {res.size} - {res.full_path}"
                        if res.redirect:
                            msg += f" -> {res.redirect}"
                        print(msg)
                        
            except (KeyboardInterrupt, EOFError):
                break


        return []

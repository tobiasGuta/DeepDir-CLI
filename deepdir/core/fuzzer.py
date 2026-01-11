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
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Any, Callable, Generator

from deepdir.connection.requester import AsyncRequester, BaseRequester, Requester
from deepdir.connection.response import BaseResponse
from deepdir.core.data import blacklists, options
from deepdir.core.dictionary import Dictionary
from deepdir.core.exceptions import RequestException
from deepdir.core.logger import logger
from deepdir.core.scanner import AsyncScanner, BaseScanner, Scanner
from deepdir.core.settings import (
    DEFAULT_TEST_PREFIXES,
    DEFAULT_TEST_SUFFIXES,
    WILDCARD_TEST_POINT_MARKER,
)
from deepdir.core.waf import WAF
from deepdir.parse.url import clean_path
from deepdir.utils.common import get_readable_size, lstrip_once


class BaseFuzzer:
    def __init__(
        self,
        requester: BaseRequester,
        dictionary: Dictionary,
        *,
        match_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        not_found_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        error_callbacks: tuple[Callable[[RequestException], Any], ...],
    ) -> None:
        self._requester = requester
        self._dictionary = dictionary
        self._base_path: str = ""
        self._hashes: dict = {}
        self.match_callbacks = match_callbacks
        self.not_found_callbacks = not_found_callbacks
        self.error_callbacks = error_callbacks
        self.waf_detected = False

        self.scanners: dict[str, dict[str, Scanner]] = {
            "default": {},
            "prefixes": {},
            "suffixes": {},
        }

    def set_base_path(self, path: str) -> None:
        self._base_path = path

    def get_scanners_for(self, path: str) -> Generator[BaseScanner, None, None]:
        # Clean the path, so can check for extensions/suffixes
        path = clean_path(path)

        for prefix in self.scanners["prefixes"]:
            if path.startswith(prefix):
                yield self.scanners["prefixes"][prefix]

        for suffix in self.scanners["suffixes"]:
            if path.endswith(suffix):
                yield self.scanners["suffixes"][suffix]

        for scanner in self.scanners["default"].values():
            yield scanner

    def is_excluded(self, resp: BaseResponse) -> bool:
        """Validate the response by different filters"""

        if resp.status in options.exclude_status_codes:
            return True

        if (
            options.include_status_codes
            and resp.status not in options.include_status_codes
        ):
            return True

        if (
            resp.status in blacklists
            and any(
                resp.path.endswith(lstrip_once(suffix, "/"))
                for suffix in blacklists.get(resp.status)
            )
        ):
            return True

        if get_readable_size(resp.length).rstrip() in options.exclude_sizes:
            return True

        if resp.length < options.minimum_response_size:
            return True

        if resp.length > options.maximum_response_size > 0:
            return True

        if options.exclude_texts and any(text in resp.content for text in options.exclude_texts):
            return True

        if options.exclude_regex and re.search(options.exclude_regex, resp.content):
            return True

        if (
            options.exclude_redirect
            and (
                options.exclude_redirect in resp.redirect
                or re.search(options.exclude_redirect, resp.redirect)
            )
        ):
            return True

        if (
            options.filter_threshold
            and self._hashes.get(hash(resp), 0) >= options.filter_threshold
        ):
            return True

        return False


class Fuzzer(BaseFuzzer):
    def __init__(
        self,
        requester: Requester,
        dictionary: Dictionary,
        *,
        match_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        not_found_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        error_callbacks: tuple[Callable[[RequestException], Any], ...],
    ) -> None:
        super().__init__(
            requester,
            dictionary,
            match_callbacks=match_callbacks,
            not_found_callbacks=not_found_callbacks,
            error_callbacks=error_callbacks,
        )
        self._exc: Exception | None = None
        self._play_event = threading.Event()
        self._quit_event = threading.Event()
        self._pause_semaphore = threading.Semaphore(0)
        self._executor = None
        self._futures: list[Future] = []
        self._print_lock = threading.Lock()

    def setup_scanners(self) -> None:
        # Default scanners (wildcard testers)
        self.scanners["default"]["random"] = Scanner(
            self._requester, path=self._base_path + WILDCARD_TEST_POINT_MARKER
        )
        
        # Report wildcard response
        if not options.no_wildcard:
            wildcard_response = self.scanners["default"]["random"].response
            if wildcard_response:
                waf_name = WAF.detect(wildcard_response)
                msg = f"Wildcard response: {wildcard_response.status} - {wildcard_response.size}"
                if waf_name:
                    msg += f" [{waf_name}]"
                print(msg)

        # Check for WAF on the base path first
        try:
            response = self._requester.request(self._base_path)
            if waf_name := WAF.detect(response):
                self.waf_detected = True
                print(f"[WARNING] WAF Detected: {waf_name}")
        except RequestException:
            pass

        if options.exclude_response:
            self.scanners["default"]["custom"] = Scanner(
                self._requester, tested=self.scanners, path=options.exclude_response
            )

        for prefix in set(options.prefixes + DEFAULT_TEST_PREFIXES):
            self.scanners["prefixes"][prefix] = Scanner(
                self._requester,
                tested=self.scanners,
                path=f"{self._base_path}{prefix}{WILDCARD_TEST_POINT_MARKER}",
                context=f"/{self._base_path}{prefix}***",
            )

        for suffix in set(options.suffixes + DEFAULT_TEST_SUFFIXES):
            self.scanners["suffixes"][suffix] = Scanner(
                self._requester,
                tested=self.scanners,
                path=f"{self._base_path}{WILDCARD_TEST_POINT_MARKER}{suffix}",
                context=f"/{self._base_path}***{suffix}",
            )

        for extension in options.extensions:
            if "." + extension not in self.scanners["suffixes"]:
                self.scanners["suffixes"]["." + extension] = Scanner(
                    self._requester,
                    tested=self.scanners,
                    path=f"{self._base_path}{WILDCARD_TEST_POINT_MARKER}.{extension}",
                    context=f"/{self._base_path}***.{extension}",
                )

    def start(self) -> None:
        self.setup_scanners()
        self.play()
        self._quit_event.clear()
        
        self._executor = ThreadPoolExecutor(max_workers=options.thread_count)
        self._futures = []
        
        # Submit tasks to executor
        for _ in range(options.thread_count):
            self._futures.append(self._executor.submit(self.thread_proc))

    def is_finished(self) -> bool:
        if self._exc:
            raise self._exc
            
        return all(f.done() for f in self._futures)

    def play(self) -> None:
        self._play_event.set()

    def pause(self) -> None:
        self._play_event.clear()
        # With ThreadPoolExecutor we can't force pause easily, 
        # but our thread_proc checks the event.
        # We can't wait for them to stop easily without a counter.
        # For now, we just clear the event.

    def quit(self) -> None:
        self._quit_event.set()
        self.play()
        if self._executor:
            self._executor.shutdown(wait=False)

    def scan(self, path: str) -> None:
        if self._quit_event.is_set():
            return

        scanners = self.get_scanners_for(path)
        try:
            response = self._requester.request(path)
        except RequestException as e:
            for callback in self.error_callbacks:
                callback(e)
            return

        if self._quit_event.is_set():
            return

        if not self._play_event.is_set():
            self._play_event.wait()

        if self._quit_event.is_set():
            return

        if not self.waf_detected:
            if waf_name := WAF.detect(response):
                self.waf_detected = True
                logger.warning(f"WAF Detected: {waf_name}")

        if self.is_excluded(response):
            for callback in self.not_found_callbacks:
                callback(response)
            return

        for tester in scanners:
            # Check if the response is unique, not wildcard
            if not tester.check(path, response):
                for callback in self.not_found_callbacks:
                    callback(response)
                return

        if options.filter_threshold:
            hash_ = hash(response)
            self._hashes.setdefault(hash_, 0)
            self._hashes[hash_] += 1

        # Collect responses to report (atomically)
        to_report = [response]

        # Multi-method scan: Check other methods for the found path
        if len(options.http_methods) > 1:
            # Get other methods excluding the one used for the current response
            current_method = getattr(response, 'method', options.http_method)
            other_methods = [m for m in options.http_methods if m != current_method]
            
            for method in other_methods:
                try:
                    resp2 = self._requester.request(path, method=method)
                    resp2.is_child = True
                    resp2.method = method

                    if not self.is_excluded(resp2):
                         to_report.append(resp2)
                except RequestException:
                    pass

        # Report all gathered results atomically for this path
        with self._print_lock:
            for resp in to_report:
                for callback in self.match_callbacks:
                    callback(resp)

    def thread_proc(self) -> None:
        logger.info(f'THREAD-{threading.get_ident()} started"')

        while True:
            try:
                path = next(self._dictionary)
                self.scan(self._base_path + path)

            except StopIteration:
                break

            except Exception as e:
                self._exc = e
                break

            finally:
                time.sleep(options.delay)

                if not self._play_event.is_set():
                    logger.info(f'THREAD-{threading.get_ident()} paused"')
                    self._pause_semaphore.release()
                    self._play_event.wait()
                    logger.info(f'THREAD-{threading.get_ident()} continued"')

                if self._quit_event.is_set():
                    break


class AsyncFuzzer(BaseFuzzer):
    def __init__(
        self,
        requester: AsyncRequester,
        dictionary: Dictionary,
        *,
        match_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        not_found_callbacks: tuple[Callable[[BaseResponse], Any], ...],
        error_callbacks: tuple[Callable[[RequestException], Any], ...],
    ) -> None:
        super().__init__(
            requester,
            dictionary,
            match_callbacks=match_callbacks,
            not_found_callbacks=not_found_callbacks,
            error_callbacks=error_callbacks,
        )
        self._play_event = asyncio.Event()
        self._background_tasks = set()

    async def setup_scanners(self) -> None:
        # Default scanners (wildcard testers)
        self.scanners["default"].update(
            {
                "index": await AsyncScanner.create(
                    self._requester, path=self._base_path
                ),
                "random": await AsyncScanner.create(
                    self._requester, path=self._base_path + WILDCARD_TEST_POINT_MARKER
                ),
            }
        )
        
        # Report wildcard response
        if not options.no_wildcard:
            wildcard_response = self.scanners["default"]["random"].response
            if wildcard_response:
                waf_name = WAF.detect(wildcard_response)
                msg = f"Wildcard response: {wildcard_response.status} - {wildcard_response.size}"
                if waf_name:
                    msg += f" [{waf_name}]"
                print(msg)

        # Check for WAF on the base path first
        try:
            response = await self._requester.request(self._base_path)
            if waf_name := WAF.detect(response):
                self.waf_detected = True
                print(f"[WARNING] WAF Detected: {waf_name}")
        except RequestException:
            pass

        if options.exclude_response:
            self.scanners["default"]["custom"] = await AsyncScanner.create(
                self._requester, tested=self.scanners, path=options.exclude_response
            )

        for prefix in options.prefixes + DEFAULT_TEST_PREFIXES:
            self.scanners["prefixes"][prefix] = await AsyncScanner.create(
                self._requester,
                tested=self.scanners,
                path=f"{self._base_path}{prefix}{WILDCARD_TEST_POINT_MARKER}",
                context=f"/{self._base_path}{prefix}***",
            )

        for suffix in options.suffixes + DEFAULT_TEST_SUFFIXES:
            self.scanners["suffixes"][suffix] = await AsyncScanner.create(
                self._requester,
                tested=self.scanners,
                path=f"{self._base_path}{WILDCARD_TEST_POINT_MARKER}{suffix}",
                context=f"/{self._base_path}***{suffix}",
            )

        for extension in options.extensions:
            if "." + extension not in self.scanners["suffixes"]:
                self.scanners["suffixes"]["." + extension] = await AsyncScanner.create(
                    self._requester,
                    tested=self.scanners,
                    path=f"{self._base_path}{WILDCARD_TEST_POINT_MARKER}.{extension}",
                    context=f"/{self._base_path}***.{extension}",
                )

    async def start(self) -> None:
        # In Python 3.9, initialize the Semaphore within the coroutine
        # to avoid binding to a different event loop.
        self.sem = asyncio.Semaphore(options.thread_count)
        await self.setup_scanners()
        self.play()

        # Create tasks up to thread_count
        for _ in range(options.thread_count):
            task = asyncio.create_task(self.task_proc())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        await asyncio.gather(*self._background_tasks)

    def play(self) -> None:
        self._play_event.set()

    def pause(self) -> None:
        self._play_event.clear()

    def quit(self) -> None:
        for task in self._background_tasks:
            task.cancel()

    async def scan(self, path: str) -> None:
        scanners = self.get_scanners_for(path)
        try:
            response = await self._requester.request(path)
        except RequestException as e:
            for callback in self.error_callbacks:
                callback(e)
            return

        if not self._play_event.is_set():
            await self._play_event.wait()

        if not self.waf_detected:
            if waf_name := WAF.detect(response):
                self.waf_detected = True
                logger.warning(f"WAF Detected: {waf_name}")

        if self.is_excluded(response):
            for callback in self.not_found_callbacks:
                callback(response)
            return

        for tester in scanners:
            # Check if the response is unique, not wildcard
            if not tester.check(path, response):
                for callback in self.not_found_callbacks:
                    callback(response)
                return

        if options.filter_threshold:
            hash_ = hash(response)
            self._hashes.setdefault(hash_, 0)
            self._hashes[hash_] += 1

        # Collect responses first
        to_report = [response]
            
        # Multi-method scan: Check other methods for the found path
        if len(options.http_methods) > 1:
            current_method = getattr(response, 'method', options.http_method)
            other_methods = [m for m in options.http_methods if m != current_method]
            
            # Helper to run request and return response or None
            async def check_method(m):
                try:
                    r = await self._requester.request(path, method=m)
                    r.is_child = True
                    r.method = m
                    if not self.is_excluded(r):
                        return r
                except RequestException:
                    pass
                return None

            # Run all other requests concurrently
            results = await asyncio.gather(*(check_method(m) for m in other_methods))
            for res in results:
                if res:
                    to_report.append(res)

        # Report all gathered results atomically (synchronously in event loop)
        for resp in to_report:
            for callback in self.match_callbacks:
                callback(resp)

    async def task_proc(self) -> None:
        # Each task will loop until dictionary is exhausted
        while True:
            async with self.sem:
                await self._play_event.wait()

                try:
                    path = next(self._dictionary)
                    await self.scan(self._base_path + path)
                except StopIteration:
                    break
                except Exception:
                    break
                finally:
                    await asyncio.sleep(options.delay)

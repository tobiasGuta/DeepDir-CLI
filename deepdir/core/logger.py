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

import logging
from logging.handlers import RotatingFileHandler

from deepdir.core.data import options


logger = logging.getLogger("DeepDir")
logger.setLevel(logging.DEBUG)
# Default to NullHandler to avoid "No handler found" warnings
logger.addHandler(logging.NullHandler())


def enable_logging() -> None:
    # Remove NullHandler if present to avoid duplicate handling if we add real handlers
    for handler in logger.handlers:
        if isinstance(handler, logging.NullHandler):
            logger.removeHandler(handler)
            
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    
    # File Handler
    if options.log_file:
        handler = RotatingFileHandler(options.log_file, maxBytes=options.log_file_size)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    # We could add a StreamHandler here if we wanted console logging via standard logging
    # but the project uses a custom CLI class for console output.

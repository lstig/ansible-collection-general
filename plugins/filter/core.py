# Copyright: (c) 2021, Luke Stigdon <contact@lukestigdon.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import absolute_import, division, print_function
__metaclass__ = type

FILTERS = {}


def filter(func):
    FILTERS[func.__name__] = func
    return func


@filter
def dig(d, keys, default=None):
    """Safely looks up arbitrarily nested dict keys"""
    for key in keys:
        d = d.get(key, default)
    return d


class FilterModule(object):
    def filters(self):
        return FILTERS

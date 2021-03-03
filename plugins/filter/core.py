FILTERS = {}

def filter(func):
    FILTERS[func.__name__] = func
    return func

@filter
def dig(d, *keys, default=None):
    """Safely looks up arbitrarily nested dict keys"""
    for key in keys:
        d = d.get(key, default)
    return d

@filter
def map_format(*values, pattern):
    """Performs more complex formatting on a list of values"""
    return pattern.format(*values)

class FilterModule(object):
    def filters(self):
        return FILTERS
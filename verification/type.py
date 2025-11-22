def is_hashable(an_object):
    try:
        hash(an_object)
        return True
    except:
        return False

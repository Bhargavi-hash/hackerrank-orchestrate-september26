from functools import lru_cache
from src.data.loader import load_all_data


@lru_cache(maxsize=1)
def dataset():
    return load_all_data()

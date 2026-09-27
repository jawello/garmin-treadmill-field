import logging

import pytest
from bumble.link import LocalLink

logging.getLogger("bumble").setLevel(logging.WARNING)


@pytest.fixture
def link():
    return LocalLink()

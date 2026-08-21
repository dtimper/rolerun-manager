from pathlib import Path

from app.boxed_metadata import item_name
from app.usum_live import parse_pk7_party


def test_pkhex_item_catalog_resolves_tm51():
    assert item_name(378) == "MT51"


def test_pkhex_item_catalog_resolves_common_held_item():
    assert item_name(234) == "Restos"


def test_item_name_preserves_safe_fallback_for_unknown_id():
    assert item_name(99999) == "Objeto #99999"

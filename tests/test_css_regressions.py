from pathlib import Path


CSS = (Path(__file__).parents[1] / 'src' / 'style.css').read_text(encoding='utf-8')


def test_status_utility_does_not_resize_whole_cards():
    """A bare `.ok` selector collapsed GPU/printer cards to 18 px wide."""
    assert '\n.ok {' not in CSS
    assert '.asset-row .ok {' in CSS


def test_console_stat_grids_keep_minimum_card_widths():
    assert '.gpu-console .gpu-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr))' in CSS
    assert '.printer-console .printer-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr))' in CSS

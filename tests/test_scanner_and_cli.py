import pytest

from indiabloom.cli import main
from indiabloom.demo import synthetic_closes
from indiabloom.graph import Graph, parse_relations
from indiabloom.scanner import scan


def _rel(indian, confidence="high", source="MU", target=None):
    return {
        "source": source,
        "target": target or indian,
        "relation": "thematic",
        "confidence": confidence,
        "rationale": "test",
        "sources": [],
    }


def test_scanner_ranks_planted_follower_first():
    graph = Graph(parse_relations([_rel("FOLLOW.NS"), _rel("NOISE.NS")]))
    closes = synthetic_closes("MU", {"FOLLOW.NS": 0.9, "NOISE.NS": 0.0}, days=300, seed=11)
    rows = scan("MU", graph, closes)
    assert rows[0].indian_ticker == "FOLLOW.NS"
    assert rows[0].next_session_corr > 0.5


def test_scanner_handles_global_on_target_side():
    graph = Graph(parse_relations([_rel("FOLLOW.NS", source="FOLLOW.NS", target="MU")]))
    closes = synthetic_closes("MU", {"FOLLOW.NS": 0.9}, days=300, seed=5)
    rows = scan("MU", graph, closes)
    assert [r.indian_ticker for r in rows] == ["FOLLOW.NS"]


def test_scanner_reports_missing_price_data():
    graph = Graph(parse_relations([_rel("GHOST.NS")]))
    rows = scan("MU", graph, synthetic_closes("MU", {}, days=100))
    assert rows[0].note == "no price data"
    assert rows[0].score is None


def test_scanner_insufficient_data_is_not_ranked():
    graph = Graph(parse_relations([_rel("SHORT.NS")]))
    rows = scan("MU", graph, synthetic_closes("MU", {"SHORT.NS": 0.5}, days=20))
    assert rows[0].note == "insufficient data"
    assert rows[0].score is None


def test_cli_relations_shows_competitors_for_indian_stock(capsys):
    code = main(["relations", "INFY.NS"])
    out = capsys.readouterr().out
    assert code == 0
    assert "TCS.NS" in out and "ACN" in out and "peer" in out


def test_cli_relations_unknown_ticker(capsys):
    assert main(["relations", "NOSUCH"]) == 0
    assert "no relations recorded" in capsys.readouterr().out


def test_cli_scan_offline_demo_runs(capsys):
    code = main(["scan", "ACN", "--offline-demo", "--top", "5"])
    out = capsys.readouterr().out
    assert code == 0
    assert "NEXT-CORR" in out and "INFY.NS" in out


def test_cli_rejects_negative_extra_lag():
    with pytest.raises(SystemExit):
        main(["scan", "ACN", "--offline-demo", "--extra-lag", "-1"])


def test_cli_invalid_relations_file_exit_code(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('[{"source": "MU"}]', encoding="utf-8")
    assert main(["--relations", str(bad), "relations", "MU"]) == 2
    assert "relations file invalid" in capsys.readouterr().err

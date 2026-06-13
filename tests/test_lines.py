"""コアの契約テスト (センサー先行)。

最初に書くべきテスト: 勝利ラインがちょうど 76 本であること。
その後、参照実装との一致テスト・既知局面の回帰テストを増やす。
"""
import pytest

from score_four.lines import all_lines


@pytest.mark.skip(reason="all_lines 実装後に有効化する")
def test_there_are_exactly_76_lines() -> None:
    assert len(all_lines()) == 76

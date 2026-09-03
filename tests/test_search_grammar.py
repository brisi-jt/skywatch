"""Unit tests for the clip-library search mini-grammar."""

from datetime import date

from skywatch.api.services.search import ParsedSearch, parse_search


class TestFreeText:
    def test_empty_and_blank_parse_to_nothing(self):
        assert parse_search(None) == ParsedSearch()
        assert parse_search("") == ParsedSearch()
        assert parse_search("   ") == ParsedSearch()

    def test_bare_words_become_and_terms(self):
        result = parse_search("mayday speedbird")
        assert result.text_terms == ("mayday", "speedbird")
        assert result.fts_match == '"mayday" "speedbird"'

    def test_quoted_phrase_stays_one_term(self):
        result = parse_search('"go around"')
        assert result.text_terms == ("go around",)
        assert result.fts_match == '"go around"'

    def test_mixed_words_and_phrase(self):
        result = parse_search('tower "good morning" stansted')
        assert result.text_terms == ("tower", "good morning", "stansted")
        assert result.fts_match == '"tower" "good morning" "stansted"'

    def test_special_characters_are_quoted_not_operators(self):
        # A stray dash/colon would be FTS5 syntax if unquoted; here it stays literal.
        result = parse_search("g-euyw")
        assert result.text_terms == ("g-euyw",)
        assert result.fts_match == '"g-euyw"'

    def test_embedded_quote_is_doubled(self):
        result = parse_search('say "6" again')
        assert result.fts_match == '"say" "6" "again"'


class TestStructuredTokens:
    def test_freq_by_mhz(self):
        result = parse_search("freq:123.8")
        assert result.freq == "123.8"
        assert result.text_terms == ()
        assert result.fts_match is None

    def test_freq_by_quoted_label(self):
        result = parse_search('freq:"stansted tower"')
        assert result.freq == "stansted tower"

    def test_callsign(self):
        result = parse_search("callsign:BAW2761")
        assert result.callsign == "BAW2761"

    def test_interesting_flag(self):
        result = parse_search("interesting")
        assert result.interesting is True
        assert result.text_terms == ()

    def test_interesting_is_case_insensitive(self):
        assert parse_search("INTERESTING").interesting is True

    def test_before_and_after_dates(self):
        result = parse_search("after:2026-07-10 before:2026-07-12")
        assert result.after == date(2026, 7, 10)
        assert result.before == date(2026, 7, 12)


class TestCombinations:
    def test_text_plus_filters_together(self):
        result = parse_search("mayday callsign:BAW freq:121.5 interesting after:2026-07-01")
        assert result.text_terms == ("mayday",)
        assert result.callsign == "BAW"
        assert result.freq == "121.5"
        assert result.interesting is True
        assert result.after == date(2026, 7, 1)

    def test_last_value_wins_for_repeated_key(self):
        result = parse_search("freq:118.5 freq:121.5")
        assert result.freq == "121.5"


class TestMalformedDegradesToText:
    def test_bad_date_becomes_a_search_term(self):
        result = parse_search("before:notadate")
        assert result.before is None
        assert result.text_terms == ("before:notadate",)
        assert result.fts_match == '"before:notadate"'

    def test_empty_value_becomes_a_search_term(self):
        result = parse_search("freq:")
        assert result.freq is None
        assert result.text_terms == ("freq:",)

    def test_unknown_key_becomes_a_search_term(self):
        result = parse_search("altitude:3000")
        assert result.freq is None
        assert result.callsign is None
        assert result.text_terms == ("altitude:3000",)

    def test_malformed_token_alongside_valid_ones(self):
        result = parse_search("emergency before:oops callsign:BAW")
        assert result.callsign == "BAW"
        assert result.before is None
        assert result.text_terms == ("emergency", "before:oops")

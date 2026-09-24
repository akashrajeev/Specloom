from backend.provenance.proof import answer_lines, build_proof


def test_meta_lines_are_not_scored():
    text = (
        "Candidate list (derived from the fetched arXiv query)\n"
        "1. Harness as a Language: A Minimalist Agent Framework - https://arxiv.org/abs/2609.26891v1 (2026-09-22)\n"
        "These ten entries constitute the complete set of candidates matching the query\n"
        "Selected papers:\n"
    )
    lines = [line for line, _ in answer_lines(text)]
    assert len(lines) == 1
    assert "Harness as a Language" in lines[0]


def test_claims_with_numbers_still_scored_even_if_meta_words():
    text = "The following book costs £50.10 and has 20 in stock"
    assert len(answer_lines(text)) == 1


def test_made_up_value_still_flagged():
    page = "Soumission £50.10 In stock (20 available)"
    proof = build_proof("Soumission is priced at £49.99", {"https://x.test/p": page})
    assert proof and proof["lines"][0]["status"] != "supported"


def test_sources_section_lines_are_not_scored():
    text = (
        "| Title | Price |\n|---|---|\n| Soumission | £50.10 |\n\n"
        "*Sources*\n"
        "- Soumission details: price and stock shown in the page content【3】.\n"
    )
    lines = [line for line, _ in answer_lines(text)]
    assert lines == ["Soumission £50.10"]


def test_inline_sources_line_is_not_scored():
    text = "| Title | Price |\n|---|---|\n| Soumission | £50.10 |\n*Sources:* A Light in the Attic details【1】; Soumission details【3】.\n"
    assert [line for line, _ in answer_lines(text)] == ["Soumission £50.10"]

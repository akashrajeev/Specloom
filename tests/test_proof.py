from backend.notify import telegram
from backend.provenance.proof import build_proof

PAGE = ("A Light in the Attic | Books to Scrape Home Books Poetry A Light in the Attic A Light in the Attic "
        "£51.77 In stock (22 available) Warning! This is a demo website.")
URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
TEXT = f"""**Book details**

| Title | Price | Availability |
|---|---|---|
| A Light in the Attic | £51.77 | In stock (22 available)【{URL}】 |
| A Light in the Attic | £49.99 | In stock (22 available) |
"""


def test_each_line_links_to_its_quote():
    proof = build_proof(TEXT, {URL: PAGE})
    assert proof["total"] == 2 and proof["supported"] == 1
    good, bad = proof["lines"]
    assert good["status"] == "supported" and "£51.77 In stock (22 available)" in good["quote"]
    assert good["link"].startswith(URL + "#:~:text=")
    assert bad["status"] != "supported" and bad["missing"] == ["£49.99"]


def test_no_pages_no_proof():
    assert build_proof(TEXT, {}) is None


def test_approval_message_carries_proof_summary():
    proof = build_proof(TEXT, {URL: PAGE})
    summary = telegram.proof_summary({"output": "x", "proof": proof})
    assert "1/2 lines backed" in summary and "£49.99" in summary

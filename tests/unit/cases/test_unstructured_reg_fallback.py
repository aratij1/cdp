"""Unit tests for unstructured REG fallback heuristics + DOB YY MM DD."""

from __future__ import annotations

from packages.extraction_recovery.span_selection import _assemble_dob_from_tokens
from packages.extraction_recovery.unstructured_reg_fallback import (
    _heuristic_fields_from_di_text,
)


def test_compact_mmddyyyy_dob_with_sex_suffix():
    text = """
10 BIRTHDATE
11 SEX
071220071M
TEEL, HENRY
200399942
TOTALS 62.52
"""
    fields = _heuristic_fields_from_di_text(text)
    assert fields.get("patient_dob") == "07/12/2007"


def test_atta_dee_dee_freeform_name_prefix():
    text = """
ATTA Dec-Dee 970 Siden Manus Blvd #1512 Atlanta CA.
02/25/1969
977508972
150.00
"""
    fields = _heuristic_fields_from_di_text(text)
    assert "ATTA" in (fields.get("patient_name") or "").upper()
    assert fields.get("patient_dob") == "02/25/1969"
    assert fields.get("total_charge") == "150.00"


def test_totals_glued_cents_on_ub04():
    text = """
LAUCK, DONALD D
08281968
205093162
10 BIRTHDATE
TOTALS 2420968
"""
    fields = _heuristic_fields_from_di_text(text)
    assert fields.get("patient_dob") == "08/28/1968"
    assert fields.get("total_charge") == "24209.68"


def test_dob_mim_header_garble_stripped():
    assert _assemble_dob_from_tokens("MIM 12 30 200") == "12/30/2020"


def test_unstructured_heuristic_prefers_historical_dob_and_digit_id():
    text = """
Maines, Tammy L
01 08 69
United Healthcare
959012644
150.00
08/17/2026
"""
    fields = _heuristic_fields_from_di_text(text)
    assert fields.get("patient_dob") == "01/08/1969"
    assert fields.get("insured_id_number") == "959012644"
    assert "MAINES" in (fields.get("patient_name") or "").upper()
    assert "150.00" in (fields.get("total_charge") or "")


def test_unstructured_heuristic_inline_dob_in_mixed_line():
    """HJHO.014-class: DOB tokens sit inside a freeform identity line."""
    text = """
M . Maines, Tammy L 1040 Lenox Valley Dv NE Atlanta 30324 01 08 69 United Healthcare
959012644
120.00
08/17/2026 0500
"""
    fields = _heuristic_fields_from_di_text(text)
    assert fields.get("patient_dob") == "01/08/1969"
    assert fields.get("insured_id_number") == "959012644"
    assert "120.00" in (fields.get("total_charge") or "")


def test_unstructured_heuristic_skips_po_box_as_name():
    text = """
P. O. BOX 30755 SALTLAKECITY, UT 84130-0755 959298836
150.00
"""
    fields = _heuristic_fields_from_di_text(text)
    name = (fields.get("patient_name") or "").upper()
    assert "P. O. BOX" not in name and "SALT LAKE" not in name


def test_mailroom_separator_yields_no_fields():
    text = """
*00BREAK00*
Document Separator
Used to Separate Each Transaction
SourceHOV, Inc 4050 South 500 West Salt Lake City, UT 84123
Patch II
08/13/2026 0500
"""
    assert _heuristic_fields_from_di_text(text) == {}


def test_mailroom_unique_id_cover_yields_no_fields():
    text = """
DOCSEP
Unique ID
CERT161008
Tracking No
420841300755950011584431622266.
Last Name
First Name
RecvDate
08/18/2026
Arrival Date
08/18/2026
POBox
30755
"""
    assert _heuristic_fields_from_di_text(text) == {}


def test_ub04_prefers_person_over_facility_name():
    text = """
UB-04 CMS-1450
TYPE OF BILL 0212
KAISER FOUNDATION HOS SAC 2025 MORSE AVE
8 PATIENT NAME
9 PATIENT ADDRESS a
b HALL, SHELLETHA R.
10 BIRTHDATE
11051962
47 TOTAL CHARGES
2079.00
60 INSURED'S UNIQUE ID
958252115
58 INSURED'S NAME
HALL, SHELLETHA R.
"""
    fields = _heuristic_fields_from_di_text(text)
    name = (fields.get("patient_name") or "").upper()
    assert "HALL" in name and "SHELLETHA" in name
    assert "KAISER" not in name
    assert fields.get("patient_dob") == "11/05/1962"
    assert fields.get("insured_id_number") == "958252115"
    assert "2079.00" in (fields.get("total_charge") or "")


def test_city_state_not_treated_as_person_name():
    text = """
UB-04 CMS-1450
HEMPSTEAD, NY 11550
LOPEZRODRIGUEZ, MAYULEISI
10 BIRTHDATE
08061991
112592214
253.00
"""
    fields = _heuristic_fields_from_di_text(text)
    name = (fields.get("patient_name") or "").upper()
    assert "LOPEZRODRIGUEZ" in name
    assert "HEMPSTEAD" not in name


def test_fax_boilerplate_not_treated_as_person_name():
    text = """
FAX IMAGE - ORIGINAL SOURCE MAY BE BAD, THEREFORE BETTER IMAGE QUALITY CANNOT BE OBTAINED
08/18/2026
"""
    assert _heuristic_fields_from_di_text(text) == {}


def test_space_separated_total_charge_near_box28():
    text = """
NAKACHE, SHELLEY
05211974
985321153
28. TOTAL CHARGE
$ 780 00 $
"""
    fields = _heuristic_fields_from_di_text(text)
    assert fields.get("patient_name", "").upper().startswith("NAKACHE")
    assert fields.get("insured_id_number") == "985321153"
    assert fields.get("patient_dob") == "05/21/1974"
    assert "780.00" in (fields.get("total_charge") or "")


def test_member_id_kept_when_leading_address_soup_line():
    text = """
ATTA, Dee-Dee
02 21 69
977508972 ATTA De-Die 970 Sidney Haus Blvd #1512 Atlanta GA 30324
300.00
"""
    fields = _heuristic_fields_from_di_text(text)
    assert fields.get("insured_id_number") == "977508972"
    assert "ATTA" in (fields.get("patient_name") or "").upper()


def test_ifyes_return_form_instruction_rejected():
    text = """
IFyes, return to and completoliem 9a-d,
LUTH, LAURA
959298836
150.00
"""
    fields = _heuristic_fields_from_di_text(text)
    name = (fields.get("patient_name") or "").upper()
    assert "IFYES" not in name and "RETURN" not in name
    assert "LUTH" in name


def test_cms_colon_pipe_dob_and_glued_box28_total():
    """DI cell separators ``02:28:1967MX`` + ``$ 23700`` must not miss DOB/charge."""
    text = """
OTHER 1a. INSURED'S I.D. NUMBER
(Member ID#)
M01406484
2. PATIENT'S NAME (Last Name, First Name, Middle Initial)
SEKIYA, FAIRES A
3. PATIENT'S BIRTH DATE
02:28:1967MX
SEX
ZIP CODE
601377057
25. FEDERAL TAX I.D. NUMBER 362169147
28. TOTAL CHARGE $ 23700
23700.
"""
    fields = _heuristic_fields_from_di_text(text)
    assert fields.get("patient_dob") == "02/28/1967"
    assert fields.get("insured_id_number") == "M01406484"
    assert fields.get("total_charge") == "237.00"
    assert "SEKIYA" in (fields.get("patient_name") or "").upper()


def test_cms_pipe_yy_dob_member_id_and_line_sum_total():
    """``11 : 06 | 96`` DOB + zero-padded 1a id + bare ``1320`` after line charges."""
    text = """
(Member ID#)
0000548763
2. PATIENT'S NAME (Last Name, First Name, Middle Initial)
Urita, Luke, N.
3. PATIENT'S BIRTH DATE
11 : 06 | 96
SEX
B IF 43.24
220 00
220 00
220 00
220 00
220 00
220 00
1320
25 FEDERAL TAX I.D. NUMBER 569295610
28 TOTAL CHARGE
"""
    fields = _heuristic_fields_from_di_text(text)
    assert fields.get("patient_dob") == "11/06/1996"
    assert fields.get("insured_id_number") == "0000548763"
    assert fields.get("total_charge") == "1320.00"
    assert "URITA" in (fields.get("patient_name") or "").upper()


def test_cms_bare_total_with_pipe_junk_suffix():
    text = """
(Member ID#)
0000548763
Urita, Luke, N.
3. PATIENT'S BIRTH DATE
11 | 06 : 96
220 00
1320 00| 3
28 TOTAL CHARGE
"""
    fields = _heuristic_fields_from_di_text(text)
    assert fields.get("patient_dob") == "11/06/1996"
    assert fields.get("insured_id_number") == "0000548763"
    assert fields.get("total_charge") == "1320.00"


def test_dob_fragment_not_promoted_as_total_charge_without_cue():
    """Sparse DI miss: ``02.28`` birthdate ink must stay HITL, not Box 28."""
    text = """
SEKIYA, FAIRES A
601377057
02.28
"""
    fields = _heuristic_fields_from_di_text(text)
    assert fields.get("total_charge") != "02.28"
    assert "patient_dob" not in fields or fields.get("patient_dob") != "02/28"


def test_cms_checkbox_dob_garble_and_labeled_box28_beats_year_stem():
    """JF1.005-class: ``06113 /1992MX`` DOB + ``$ 23300`` must beat bare ``11992``."""
    text = """
OTHER| 1a. INSURED'S I.D. NUMBER
(Member ID#)
(ID#)
OSC76422826
2. PATIENT'S NAME (Last Name, First Name, Middle Initial)
CANNULI, DAVID MICHAEL
3. PATIENT'S BIRTH DATE
06113 /1992MX
F
a. INSURED'S DATE OF BIRTH MM 06
SEX
1º3
11992
M
99232 GC
23300
28. TOTAL CHARGE $ 23300
AMBER HASSINONE COOPER PLAZA CAMDEN NJ 081031461
"""
    fields = _heuristic_fields_from_di_text(text)
    assert fields.get("patient_dob") == "06/13/1992"
    assert fields.get("insured_id_number") == "OSC76422826"
    assert fields.get("total_charge") == "233.00"
    assert "CANNULI" in (fields.get("patient_name") or "").upper()


def test_patients_apostrophe_label_not_illness_injury_name():
    """JFQ.032-class: PATIENT'S NAME + reject form label ILLNESS, INJURY."""
    text = """
2. PATIENT'S NAME (Last Name, First Name, Middle Initial)
VOLK MAVERICK
3. PATIENT'S BIRTH DATE 09 --
18 M X
F
4. INSURED'S NAME (Last Name, First Name. Middle Initial)
SONG SHERRY
14. DATE OF CURRENT ILLNESS, INJURY, or PREGNANCY (LMP)
20987802
28. TOTAL CHARGE $ 304 04
ZIP CODE
34275
"""
    fields = _heuristic_fields_from_di_text(text)
    name = (fields.get("patient_name") or "").upper()
    assert "VOLK" in name and "MAVERICK" in name
    assert "ILLNESS" not in name and "INJURY" not in name
    assert fields.get("insured_id_number") == "20987802"
    assert fields.get("total_charge") == "304.04"
    # Blank/partial DOB must stay HITL — do not invent a month/year from ``09 --``.
    assert "patient_dob" not in fields


def test_pediatric_dob_bang_separator_from_local_ocr_text():
    """JFQ.032 ink: local OCR ``06:09! 18`` → pediatric 06/09/2018 (not year>2015 drop)."""
    text = """
3. PATIENT'S BIRTH DATE SEX
06:09! 18 mX|
4. INSURED'S NAME
SONG SHERRY
"""
    fields = _heuristic_fields_from_di_text(text)
    assert fields.get("patient_dob") == "06/09/2018"


def test_hyphenated_1a_id_not_harvested_as_charge():
    """JGK.011-class: ``569-90-4716`` on 1a is member id, not Box 28."""
    text = """
OTHER| 1a. INSURED'S I.D. NUMBER 569-90-4716
2. PATIENT'S NAME
YEE, TRUDY
3. PATIENT'S BIRTH DATE
10/10/2000
28. TOTAL CHARGE
200.00
"""
    fields = _heuristic_fields_from_di_text(text)
    assert fields.get("insured_id_number") == "569-90-4716"
    assert fields.get("total_charge") == "200.00"
    assert fields.get("patient_dob") == "10/10/2000"


def test_dollar_amount_with_ocr_junk_trail_as_box28():
    """JHK.001-class: ``$ 300 100`` far from TOTAL CHARGE label → 300.00."""
    text = """
SERVIDEO NICKOLAS
06/27/1977
226141920
28. TOTAL CHARGE
29. AMOUNT PAID
$ 300 100
$
"""
    fields = _heuristic_fields_from_di_text(text)
    assert fields.get("total_charge") == "300.00"
    assert fields.get("insured_id_number") == "226141920"
    assert fields.get("patient_dob") == "06/27/1977"

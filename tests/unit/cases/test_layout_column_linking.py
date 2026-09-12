"""Synthetic multi-column forms must not mix patient and insured values."""
from packages.layout_intelligence import BundleDLayoutEngine
from workers.page_detection.text_extraction import TextLine


def test_parallel_label_value_columns_remain_independent():
    result=BundleDLayoutEngine().extract([
        TextLine("Patient Name",20,20,180,40,.99),
        TextLine("Insured Name",500,20,660,40,.99),
        TextLine("SYNTHETIC PATIENT",20,50,190,70,.99),
        TextLine("SYNTHETIC INSURED",500,50,690,70,.99),
    ],page_number=1,width=1000,height=1000,engine="synthetic")
    assert result.candidates["patient_name"][0].value=="SYNTHETIC PATIENT"
    assert result.candidates["subscriber_name"][0].value=="SYNTHETIC INSURED"
    assert result.candidates["patient_name"][0].bbox.x1==190


def test_next_reading_order_line_in_other_column_is_not_a_value():
    result=BundleDLayoutEngine().extract([
        TextLine("Patient Name",20,20,180,40,.99),
        TextLine("WRONG COLUMN",500,45,680,65,.99),
        TextLine("SYNTHETIC PATIENT",20,75,190,95,.99),
    ],page_number=1,width=1000,height=1000,engine="synthetic")
    assert result.candidates["patient_name"][0].value=="SYNTHETIC PATIENT"
    assert all(c.value!="WRONG COLUMN" for c in result.candidates["patient_name"])

import json

def run():
    try:
        with open('apps/evaluation_ui/public/reports/evaluation.json') as f:
            d = json.load(f)
        
        cms1500_evidence = [row for row in d.get('field_evidence', []) if row.get('form_type') == 'CMS1500']
        not_correct = [row for row in cms1500_evidence if not row.get('correct')]
        
        for r in not_correct:
            print(f"Field: {r.get('field_name')}")
            print(f"  Expected: {r.get('expected_value')}")
            print(f"  Extracted: {r.get('extracted_value')}")
            print(f"  Normalized: {r.get('normalized_value')}")
            print(f"  Method: {r.get('extraction_method')}")
            print(f"  Status: {r.get('status')}")
            print("-" * 40)
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    run()

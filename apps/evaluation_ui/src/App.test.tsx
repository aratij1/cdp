import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("evaluation dashboard", () => {
  it("loads a report and renders side-by-side mismatches", async () => {
    render(<App />);
    const input = screen.getAllByLabelText(/choose report|load evaluation json/i)[0];
    const file = new File(
      [JSON.stringify({
        field_count: 2,
        raw_exact_match_accuracy: 0.5,
        normalized_field_accuracy: 0.5,
        ocr_deterministic_accuracy: 0.4,
        llm_diversion_rate: 0.5,
        llm_diverted_fields: 1,
        llm_processing_cost: {
          currency: "USD", run_cost_usd: 0.0042, routed_fields: 1,
          status: "ESTIMATED", basis: "Token-based test estimate",
        },
        critical_field_accuracy: 1,
        character_error_rate: 0.1,
        missing_field_rate: 0,
        false_accept_rate: 0.5,
        critical_false_accept_rate: 0,
        false_review_rate: 0,
        perfect_claim_rate: 0,
        straight_through_processing_rate: 0,
        accuracy_before_fallback: 0.4,
        accuracy_after_fallback: 0.8,
        accuracy_by_field: { total_charge: 0.5 },
        accuracy_by_form_type: { CMS1500: 0.5 },
        accuracy_by_extraction_method: { REGIONAL_PADDLEOCR: 0.5 },
        accuracy_by_image_quality_bucket: { good: 0.5 },
        field_evidence: [{
          document_id: "A-01", form_type: "CMS1500", field_name: "total_charge",
          expected_value: "100.00", extracted_value: "900.00", normalized_value: "900.00",
          extraction_method: "REGIONAL_PADDLEOCR", confidence: 0.99, status: "INVALID",
          correct: false, original_page_url: null, row_context_url: null, crop_url: null,
        }],
        operational_metrics: {
          total_pages_processed: 2, processing_time_seconds: 4,
          average_latency_seconds: 2, pages_per_second: 0.5,
          accuracy: 0.5, precision: 0.5, recall: 0.5,
        },
        cost_analysis: {
          currency: "USD", total_cost_per_page_usd: 0.01,
          actual_run_cost_usd: 0.02, actual_invoice_cost_usd: null,
          components: [{ name: "LLM", cost_per_page_usd: 0.01, status: "MEASURED", basis: "Test tokens" }],
        },
        mismatches: [{
          document_id: "A-01", form_type: "CMS1500", field_name: "total_charge",
          expected_value: "100.00", extracted_value: "900.00", normalized_value: "900.00",
          ocr_confidence: 0.99, validation_result: "INVALID",
          extraction_method: "REGIONAL_PADDLEOCR", bounding_box: null,
          crop_reference: null, failure_category: "FALSE_ACCEPT",
        }],
      })],
      "evaluation.json",
      { type: "application/json" },
    );
    fireEvent.change(input, { target: { files: [file] } });
    expect(await screen.findByText("Governed extraction results")).toBeInTheDocument();
    expect(screen.getByText("Current-sample validated accuracy")).toBeInTheDocument();
    expect(screen.getByText("LLM processing cost")).toBeInTheDocument();
    expect(screen.getByText("$0.004200")).toBeInTheDocument();
    expect(screen.getByText("Token-based test estimate")).toBeInTheDocument();
    expect(screen.getByText("Group-wise accuracy")).toBeInTheDocument();
    expect(screen.getByText("CMS-1500 professional claim")).toBeInTheDocument();
    expect(screen.getByText("Final governed accuracy")).toBeInTheDocument();
    expect(screen.queryByText("Performance & cost analysis")).not.toBeInTheDocument();
    expect(screen.queryByText("Optimized component cost per page")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Field evidence" }));
    expect(screen.getByText("Field-level evidence")).toBeInTheDocument();
    expect(screen.getAllByText("100.00")).toHaveLength(2);
    expect(screen.getAllByText("900.00")).toHaveLength(4);
    expect(screen.getAllByText("FALSE_ACCEPT")).toHaveLength(2);

    fireEvent.click(screen.getByRole("tab", { name: "OCR & LLM flow" }));
    expect(screen.getByText("How evidence becomes a validated field")).toBeInTheDocument();
    expect(screen.getByText("Run local OCR cascade")).toBeInTheDocument();
    expect(screen.getByText("Escalate unresolved crops")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Tuning & governance" }));
    expect(screen.getByText("Tuning applied across the extraction stack")).toBeInTheDocument();
    expect(screen.getByText("Alignment & coordinates")).toBeInTheDocument();
    expect(screen.getByText("HITL to HOTL")).toBeInTheDocument();
    expect(screen.getByText("Structured correction memory")).toBeInTheDocument();
    expect(screen.getByText("HOTL with continuous control")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Submission" }));
    expect(screen.getByText("Submission readiness centre")).toBeInTheDocument();
    expect(screen.getByText("10-minute live demonstration")).toBeInTheDocument();
    expect(screen.getByText("Excel-ready measured metrics")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Process claims" }));
    expect(screen.getByText("Upload and process claims")).toBeInTheDocument();
    expect(screen.getByLabelText("Choose files")).toBeInTheDocument();
  });
});

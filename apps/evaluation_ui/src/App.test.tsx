import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "./App";

// Mock Query Client Provider and dynamic API calls
vi.mock("@tanstack/react-query", () => {
  return {
    useQuery: ({ queryKey }: { queryKey: string[] }) => {
      const key = queryKey[0];
      if (key === "review-tasks") {
        return {
          data: [
            {
              task_id: "live-task-1",
              claim_id: "clm-live-1",
              field_name: "billing_provider_npi",
              status: "OPEN",
              created_at: "2026-08-26T12:00:00Z",
              version: 1,
              assigned_to: null
            }
          ],
          isLoading: false,
          isError: false
        };
      }
      if (key === "review-task") {
        return {
          data: {
            task_id: "live-task-1",
            claim_id: "clm-live-1",
            field_name: "billing_provider_npi",
            status: "OPEN",
            created_at: "2026-08-26T12:00:00Z",
            version: 1,
            assigned_to: null,
            document_id: "doc-1",
            page_number: 1,
            crop_signed_url: null,
            ocr_candidates: ["1234567893"],
            vlm_candidate: "1234567893",
            validation_errors: ["Luhn check fail"],
            review_reason_codes: ["LOW_CONFIDENCE"],
            candidate_evidence: [],
            reference_evidence: [],
            system_recommendation: "1234567893",
            evidence_versions: {}
          },
          isLoading: false,
          isError: false
        };
      }
      if (key === "review-task-audit") {
        return {
          data: [
            {
              occurred_at: "2026-08-26T12:01:00Z",
              actor: "System Pipeline",
              event_type: "DOCUMENT_RECEIVED",
              task_version: 1,
              reason_code: "SYSTEM_INTAKE"
            }
          ],
          isLoading: false,
          isError: false
        };
      }
      return { data: [], isLoading: false, isError: false };
    },
    useMutation: () => ({ mutate: vi.fn(), isPending: false, isError: false, error: null }),
    useQueryClient: () => ({ invalidateQueries: vi.fn() })
  };
});

describe("Claims IDP Enterprise UI & Authentication Tests", () => {
  it("renders Claims IDP login screen matching reference without extracted preview or SSO", () => {
    render(<App />);

    // 1. Console UI tabs must NOT be visible before signing in
    expect(screen.queryByRole("tab", { name: /Dashboard/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /Work Queue/i })).not.toBeInTheDocument();

    // 2. Left Brand Panel with Upgraded Logo & Live Status Indicator
    expect(screen.getByTitle("Claims IDP Intelligence Core")).toBeInTheDocument();
    expect(screen.getByText("Claims IDP")).toBeInTheDocument();
    expect(screen.getByText("Healthcare Core")).toBeInTheDocument();
    expect(screen.getByText("Operational · Production Pipeline v2.4")).toBeInTheDocument();
    expect(screen.getByText("Claims intake that checks itself before an auditor does.")).toBeInTheDocument();
    expect(screen.getByText(/CMS-1500 and UB-04 extraction, validated by 16 agents/i)).toBeInTheDocument();
    expect(screen.getByText("HIPAA compliant")).toBeInTheDocument();
    expect(screen.getByText("SOC 2 Type II")).toBeInTheDocument();
    expect(screen.getByText("Datamatics Core")).toBeInTheDocument();

    // 3. Removed extraction preview card as requested
    expect(screen.queryByText(/Claim 48213/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Meera K\. Iyer/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/1457390862/i)).not.toBeInTheDocument();

    // 4. Right Form Panel with Datamatics Corporate Branding
    expect(screen.getByText("DATAMATICS")).toBeInTheDocument();
    expect(screen.getByText("Intelligent Claims IDP")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
    expect(screen.getByText("Sign in to the claims auditor workspace.")).toBeInTheDocument();
    expect(screen.getByText("Work email")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("auditor@cdp.internal")).toBeInTheDocument();
    expect(screen.getByText("Password")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("••••••••••••")).toBeInTheDocument();
    expect(screen.getByText("Remember me for 30 days")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Forgot password\?/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Sign in$/i })).toBeInTheDocument();

    // 5. Removed SSO and role bypass buttons as requested
    expect(screen.queryByText(/or continue with/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Google/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Microsoft/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/Open read-only viewer/i)).not.toBeInTheDocument();
    expect(screen.queryByText("OR QUICK ROLE SWITCH")).not.toBeInTheDocument();

    // 6. Zero personal names
    expect(screen.queryByText(/Aarati/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/aarati\.joshi/i)).not.toBeInTheDocument();
  });

  it("blocks sign-in when email or password is empty and shows validation error", () => {
    render(<App />);

    // Click Sign In with empty inputs
    fireEvent.click(screen.getByRole("button", { name: /^Sign in$/i }));

    // Error banner must be shown
    expect(screen.getByRole("alert")).toHaveTextContent("Please enter your email and password.");

    // UI console must remain unmounted
    expect(screen.queryByRole("tab", { name: /Dashboard/i })).not.toBeInTheDocument();
  });

  it("authenticates as Auditor with valid credentials and renders the Claims IDP console", () => {
    render(<App />);

    // Fill credentials
    fireEvent.change(screen.getByPlaceholderText("auditor@cdp.internal"), { target: { value: "auditor@cdp.internal" } });
    fireEvent.change(screen.getByPlaceholderText("••••••••••••"), { target: { value: "password123" } });

    // Submit
    fireEvent.click(screen.getByRole("button", { name: /^Sign in$/i }));

    // Verify console is now displayed
    expect(screen.getByRole("tab", { name: /Dashboard/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Batch Intake/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Work Queue/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Document Review/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Analytics/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Audit Trail/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Settings/i })).toBeInTheDocument();

    // Operational KPIs
    expect(screen.getByText("STP Rate")).toBeInTheDocument();
    expect(screen.getByText("Total Ingested")).toBeInTheDocument();
    expect(screen.getByText("Pending HITL")).toBeInTheDocument();
    expect(screen.getByText("Role: REVIEWER")).toBeInTheDocument();
  });

  it("authenticates as Lead Adjudicator with valid credentials and enforces Admin permissions", () => {
    render(<App />);

    // Fill Adjudicator credentials
    fireEvent.change(screen.getByPlaceholderText("auditor@cdp.internal"), { target: { value: "adjudicator@cdp.internal" } });
    fireEvent.change(screen.getByPlaceholderText("••••••••••••"), { target: { value: "password123" } });

    fireEvent.click(screen.getByRole("button", { name: /^Sign in$/i }));

    // Verify Admin role is active
    expect(screen.getByText("Role: ADMIN")).toBeInTheDocument();
    expect(screen.getAllByText("Lead Adjudicator").length).toBeGreaterThan(0);

    // Verify Settings permissions
    fireEvent.click(screen.getByRole("tab", { name: /Settings/i }));
    expect(screen.queryByText("Read-Only Configuration Mode")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save Settings/i })).not.toBeDisabled();
  });

  it("authenticates as Compliance Viewer with credentials and enforces read-only mode", () => {
    render(<App />);

    // Fill Viewer credentials
    fireEvent.change(screen.getByPlaceholderText("auditor@cdp.internal"), { target: { value: "viewer@cdp.internal" } });
    fireEvent.change(screen.getByPlaceholderText("••••••••••••"), { target: { value: "password123" } });

    fireEvent.click(screen.getByRole("button", { name: /^Sign in$/i }));

    // Verify Viewer role is active
    expect(screen.getByText("Role: VIEWER")).toBeInTheDocument();
    expect(screen.getAllByText("Compliance Viewer").length).toBeGreaterThan(0);

    // Verify Settings tab enforces read-only mode
    fireEvent.click(screen.getByRole("tab", { name: /Settings/i }));
    expect(screen.getByText("Read-Only Configuration Mode")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Admin Permission Required/i })).toBeDisabled();
  });

  it("signs out and returns to the full-page login gatekeeper", () => {
    render(<App />);

    // Fill credentials and sign in
    fireEvent.change(screen.getByPlaceholderText("auditor@cdp.internal"), { target: { value: "auditor@cdp.internal" } });
    fireEvent.change(screen.getByPlaceholderText("••••••••••••"), { target: { value: "password123" } });
    fireEvent.click(screen.getByRole("button", { name: /^Sign in$/i }));
    expect(screen.getByRole("tab", { name: /Dashboard/i })).toBeInTheDocument();

    // Click Sign Out
    fireEvent.click(screen.getByTitle("Sign out of Claims IDP"));

    // Verify UI console is unmounted and full login page is back
    expect(screen.queryByRole("tab", { name: /Dashboard/i })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Sign in$/i })).toBeInTheDocument();
  });

  it("displays tested batch processing and new batch investigating status in Work Queue", () => {
    render(<App />);

    // Fill credentials and sign in
    fireEvent.change(screen.getByPlaceholderText("auditor@cdp.internal"), { target: { value: "auditor@cdp.internal" } });
    fireEvent.change(screen.getByPlaceholderText("••••••••••••"), { target: { value: "password123" } });
    fireEvent.click(screen.getByRole("button", { name: /^Sign in$/i }));

    // Switch to Work Queue tab
    fireEvent.click(screen.getByRole("tab", { name: /Work Queue/i }));

    // 1. Batch Operations Overview Strip
    expect(screen.getByText(/Batch Processing Ingestion & Verification/i)).toBeInTheDocument();
    expect(screen.getByText(/Batch #100-v13b \(Independent-100\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Batch #100-B2 \(Ops Backfill\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Batch #2026-09-NEW \(Incoming Intake\)/i)).toBeInTheDocument();

    // 2. Tested batches show Verified, STP metrics
    expect(screen.getByText("90.0%")).toBeInTheDocument();
    expect(screen.getByText("84.0%")).toBeInTheDocument();

    // 3. New batch shows Investigating badge
    const investigatingBadges = screen.getAllByText("Investigating");
    expect(investigatingBadges.length).toBeGreaterThan(0);

    // 4. Batch Table Column and Filter
    expect(screen.getByRole("columnheader", { name: "Batch" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("All Batches")).toBeInTheDocument();

    // 5. Clean Work Queue: Dropzone is NOT visible on Work Queue
    expect(screen.getByText(/Drop claim batch scans or multi-page documents here/i)).not.toBeVisible();

    // 6. Navigate to dedicated Batch Intake tab
    fireEvent.click(screen.getByRole("tab", { name: /Batch Intake/i }));
    expect(screen.getByText("Claim Document Batch Ingestion Hub")).toBeVisible();
    expect(screen.getByText(/Drop claim batch scans or multi-page documents here/i)).toBeVisible();
    expect(screen.getByText("Target Ingestion Batch")).toBeVisible();
  });
});

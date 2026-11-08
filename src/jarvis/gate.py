"""`jarvis gate`: the release gate. Run it from the repository before calling any milestone done.

It runs the whole test suite once and the linter, then checks the security items (the constitution's §9 list,
plus the protected controls: emergency stop and budget guard) against the specific tests that cover each one.

Security items are pass/fail gates, never a score: any covering test that fails, errors, is skipped or no longer
exists fails the gate, however well everything else did. Only the opt-in live tests may be skipped.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWED_SKIPS = {"test_live_ollama::real_ollama_round_trip", "test_live_ollama::real_ollama_speed"}
# Checks that need macOS itself: allowed to skip elsewhere, required to pass on a Mac.
MACOS_ONLY = {"test_macos_only::mac_app_scripts_compile", "test_macos_only::launch_agent_file_is_valid",
              "test_macos_only::code_sandbox_blocks_network_and_outside_writes",
              "test_macos_only::chat_code_self_test_sandbox",
              "test_macos_only::launcher_app_compiles_and_holds_no_secret"}
if sys.platform != "darwin":
    ALLOWED_SKIPS = ALLOWED_SKIPS | MACOS_ONLY

# Each item: what it guards, and the tests (file::name, without parameters) that prove it.
SECURITY: dict[str, tuple[str, list[str]]] = {
    "Normal task completion": ("Tasks finish with real, verified results", [
        "test_tasks::end_to_end_with_approval_and_evidence", "test_orchestrator::end_to_end_plan_execute_verify",
        "test_tools::task_with_real_tools_end_to_end", "test_documents::summarise_a_pdf_end_to_end",
        "test_bench::oracle_passes_every_task"]),
    "Prompt injection": ("Content from files, web pages, apps or models can't steer actions", [
        "test_orchestrator::injected_instructions_in_data_cannot_change_the_plan",
        "test_bench::careless_model_fails_for_the_right_reasons",
        "test_tools::fetch_returns_untrusted_text_and_dials_the_validated_ip",
        "test_lookup::lookups_can_never_change_anything", "test_mac::arguments_go_as_data_never_into_the_script",
        "test_mac::note_body_is_escaped_html"]),
    "Permission bypass": ("Every change passes the permission engine and, where needed, your approval", [
        "test_settle_steps::settling_from_the_phone_is_one_tap_once_signed_in",
        "test_learn::autonomy_tiers_pauses_and_the_emergency_stop", "test_learn::autonomy_is_mac_only",
        "test_trial::trials_need_tier_6_from_the_terminal", "test_trial::refs_are_validated",
        "test_autopilot::nothing_happens_without_tier_7",
        "test_autopilot::nudges_reorder_allowed_models_only_and_never_beat_local_first",
        "test_intent::the_dashboard_route_is_local_only_and_research_and_tasks_are_confirmed",
        "test_permissions::outside_root_denied", "test_permissions::path_traversal_denied",
        "test_permissions::symlink_escape_denied", "test_permissions::deny_beats_allow",
        "test_permissions::high_tiers_never_auto_allowed", "test_permissions::protected_paths_not_writable_but_readable",
        "test_gateway::confirm_flow_is_bound_to_exact_args_and_single_use",
        "test_gateway::rejection_cannot_be_bypassed_with_another_tool",
        "test_gateway::external_action_always_confirms_despite_allow_rule",
        "test_gateway::only_user_can_decide_approvals", "test_tools::cannot_write_jarvis_own_state_even_if_rooted",
        "test_documents::move_destination_outside_roots_or_protected_refused_even_if_approved",
        "test_bench::a_change_without_approval_is_caught", "test_remote::release_needs_face_id_bound_to_exact_request",
        "test_remote::pairing_is_mac_only_and_code_single_use", "test_remote::dashboard_token_is_not_accepted_remotely",
        "test_touchid::setting_up_signs_this_browser_in_and_others_must_sign_in", "test_touchid::sign_in_flow",
        "test_touchid::signed_in_ordinary_approvals_are_one_tap_but_high_risk_needs_touch_id",
        "test_touchid::releasing_the_stop_needs_touch_id_bound_to_the_request",
        "test_remote::high_risk_approvals_still_need_face_id_bound_to_the_request",
        "test_ui_stepup_pages::the_dangerous_few_and_only_high_risk_approvals_need_the_fingerprint",
        "test_dashboard::csrf_defences",
        "test_dashboard::requires_session", "test_dashboard::dns_rebinding_host_refused"]),
    "Interrupted tasks and recovery": ("After a crash, real state is checked before anything resumes", [
        "test_tasks::crash_recovery_resumes_idempotent_step",
        "test_tasks::crash_recovery_never_repeats_uncertain_non_idempotent_step",
        "test_tasks::crash_recovery_reconciles_when_tool_can_tell",
        "test_tasks::crash_recovery_reruns_append_that_never_landed",
        "test_leases::crashed_owner_is_taken_over_and_reconciled", "test_mac::reconcile_after_a_crash",
        "test_documents::move_reconcile", "test_tools::write_reconcile",
        "test_drill::all_drills_pass_on_a_healthy_jarvis"]),
    "Duplicate-action prevention": ("Nothing that changes things runs twice by accident", [
        "test_tasks::timeout_on_non_idempotent_step_blocks_instead_of_retrying",
        "test_gateway::concurrent_callers_cannot_both_spend_one_approval",
        "test_mac::timed_out_change_is_marked_uncertain_not_retried",
        "test_leases::second_process_does_not_hijack_a_live_task",
        "test_tools::write_is_atomic_versioned_and_idempotent"]),
    "Network and redirect limits": ("Only allowed hosts, schemes and ports; local services stay local", [
        "test_tools::ssrf_targets_refused", "test_tools::hostname_resolving_to_private_ip_refused",
        "test_tools::dns_rebinding_cannot_swap_in_a_private_address",
        "test_tools::redirects_are_rechecked_followed_and_bounded", "test_tools::ports_and_credentials_refused",
        "test_tools::web_tool_through_gateway_rejects_bad_schemes", "test_models::local_provider_must_be_loopback",
        "test_models::cloud_provider_requires_https_and_key", "test_voice::client_loopback_only",
        "test_remote::push_endpoint_allowlist", "test_proactive::notification_links_stay_inside_jarvis",
        "test_dashboard::only_loopback"]),
    "Corrupted or inconsistent state": ("Damage is detected and reported, never silently trusted", [
        "test_tasks::corrupt_checkpoint_skipped", "test_tasks::invalid_transitions_rejected",
        "test_audit::tampering_detected_even_if_triggers_removed", "test_audit::deleted_middle_entry_detected",
        "test_backup_service::wrong_passphrase_and_tampering_detected",
        "test_orchestrator::writes_verified_detects_tampering",
        "test_doctor::broken_settings_give_a_plain_message_not_a_traceback",
        "test_documents::scanned_encrypted_and_corrupt_pdfs_reported_honestly",
        "test_flight::timeline_reports_a_damaged_audit_log"]),
    "Resource exhaustion and runaway retries": ("Retries, time, output and memory are bounded", [
        "test_tasks::bounded_retries_with_backoff", "test_tasks::retry_limit_reached",
        "test_gateway::timeout_and_output_limit", "test_tools::overall_deadline_stops_drip_feeding_servers",
        "test_stop::run_tracked_deadline_kills_process_group", "test_remote::unauthenticated_challenges_are_bounded",
        "test_dashboard::bad_content_length_refused_quickly", "test_voice::transcribe_endpoint_defences",
        "test_bench::code_is_only_run_when_asked", "test_chat_intelligence::streaming_respects_the_deadline",
        "test_orchestrator::validator_rejects_oversized_and_forward_references"]),
    "Privacy and data disclosure": ("Private data leaves the Mac only with permission; logs hold no content", [
        "test_models::quality_floor_selects_cloud_but_private_data_needs_approval",
        "test_models::local_only_data_never_routes_to_cloud",
        "test_models::local_failure_falls_back_but_never_silently_sends_private_data",
        "test_models::approval_is_bound_to_exact_request", "test_models::secret_content_blocked",
        "test_models::audit_never_contains_message_content",
        "test_codecheck::off_by_default",
        "test_audit_privacy::forget_removes_text_from_every_table_and_the_raw_files",
        "test_audit_privacy::audit_fingerprints_free_text_but_keeps_paths_and_structure",
        "test_memory::audit_holds_no_memory_text", "test_memory::memory_context_is_private_category",
        "test_lookup::lookup_results_are_private_and_the_question_stays_local",
        "test_research::asks_before_researching_and_never_falls_back_to_local",
        "test_audit::secrets_redacted_in_audit", "test_bench::runs_never_touch_the_real_jarvis",
        "test_flight::holds_no_private_text", "test_outcome::profile_reaches_the_answering_model_as_private_memory",
        "test_outcome::forgotten_profile_facts_stay_forgotten",
        "test_projects::ideas_come_from_the_local_model_and_must_cite_real_evidence",
        "test_projects::polish_sends_only_the_idea_list_and_only_after_you_approve",
        "test_chat_intelligence::nothing_streams_before_consent",
        "test_chat_intelligence::claude_streams_pieces_that_add_up_to_the_final_reply",
        "test_chat_intelligence::local_only_is_never_overridden_by_a_mode",
        "test_telemetry_evolution::network_check_returns_no_address",
        "test_telemetry_evolution::dashboard_state_carries_real_telemetry_evolution_and_model_timings"]),
    "Honest reporting": ("Failures and unverified results are reported as such", [
        "test_tasks::failed_verification_is_not_reported_as_complete", "test_tasks::rejection_fails_task_honestly",
        "test_learn::outcomes_are_judged_by_evidence_not_by_returning",
        "test_trial::a_regression_is_caught_and_nothing_is_merged",
        "test_learn::lessons_have_evidence_confidence_and_flag_contradictions",
        "test_learn::projection_security_never_calls_pending_authorized",
        "test_orchestrator::invalid_plan_gets_one_repair_then_fails_honestly",
        "test_persona::system_prompt_lists_real_abilities_and_known_gaps",
        "test_lookup::persona_matches_the_new_abilities",
        "test_claude_code::failure_reason_is_visible_in_fallback_note",
        "test_research::research_brief_end_to_end_requires_a_verified_source",
        "test_remote::push_failures_are_recorded_not_silent", "test_flight::a_rejection_is_shown_as_a_problem",
        "test_outcome::a_made_up_time_is_retried_then_flagged",
        "test_bench::pooled_verdicts_need_five_runs_and_say_when_it_could_be_luck",
        "test_bench::rescore_refuses_what_it_cannot_verify",
        "test_chat_intelligence::deep_without_claude_answers_locally_and_says_so",
        "test_telemetry_evolution::unreadable_figures_are_reported_unavailable_not_guessed",
        "test_telemetry_evolution::activity_alone_earns_nothing",
        "test_ui_avatar::every_avatar_state_comes_from_a_real_signal",
        "test_ui_avatar::evolution_comes_from_the_server_only",
        "test_ui_avatar::speech_pulses_come_only_from_real_word_boundaries",
        "test_telemetry_evolution::a_lost_capability_holds_for_seven_days_then_stops_counting",
        "test_telemetry_evolution::stage_changes_and_definition_versions_are_audited",
        "test_telemetry_evolution::benchmark_milestone_needs_a_real_passing_run",
        "test_telemetry_evolution::doctor_and_mac_check_count_only_when_they_passed_recently",
        "test_telemetry_evolution::reliability_needs_thirty_quiet_days",
        "test_ui_avatar::idle_liveliness_is_limited_to_rest_and_never_fakes_activity",
        "test_avatar25::gestures_are_captured_only_while_inspecting",
        "test_avatar25::presets_and_diagnostics_change_the_look_only_and_show_measured_numbers"]),
    "Emergency stop (protected)": ("One stop halts everything, including work in progress", [
        "test_gateway::emergency_stop_blocks_everything", "test_tasks::emergency_stop_pauses_then_requires_explicit_resume",
        "test_stop::stop_kills_running_claude_and_its_children", "test_models::emergency_stop_blocks_model_calls",
        "test_streaming::emergency_stop_cuts_a_reply_off_mid_sentence", "test_dashboard::emergency_stop_and_release",
        "test_gateway::emergency_stop_after_claim_restores_the_approval", "test_ui_stepup_pages::sign_in_screen_keeps_emergency_stop_one_click_away",
        "test_chat_intelligence::emergency_stop_kills_a_streaming_reply"]),
    "Budget guard (protected)": ("No spending: paid use is refused under a $0 budget", [
        "test_models::paid_model_excluded_under_zero_budget", "test_models::budget_guard_blocks_and_records",
        "test_bench::settings_for_a_run"]),
}


@dataclass
class Item:
    name: str
    guards: str
    passed: bool
    detail: str
    tests: int = 0


@dataclass
class GateResult:
    passed: bool
    suite: dict = field(default_factory=dict)
    lint: dict = field(default_factory=dict)
    items: list[Item] = field(default_factory=list)
    seconds: float = 0.0


def parse_junit(xml_text: str) -> dict[str, str]:
    """{"test_file::test_name": "passed" | "failed" | "skipped"}. A parametrized test counts as failed if any
    of its cases failed, skipped if all were skipped."""
    out: dict[str, str] = {}
    for case in ET.fromstring(xml_text).iter("testcase"):
        module = case.get("classname", "").split(".")[-1]
        name = case.get("name", "").split("[")[0].removeprefix("test_")  # lists below name tests without it
        key = f"{module}::{name}"
        if case.find("failure") is not None or case.find("error") is not None:
            status = "failed"
        elif case.find("skipped") is not None:
            status = "skipped"
        else:
            status = "passed"
        prev = out.get(key)
        if prev == "failed" or status == "failed":
            out[key] = "failed"
        elif prev == "passed" or status == "passed":
            out[key] = "passed"
        else:
            out[key] = status
    return out


def evaluate(results: dict[str, str], lint_ok: bool, lint_detail: str = "") -> GateResult:
    failed = sorted(k for k, v in results.items() if v == "failed")
    bad_skips = sorted(k for k, v in results.items() if v == "skipped" and k not in ALLOWED_SKIPS)
    suite_ok = bool(results) and not failed and not bad_skips
    items = []
    for name, (guards, tests) in SECURITY.items():
        missing = [t for t in tests if t not in results]
        broken = [t for t in tests if results.get(t) in ("failed", "skipped")]
        ok = not missing and not broken
        detail = (f"all {len(tests)} covering tests passed" if ok else
                  "; ".join(filter(None, [f"failed or skipped: {', '.join(broken)}" if broken else "",
                                          f"no longer exist: {', '.join(missing)}" if missing else ""])))
        items.append(Item(name, guards, ok, detail, len(tests)))
    suite = {"passed": sum(v == "passed" for v in results.values()), "failed": failed,
             "skipped": sorted(k for k, v in results.items() if v == "skipped"), "unexpected_skips": bad_skips,
             "ok": suite_ok}
    return GateResult(passed=suite_ok and lint_ok and all(i.passed for i in items), suite=suite,
                      lint={"ok": lint_ok, "detail": lint_detail}, items=items)


def run(root: Path = ROOT, timeout: float = 1800) -> GateResult:
    if not (root / "tests").is_dir() or not (root / "pyproject.toml").is_file():
        raise RuntimeError("run `jarvis gate` from the JARVIS repository (with `uv run`), not an installed copy")
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "junit.xml"
        try:
            subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}"],
                           cwd=root, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"the test suite took longer than {timeout:.0f}s") from None
        results = parse_junit(report.read_text()) if report.exists() else {}
    try:
        lint = subprocess.run([sys.executable, "-m", "ruff", "check", "src", "tests"], cwd=root,
                              capture_output=True, text=True, timeout=300)
        lint_ok = lint.returncode == 0
        lint_detail = "clean" if lint_ok else (lint.stdout + lint.stderr).strip()[-1500:]
        if "No module named ruff" in lint.stderr:
            lint_ok, lint_detail = False, "the linter isn't installed: run `uv sync` (it's a pinned dev dependency)"
    except (OSError, subprocess.TimeoutExpired) as exc:
        lint_ok, lint_detail = False, f"the linter didn't run: {exc}"
    result = evaluate(results, lint_ok, lint_detail)
    result.seconds = round(time.monotonic() - started, 1)
    return result


def report(r: GateResult) -> str:
    s = r.suite
    lines = [f"JARVIS release gate: {'PASS' if r.passed else 'FAIL'}  ({r.seconds:.0f}s)", "",
             f"{'✓' if s['ok'] else '✗'} Test suite      {s['passed']} test functions passed, {len(s['failed'])} failed, "
             f"{len(s['skipped'])} skipped" + (f" (not allowed: {', '.join(s['unexpected_skips'])})" if s["unexpected_skips"] else ""),
             f"{'✓' if r.lint['ok'] else '✗'} Linter          {r.lint['detail'] if r.lint['ok'] else 'problems found'}", ""]
    for f in s["failed"]:
        lines.append(f"    failed: {f}")
    if not r.lint["ok"]:
        lines += ["    " + x for x in r.lint["detail"].splitlines()[-12:]]
    lines.append("Security items (each must pass; they can't be outweighed):")
    for i in r.items:
        lines.append(f"{'✓' if i.passed else '✗'} {i.name:<40} {i.detail}")
    return "\n".join(lines)


def as_json(r: GateResult) -> str:
    return json.dumps({"passed": r.passed, "seconds": r.seconds, "suite": r.suite, "lint": r.lint,
                       "items": [i.__dict__ for i in r.items]}, indent=2)

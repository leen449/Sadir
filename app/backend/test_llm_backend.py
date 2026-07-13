"""
test_llm_backend.py

Lightweight, dependency-free test script for the LLM backend module.
Run with:  python backend/test_llm_backend.py

Covers:
    - validation rejects bad transaction_id / mismatched node / bad question_id
    - question_id -> template mapping is exact (Q1/Q2/Q3)
    - each template receives ONLY its whitelisted evidence fields
      (the data-leakage guard between question types)
    - Azure OpenAI is mocked -- no real key/network needed to run this file
    - missing/empty evidence renders as an explicit "not supplied" marker
      rather than crashing

No pytest required so this can run in any environment during the hackathon
without adding a new dependency.
"""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(__file__))

from app.backend.services import artifact_service
from app.backend.services.transaction_service import TransactionContext, SelectedNode, build_context, TransactionNotFoundError
from app.backend.security.validation import validate_request, ValidationError
from app.backend.services import llm_service
from app.backend.utils.cache import ArtifactCache, ExecutiveSummaryCache


PASSED = 0
FAILED = 0


def check(name, condition):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name}")


def make_context(**overrides) -> TransactionContext:
    defaults = dict(
        transaction_id="339094191",
        prediction="suspicious",
        true_label="illicit",
        risk_score=0.87,
        gnn_importance=0.62,
        positive_shap_features="V6:+1.17; V54:+0.90",
        negative_shap_features="V22:-0.45",
        important_neighbors=[{"txId": "111", "importance": 0.7}],
        important_edges=[{"source": "339094191", "target": "111"}],
        feature_categories={"ranges": [{"prefix": "V", "start": 1, "end": 20, "label": "Transaction Profile"}]},
        selected_node=SelectedNode(node_index=1, txId="339094191", graph_position={"x": 0, "y": 0, "z": 0}),
    )
    defaults.update(overrides)
    return TransactionContext(**defaults)


def test_validation_rejects_bad_transaction_id():
    print("\n[Validation] unknown transaction_id is rejected")
    with patch.object(artifact_service, "transaction_exists", return_value=False):
        try:
            validate_request("does_not_exist", SelectedNode(1, "does_not_exist"), "initial_analysis")
            check("raises ValidationError", False)
        except ValidationError as e:
            check("raises ValidationError", True)
            check("reason_code is TRANSACTION_NOT_FOUND", e.reason_code == "TRANSACTION_NOT_FOUND")


def test_validation_rejects_missing_node():
    print("\n[Validation] missing selected_node is rejected")
    with patch.object(artifact_service, "transaction_exists", return_value=True):
        try:
            validate_request("339094191", None, "initial_analysis")
            check("raises ValidationError", False)
        except ValidationError as e:
            check("reason_code is SELECTED_NODE_MISSING", e.reason_code == "SELECTED_NODE_MISSING")


def test_validation_rejects_mismatched_node():
    print("\n[Validation] node/transaction mismatch is rejected")
    with patch.object(artifact_service, "transaction_exists", return_value=True), \
         patch.object(artifact_service, "node_exists", return_value=True):
        node = SelectedNode(node_index=2, txId="OTHER_TX")
        try:
            validate_request("339094191", node, "initial_analysis")
            check("raises ValidationError", False)
        except ValidationError as e:
            check("reason_code is NODE_TRANSACTION_MISMATCH", e.reason_code == "NODE_TRANSACTION_MISMATCH")


def test_validation_rejects_bad_question_id():
    print("\n[Validation] unsupported question_id is rejected")
    with patch.object(artifact_service, "transaction_exists", return_value=True), \
         patch.object(artifact_service, "node_exists", return_value=True):
        node = SelectedNode(node_index=1, txId="339094191")
        try:
            validate_request("339094191", node, "question", question_id="question_999")
            check("raises ValidationError", False)
        except ValidationError as e:
            check("reason_code is UNSUPPORTED_QUESTION_ID", e.reason_code == "UNSUPPORTED_QUESTION_ID")


def test_validation_passes_for_valid_request():
    print("\n[Validation] fully valid request passes")
    with patch.object(artifact_service, "transaction_exists", return_value=True), \
         patch.object(artifact_service, "node_exists", return_value=True):
        node = SelectedNode(node_index=1, txId="339094191")
        try:
            validate_request("339094191", node, "question", question_id="question_1")
            check("no exception raised", True)
        except ValidationError:
            check("no exception raised", False)


def test_question_template_mapping():
    print("\n[LLM Service] question_id -> template mapping is exact")
    check("question_1 -> positive_shap", llm_service.QUESTION_TEMPLATE_MAP["question_1"] == "question_1_positive_shap.txt")
    check("question_2 -> gnn_neighbors", llm_service.QUESTION_TEMPLATE_MAP["question_2"] == "question_2_gnn_neighbors.txt")
    check("question_3 -> negative_shap", llm_service.QUESTION_TEMPLATE_MAP["question_3"] == "question_3_negative_shap.txt")


def test_no_cross_question_evidence_leakage():
    print("\n[LLM Service] each template only receives its whitelisted fields")
    ctx = make_context()

    q1_evidence = llm_service._build_evidence("question_1_positive_shap.txt", ctx)
    check("Q1 excludes negative_shap_features", "negative_shap_features" not in q1_evidence)
    check("Q1 excludes important_neighbors", "important_neighbors" not in q1_evidence)
    check("Q1 includes positive_shap_features", "positive_shap_features" in q1_evidence)

    q2_evidence = llm_service._build_evidence("question_2_gnn_neighbors.txt", ctx)
    check("Q2 excludes positive_shap_features", "positive_shap_features" not in q2_evidence)
    check("Q2 excludes negative_shap_features", "negative_shap_features" not in q2_evidence)
    check("Q2 includes important_neighbors", "important_neighbors" in q2_evidence)

    q3_evidence = llm_service._build_evidence("question_3_negative_shap.txt", ctx)
    check("Q3 excludes positive_shap_features", "positive_shap_features" not in q3_evidence)
    check("Q3 excludes gnn_importance", "gnn_importance" not in q3_evidence)
    check("Q3 includes negative_shap_features", "negative_shap_features" in q3_evidence)


def test_missing_evidence_renders_safely():
    print("\n[LLM Service] missing/empty evidence renders as 'not supplied' instead of crashing")
    ctx = make_context(positive_shap_features="", important_neighbors=[])
    evidence = llm_service._build_evidence("question_1_positive_shap.txt", ctx)
    template_text = llm_service._load_prompt("question_1_positive_shap.txt")
    try:
        rendered = llm_service._render_template(template_text, evidence)
        check("render does not raise", True)
        check("'not supplied' marker present for empty field", "not supplied" in rendered)
    except Exception:
        check("render does not raise", False)


def test_generate_explanation_calls_azure_with_correct_params():
    print("\n[LLM Service] generate_explanation() calls Azure with GPT-5-compatible params (mocked)")
    ctx = make_context()

    fake_response = MagicMock()
    fake_response.choices[0].message.content = "Mocked explanation text."

    with patch.object(artifact_service, "transaction_exists", return_value=True), \
         patch.object(artifact_service, "node_exists", return_value=True), \
         patch.object(llm_service.settings, "AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/"), \
         patch.object(llm_service.settings, "AZURE_OPENAI_KEY", "fake-key"), \
         patch.object(llm_service.settings, "AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini"), \
         patch("services.llm_service._get_azure_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = fake_response
        mock_get_client.return_value = mock_client

        result = llm_service.generate_explanation(ctx, "question", question_id="question_1")

        check("returns only text (str)", isinstance(result, str))
        check("returns mocked content", result == "Mocked explanation text.")

        _, call_kwargs = mock_client.chat.completions.create.call_args
        check("uses max_completion_tokens (not max_tokens)", "max_completion_tokens" in call_kwargs and "max_tokens" not in call_kwargs)
        check("uses reasoning_effort", "reasoning_effort" in call_kwargs)
        check("does not use temperature", "temperature" not in call_kwargs)
        check("does not use top_p", "top_p" not in call_kwargs)
        check("model is read from env (gpt-5-mini)", call_kwargs["model"] == "gpt-5-mini")


def test_azure_v1_base_url_construction():
    print("\n[LLM Service] Azure v1 base_url is built correctly from endpoint")
    with patch.object(llm_service.settings, "AZURE_OPENAI_ENDPOINT", "https://myres.openai.azure.com/"), \
         patch.object(llm_service.settings, "AZURE_OPENAI_KEY", "fake-key"), \
         patch("services.llm_service.OpenAI") as mock_openai_cls:
        llm_service._get_azure_client()
        _, call_kwargs = mock_openai_cls.call_args
        check("base_url ends with openai/v1/", call_kwargs["base_url"] == "https://myres.openai.azure.com/openai/v1/")
        check("api_key passed through", call_kwargs["api_key"] == "fake-key")

    # also handle endpoint without trailing slash
    with patch.object(llm_service.settings, "AZURE_OPENAI_ENDPOINT", "https://myres.openai.azure.com"), \
         patch.object(llm_service.settings, "AZURE_OPENAI_KEY", "fake-key"), \
         patch("services.llm_service.OpenAI") as mock_openai_cls:
        llm_service._get_azure_client()
        _, call_kwargs = mock_openai_cls.call_args
        check("base_url correct with no trailing slash in endpoint", call_kwargs["base_url"] == "https://myres.openai.azure.com/openai/v1/")


def test_artifact_cache_loads_once():
    print("\n[Cache] ArtifactCache calls loader only once per key")
    cache = ArtifactCache()
    call_count = {"n": 0}

    def loader():
        call_count["n"] += 1
        return "loaded-value"

    r1 = cache.get_or_load("k1", loader)
    r2 = cache.get_or_load("k1", loader)
    check("returns loaded value", r1 == "loaded-value" and r2 == "loaded-value")
    check("loader called exactly once", call_count["n"] == 1)


def test_artifact_service_uses_shared_cache_regression():
    print("\n[Cache] artifact_service.py loaders still work after cache refactor")
    artifact_service.artifact_cache.clear()
    with patch("os.path.exists", return_value=True), \
         patch("pandas.read_csv") as mock_read_csv:
        import pandas as pd
        mock_read_csv.return_value = pd.DataFrame({"txId": ["339094191"], "prediction": ["suspicious"]})
        df1 = artifact_service._load_csv_cached(artifact_service.PREDICTIONS_PATH, "predictions")
        df2 = artifact_service._load_csv_cached(artifact_service.PREDICTIONS_PATH, "predictions")
        check("returns cached dataframe on second call", df1 is df2)
        check("read_csv called exactly once", mock_read_csv.call_count == 1)
    artifact_service.artifact_cache.clear()


def test_executive_summary_cache_set_and_get():
    print("\n[Cache] ExecutiveSummaryCache set/get roundtrip")
    cache = ExecutiveSummaryCache(ttl_seconds=1800)
    cache.set("session_A", "339094191", "Executive summary text.")
    check("get returns stored text", cache.get("session_A", "339094191") == "Executive summary text.")
    check("different session returns None", cache.get("session_B", "339094191") is None)
    check("different transaction returns None", cache.get("session_A", "OTHER_TX") is None)


def test_executive_summary_cache_ttl_expiry():
    print("\n[Cache] ExecutiveSummaryCache expires entries past TTL")
    cache = ExecutiveSummaryCache(ttl_seconds=1800)
    cache.set("session_A", "339094191", "Executive summary text.")
    # Simulate 31 minutes having passed without sleeping.
    key = cache._make_key("session_A", "339094191")
    stored_at, text = cache._store[key]
    cache._store[key] = (stored_at - 1900, text)
    check("expired entry returns None", cache.get("session_A", "339094191") is None)
    check("expired entry is evicted from store", key not in cache._store)


def test_generate_explanation_uses_executive_summary_cache():
    print("\n[LLM Service] initial_analysis result is cached and reused without a second Azure call")
    llm_service.executive_summary_cache.clear()
    ctx = make_context()

    fake_response = MagicMock()
    fake_response.choices[0].message.content = "Cached executive summary."

    with patch.object(artifact_service, "transaction_exists", return_value=True), \
         patch.object(artifact_service, "node_exists", return_value=True), \
                  patch.object(llm_service.settings, "AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini"), \
         patch("services.llm_service._get_azure_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = fake_response
        mock_get_client.return_value = mock_client

        r1 = llm_service.generate_explanation(ctx, "initial_analysis", session_id="sess_1")
        r2 = llm_service.generate_explanation(ctx, "initial_analysis", session_id="sess_1")

        check("both calls return same text", r1 == r2 == "Cached executive summary.")
        check("Azure called only once (second call served from cache)", mock_client.chat.completions.create.call_count == 1)

    llm_service.executive_summary_cache.clear()


def test_generate_explanation_without_session_id_skips_cache():
    print("\n[LLM Service] omitting session_id skips Executive Summary caching (Q1/Q2/Q3 flow)")
    llm_service.executive_summary_cache.clear()
    ctx = make_context()

    fake_response = MagicMock()
    fake_response.choices[0].message.content = "Answer text."

    with patch.object(artifact_service, "transaction_exists", return_value=True), \
         patch.object(artifact_service, "node_exists", return_value=True), \
                  patch.object(llm_service.settings, "AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini"), \
         patch("services.llm_service._get_azure_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = fake_response
        mock_get_client.return_value = mock_client

        llm_service.generate_explanation(ctx, "question", question_id="question_1")
        llm_service.generate_explanation(ctx, "question", question_id="question_1")

        check("Azure called for each request (no caching without session_id)", mock_client.chat.completions.create.call_count == 2)


def test_generate_explanation_cache_isolated_by_transaction():
    print("\n[LLM Service] same session, different transactions -> Azure called twice (no cache leak)")
    llm_service.executive_summary_cache.clear()
    ctx_a = make_context(transaction_id="TX-A", selected_node=SelectedNode(1, "TX-A"))
    ctx_b = make_context(transaction_id="TX-B", selected_node=SelectedNode(2, "TX-B"))

    fake_response = MagicMock()
    fake_response.choices[0].message.content = "Summary text."

    with patch.object(artifact_service, "transaction_exists", return_value=True), \
         patch.object(artifact_service, "node_exists", return_value=True), \
                  patch.object(llm_service.settings, "AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini"), \
         patch("services.llm_service._get_azure_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = fake_response
        mock_get_client.return_value = mock_client

        llm_service.generate_explanation(ctx_a, "initial_analysis", session_id="session-1")
        llm_service.generate_explanation(ctx_b, "initial_analysis", session_id="session-1")

        check("Azure called twice (TX-A and TX-B are distinct cache keys)", mock_client.chat.completions.create.call_count == 2)

    llm_service.executive_summary_cache.clear()


def test_generate_explanation_cache_isolated_by_session():
    print("\n[LLM Service] different sessions, same transaction -> Azure called twice (no cache leak)")
    llm_service.executive_summary_cache.clear()
    ctx = make_context()

    fake_response = MagicMock()
    fake_response.choices[0].message.content = "Summary text."

    with patch.object(artifact_service, "transaction_exists", return_value=True), \
         patch.object(artifact_service, "node_exists", return_value=True), \
                  patch.object(llm_service.settings, "AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini"), \
         patch("services.llm_service._get_azure_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = fake_response
        mock_get_client.return_value = mock_client

        llm_service.generate_explanation(ctx, "initial_analysis", session_id="session-A")
        llm_service.generate_explanation(ctx, "initial_analysis", session_id="session-B")

        check("Azure called twice (session-A and session-B are distinct cache keys)", mock_client.chat.completions.create.call_count == 2)

    llm_service.executive_summary_cache.clear()


def test_artifact_service_matches_real_pipeline_schema():
    print("\n[Regression] artifact_service.py reads target-scoped GNN CSVs and indexed prediction/SHAP artifacts")
    import pandas as pd

    fake_predictions = pd.DataFrame({
        "txId": [339094191, 111],
        "pred": [1, 0],
        "prob": [0.87, 0.12],
        "true_label": [1, 0],
    })
    fake_shap = pd.DataFrame({
        "txId": [339094191],
        "top_positive_factors": ['[{"category":"Transaction Profile","feature":"V6","impact":"+1.17"}]'],
        "top_negative_factors": ['[{"category":"Network Context","feature":"V22","impact":"-0.45"}]'],
    })
    fake_tx_ids = pd.DataFrame({"node_idx": [1, 2, 3], "txId": [339094191, 111, 222]})
    fake_nodes = pd.DataFrame({
        "explained_target_node_idx": [1, 1],
        "explained_target_txId": [339094191, 339094191],
        "node_idx": [2, 3],
        "txId": [111, 222],
        "node_importance": [0.62, 0.35],
    })
    fake_edges = pd.DataFrame({
        "explained_target_node_idx": [1, 1],
        "explained_target_txId": [339094191, 339094191],
        "source_node_idx": [2, 2],
        "target_node_idx": [1, 3],
        "source_txId": [111, 111],
        "target_txId": [339094191, 222],
        "edge_importance": [0.5, 0.4],
    })

    artifact_service.clear_cache()

    def fake_read_csv(path, *args, **kwargs):
        path = str(path)
        if "hybrid_predictions" in path:
            return fake_predictions
        if "transaction_explanations" in path:
            return fake_shap
        if "transaction_ids" in path:
            return fake_tx_ids
        if "important_nodes" in path:
            return fake_nodes
        if "important_edges" in path:
            return fake_edges
        raise FileNotFoundError(path)

    with patch("os.path.exists", return_value=True), \
         patch("pandas.read_csv", side_effect=fake_read_csv), \
         patch.object(artifact_service, "get_feature_categories", return_value={}):

        pred_row = artifact_service.get_prediction_row("339094191")
        check("prediction normalizes pred=1 to 'suspicious'", pred_row["prediction"] == "suspicious")
        check("true_label normalizes 1 to 'illicit'", pred_row["true_label"] == "illicit")
        check("risk_score reads from 'prob' column", pred_row["risk_score"] == 0.87)

        gnn_row = artifact_service.get_gnn_importance_row("339094191")
        check("gnn_importance summarizes strongest target-scoped neighbor importance", gnn_row["gnn_importance"] == 0.62)

        shap_row = artifact_service.get_shap_row("339094191")
        check("positive_shap parsed from JSON factors", "V6" in shap_row["positive_shap"])
        check("negative_shap parsed from JSON factors", "V22" in shap_row["negative_shap"])

        neighbors = artifact_service.get_important_neighbors("339094191")
        check("neighbors filtered by explained_target_txId", len(neighbors) == 2 and neighbors[0]["txId"] == "111")

        edges = artifact_service.get_important_edges("339094191")
        check("all target-scoped edges are preserved, including non-incident explanatory edges", len(edges) == 2)

        check("node_exists checks against transaction_ids.csv node_idx", artifact_service.node_exists(1) is True)
        check("node_exists returns False for unknown node", artifact_service.node_exists(999) is False)

    artifact_service.clear_cache()


def test_generate_explanation_blocks_invalid_request_before_azure():
    print("\n[LLM Service] invalid request is rejected before Azure is ever called")
    ctx = make_context(transaction_id="does_not_exist", selected_node=SelectedNode(1, "does_not_exist"))
    with patch.object(artifact_service, "transaction_exists", return_value=False), \
         patch("services.llm_service._get_azure_client") as mock_get_client:
        try:
            llm_service.generate_explanation(ctx, "initial_analysis")
            check("raises ValidationError", False)
        except ValidationError:
            check("raises ValidationError", True)
        check("Azure client never constructed", mock_get_client.call_count == 0)


if __name__ == "__main__":
    test_validation_rejects_bad_transaction_id()
    test_validation_rejects_missing_node()
    test_validation_rejects_mismatched_node()
    test_validation_rejects_bad_question_id()
    test_validation_passes_for_valid_request()
    test_question_template_mapping()
    test_no_cross_question_evidence_leakage()
    test_missing_evidence_renders_safely()
    test_generate_explanation_calls_azure_with_correct_params()
    test_azure_v1_base_url_construction()
    test_artifact_cache_loads_once()
    test_artifact_service_uses_shared_cache_regression()
    test_executive_summary_cache_set_and_get()
    test_executive_summary_cache_ttl_expiry()
    test_generate_explanation_uses_executive_summary_cache()
    test_generate_explanation_without_session_id_skips_cache()
    test_generate_explanation_cache_isolated_by_transaction()
    test_generate_explanation_cache_isolated_by_session()
    test_artifact_service_matches_real_pipeline_schema()
    test_generate_explanation_blocks_invalid_request_before_azure()

    print(f"\n{'='*50}")
    print(f"RESULTS: {PASSED} passed, {FAILED} failed")
    print(f"{'='*50}")
    sys.exit(1 if FAILED else 0)

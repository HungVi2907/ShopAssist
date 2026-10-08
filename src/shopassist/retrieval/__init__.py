"""ShopAssist retrieval engines package.

Provides lexical (TF-IDF), semantic (dense vector), and hybrid retrieval implementations.
"""

from shopassist.retrieval.semantic import (
    DEFAULT_REPORT_PATH as DEFAULT_SEMANTIC_REPORT_PATH,
    DenseQueryEncoder,
    SemanticSearchConfig,
    SemanticSearchEngine,
    SemanticSearchResult,
    benchmark_semantic_retrieval,
    compute_result_overlap,
)
from shopassist.retrieval.tfidf import (
    DEFAULT_TFIDF_ARTIFACT_DIR,
    DEFAULT_TFIDF_REPORT_PATH,
    SearchResult,
    TFIDFConfig,
    TFIDFIndex,
    build_tfidf_baseline,
    load_canonical_products,
)

__all__ = [
    "DEFAULT_SEMANTIC_REPORT_PATH",
    "DEFAULT_TFIDF_ARTIFACT_DIR",
    "DEFAULT_TFIDF_REPORT_PATH",
    "DenseQueryEncoder",
    "SearchResult",
    "SemanticSearchConfig",
    "SemanticSearchEngine",
    "SemanticSearchResult",
    "TFIDFConfig",
    "TFIDFIndex",
    "benchmark_semantic_retrieval",
    "build_tfidf_baseline",
    "compute_result_overlap",
    "load_canonical_products",
]


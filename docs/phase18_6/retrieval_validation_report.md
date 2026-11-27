# Phase 18.6 retrieval validation

**Actual pgvector + BGE + TF-IDF + hybrid RRF retrieval works against the 8,405-product database.** Product-type quality and suitability remain limited; no new retrieval model or algorithm was introduced. R3 continues to refuse unverified or irrelevant candidates.

The first API run encountered a genuine database outage. After a successful operator-requested retry, captured frozen Q1S results were replayed through real preference encoding, SQL filtering, dense retrieval, lexical retrieval, fusion and RRF. This replay has no new QU inference and is a retrieval preflight, not a substitute for the subsequent genuine full API requests.

The [preflight artifact](../../data/interim/phase18_6/retrieval_results/live_hybrid_preflight_01.json) records raw queries, Q1S raw extraction/transformed output, semantic query, hard/soft constraints, price inclusivity, preference representation, dense rows, lexical candidates, hybrid source ranks/scores, reranked products and canonical schema fingerprints. Reference-query ablations are stored separately and never represented as actual Q1S outputs.

## Positive and terminal behavior

| Scenario | Actual finding |
|---|---|
| Running shoes under 2000 INR | Real Footwear candidates; successful API result with three products, correct upper-bound filtering and source quotations. |
| AMCO running shoes under 2000 INR | Brand filter works; explicit top-k 2 succeeds. Distinct catalog IDs may share a product name; no product was duplicated to meet cardinality. |
| Comfortable running shoes for daily jogging | Real preference embedding used with the same cached BGE model; explicit top-k 4 succeeds. Usefulness remains provisional. |
| Headphones under 1000 / cheap headphones | Top-k 5 and 3 successes respectively, with no invented hard price for “cheap.” |
| Headphones with minimum 4 stars | Null ratings are excluded. Top-k 3 contains a product-type ambiguity and is refused; the separately preclassified top-k 1 request succeeds. Runtime candidate trimming was not changed to force success. |
| Laptop between 20000 and 40000 INR | SQL lower/upper price constraints execute. The top two results are HP Notebook models, followed by an Intel processor. The mixed top-k 3 set is refused; exact-name `laptop` matching also misses legitimate `Notebook` names. This is candidate contamination plus conservative alias coverage, not catalog absence. |
| Laptop with 16 GB RAM | Mandatory specification/type is not established by the retrieved accessories; no successful suitability claim. |
| Running shoes under 1 INR | Genuine empty filtered database result; API returns `NO_RESULTS`. |
| Shoes not exceeding 2000 rupees | Frozen Q1S returns upper bound 2000; all downstream numeric-aware checks pass; final live API result succeeds with the bound preserved. |
| Foreign currency, missing intent, unsupported domain, ambiguous maker, Vietnamese request | Observed clarification rather than fabricated successful products. The Vietnamese case remains a coverage limitation. |

Accepted final-run products passed category/brand/price/rating checks against transformed constraints and explicit strict/inclusive price semantics. Accepted IDs and order match reranking exactly; authoritative database metadata and URLs/images match public response values. ID uniqueness is checked by existing contracts. These checks validate the exercised requests; they are not broad retrieval recall or diversity-quality scores.

## Three preserved product-type failures

| Query | Catalog evidence and actual retrieval diagnosis | Safe outcome |
|---|---|---|
| Wireless charging pad | No name co-occurrence establishes a wireless charger. A `Newdort Usb Charger Full Charging Pad` name does not establish Qi/wireless capability. Real hybrid retrieval returns related cables/accessories, including Lightning cable results. The first reference probe timed out; targeted retry succeeded. | Actual API returns `VALIDATION_FAILURE`; R3 does not generate a cable recommendation. RRF, multi-signal and existing CrossEncoder reference comparisons all fail the conservative product-type check. |
| Bluetooth speaker | No name co-occurrence establishes a Bluetooth speaker. Broad mobile-accessory retrieval returns headphones/headsets; automotive speakers are a different context/category. | Actual Q1S asks clarification. A separately labeled manual reference QU ablation still retrieves unsuitable products under all three existing reranking methods; R3 refuses them. |
| Honda City body cover | Honda City records include mats, sunshade and a steering cover. The one Honda+City+cover name co-occurrence is a steering cover, not a verified body cover. Other two-wheeler covers do not establish Honda City compatibility. | Actual Q1S asks clarification. Correct-category reference retrieval/reranking also fails R3 product-type validation; compatibility remains unverified. |

The catalog inspection covers full names and available retrieval/evidence context; absence of an exact name alone is not a formal proof that no specification anywhere could establish a requested feature. The defensible classification is **no suitable product verified from this catalog evidence**, with coarse category and lexical/dense accessory similarities explaining the observed substitutions. There is no reviewed relevant-product set supporting a recall-improvement claim. No guard was relaxed and no unrelated item was converted into successful fallback.

See [initial local inspection](../../data/interim/phase18_6/retrieval_results/local_catalog_baseline.json), [reference ablation](../../data/interim/phase18_6/retrieval_results/relevance_reference_ablation_01.json) and [targeted wireless retry](../../data/interim/phase18_6/retrieval_results/relevance_reference_ablation_02.json). The reference ablation uses explicitly constructed correct-type QU only to locate retrieval/ranking limitations; it is not end-to-end acceptance and issues no route permission.

## Decisions and limits

No evidence justified a new embedding model, reranking model, taxonomy, score-fusion change or broad query rewrite. The only retrieval/reranking code correction was numeric-exclusion compatibility; existing RRF and other algorithms are otherwise unchanged. R3's conservative relevance checks intentionally reduce coverage.

The historical Puma-running-shoes example is not a reliable positive fixture: this snapshot has zero product names combining Puma with running shoes. Positive cases were chosen from verified running-shoe/AMCO and headphone catalog records. The preclassified E07 expectation incorrectly inferred laptop absence from literal `laptop` matches; actual retrieval revealed HP `Notebook` models. The original expectation file is preserved and that premise is explicitly corrected here. No alias/guard relaxation or silent candidate trimming was made to force this case to succeed. Product links/images are authoritative snapshot fields, not verified current storefront availability; no external storefront was fetched.

Independent product relevance, preference usefulness, compatibility and language review remain open. A future improvement must distinguish missing catalog support, filtering, retrieval recall and reranking failure before changing behavior. The final API evidence establishes backend integration and safe rejection, not universal product suitability.

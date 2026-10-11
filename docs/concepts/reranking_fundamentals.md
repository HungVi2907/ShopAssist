# Reranking Fundamentals for ShopAssist

This guide explains the theory behind Phase 11. Examples describe the architecture; measured ShopAssist results are only those in [the Phase 11 evaluation](../phase11_reranking_evaluation.md). In particular, the guide does not imply that the Cross-Encoder has been run on this catalog.

## 1. Information retrieval ranking

**Definition:** Ordering records by usefulness for an information need. **Intuition:** A search engine should put the best matching products first. **Technical view:** Given query `q` and products `d`, a ranker estimates an ordering function `s(q,d)`. ShopAssist keeps scores and ranks separate: scores can be method-specific, while rank is their sorted order. Ranking is useful after retrieval, but errors in retrieved membership cannot be repaired here.

## 2. Candidate generation

**Definition:** Finding a tractable subset of the catalog for later stages. **Intuition:** Evaluate a few dozen plausible products instead of every product with an expensive model. **Technical view:** Phase 10 returns a fixed Top-N set from SQL-filtered dense and lexical retrieval. Phase 11 enforces `output IDs ⊆ input IDs`. Candidate generation limits compute, but missed products are unrecoverable downstream.

## 3. Two-stage retrieval

**Definition:** A fast broad first stage followed by a more expensive narrow ranker. **Intuition:** First gather likely matches, then spend more time comparing them to the request. **Technical view:** Phase 10 performs hybrid retrieval; Phase 11 reorders its Top-N into Top-K. This is a standard latency/quality split. End-to-end quality is bounded by the candidate set's recall.

## 4. Bi-Encoder architecture

**Definition:** Encode query and document separately into vectors, then compare vectors. **Intuition:** Precompute product vectors once and cheaply compare each new query. **Technical view:** `q=f(q_text)`, `d=g(product_text)`, then cosine similarity `q·d` for normalized vectors. Phase 7's BGE model supplies query vectors and saved product vectors. It scales well but cannot jointly inspect fine token interactions at scoring time.

## 5. Cross-Encoder architecture

**Definition:** Process query and document together in a transformer and predict a relevance score. **Intuition:** The model can compare words such as “red”, “party”, and “wedge” in both texts directly. **Technical view:** Tokenized pair `[CLS] q [SEP] d [SEP]` passes through shared self-attention and a scalar head. Phase 11 exposes batched pair scoring. It can be more precise but costs a forward pass per candidate and cannot precompute document vectors.

## 6. Bi-Encoder versus Cross-Encoder

**Definition:** Separate-vector scoring versus joint pair scoring. **Intuition:** Bi-Encoder is a fast shortlist maker; Cross-Encoder is a slower second opinion. **Technical view:** Bi-Encoder dot products permit ANN search across a catalog; Cross-Encoder inference is approximately proportional to candidate count and sequence length. ShopAssist already has the former in Phase 7 and only optionally uses the latter in Phase 11. A passage-trained Cross-Encoder may not transfer to product purchase intent.

## 7. Query-document pair scoring

**Definition:** A score for one query and one candidate text. **Intuition:** Ask “how well does this product text satisfy this shopping request?” **Technical view:** `s_i = model.predict((q, d_i))`. Phase 11 uses the positive Phase 9 composed query when available and canonical `retrieval_text` mapped by product ID. Correct pairing prevents comparing one item's text with another item's ID. Pair scoring does not establish factual truth beyond the input text.

## 8. Transformer self-attention

**Definition:** A learned mechanism that lets each token use context from other tokens. **Intuition:** “Apple” can be interpreted differently near “phone” than near “fruit”. **Technical view:** `Attention(Q,K,V)=softmax(QKᵀ/√d_k)V`. A Cross-Encoder applies attention across query and product tokens jointly. This supports attribute interactions but grows computational cost with sequence length and may attend to noisy catalog prose.

## 9. Relevance scores

**Definition:** Numeric values used to order candidates. **Intuition:** Higher means “put earlier” for a given model. **Technical view:** Score scale depends on model and training objective; Phase 10 RRF, TF-IDF cosine, dense cosine, and Cross-Encoder outputs are not interchangeable units. Phase 11 records raw components and uses deterministic tie-breaks. A larger score is not automatically a probability or a calibrated confidence.

## 10. Cross-Encoder logits

**Definition:** The scalar output before a probability transform in a classifier. **Intuition:** Logit 6 versus 2 means stronger model preference, not 6/2 times the relevance. **Technical view:** A logit `z` can be transformed by sigmoid `σ(z)=1/(1+e^-z)`, which is monotonic for ordering but does not guarantee calibration. The selected MS MARCO model card shows unbounded example logits. Phase 11 stores raw scores and never presents them as probabilities.

## 11. Score calibration

**Definition:** Mapping scores to probabilities whose numeric confidence matches observed frequencies. **Intuition:** When a model says 0.8, about eight of ten comparable predictions should be relevant. **Technical view:** Calibration can use held-out labels with methods such as Platt scaling or isotonic regression. ShopAssist has too few independently judged cases to calibrate. Calibration helps thresholds and confidence displays, but it is not required just to sort one query's scores.

## 12. Score normalization

**Definition:** Transforming different score scales to a comparable range. **Intuition:** Do not add a 0–1 rating to a raw logit near 8 without a scale policy. **Technical view:** Phase 11 combined mode min-max maps within-query Cross-Encoder scores into `[0,1]`; constant vectors map to `0.5`. Min-max is sensitive to outliers and tiny score ranges. The current combined method requires caller-supplied weights and is not enabled by default.

## 13. Multi-Signal ranking

**Definition:** Use multiple signals to decide an order. **Intuition:** Agreement between dense meaning and literal terms may be more convincing than either alone. **Technical view:** The experimental Phase 11 method computes the mean of normalized dense and lexical rank utilities, assigning zero to a branch with no evidence. The symmetric weights are a design choice, not learned values. Signals can be correlated, so this method must be compared on labels before adoption.

## 14. Feature weighting

**Definition:** Assigning each feature a relative contribution. **Intuition:** A relevance score should usually matter more than a noisy optional rating. **Technical view:** `S=Σ w_j x_j`, with `w_j≥0` and often `Σw_j=1`. Phase 11 refuses combined CE/rank scoring unless both weights are configured explicitly; no evaluation split supports defaults. Weights tuned on the final evaluation labels leak information and make results optimistic.

## 15. Hard constraints versus ranking signals

**Definition:** Eligibility rules versus preferences that order eligible items. **Intuition:** “Under ₹1,000” can determine eligibility; “stylish” may influence order. **Technical view:** SQL constraints are predicates `eligible(d)∈{0,1}`; ranking evaluates `s(q,d)` only after eligibility. Phase 10 owns those filters. Phase 11 fails closed on visible contradictions, and no score can override category, brand, rating, or price conditions.

## 16. Product rating as a ranking feature

**Definition:** A structured customer rating used to order otherwise relevant items. **Intuition:** Between equally relevant products, buyers may prefer a consistently well-rated item. **Technical view:** A possible scale is `rating/5`; missing values need a neutral or excluded policy, not an invented low score. About 89.36% of catalog ratings are missing, and review counts are unavailable. Phase 11 preserves ratings for downstream use but does not rank on them due to weak coverage and no supporting evaluation.

## 17. Reciprocal Rank Fusion

**Definition:** Combining ranked lists using inverse rank contributions. **Intuition:** A product near the top of several lists accumulates evidence. **Technical view:** `RRF(d)=Σ_j 1/(k+r_j(d))`; absent-list items add nothing. Phase 10 uses `k=60`. The scale is independent of raw dense/lexical scores. RRF is robust and simple, but ignores score gaps and cannot model detailed attribute relevance.

## 18. Learning to Rank

**Definition:** Learning a ranking function from queries, products, and relevance judgments or behavior. **Intuition:** Show examples of which candidate should win and learn the patterns. **Technical view:** Models can optimize pointwise loss, pairwise preference loss, or listwise ranking metrics. ShopAssist has no suitable ranking training labels in this phase. Learning to rank could outperform hand-designed signals, but needs stable query-level labels and leakage controls.

## 19. Pointwise, pairwise, and listwise ranking

**Definition:** Three training/evaluation views of ranking. **Intuition:** Score each item; compare two items; or optimize the whole ordered list. **Technical view:** Pointwise predicts grade `y_i`; pairwise predicts whether `d_i ≻ d_j`; listwise optimizes a list loss or metric surrogate. Cross-Encoder inference here is pair scoring but is not trained on ShopAssist labels. Pairwise/listwise training needs substantially more qrels than the current four-query sample.

## 20. Precision@K

**Definition:** Fraction of top K results judged relevant. **Formula:** `P@K = relevant_in_topK / K`. **Example:** Four relevant products among five gives 0.8. Phase 11 uses grade ≥2. Precision is easy to interpret for a short recommendation slate, but ignores relevant candidates below K and treats all relevant grades alike.

## 21. Recall@K

**Definition:** Fraction of all relevant products retrieved within top K. **Formula:** `R@K = relevant_in_topK / total_relevant`. **ShopAssist note:** Recall must specify its universe. Evaluation on a fixed reranking pool measures conditional recall only; it says nothing about relevant products Phase 10 failed to retrieve. Recall is useful for pool coverage, but cannot compare candidate-generation quality when the pool is frozen.

## 22. Mean Reciprocal Rank

**Definition:** Average reciprocal position of the first relevant result. **Formula:** `MRR=(1/|Q|)Σ_q 1/rank_q`. **ShopAssist policy:** relevance is grade ≥2. MRR rewards getting one useful product very early, fitting “show me a good option first”. It ignores additional relevant products and their grades.

## 23. Discounted Cumulative Gain

**Definition:** Reward relevance with larger grades and discount lower positions. **Formula:** `DCG@K=Σ_i (2^rel_i-1)/log2(i+1)`. **Intuition:** Strong matches near the top matter most. Phase 11 uses graded 0–3 labels. DCG is interpretable as accumulated usefulness but is not normalized across queries with different ideal score totals.

## 24. Normalized DCG

**Definition:** DCG divided by the ideal DCG for that query. **Formula:** `nDCG@K=DCG@K/IDCG@K`. **Intuition:** 1.0 is an ideal order for those judgments. The Phase 11 report calculates it over the fixed judged candidate pool. nDCG supports graded relevance, but a high value on four curated cases is not population-level evidence.

## 25. Ranking ablation studies

**Definition:** Change one scoring component at a time under fixed inputs. **Intuition:** If removing ratings changes results, ratings caused that change. **Technical view:** Keep query set, candidate pools, qrels, and K constant; compare RRF, rank aggregation, CE, and combinations. Phase 11 compares RRF with Multi-Signal. Cross-Encoder arms were not run. Ablations explain contribution but can mislead when labels are small or features interact.

## 26. Latency-quality trade-off

**Definition:** Balance ranking gains against computation and delay. **Intuition:** A tiny improvement may not justify a slow model on every request. **Technical view:** Measure candidate generation, model initialization, batched inference, and sorting separately. The 0.043 ms Phase 11 warm ranker timing excludes Phase 10 retrieval and model inference. Cross-Encoder latency remains unknown locally. Quality should be interpreted alongside p50/p95 latency and hardware.

## 27. Model batching

**Definition:** Score multiple query-document pairs in one model call. **Intuition:** Reuse hardware work instead of calling the model separately for every product. **Technical view:** `predict([(q,d_1),...,(q,d_n)], batch_size=B)` pads and processes pair batches. Phase 11 uses configurable batches (default 16). Larger batches can improve throughput but consume more memory and can increase per-request tail latency.

## 28. CPU and GPU inference

**Definition:** Execute model tensors on processor cores or a graphics accelerator. **Intuition:** GPUs handle many transformer calculations in parallel; CPU works without accelerator availability. **Technical view:** Device placement affects load time, memory, throughput, and numeric behavior. The Phase 11 local Cross-Encoder loader requests CPU for broad fallback. No CE benchmark exists yet; published V100 throughput cannot predict this project's laptop or server performance.

## 29. Reranker generalization

**Definition:** Performance on requests/products beyond training data. **Intuition:** A model trained to find answer passages may misunderstand shopping attributes. **Technical view:** Distribution shift changes query vocabulary, relevance criteria, document length, and label policy. The proposed Cross-Encoder is trained for MS MARCO passage ranking; ShopAssist product search is a different domain. Independent catalog qrels are required before trusting transfer.

## 30. Reranking in recommendation systems

**Definition:** Reorder retrieved items to satisfy intent, utility, and product constraints. **Intuition:** Search brings plausible choices; reranking chooses the most fitting few. **Technical view:** A recommender commonly stages eligibility filtering, candidate generation, ranking, business rules, and grounded presentation. ShopAssist Phase 11 owns only ordering and Top-K selection. Diversity, personalization, fairness, stock status, and review confidence are outside the verified contract and must not be silently inferred.
